# Parser Kernel

This note describes the runtime object that should sit at the center of the
execution layer.

The main proposal is simple:

- the live execution state should be owned directly by `Parser`
- `state.py` should keep the reusable domain and grouping machinery
- `eqtb` should be treated as a specialized domain, not just another generic dict

This is a design note for the refactor starting on the `execution-ir` branch.

## Main Conclusion

The engine probably does not need a separate live `State` object.

Instead:

- `Parser` should be the execution kernel
- domains should be attached directly to `Parser`
- group bookkeeping should be attached directly to `Parser`
- token flow, conditionals, layout stack state, and execution holders should
  also live directly on `Parser`

So the runtime center becomes one object with a small number of clearly owned
subsystems.

## What The Parser Owns

At the execution level, `Parser` should own at least:

- domains
- group stack
- input stack
- if-stack
- list stack
- `current_value`
- other execution-local attributes such as `current_token` and debugging/tracing state

That gives a concrete runtime shape:

- domain state
- control-flow state
- token-flow state
- execution holders
- layout-construction bridge state

This is a better fit for the current code than splitting "parser logic" from a
second live object that merely stores most of the fields the parser already uses.

## Domains

The key state abstraction is not the `State` object itself. It is the domains.

Those domains are things like:

- parameter tables
- layout parameter tables
- register arrays
- token/register storage
- control-sequence meaning tables

So the important reusable abstractions are:

- `Dict`
- `Array`
- saved-entry objects
- group restore logic

Those should remain in `state.py` or another domain-oriented module even if the
top-level `State` container goes away.

## Groups

Grouping is part of the live execution kernel and should be owned by `Parser`.

That includes:

- `groups`
- `current_group`
- `beginGroup(...)`
- `endGroup(...)`
- saved-value invalidation for global writes

The `Group` class and saved-value helpers can still live in `state.py`, but the
owning runtime object should be the parser itself.

So the split becomes:

- parser owns group frames
- domain entries consult the parser for current grouping context
- group implementation details remain reusable helpers

## Input Stack, If-Stack, And List Stack

These are not "state domains" in the same sense as TeX registers or parameter
tables, but they are still part of the live execution kernel.

They should sit directly on `Parser`:

- input stack for scanner scheduling and unread tokens
- if-stack for conditionals
- list stack for layout construction context

This matters because the parser kernel is broader than grouped assignments.
It is the full execution environment.

## Execution Holders

The parser kernel should also own the execution holders described in the
execution IR notes:

- `current_value`

This is not a domain entry. It is a transient execution holder used while
parser ops run.

It belongs on the parser kernel for the same reason `current_token` already
does: it is part of the active execution machine, not part of grouped TeX
register state.

Temporary scratch values are still needed sometimes, for example in:

- `\futurelet`
- `\expandafter`
- some condition tests

But those do not need to become a persistent parser register if we are not
materializing explicit IR objects. In the implementation, they can usually stay
as local variables inside the relevant parser method or command logic.

## Globals

Globals are different from grouped domains because they are not restored by
group exit.

That suggests a simpler runtime representation:

- make global values ordinary parser attributes

Examples include things like:

- open file tables
- previous depth
- dead-cycle counters
- runtime-only insert scratch structures
- other non-grouped execution state

This removes the need to treat globals as just another domain when they do not
share the same semantics.

## Compatibility For Globals

Even if globals become ordinary parser attributes, compatibility is still
important during the refactor.

The simplest compatibility story is:

- provide `Parser.__getitem__`
- provide `Parser.__setitem__`

for the global-like lookup pattern currently used in some places.

That lets old code keep an indexed style where helpful, while new code can
gradually move toward direct parser attributes.

If we want a narrower compatibility boundary, we can also keep a lightweight
`globals` adapter object that forwards into parser attributes. But the main
runtime ownership should still be on `Parser`.

## `eqtb` / Equitable

The control-sequence table is special and should be treated as special.

The current code already gives it unusual behavior:

- command tokens keep a stable `entry`
- token reads refresh `definition` from `entry.value`
- grouped redefinitions mutate the value behind that stable entry

That is much closer to TeX's `eqtb` than to an ordinary generic dict domain.

So the design should be:

- keep generic `Dict` and `Array` for most domains
- split `equitable` into a specialized `EqTable`
- likely rename the public concept to `eqtb`

This specialized table should provide:

- stable entry objects for command tokens
- efficient meaning refresh
- ordinary grouped/local/global assignment semantics

In other words, `eqtb` is still a domain, but it is a specialized domain.

## What Stays In `state.py`

After the refactor, `state.py` should still be valuable.

It should keep the machinery for:

- `GROUP_TYPE`
- `Group`
- saved-value objects
- generic domain abstractions such as `Dict` and `Array`
- maybe `EqTable` once that is introduced

What it should probably stop being is the owner of the live execution kernel.

## Migration Strategy

The safest refactor path is incremental.

### Step 1

Move the live fields onto `Parser`:

- groups
- current group
- domains
- arrays
- execution holders such as `current_value`

### Step 2

Keep a compatibility alias during transition:

- `parser.state = parser`

This allows existing `parser.state.foo` call sites to keep working while the
codebase is migrated gradually.

### Step 3

Adjust domain helpers so they refer to a generic owner rather than a dedicated
`State` container type.

### Step 4

Introduce a specialized `EqTable` for the control-sequence table.

### Step 5

Gradually replace `parser.state.` call sites with direct parser ownership where
that improves clarity.

## Why Not Subclass `State`

Making `Parser` a subclass of `State` can work as a short-term migration trick,
but it is probably not the best long-term model.

Inheritance suggests that "parser is a kind of state container", but the more
accurate relationship is:

- parser owns execution state
- parser also owns input flow, conditionals, layout context, and runtime services

So direct ownership is clearer than inheritance.

## Short Version

- the live runtime center should be `Parser`
- the key abstraction is domains, not the `State` wrapper
- groups, input stack, if-stack, list stack, and `current_value`
  all belong directly on `Parser`
- scratch values are still real, but they can remain local implementation detail unless later tracing machinery needs a persistent slot
- globals can become parser attributes, with a compatibility access layer
- `eqtb` should be a specialized domain
- `state.py` should survive as reusable machinery, not as the owner of live runtime state
