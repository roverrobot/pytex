# Parser state in the current codebase

This note describes the current implementation in `parser.py` and `state.py`. It is not trying to define a minimal ideal IR. Instead, it explains how parser state is actually represented and manipulated in the code as it stands now.

## Scope

This note covers the part of execution that owns grouped state and assignment-related runtime hooks. In the current code, that mainly means:

- the parser-owned state containers initialized by `Parser.initState()`
- the concrete grouped-domain implementations in `state.py`
- group entry and exit, including callbacks and `\aftergroup`
- assignment-facing helpers such as bound targets, `\globaldefs`, and `\afterassignment`
- state dump and load for format-like serialization

This note does not try to describe the whole parser. `parser.py` also contains token expansion, mode handling, list building, math handling, page interaction, and many other concerns.

## What the parser owns

The parser does not expose parser state as a single abstract store object. Instead, `Parser.initState()` creates a fixed set of parser attributes:

- `groups`: a stack of outer groups
- `current_group`: the innermost open group, or `None`
- `globals`: ungrouped global runtime state
- `volatile`: a grouped dictionary for runtime values such as date and time
- `parameters`: a grouped dictionary for parameter-like values
- `equitable`: a grouped dictionary for control sequence meanings
- `layout`: a grouped dictionary for layout-related state
- `arrays`: a registry of array-like domains added by modules

So the current design is partly domain-based, but not through one generic domain registry. Some domains are fixed parser attributes, while array domains are registered dynamically by modules.

## The concrete domain types in `state.py`

`state.py` provides three concrete storage types.

### `Globals`

`Globals` is just a plain dictionary with a `setGlobal()` helper. It does not participate in grouping. It is used for parser runtime values that should ignore local scope.

### `Dict`

`Dict` stores `NamedEntry` objects internally. Reading `domain[key]` returns the entry's current value, while `entry(key)` returns the `NamedEntry` itself.

A `NamedEntry` knows:

- its owning parser state object
- its domain name
- its key
- its current value

A local write goes through `NamedEntry.set()`. If there is an open group, the old value is saved in that group the first time that `(domain, key)` is written in the current group. A global write goes through `NamedEntry.setGlobal()` and clears pending restores from active groups.

### `Array`

`Array` is the grouped array implementation. It uses a fixed list for indices below `SIZE` (currently `256`) and an overflow dictionary for larger indices. Like `Dict`, it records the old value on the first local write within a group, and a global write clears pending restores from open groups.

This means the current grouped-state logic is implemented directly inside `NamedEntry` and `Array`, not through a separate generic transaction layer.

## How groups are represented

A group is represented by `state.Group`. A `Group` stores:

- `group_type`
- `position`
- `to_end`: a callback run before local values are restored
- `ended`: a callback run after the group has been closed
- `aftergroup`: a list of queued tokens
- `values`: the saved old values that will be restored on exit

The parser keeps the innermost group in `current_group`, while older open groups live in `groups`. So `groups` is not the full stack by itself; the active top group is stored separately.

## How local and global writes work

The current grouped write rule is straightforward.

For a local write:

- if there is no open group, the value is written directly
- if there is an open group, the old value is saved only on the first write to that `(domain, key)` in the current group
- the live value is then updated in place

For a global write:

- the live value is updated in place
- pending restore entries for that `(domain, key)` are removed from the current and outer open groups

This behavior matches TeX-style grouping and is what `Dict` and `Array` currently implement.

## Group matching in the current code

Group matching is handled by `Group.match()`.

The current logic is not simply “start type must equal end type”. Exact matches are accepted, but most non-simple groups can also be closed by a `SIMPLE` end-group marker. The main exceptions are `SEMI_SIMPLE` and `MATH_SHIFT`, which require exact matching.

That reflects the fact that many TeX groups are opened by a special operation but closed by `}`.

## `Parser.beginGroup()` and `Parser.endGroup()`

The parser, not `state.Group`, owns the full open/close protocol.

`Parser.beginGroup()`:

- optionally rewrites a simple group in math mode into a subformula group
- pushes the previous `current_group` onto `groups`
- creates a new `state.Group`

`Parser.endGroup()` does the work in this order:

1. validate that a group is open and that the closing type matches
2. run `to_end(self)` if present
3. restore saved local values
4. pop the next outer group into `current_group`
5. run `ended(self)` if present
6. push any queued `aftergroup` tokens back to the input

That order matters. In particular, `to_end` sees the inner local state before restoration, while `ended` sees the restored outer state.

## Math-mode special case in `beginGroup()`

There is one important parser-level special case.

When `beginGroup()` is called with `GROUP_TYPE.SIMPLE` and the current list is a math list, the parser creates a subformula list and installs an `mmode.MathEndGroupCallback` as the `ended` callback. So, in current code, group entry is not purely a state operation; it can also change the active math-list structure.

## `\aftergroup`

`\aftergroup` is not stored in an ordinary state domain. The command in `toks.py` reads the next unexpanded token and appends it to `parser.current_group.aftergroup`.

When the group closes, `Parser.endGroup()` pushes that token list back into the input after restoration and after the `ended` callback runs.

So `\aftergroup` is group-local runtime state attached directly to `Group`, not to `globals`, `parameters`, or another named domain.

## `\afterassignment`

`\afterassignment` is implemented differently.

The command in `accessor.py` reads the next unexpanded token and stores it in `parser.globals["afterassignment"]`. Later, `Parser.afterAssignment()` checks that slot, unread-pushes the token back to the input if it exists, and then clears the slot.

This means `\afterassignment` is:

- global runtime state
- one-shot
- consumed by assignment completion
- not tied to group restoration

## Assignment handling is now target-based

This is the biggest place where the older note needs updating.

The parser no longer mainly works in terms of raw `(domain, key)` pairs. In current code, assignment-facing operations are organized around bound targets.

The key parser helpers are:

- `readTarget()`: read the next token occurrence and resolve it into a bound target if its meaning provides `getTarget()`
- `get(target)`: read from a bound target
- `set(target, value, global_scope=False)`: write through a bound target
- `readAssignment()`: parse an assignment occurrence if the meaning provides `getAssignment()`

Targets come from `accessor.py`. The main target classes are:

- `KeyTarget`, backed by `domain[key]`
- `AttrTarget`, backed by `getattr` and `setattr`
- `ReadOnlyTarget`, for readable but unwritable values

So the current parser-facing model is closer to:

- resolve command occurrence to a bound target
- read or write through that target

rather than a direct public API of `get(domain, key)` and `set(domain, key, scope)`.

## Reading internal values

`parser.py` also has a generic mechanism for reading internal values from command occurrences.

`readInternalValueInfo()` reads the next token, asks its meaning for `fetchValue()`, and returns both the value and its effective type. If needed, `Parser.cast()` performs a limited set of conversions, mainly along TeX-like numeric coercions such as integer, dimension, and glue.

This is adjacent to parser state because many internal values are read from grouped state, but the mechanism itself lives at the parser/meaning boundary, not in `state.py`.

## `\globaldefs` handling

Global-versus-local assignment is finalized by `Parser.resolveGlobalScope()`.

The current rule is:

- if `\globaldefs > 0`, force the write to be global
- if `\globaldefs < 0`, force the write to be local
- if `\globaldefs == 0`, use the caller's requested scope

Parsed assignments are represented by `accessor.Assignment`. Its `apply()` method resolves the final scope through `parser.resolveGlobalScope()`, performs the write through the target, and then runs `parser.afterAssignment()`.

## State dumping and loading

The current code does not attach dump behavior as a trait on each domain object. Instead, `Parser.dumpState()` explicitly chooses what to serialize.

At the moment, it dumps:

- `equitable`
- `parameters`
- `layout`
- all registered arrays in `parser.arrays`

It does not dump:

- `globals`
- `volatile`
- open groups
- `current_group`
- `groups`
- pending `aftergroup` queues

So the current code distinguishes persistent versus runtime-only state by parser policy in `dumpState()` and `loadState()`, not by a generic per-domain `dumped` flag.

## What is true in the current code, and what is not

A few points from the earlier note still describe the code well:

- parser state is still organized around named domains and grouped restoration
- `\aftergroup` and `\afterassignment` are separate from ordinary register writes
- arithmetic register updates can still be understood as read/compute/write at a higher level

But a few parts should be stated differently to match the implementation.

First, the parser-facing API is no longer best described as a raw `(domain, key)` algebra. Bound targets and parsed assignment objects are now the main interface.

Second, the code does not currently model domain traits such as `scoped` and `dumped` as first-class metadata. Grouping behavior is encoded by the concrete storage class, and persistence is decided by `Parser.dumpState()`.

Third, group entry and exit are not purely state operations. In `parser.py`, group transitions can also trigger mode-specific callbacks, math subformula handling, and input requeueing.

## Summary

The current implementation is best described as follows.

Parser state is a collection of parser-owned domains, mostly implemented by grouped `Dict` and `Array` containers plus an ungrouped `Globals` dictionary. Local writes save old values in the current `Group`, and group exit restores them. Global writes clear pending restores from all open groups.

The parser does not expose this mainly as a minimal `get(domain, key)` / `set(domain, key, scope)` interface. Instead, command occurrences are resolved into bound targets, assignments are parsed into `Assignment` objects, and writes are finalized through `\globaldefs` before `\afterassignment` is handled.

Group management also includes parser-level behavior beyond restoration: pre-close and post-close callbacks, math-mode special handling, and replay of `\aftergroup` tokens.

That is a more accurate description of the current `parser.py` and `state.py` than the earlier smaller IR-focused note.
