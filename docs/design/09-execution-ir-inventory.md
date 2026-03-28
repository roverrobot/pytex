# Execution IR Inventory

This note summarizes the execution-layer IR families identified so far.

The main point is that the execution layer should not be treated as one single
IR. It is better understood as a small family of related IRs and effect
interfaces that together cover TeX execution before the final structural layout
artifact exists.

Some of these are already fairly crisp. Others are still provisional.

## Main Conclusion

The execution layer is not one IR.

It is at least:

- token-flow IR
- parser-state IR
- command/expansion control IR
- execution-time side-effect IR such as I/O
- execution-to-layout bridge operations

Some of these belong fully inside the execution layer. Some are boundary
interfaces to the layout layer. The important thing is to keep them distinct.

## 1. Token-Flow IR

This is the smallest and most mechanical part of execution.

It covers scanners and the input stack.

### Scanner IR

- `emit(token)`
- `eof`

### Input-Stack IR

- `push(scanner)`
- `pop()`

### Derived Input-Stack Operations

- `unread(token)`

Semantically, `unread(token)` behaves like pushing a one-token source. In the
current implementation it is better handled by an input-stack-local saved-token
buffer.

### Token-Control Operations

Some execution behavior needs more than plain scanner push/pop. In particular,
`\expandafter` and `\futurelet` suggest a tiny token-control sublayer with
operations such as:

- `read_next_raw()`
- `store(token_slot, token)`
- `expand_current_once()`
- `unread(token)`

This can be modeled with a current token plus a scratch token register such as
`A`, rather than with one dedicated IR primitive per TeX command.

### Purpose

This IR family answers:

- where does the next token come from
- what token source becomes active next
- how macro expansion or token-list replay changes future token flow

## 2. Parser-State IR

This is the grouped typed-store part of execution.

### Core Operations

- `read(domain, key)`
- `write(domain, key, value, scope)`
- `begin_group(kind)`
- `end_group(kind)`

### Nearby Runtime Hooks

- `aftergroup(token)`
- `set_afterassignment(token)`
- `clear_afterassignment()`

### Derived Update Operation

- `update(domain, key, op, arg, scope)`

This is optional sugar for operations such as `\advance`, `\multiply`, and
`\divide`, which can also be lowered to `read + compute + write`.

### Hidden Micro-Ops

These do not need to be public IR primitives, but they exist conceptually
inside the grouped write/end-group behavior:

- `save_old(domain, key, old_value, group)`
- `restore_saved(domain, key, group)`
- `discard_saved(domain, key)`

### Purpose

This IR family answers:

- what mutable parser state exists
- how grouping restores local state
- how assignments affect domains and registers

## 3. Command And Expansion Control IR

This family is real, but less fully nailed down than token flow and parser
state.

It covers execution behavior such as:

- resolving a token's current meaning
- deciding whether that meaning is expandable or executable
- expanding macros and expandable primitives
- applying prefixes
- performing conditional control flow

### Provisional Operation Shapes

At a conceptual level, likely operations include things like:

- `resolve(token) -> meaning`
- `expand(token_or_meaning)`
- `execute(command, prefixes)`
- `begin_conditional(kind)`
- `select_branch(...)`
- `end_conditional()`

This is still provisional because the right split between token dispatch,
command semantics, and input-stack manipulation is not fully settled yet.

### Purpose

This IR family answers:

- what does this token mean right now
- is it expanded, executed, or treated as a literal token
- how do prefixes and conditionals alter execution

## 4. Execution-Time I/O IR

I/O is adjacent to parser state, but it is not grouped domain state.

### Likely Operations

- `open_input(channel, source)`
- `close_input(channel)`
- `read_line_or_tokens(channel, target)`
- `open_output(channel, destination)`
- `write_output(channel, data)`
- `close_output(channel)`
- `message(data)`
- `error(data)`

The exact shape is still open, but the family is clearly separate from grouped
state and from token-flow mechanics.

### Purpose

This IR family answers:

- what observable external side effects execution performs
- how TeX input and output channels are managed

## 5. Execution-To-Layout Bridge

Execution does not only mutate parser state. It also drives layout
construction.

That means some execution steps need access to layout-facing operations and
queries, such as:

- current mode
- last node
- current list
- paragraph/box-building auxiliaries

This boundary is where execution-layer semantics start to talk to the layout
builder.

### Query Side

Likely queries include:

- `current_mode()`
- `last_node()`
- `current_list()`
- `current_builder_state(...)`

### Effect Side

The corresponding effect side belongs to the layout-builder layer rather than
pure execution:

- begin list
- append node
- finish paragraph
- pack box
- begin/end math list

So this is not a pure execution IR family on its own. It is a bridge between
execution and layout.

### Purpose

This boundary answers:

- what layout state command semantics need to inspect
- what layout-building operations execution is allowed to request

## Stable Vs Provisional

The most stable execution IR families so far are:

- token-flow IR
- parser-state IR

Clearly necessary, but not yet fully specified:

- command and expansion control IR
- execution-time I/O IR
- execution-to-layout bridge

This is a feature, not a problem. It means we can formalize the cleanest parts
first without pretending the entire execution layer is already one finished
design.

## Proposed Working Checklist

When we say "execution-layer IRs", we currently mean this inventory:

1. token-flow IR
2. parser-state IR
3. command/expansion control IR
4. I/O IR
5. execution-to-layout bridge

And the current priority order for formalization is probably:

1. parser-state IR
2. token-flow IR
3. command/expansion control IR
4. execution-to-layout bridge
5. I/O IR

## Short Version

The execution layer is not one thing.

Its main IR families are:

- token flow
- grouped parser state
- command/expansion control
- I/O side effects
- the bridge from execution into layout building

The first two are already relatively crisp. The rest should be formalized next
without collapsing them into one monolithic "parser IR".
