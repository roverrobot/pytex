# Parser Kernel

This note describes the current runtime structure of the parser as implemented in
`parser.py` and `state.py`.

At present, `Parser` is already the live execution kernel. There is no separate
runtime `State` object that owns the active execution state. Instead, `Parser`
owns the grouped domains, group stack, input stack, conditional stack, and list
stack directly, while `state.py` provides the reusable machinery for domains,
entries, saved values, arrays, and groups.

This note is broader than the parser-state note. The parser-state note focuses
on grouped state semantics. This note describes the larger runtime object that
owns those state components.

## Main Structure

The current `Parser` object owns both execution flow and grouped state.

In `Parser.__init__` and `Parser.initState()`, the parser sets up at least the
following runtime components:

- `input`, the input stack
- `ifstack`, the conditional stack
- `lists`, the current list-stack state
- `groups` and `current_group`, which hold active group frames
- grouped domains such as `volatile`, `parameters`, `equitable`, and `layout`
- `globals`, which is a separate always-global dictionary-like store
- `arrays`, which holds registered array domains such as registers and similar tables
- other runtime attributes such as `builtin`, `value_readers`, `current_token`,
  `lastbox`, `ended`, `jobname`, logging fields, and resolver-related state

So, in the current code, the parser is not just a front end over another live
state container. It is the live runtime object.

## What `state.py` Provides

Although `Parser` owns the live runtime state, `state.py` still contains the
core reusable machinery for grouped storage.

That file currently provides:

- `GROUP_TYPE`
- `Group`
- `Domain`
- `NamedEntry` and `NamedSavedValue`
- `Dict`
- `Array` and `ArraySavedValue`
- `Globals`
- the `\begingroup` and `\endgroup` command implementations

This is an important split in the current code base:

- `Parser` owns the live runtime objects
- `state.py` implements the storage and restoration machinery those objects use

So the code already follows the broad direction that the parser owns execution,
while `state.py` provides support classes rather than acting as the top-level
runtime owner.

## Domains In The Current Code

The key reusable abstraction in the current implementation is still the domain.

The main grouped dictionary-style domains created in `Parser.initState()` are:

- `volatile`
- `parameters`
- `equitable`
- `layout`

In addition, `Parser` owns `arrays`, which is a registry of array-like domains.
Those arrays are also grouped when they are constructed with the parser as their
state owner.

A domain entry is represented by `NamedEntry`. A local write saves the previous
value in the current group frame before updating the live entry. A global write
updates the live entry and asks the parser to remove any pending saved
restoration records for that location from open groups.

So the important abstraction is not a wrapper `State` object. It is the set of
group-aware domain and array classes.

## Group Ownership And Group Closing

Grouping is owned directly by `Parser`.

The parser keeps:

- `current_group` for the innermost open group
- `groups` for outer saved group frames

`Parser.beginGroup(...)` creates a new `state.Group` and makes it the current
group. `Parser.endGroup(...)` closes the current group, runs the close
callbacks, restores saved values, re-establishes the previous current group, and
then replays any `aftergroup` tokens.

The current close order in `Parser.endGroup(...)` is:

1. validate the group type
2. run `to_end`, if present
3. call `group.end(...)`, which restores saved values
4. restore the enclosing current group
5. run `ended`, if present
6. push any `aftergroup` token list back onto the input stack

That ordering matters, because the callbacks are not just metadata. They are
part of the active runtime behavior.

`Parser.beginGroup(...)` also contains a math-specific special case: when a
simple group starts while the current list is a math list, the parser creates a
subformula list and replaces the end callback accordingly. So group entry is not
just generic bookkeeping; it is also tied to the surrounding execution context.

## Input Stack, If-Stack, And List Stack

These structures are not grouped domains, but they are clearly part of the
parser kernel.

In the current code:

- the input stack is `parser.input`
- the conditional stack is `parser.ifstack`
- the list stack is `parser.lists`

This matches the practical runtime boundary much better than a model in which
only grouped assignments count as parser state. The live parser owns token flow,
conditional flow, and layout-context flow as well as grouped storage.

## Assignment And Value Flow

The current parser no longer uses a persistent `current_value` holder.

Instead, assignment and internal-value handling are done through direct parsing
operations such as:

- `readTarget()`
- `get(target)`
- `set(target, value, global_scope=...)`
- `readAssignment(...)`
- `readInternalValueInfo(...)`
- `readInternalValue(...)`
- `readValue(value_type)`

This means the parser is not currently organized around an assignment IR state
machine with a shared execution value slot. Parsed assignments are represented
by bound targets and explicit values, and temporary scratch data stays local to
the relevant operation.

That is the main reason `current_value` should not appear in this note.

## Globals In The Current Code

The code does have a separate always-global store, but it is not implemented as
ordinary parser attributes. Instead, `Parser.initState()` creates:

- `globals = state.Globals()`

`Globals` is a small dictionary-like object in `state.py` that is not subject to
group restoration.

So, at the moment, the code does **not** implement the stronger refactor idea of
turning global values into ordinary parser attributes with `__getitem__` and
`__setitem__` compatibility on `Parser`. The actual code still uses a dedicated
`globals` store.

Examples in the current code include `afterassignment`, `spacefactor`, and
`prevgraf`.

## `equitable` Versus A Specialized `eqtb`

The current code gives the control-sequence table some special operational
behavior, but it is not yet implemented as a separate `EqTable` class.

What is true in the current code is:

- `Parser` owns an `equitable` domain
- that domain is currently a `state.Dict`
- command tokens keep an `entry`
- token reads refresh `definition` from `entry.value`
- grouped redefinitions therefore work by mutating the value behind a stable entry object

So the runtime behavior already has some `eqtb`-like flavor. However, the data
structure is still a generic grouped dictionary. Any statement that the current
code already has a distinct `EqTable` would be inaccurate.

## Dump And Load Boundary

The parser also owns the grouped-state serialization boundary.

`Parser.dumpState()` currently dumps:

- `equitable`
- `parameters`
- `layout`
- all registered arrays in `parser.arrays`

`Parser.loadState()` restores the same categories.

Notably, the current dump/load path does **not** serialize every runtime field.
For example, `globals`, `volatile`, the input stack, the group stack, and other
runtime-only structures are outside this dump/load boundary.

So the effective serialization contract is narrower than “all parser state.” It
is specifically the parser-owned grouped state that is intended to survive the
format dump/load path.

## No Separate Live `State` Wrapper

The current code already makes one architectural point quite clear: there is no
separate live `State` wrapper sitting underneath the parser.

There is also no `parser.state = parser` compatibility layer in the current
code, and `Parser` is not a subclass of some runtime `State` class.

Instead, the ownership model is direct:

- `Parser` owns runtime execution state
- grouped domain helpers hold a reference back to the parser as their `state`
  owner
- those helpers consult `parser.current_group` and call `parser.remove(...)`
  when they need group-aware behavior

That is the actual current relationship between `parser.py` and `state.py`.

## Practical Summary

The current code can be summarized as follows.

- `Parser` is already the live execution kernel.
- Grouped domains and arrays are owned by `Parser`, not by a separate runtime state object.
- `state.py` provides reusable support classes for groups, entries, dictionaries, arrays, and globals.
- Group bookkeeping is owned directly by `Parser` through `groups` and `current_group`.
- The input stack, conditional stack, and list stack also live directly on `Parser`.
- The current parser does not use a persistent `current_value` execution holder.
- `globals` is still a dedicated always-global store, not just ordinary parser attributes.
- `equitable` still uses `state.Dict`; a specialized `EqTable` is still only a possible future refactor.
- Dump/load currently covers selected grouped domains and arrays, not the entire live runtime.

That is a more accurate description of the present code than a note framed as a
future refactor proposal.
