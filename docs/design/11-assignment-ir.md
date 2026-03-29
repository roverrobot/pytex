# Assignment IR

This note consolidates the current direction for assignment execution.

The main idea is to make assignments target-centric.

Instead of threading `(domain, key)` pairs through every assignment-like
operation, the parser should own an explicit target register and a small number
of typed value holders.

## Main Conclusion

Assignments should be expressed in terms of parser operations such as:

- `readTarget()`
- `setTarget(target, target_type)`
- `get(use_scratch=False)`
- `set(global_scope=False, use_scratch=False)`
- `readValue(use_scratch=False)`

Under this model:

- accessors parse target syntax
- the parser owns the active target
- the parser owns typed value reading
- the parser owns target reads and writes
- `afterAssignment()` remains a separate operation from `set()`

This is a better fit for the execution-IR direction than letting accessors keep
their own ad hoc read/write logic.

## Runtime Registers

The parser should own these assignment-related registers:

- `target`
- `target_type`
- `current_value`
- `scratch`
- `scratch_type`

`target` is the active location being assigned to or read from.

`target_type` is the type restriction for that location.

Examples:

- `INT`
- `DIMEN`
- `GLUE`
- `MUGLUE`
- `TOKS`
- `BOX`
- `FONT`

`current_value` is the main value holder used by `get()`, `readValue()`, and
later `set()`.

`scratch` is the secondary holder used when a command needs an extra operand.

`scratch_type` is needed because the scratch operand does not always have the
same type as the target.

Example:

- `\multiply\dimen0 by 2`
- target type is `DIMEN`
- scratch type is `INT`

So one persistent target type is not enough by itself.

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

So `target` is "where", while `target_type` is "what kind of value belongs
there."

## Parser Operations

### `readTarget()`

This operation reads the next assignment target and loads:

- `parser.target`
- `parser.target_type`

It should be implemented through accessors.

### `setTarget(target, target_type)`

This operation sets the active target registers explicitly.

It is useful when:

- a command wants to bind a target once and reuse it later
- a delayed assignment needs to preserve the target
- an operation such as `\setbox` or `\read` needs to carry target information
  across more parsing

### `get(use_scratch=False)`

This operation reads from `parser.target`.

By default it loads the result into `current_value`.

If `use_scratch=True`, it loads into `scratch` instead.

The value loaded by `get()` must conform to `target_type`.

### `set(global_scope=False, use_scratch=False)`

This operation writes to `parser.target`.

By default it stores `current_value`.

If `use_scratch=True`, it stores `scratch`.

The stored value must conform to `target_type`.

This is a pure state-write operation. It should not implicitly run
`\afterassignment`.

### `readValue(use_scratch=False)`

This operation reads a value from input according to the destination type.

The rule is:

- if reading into `current_value`, use `target_type`
- if reading into `scratch`, use `scratch_type`

So `readValue()` should not take an explicit type argument.

The parser should instead dispatch through a reader table keyed by the active
type:

- `INT -> readInteger`
- `DIMEN -> readDimen`
- `GLUE -> readGlue`
- `TOKS -> readGeneralText` or token-list reader
- etc.

Commands that need a truly special scan rule can still use a specialized parser
method directly.

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
3. load `parser.target = target`
4. load `parser.target_type = accessor.target_type`

This means the accessor parses target syntax, but the parser performs the
execution-layer state changes.

## Ordinary Assignment Shape

The normal assignment flow becomes:

1. read the accessor command
2. `readTarget()`
3. `readEq()`
4. `readValue()`
5. apply prefixes to determine final `global_scope` and any value modification
6. `set(global_scope=...)`
7. `afterAssignment()`

This gives a clean separation:

- `set()` is state mutation
- `afterAssignment()` is assignment completion

That distinction matters because not every future use of `set()` will represent
a TeX assignment. For example, layout-layer updates like `prevdepth` should not
trigger `\afterassignment`.

## Arithmetic Shape

Arithmetic commands become much cleaner under this model.

### `\advance`

1. `readTarget()`
2. `get()`
3. set `scratch_type = target_type`
4. `readKeyword(["by"])`
5. `readValue(use_scratch=True)`
6. compute from `current_value` and `scratch`
7. `set(global_scope=...)`
8. `afterAssignment()`

### `\multiply` / `\divide`

1. `readTarget()`
2. `get()`
3. set `scratch_type = INT`
4. `readKeyword(["by"])`
5. `readValue(use_scratch=True)`
6. compute from `current_value` and `scratch`
7. `set(global_scope=...)`
8. `afterAssignment()`

This is one of the main reasons `scratch_type` is needed.

## Why This Is More IR-Centric

This design shifts the important work into parser operations:

- target binding
- typed value scanning
- target reads
- target writes
- assignment completion

That makes command implementations read more like short execution programs over
a fixed parser-op vocabulary.

It also reduces the amount of behavior hidden inside individual accessor
classes.

## Migration Path

A practical incremental migration is:

1. add `target`, `target_type`, `scratch_type`, and `setTarget(...)` to
   `Parser`
2. add `Accessor.getTarget(parser)` and type metadata consistently
3. make `Parser.readTarget()` populate the target registers
4. make `Parser.readValue()` dispatch from `target_type` / `scratch_type`
5. move ordinary `Accessor.assign()` onto `readTarget()`, `readValue()`, and
   `set()`
6. rework arithmetic commands to use `get()`, `readValue(use_scratch=True)`,
   and `set()`

This keeps the change incremental while still moving toward the cleaner
execution model.
