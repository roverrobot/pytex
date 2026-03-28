# Parser State Layer

This note narrows the execution layer down to one specific piece: parser state.

The goal is to describe the part of TeX execution that looks like a grouped
state machine over typed domains, without mixing in input-stack manipulation,
expansion, or layout building.

## Scope

This note covers:

- grouped domains and their items
- global-only state
- group entry and exit
- group-exit token queues such as `\aftergroup`
- assignment-adjacent hooks such as `\afterassignment`
- register update operations as sugar over reads and writes

This note does not cover:

- token expansion
- input stack operations
- macro execution
- node/list/box construction
- page building or shipout

Those belong to other layers.

## Core Model

At this layer, parser state is a collection of domains.

Each domain has:

- a name
- a key space
- a value type
- grouping behavior
- dump/load behavior

The current code already has this flavor in [pytex/state.py](/Users/jma/dev/pytex/pytex/state.py), with domains such as:

- `globals`
- `volatile`
- `parameters`
- `equitable`
- `layout`
- registered arrays such as `catcode`, `count`, `dimen`, `skip`, `toks`, and similar tables

The important abstraction is not whether a domain is implemented as a dict or an
array. The important abstraction is that commands read and write typed items in a
named domain.

## Core IR

The minimal grouped-state IR is:

- `read(domain, key)`
- `write(domain, key, scope)`
- `begin_group(kind)`
- `end_group(kind)`

Where:

- `domain` names the target state table
- `key` identifies the item within that table
- `scope` is `local` or `global`
- `kind` is the TeX group kind, such as simple group, hbox group, math group, or `\begingroup` group

In practice, provenance such as source position may also be attached for
diagnostics, but it is not part of the essential algebra.

The intended convention is that `write(domain, key, scope)` consumes the
current tagged execution value. The typed reader or constructor that ran just
before the write determines the value's type.

At a lower implementation level, this can still be understood as an explicit
store operation with a value argument. The public execution IR is simply
choosing to route that value through the shared execution holder.

## Why `key`, Not `index`

Some domains are naturally array-like, but not all are.

Examples:

- `catcode[codepoint]`
- `count[number]`
- `equitable[control_sequence]`
- `parameters[name]`

So `key` is the better general term. Array domains can still use integer keys.

## Group Semantics

Most domains are subject to grouping rules.

The local write rule is:

- on the first local write to `(domain, key)` in the current group, save the old value in the current group frame
- write the new value in place
- on `end_group`, restore the saved old values

The global write rule is:

- write the new value in place
- remove any saved restoration entries for that `(domain, key)` from open groups

This matches the current implementation in [pytex/state.py](/Users/jma/dev/pytex/pytex/state.py), where local writes capture previous values in the current `Group`, while global writes clear pending restores.

## Group Kind Matters

`begin_group` and `end_group` should carry group kind, not just nesting depth.

That matters for:

- mismatch validation
- tracing
- e-TeX introspection such as current group type and level
- special behavior at certain boundaries, such as output routine or math-related groups

So the IR should retain group kind even if many writes do not care about it directly.

## Scoped And Unscoped Domains

Not every domain is grouped.

At a minimum, the state layer should distinguish:

- grouped domains
- always-global domains

In the current code:

- `globals` is always global
- most other domains participate in grouping
- some domains are runtime-only and should not be dumped, even if they are grouped

This suggests that each domain should declare at least two traits:

- `scoped`: whether local writes are restored by group exit
- `dumped`: whether the domain participates in format/state serialization

## `\aftergroup`

`\aftergroup` is not an ordinary domain write.

It is a group-local queue attached to the current group frame. Conceptually, the
relevant operation is:

- `enqueue_group_exit_token(token)`

or, more explicitly:

- `aftergroup(token)`

Its behavior is:

- store the token on the current group frame
- when that group ends, return the queued tokens in order
- push those tokens back to the input stream after group restoration

So `\aftergroup` belongs next to group state, but not as a normal `(domain, key)` item.

## `\afterassignment`

`\afterassignment` is also adjacent to parser state, but it is different from
`\aftergroup`.

It is best modeled as a deferred assignment hook:

- `set_afterassignment(token)`
- `clear_afterassignment()`

Operationally:

- the token is stored in global runtime state
- the next completed assignment consumes it
- that token is then returned to the input stream

This is not grouped-state restoration. It is a one-shot execution hook tied to
assignment completion.

## Register Updates

Arithmetic assignment commands such as `\advance`, `\multiply`, and `\divide`
do not need a larger state algebra.

They can be understood as:

- `read(domain, key)`
- compute new value
- `write(domain, key, scope)`

If we want a more faithful execution trace, we can also admit a first-class
derived operation:

- `update(domain, key, op, scope)`

But this is a convenience form, not a new semantic primitive.

## Undefined Values

The state layer does not need a separate delete operation.

TeX-style "undefined" or "unset" states can usually be represented as a valid
stored value such as `None` or another distinguished sentinel of the domain's
value type.

So the core algebra stays small.

## I/O Is Adjacent, But Separate

I/O is observable execution state, but it is not grouped domain state.

Examples include:

- `openin`
- `openout`
- `read`
- `write`
- `closein`
- `closeout`

These effects should sit next to the parser-state layer, not inside the grouped
domain algebra itself.

## Relationship To Expansion

The parser-state layer is not the same thing as the input-stack or expansion
layer.

Commands like macro expansion, token re-reading, and scanner control operate on
top of this state and consult it, but they are a different effect family.

That separation is especially important for TeX because catcode-dependent
tokenization and expansion are stateful, but they are still not the same as
ordinary domain mutation.

## Proposed Summary

The parser-state layer is a grouped typed store plus a few adjacent runtime
hooks.

Its clean core is:

- `read(domain, key)`
- `write(domain, key, value, scope)`
- `begin_group(kind)`
- `end_group(kind)`

Nearby but still part of this layer's contract are:

- `aftergroup(token)`
- `set_afterassignment(token)`
- optional `update(domain, key, op, arg, scope)` sugar

Not part of this layer:

- expansion
- input-stack operations
- layout construction
- page building

This gives us a compact IR for parser state without pretending that all of TeX
execution reduces to grouped assignments.
