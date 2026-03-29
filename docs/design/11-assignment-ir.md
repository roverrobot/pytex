# Assignment IR

This note consolidates the current direction for assignment execution.

The main idea is to make assignments target-centric.

Instead of threading `(domain, key)` pairs through every assignment-like
operation, commands should work with an explicit target plus a small number of
typed local values.

## Main Conclusion

Assignments should be expressed in terms of parser operations such as:

- `readTarget() -> target`
- `readValue(value_type) -> value`
- `cast(value, value_type) -> value | None`

Under this model:

- accessors parse target syntax
- bound targets own target semantics
- the parser owns typed value reading
- the parser owns typed coercions
- assignment commands/accessors own assignment policy such as `\globaldefs`
- `afterAssignment()` remains a separate operation from `set()`

This is a better fit for the execution-IR direction than letting accessors keep
their own ad hoc read/write logic.

## Conceptual Registers vs Runtime Locals

The execution model is still easiest to describe using a few conceptual
registers:

- `target`
- `current_value`
- `scratch`
- `scratch_type`

But these should not be understood as mandatory long-lived parser instance
variables.

In practice, TeX execution is highly reentrant. Nested internal reads can occur
while an outer assignment is still being scanned. If these values are kept on
the parser itself, commands such as `\advance` end up needing a stack-backed
save/restore mechanism just to protect outer state from inner reads.

That is both awkward and expensive in a hot path.

So the implementation direction should be:

- keep these names as conceptual IR registers
- implement them as local variables inside command execution
- let parser operations return values instead of mutating parser-held holders

This gives the same conceptual model, but Python locals provide the necessary
stack discipline for free.

`target` is the active location being assigned to or read from, together with
the type restriction for that location.

Examples:

- `INT`
- `DIMEN`
- `GLUE`
- `MUGLUE`
- `TOKS`
- `BOX`
- `FONT`

`current_value` is the main value loaded by `get()` or `readValue()`.

`scratch` is the secondary local value used when a command needs an extra
operand.

`scratch_type` is needed because the scratch operand does not always have the
same type as the target.

Example:

- `\multiply\dimen0 by 2`
- target type is `DIMEN`
- scratch type is `INT`

So one target-local type plus one temporary `scratch_type` is enough. The
target's type should travel with the target itself, not as a separate parallel
value.

## What A Target Is

`target` is the position to read or write.

In the simplest representation, it can be:

- `(domain, key)`

where `domain` is any array/dict-like mutable store and `key` is the index or
name inside that store.

That means targets are not limited to parser-owned register arrays. They can
also point to domain-like objects such as:

- a font parameter array for `\fontdimen`
- a font-character attribute array for `\hyphenchar` / `\skewchar`
- other array/dict-like stores used by the engine

So `target` is not just "where"; it is "where plus what kind of value belongs
there."

A simple representation would be:

- `(domain, key, value_type)`

But the more useful representation is a bound target object with fields and
methods such as:

- `domain`
- `key`
- `value_type`
- `get()`
- `set(value, global_scope=False)`

This is better than a raw `(domain, key)` pair because some TeX targets are not
just ordinary parser domains. Examples include:

- `\wd`, `\ht`, `\dp`
- `\fontdimen`
- guarded or mode-sensitive targets such as `\spacefactor`

Those are still assignment targets, but their semantics belong with the bound
target rather than inside generic parser `get/set` methods.

The important distinction is:

- accessors need `parser` while binding a target
- a bound target should not need `parser` anymore

So target construction is parser-dependent, but target use is parser-free.

## Parser Operations

### `readTarget() -> target`

This operation reads the next assignment target and returns:

- `target`

It should be implemented through accessors.

### `readValue(value_type) -> value`

This operation reads a value from input according to the requested type.

The parser should dispatch through a reader table keyed by the requested type:

- `INT -> readInteger`
- `DIMEN -> readDimen`
- `GLUE -> readGlue`
- `TOKS -> readGeneralText` or token-list reader
- etc.

Commands that need a truly special scan rule can still use a specialized parser
method directly.

### `cast(value, value_type) -> value | None`

This operation attempts a coercion.

It should return:

- the coerced value on success
- `None` when the value is not valid for that type in the current context

For example, when a command wants a dimension-like internal quantity, it can:

1. bind a target
2. `value = get(target)`
3. `value = cast(value, DIMEN)`
4. treat `None` as "not a dimen"

## Target Operations

The bound target should provide:

- `target.value_type`
- `target.get() -> value`
- `target.set(value, global_scope=False)`

That means generic parser-side `get/set` helpers are optional convenience
wrappers at most. The primary runtime API should live on the target itself.

This keeps responsibilities clearer:

- `Parser` handles token scanning, typed readers, coercion, and
  `afterAssignment`
- assignment commands/accessors handle prefix processing and `globaldefs`
  resolution
- `target` handles the semantics of one already-bound assignment location

## Accessor Role

Under this model, accessors become mostly syntax adapters.

They should provide:

- `readEq(parser)` when the command family uses TeX assignment syntax
- `getTarget(parser)` to parse and return the target location
- `target_type` metadata, or an equivalent way for `readTarget()` to learn the
  target's type

So the parser's `readTarget()` can be implemented as:

1. read the accessor-like command occurrence
2. ask it for `target = accessor.getTarget(parser)`
3. return that typed target

This means:

1. the accessor uses `parser` to parse target syntax and construct a bound
   target
2. the parser performs typed reads, coercions, and assignment-completion
   behavior
3. the bound target performs the eventual `get/set` without needing `parser`

## Ordinary Assignment Shape

The normal assignment flow becomes:

1. read the accessor command
2. `target = readTarget()`
3. `readEq()`
4. `value = readValue(target.value_type)`
5. apply prefixes to determine requested `global_scope` and any value
   modification
6. apply `\globaldefs` to determine the effective `global_scope`
7. `target.set(value, global_scope=...)`
8. `afterAssignment()`

This gives a clean separation:

- `set()` is state mutation
- `afterAssignment()` is assignment completion

That distinction matters because not every future use of `set()` will represent
a TeX assignment. For example, layout-layer updates like `prevdepth` should not
trigger `\afterassignment`.

## Arithmetic Shape

Arithmetic commands become much cleaner under this model.

### `\advance`

1. `target = readTarget()`
2. `current_value = target.get()`
3. `scratch_type = target.value_type`
4. `readKeyword(["by"])`
5. `scratch = readValue(scratch_type)`
6. compute from `current_value` and `scratch`
7. apply prefixes and `\globaldefs` to determine effective `global_scope`
8. `target.set(result, global_scope=...)`
9. `afterAssignment()`

### `\multiply` / `\divide`

1. `target = readTarget()`
2. `current_value = target.get()`
3. `scratch_type = INT`
4. `readKeyword(["by"])`
5. `scratch = readValue(scratch_type)`
6. compute from `current_value` and `scratch`
7. apply prefixes and `\globaldefs` to determine effective `global_scope`
8. `target.set(result, global_scope=...)`
9. `afterAssignment()`

This is one of the main reasons `scratch_type` is needed.

## Why This Is More IR-Centric

This design shifts the important work into parser operations:

- target binding
- typed value scanning
- target reads
- target writes
- typed coercion
- assignment completion

More precisely:

- parser operations cover scanning, target binding, typed reads, coercion, and
  assignment support
- assignment commands/accessors cover prefix handling and `\globaldefs`
  resolution
- bound targets cover reads and writes at one already-bound location

That still makes command implementations read like short execution programs over
a small fixed vocabulary.

It also reduces the amount of behavior hidden inside individual accessor
classes.

## Migration Path

A practical incremental migration is:

1. add `Accessor.getTarget(parser)` and type metadata consistently
2. make `Parser.readTarget()` return a typed target
3. make `Parser.readValue(value_type)` dispatch from an explicit type
4. add `Parser.cast(value, value_type)`
5. move ordinary `Accessor.assign()` onto `readTarget()`, `readValue()`, and
   `target.set(...)`
6. rework arithmetic commands to bind a target once, use locals for
   `current_value` / `scratch`, and then `target.set(...)`

This keeps the change incremental while still moving toward the cleaner
execution model.
