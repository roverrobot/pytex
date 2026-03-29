# Assignment IR

This note records the assignment and internal-value design that the codebase now
uses.

The design is target-centric:

- commands bind a target
- the parser reads values by `VALUE_TYPE`
- bound targets own the concrete get/set semantics
- assignment policy such as `\globaldefs` and `\afterassignment` stays outside
  the target itself

## Main Conclusion

The execution vocabulary for assignment-like commands is:

- `readTarget() -> target | None`
- `readValue(value_type) -> value`
- `readInternalValue(value_type, expand=True) -> value | None`
- `cast(value, value_type) -> value | None`
- `resolveGlobalScope(global_scope=False) -> bool`
- `afterAssignment()`

And the bound target vocabulary is:

- `target.value_type`
- `target.get() -> value`
- `target.set(value, global_scope=False) -> value`

This is the stable split:

- `Parser` owns scanning, typed readers, coercion, and assignment-adjacent
  policy
- `Accessor` owns target syntax
- `target` owns the already-bound storage semantics

## Target Model

The runtime does not use parser-owned `target`, `current_value`, or `scratch`
registers.

Those are still useful conceptual names, but the implementation uses ordinary
Python locals. This avoids stack/save-restore machinery for nested scans such
as:

- `\advance\count0 by \count1`
- `\multiply\dimen0 by \count2`

So the runtime shape is:

- `target = parser.readTarget()`
- `value = parser.readValue(target.value_type)`
- `current = parser.get(target)` when needed
- `value = parser.cast(value, target.value_type)` when needed

The target itself carries the type information needed for assignment and
internal reads.

## Concrete Target Types

The current code uses three concrete target forms in
[pytex/accessor.py](/Users/jma/dev/pytex/pytex/accessor.py):

- `KeyTarget`
  - backed by `domain[key]`
  - optionally uses `domain.setGlobal(key, value)` when supported
- `AttrTarget`
  - backed by `getattr(obj, attr)` / `setattr(obj, attr, value)`
- `ReadOnlyTarget`
  - stores a readable value directly
  - rejects writes

This is enough for the current engine:

- plain registers and parameters use `KeyTarget`
- object-backed locations such as box dimensions use `AttrTarget`
- read-only internal values use `ReadOnlyTarget`

Examples of read-only targets:

- `\chardef` values
- `\mathchardef` values
- fixed integer commands
- e-TeX read-only introspection values
- mark token-list readers

## Parser-Side Target Operations

### `readTarget()`

`Parser.readTarget()` is a scanner operation.

It:

1. reads the next expanded token
2. checks whether its meaning supports `getTarget(parser)`
3. returns the bound target when available
4. otherwise unreads the token and returns `None`

So `readTarget()` is now the normal entry point for target-based commands such
as:

- `\the`
- arithmetic assignments
- box reads
- internal-value readers

### `get(target)` and `set(target, value, global_scope=False)`

`Parser.get()` and `Parser.set()` remain as thin convenience wrappers.

Semantically, the real behavior belongs to the bound target:

- `parser.get(target)` delegates to `target.get()`
- `parser.set(target, value, ...)` delegates to `target.set(...)`

This means parser-side get/set are convenience parser ops, not the true owner
of storage semantics.

## Value Types

The current type family is represented by `VALUE_TYPE` in
[pytex/accessor.py](/Users/jma/dev/pytex/pytex/accessor.py):

- `INT`
- `DIMEN`
- `GLUE`
- `MUGLUE`
- `BOX`
- `TOKS`
- `FONT`
- `MEANING`

The important rule is:

- targets carry their own `value_type`
- parser readers and casts dispatch from that type

## Parser Value Readers

The parser now has a reader table keyed by `VALUE_TYPE`, exposed through
`Parser.readValue(value_type)` in
[pytex/parser.py](/Users/jma/dev/pytex/pytex/parser.py).

Conceptually:

- `INT -> readInteger`
- `DIMEN -> readDimen`
- `GLUE -> readGlue`
- `MUGLUE -> readGlue(mu=True)`
- `BOX -> readBox`
- `TOKS -> readToks`
- `FONT -> readFont`

This means ordinary typed accessors no longer need to implement their own RHS
reader logic. They can simply say what type they carry.

## Internal Value Reads

`Parser.readInternalValue(value_type, expand=True)` is the generic internal
value reader.

Its behavior is:

1. read one token, expanded or raw depending on `expand`
2. if the meaning supports target binding, bind the target
3. if the target is readable, call `target.get()`
4. cast the result to the requested type
5. if that fails, unread the token and return `None`

The only remaining non-target fallback is for special meaning-like values such
as `MEANING`.

So integer, dimension, glue, token-list, font, and box internal reads now all
prefer the target path.

## Accessor Role

The important role of an accessor is now:

- parse target syntax
- expose `target_type` / `value_type`
- optionally customize `getTarget(parser)`
- reuse the generic assignment flow

Plain typed array/parameter accessors are no longer meaningful subclasses.

Instead, [pytex/accessor.py](/Users/jma/dev/pytex/pytex/accessor.py) provides
`typedAccessor(value_type, read_key=None)`, which returns a generator for a
plain configured `Accessor`.

So the common families now mean:

- "make me an accessor whose target/value type is `INT`"
- "make me an accessor whose target/value type is `DIMEN`"
- etc.

Only genuinely special accessors remain real subclasses, for example:

- equitable accessors
- font character and font dimension accessors
- box dimension accessors
- guarded accessors such as `\spacefactor`, `\prevgraf`, `\badness`

## Ordinary Assignment Shape

The normal assignment flow is now:

1. bind the target
2. `readEq()`
3. `value = readValue(self.value_type)`
4. apply prefixes
5. `global_scope = parser.resolveGlobalScope(global_scope)`
6. `target.set(value, global_scope=global_scope)`
7. `parser.afterAssignment()`

That is implemented by the generic `Accessor.assign()` path in
[pytex/accessor.py](/Users/jma/dev/pytex/pytex/accessor.py).

The key separation is:

- `target.set(...)` is storage mutation
- `afterAssignment()` is one-shot assignment completion

## Arithmetic Shape

Arithmetic commands are now target-driven rather than accessor-driven.

The intended shape is:

1. `target = parser.readTarget()`
2. `current = parser.get(target)`
3. read the operand
4. compute
5. `parser.set(target, result, global_scope=...)`
6. `parser.afterAssignment()`

The command should reject failure through target semantics, not through an
independent "must be an accessor" rule.

So read-only targets naturally reject:

- `\advance\foo by 1` when `\foo` is a read-only integer value

## `\globaldefs` And `\afterassignment`

These do not belong on the target itself.

### `\globaldefs`

`\globaldefs` is assignment policy, not storage semantics.

So the final rule is:

- prefixes produce a requested `global_scope`
- assignment code calls `parser.resolveGlobalScope(...)`
- the resulting boolean is passed to `target.set(...)`

### `\afterassignment`

`\afterassignment` is also separate from `target.set(...)`.

The assignment command calls:

- `parser.afterAssignment()`

after the assignment actually commits.

This matters for delayed assignments such as `\setbox`, where the write and the
assignment completion are not necessarily at the same earlier scan point.

## Box And Token-List Notes

Two cases were subtle enough to matter for the final design:

### Box Reads

Box reads now follow the same target model for true box-valued meanings such as:

- `\box`
- `\copy`
- `\lastbox`
- `\vsplit`

Builder commands such as `\hbox`, `\vbox`, and `\vtop` remain explicit
box-building readers rather than simple value targets.

### Token Lists

Token-list internal reads use:

- `readInternalValue(VALUE_TYPE.TOKS, expand=False)`

because token-list sources such as marks must be recognized without expansion.

So `TOKS` follows the same target model, but with a non-expanding internal-read
entry point.
