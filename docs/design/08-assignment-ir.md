# Assignment and Internal-Value Reading

This note describes the current assignment and internal-value reading model in
pytex.

It sits above token flow and parser state. At this layer, a token occurrence may
be interpreted in two different ways:

- as an internal value that another command wants to read
- as an assignment head that will eventually write to some storage location

The current code has largely moved to that split, but it has not removed every
older target-oriented helper. In particular, `Accessor` still uses `getTarget()`
internally, and arithmetic assignments still use `Parser.readTarget()`
directly.

## Scope

This note covers:

- how internal values are read from command occurrences
- how assignments are parsed and applied
- the current `Assignment` object
- prefixes such as `\global`, `\long`, `\outer`, and `\protected`
- how write targets are represented
- the remaining target-oriented compatibility path

This note does not cover:

- tokenization or input-stack mechanics
- grouped state semantics themselves
- list building or typesetting
- page building or shipout

## Main Conclusion

The current parser-facing split is real, but it is not absolute.

For ordinary internal-value reads, the parser now asks the meaning of the next
token whether that token occurrence can be read as a value. For ordinary
assignments, it asks whether that token occurrence can be parsed as an
assignment head. Those two paths are represented by:

- `meaning.fetchValue(parser, requested_type)`
- `meaning.getAssignment(parser)`

On the parser side, the main entry points are:

- `Parser.readInternalValueInfo(value_type, expand=True)`
- `Parser.readInternalValue(value_type, expand=True)`
- `Parser.readAssignment(expand=True)`

However, the implementation is still partly target-based under the hood:

- `Accessor.fetchValue()` still binds a target and reads through it
- `Accessor.getAssignment()` still binds a target and packages it into an `Assignment`
- `Parser.readTarget()` still exists and is still used by `\advance`, `\multiply`, and `\divide`

So the current code is best described as a mixed but coherent model:

- the parser-level interface is mostly split into read-side and assignment-side paths
- the accessor implementation still reuses bound targets as an internal convenience

## Command-Side Interfaces

Every command may optionally support either or both of these interfaces.

### Internal Value Reading

A readable command implements:

```python
fetchValue(parser, requested_type) -> (value, actual_type)
```

The return convention is:

- `(None, None)` means that this token occurrence is not readable in the requested way
- `(value, actual_type)` means success

The requested type is one of `accessor.VALUE_TYPE`.

The important cases are:

- concrete requests such as `INT`, `DIMEN`, `GLUE`, `TOKS`, `FONT`, and so on
- `UNKNOWN`, which asks for the command occurrence's native readable type

This is the interface used by commands such as `\the`.

### Assignment Parsing

An assignment head implements:

```python
getAssignment(parser) -> Assignment | None
```

Returning `None` means that the token occurrence is not an assignment head.
Returning an `Assignment` means that the assignment has already been parsed far
enough to identify:

- the write target
- the value to be written
- whether the assignment itself requested global scope

In the common case, the command's `execute()` method simply does:

```python
self.getAssignment(parser).apply(parser)
```

## Parser-Side Value Reading

The main parser helper is:

```python
Parser.readInternalValueInfo(value_type, expand=True)
```

Its current behavior is:

1. read the next token, expanded or raw depending on `expand`
2. call `meaning.fetchValue(parser, value_type)` on that token occurrence
3. if the command does not support the requested read, unread the token and return `(None, None)`
4. if the command returned a value of another compatible type, cast it at the parser layer when possible
5. return the final `(value, actual_type)` pair

`Parser.readInternalValue(value_type, expand=True)` is just the value-only
wrapper around that helper.

This is the path used by commands such as `\the`, by box readers that first
try to interpret the next token as an internal box value, and by many other
TeX-style internal-quantity readers.

### `UNKNOWN` Requests

`VALUE_TYPE.UNKNOWN` means "tell me your native readable kind".

That matters most for `\the`. In the current code, `\the` calls:

```python
parser.readInternalValueInfo(accessor.VALUE_TYPE.UNKNOWN)
```

and then formats the result according to the returned type.

Typical examples are:

- `\count0` returning an integer value
- `\dimen0` returning a dimension
- `\toks0` returning a token list
- `\font` or `\nullfont` returning a font value

## Parser-Side Assignment Reading

The parser helper for assignments is:

```python
Parser.readAssignment(expand=True)
```

Its current behavior is:

1. read the next token, expanded or raw depending on `expand`
2. call `meaning.getAssignment(parser)`
3. if the command is not an assignment head, unread the token and return `None`
4. otherwise return the parsed `Assignment`

This helper exists and works, but not every assignment-like command currently
uses it.

In particular:

- ordinary accessors implement `getAssignment()` directly
- prefixes implement their own forwarding logic
- arithmetic commands still use `Parser.readTarget()` rather than `Parser.readAssignment()`

So `readAssignment()` is part of the current model, but it is not yet the only
assignment entry point.

## The `Assignment` Object

The common assignment object is `accessor.Assignment`.

It stores:

- `target`
- `value`
- `global_scope`

Its default `apply(parser)` method does three things:

1. resolve final global scope through `parser.resolveGlobalScope(...)`
2. write through `target.set(...)`
3. run `parser.afterAssignment()`

This means that `Assignment` is more than just a tuple. It is the current hook
where assignment policy and storage mutation meet.

### Specialized Assignment Objects

The current code also uses specialized assignment subclasses when the default
write-immediately behavior is not enough.

The main example is `box.SetBoxAssignment`, whose `apply()` method may defer the
final box write until the relevant box-building group closes. So the current
model already allows assignment objects to control more than one simple
`target.set(...)` call.

## Accessors

`Accessor` is still the main abstraction for register-like and parameter-like
commands.

An accessor knows:

- which domain it writes to
- whether it has a fixed key or must read one from the input
- what value type it naturally reads and writes

The important current point is that `Accessor` still uses `getTarget()` as its
internal unifying mechanism.

### Current `Accessor.fetchValue()`

The default accessor read path is:

1. check whether the accessor can be read as the requested type
2. bind a target with `getTarget(parser)`
3. read from that target with `target.get()`
4. return `(value, target.value_type)`

So although the parser-level interface is now `fetchValue(...)`, accessors still
implement that interface by binding targets under the hood.

### Current `Accessor.getAssignment()`

The default accessor assignment path is:

1. bind the key if necessary
2. bind the target with `getTarget(parser)`
3. read the optional `=` according to that accessor's syntax
4. read the right-hand-side value through `readValue(parser)`
5. return `Assignment(target, value)`

So accessors are still the central place where a command occurrence becomes a
specific register or parameter slot.

## Write Targets

Write targets still matter in the current code.

The main target classes are:

- `KeyTarget`, for values stored as `domain[key]`
- `AttrTarget`, for values stored through an object's attribute
- `ReadOnlyTarget`, for readable values that are not writable

These targets carry:

- a `value_type`
- a `get()` method when readable
- a `set(value, global_scope=False)` method when writable

This remains important because not every assignment target is a simple domain
entry. For example:

- `\fontdimen` uses an attribute-backed slot object
- some box-dimension accessors use attribute-backed targets
- `\font` without a control-sequence target uses a `ReadOnlyTarget` when read as the current font

So the code has not moved to a target-free design. It has instead moved to a
parser API where targets are mostly hidden behind `fetchValue(...)` and
`getAssignment(...)`, except where commands still need direct target access.

## Prefixes

Prefixes are modeled as assignment modifiers, not as ordinary readable values.

The shared implementation lives in `accessor.Prefix`.

A prefix does the following:

1. skip TeX filler with `skipFiller()`
2. read the next raw token with `parser.token()`
3. require that token's meaning to support `getAssignment(parser)`
4. modify the resulting `Assignment`
5. return the modified assignment

The current prefixes include:

- `\global`, which forces `assignment.global_scope = True`
- `\long`, which marks a macro value as long
- `\outer`, which marks a macro value as outer
- `\protected`, which marks a macro value as protected

This is one reason the assignment object matters: prefixes can modify an already
parsed assignment without reimplementing every assignment head.

## Global Scope And `\afterassignment`

These two pieces remain parser-side assignment policy.

### `\globaldefs`

Final global scope is resolved by:

```python
parser.resolveGlobalScope(global_scope)
```

The parser checks the current `globaldefs` parameter and then decides whether
the final write is local or global.

So global scope is not a property of the target itself. It is computed at apply
time.

### `\afterassignment`

After a successful assignment, the parser runs:

```python
parser.afterAssignment()
```

This unreads the pending `afterassignment` token, clears the stored slot, and
returns the token if there was one.

Again, this is assignment policy around the write, not a property of the target.

## Arithmetic Commands

`\advance`, `\multiply`, and `\divide` are the clearest remaining place where
the older target-oriented path still appears directly.

Their current flow is:

1. call `parser.readTarget()`
2. read the current value with `parser.get(target)`
3. read the `by` operand according to `target.value_type`
4. compute the new value
5. return `Assignment(target, value)`

So these commands do not yet go through `parser.readAssignment()`.

This is not inconsistent with the current design, but it does mean that the old
bound-target vocabulary still exists in active use.

## Readable Commands That Are Not Plain Accessors

Not every readable command is a plain accessor.

Examples in the current code include:

- `CharDefValue`, which reads as an integer command value
- `Font` objects, which read as font values
- `\box`, whose readable form may also clear a box register
- `\copy`, whose readable form returns a copy of a box register
- `\lastbox`, which reads from the current list and may pop the last box

So the read-side contract is wider than registers and parameters. Any command
may implement `fetchValue(...)` if a token occurrence can be treated as an
internal quantity. In the current code, some of these reads are not purely
observational: `\box` and `\lastbox` can change parser state while producing a
box value.

## What The Current Code Is Not

The current code is not the old mixed model where assignment execution was
hidden in ad hoc command methods with no common object shape.

But it is also not a fully completed "no targets on the read path" design.

In particular:

- `getTarget()` still exists and is still central inside `Accessor`
- `KeyTarget.readable` and `ReadOnlyTarget` still matter
- `Parser.readTarget()` is still present and still used

So the accurate description is:

- parser-visible reads and assignments are mostly split
- assignment application is centralized through `Assignment.apply()`
- target objects remain an important implementation tool
- some commands still work with bound targets directly

## Summary

The current assignment model has four main pieces.

- `fetchValue(...)` for reading token occurrences as internal values
- `getAssignment(...)` for parsing token occurrences as assignment heads
- `Assignment.apply(...)` for committing writes under parser policy
- bound targets as the storage-level abstraction that still underlies much of the implementation

That gives the code a cleaner structure than the older purely target-centric
model, while still keeping the target helpers that some current commands rely
on.
