# Assignment IR

This note supersedes the older target-centric read model.

The key conclusion is:

- a token occurrence is either read as a value
- or parsed as an assignment head
- but not both through one shared target contract

So the runtime contract should split cleanly into:

- read-side value production
- write-side assignment production

## Main Conclusion

The stable command-side interface should be:

- `fetchValue(parser, requested_type) -> (value, value_type)`
- `getAssignment(parser) -> Assignment | None`

with the convention:

- unsupported read: `(None, None)`
- supported read:
  - `(value, requested_type)` when the command chooses to satisfy the request directly
  - or `(value, native_type)` when the native type matters
  - notably, `(None, type)` is a valid successful read of a typed `None` value
- `requested_type == UNKNOWN` asks for the native readable form

And the stable parser-side interface should be:

- `readValue(value_type) -> value`
- `readInternalValue(value_type, expand=True) -> value | None`
- `readAssignment() -> Assignment | None`
- `cast(value, value_type) -> value | None`
- `resolveGlobalScope(global_scope=False) -> bool`
- `afterAssignment()`

The important split is:

- read side returns data
- assignment side returns a write action

There is no need for a read target abstraction.

## Why Read Targets Go Away

On the read path, we never operate on the true storage location.

We only need:

- the resulting value
- and sometimes the value's native type

We do **not** need:

- a mutable location
- a `readable` flag
- a bound storage wrapper whose only purpose is to be immediately dereferenced

So the old idea of "read target" is the wrong abstraction.

A read is just:

- "can this command occurrence produce a value of the requested shape?"

If yes, return the value.
If not, report failure in-band.

## Read-Side Contract

The read-side command hook is:

```python
value, value_type = meaning.fetchValue(parser, requested_type)
```

with these rules:

- the default implementation returns `(None, None)`
- commands that are not readable need do nothing special
- a readable command may consume trailing syntax only after it knows it can
  satisfy the requested read

This last point is important for commands like:

- `\count`
- `\dimen`
- `\skip`
- `\fontdimen`

because reading them may consume additional syntax such as register indices.

So the command must decide read compatibility **before** it consumes that
trailing syntax.

## `UNKNOWN` Requests

`VALUE_TYPE.UNKNOWN` means:

- "give me your native readable capacity"

This is the right interface for:

- `\the`
- other introspection-like reads that want the command's true readable form

Examples:

- `\count0` can return `(0, INT)`
- `\font` can return `(current_font, FONT)`
- `\toks0` can return `(token_list, TOKS)`

So `UNKNOWN` is not "cast to anything". It is "report your native readable
kind".

## Assignment-Side Contract

The assignment-side hook is:

- `getAssignment(parser) -> Assignment | None`

This replaces the older `.assign(...)` command contract.

A command provides `getAssignment(...)` if and only if it can act as an
assignment head.

That means:

- read-only commands simply return `None`
- prefixes are assignment-only wrappers
- plain value commands need not pretend to be target-like

## Assignment Object

The assignment result should be a small structured object rather than a raw
tuple.

The minimal shape is:

```python
Assignment(
    target=...,
    value=...,
    global_scope=False,
)
```

The target here is a true write target. Unlike the read path, the assignment
path really does care about the underlying storage location.

This object exists so prefixes can modify assignment semantics without changing
every caller's tuple protocol.

That is useful for things like:

- `\global`
- `\long`
- `\protected`
- future assignment modifiers

## Write Targets Still Matter

Removing read targets does **not** mean removing write targets.

Write targets are still the right abstraction for committed storage mutation.

The write-side target vocabulary remains:

- `target.value_type`
- `target.set(value, global_scope=False) -> value`

And the existing concrete target forms remain useful:

- `KeyTarget`
- `AttrTarget`
- specialized write targets such as box-dimension slots

The only thing that goes away is the idea that reads should be expressed
through those same target objects.

## Parser-Side Internal Reads

`Parser.readInternalValue(value_type, expand=True)` should now work like this:

1. read the next token, expanded or raw depending on `expand`
2. ask its meaning for `fetchValue(parser, value_type)`
3. if the returned type is `None`, unread the token and fail
4. if the returned type differs from the requested type, cast at the parser layer
5. return the final value

So parser-side coercion still exists, but only after the command has already
decided that this occurrence is readable.

This is much cleaner than:

- binding a read target
- checking `readable`
- calling `target.get()`
- then casting

## Parser-Side Assignment Reads

`Parser.readAssignment()` should:

1. read the next expanded token
2. ask its meaning for `getAssignment(parser)`
3. if no assignment is available, unread the token and return `None`
4. otherwise return the resulting `Assignment`

Then ordinary assignment execution becomes:

1. `assignment = parser.readAssignment()`
2. resolve final global scope
3. `assignment.target.set(assignment.value, global_scope=...)`
4. `parser.afterAssignment()`

That is a simpler and more explicit model than having command execution call
back into `.assign(...)`.

## Prefixes

Prefixes should provide:

- no read-side value capacity
- assignment-side forwarding only

So for prefixes:

- `fetchValue(...)` returns `(None, None)`
- `getAssignment(parser)` reads the next assignment and modifies it

This matches TeX semantics much better than pretending that prefixes are
general readable commands.

Examples:

- `\global` forwards the next assignment and changes global scope
- `\long` forwards macro definition assignment and marks the resulting macro value
- `\protected` does the same for protected macro definitions

## Accessors

Under this design, an accessor's real responsibilities are:

- parse assignment-head syntax
- optionally parse read syntax when it is readable
- expose write target type
- expose RHS value-reading type where appropriate

So the old single method:

- `getTarget(parser)`

should split conceptually into:

- read-side `fetchValue(...)`
- write-side `getAssignment(...)`

The old mixed "accessor is both a readable target provider and an assignment
provider through one hook" is exactly what this design is trying to remove.

## `\the`

`\the` is the clearest motivation for the new contract.

It does not want:

- a bound read target

It wants:

- the native readable value of the following command occurrence

So `\the` should request:

- `fetchValue(parser, UNKNOWN)`

and then serialize according to the returned native type.

That is more direct and much closer to what TeX conceptually does.

## Arithmetic Commands

Arithmetic commands such as `\advance`, `\multiply`, and `\divide` are purely
assignment-side consumers.

They should:

1. read an `Assignment`
2. inspect the target type from `assignment.target.value_type`
3. read the operand appropriately
4. compute the new value
5. write back through the target
6. trigger `afterAssignment()`

So these commands do not need read-target semantics either.

## `\globaldefs` And `\afterassignment`

These remain parser-side assignment policy, not target semantics.

### `\globaldefs`

The final global write mode is still computed outside the target:

- prefixes/requested assignment scope produce a boolean
- `parser.resolveGlobalScope(...)` adjusts it
- the resulting boolean is passed to `target.set(...)`

### `\afterassignment`

Likewise:

- the assignment commits
- then `parser.afterAssignment()` runs

This remains separate from storage mutation itself.

## Token Lists And Non-Expanding Reads

Some internal reads should still avoid expansion, for example token-list
sources such as marks.

That stays a parser concern:

- `readInternalValue(VALUE_TYPE.TOKS, expand=False)`

The new read-value contract does not change that. It only changes what the
command returns once the token has been identified.

## Migration Strategy

The safest migration path is incremental.

### Step 1

Add the new command hooks:

- `fetchValue(parser, requested_type)`
- `getAssignment(parser)`

with conservative defaults.

### Step 2

Add a small `Assignment` object and make ordinary accessors produce it.

### Step 3

Switch `Parser.readInternalValue(...)` to the new read-side contract.

### Step 4

Switch prefixes and ordinary assignment execution to `readAssignment()`.

### Step 5

Remove the older mixed contract:

- `getTarget(...)` for reads
- `.assign(...)`

once the call sites are gone.

## Summary

The final design is:

- reads return values
- assignments return assignment objects
- write targets remain real targets
- read targets disappear
- `UNKNOWN` requests return native readable capacity
- prefixes are assignment-only modifiers

That is both simpler than the old target-centric read model and closer to the
actual TeX split between:

- "read this token occurrence as a value"
- "parse this token occurrence as an assignment head"
