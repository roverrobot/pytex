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
- token-capture IR
- typed value reader IR
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

## 2. Token-Capture IR

Some execution behavior is not about scheduling token sources, but about
capturing token sequences under TeX scanning rules.

This is a distinct family from plain scanner/input-stack mechanics.

### Core Operations

- `match(token_or_predicate)`
- `read_to(stop, balanced, include_tail, expand_mode)`
- `read_command_name()`

These are higher-level scanning operations that consume from the token-flow
layer and return structured results such as command names or token lists.

### Purpose

This IR family answers:

- how commands scan syntactic delimiters
- how balanced token lists are captured
- how command names and parameter texts are read

### Why This Is Better Than Raw Token-List Builder Ops

An alternative design would expose low-level builder operations such as:

- `begin_token_list(kind)`
- `append_token(token)`
- `end_token_list()`

Those probably still exist as implementation micro-ops, but `match` and
`read_to` are the better public execution IR because they match TeX scanning
semantics more directly.

For example, a macro definition can be described as:

- `key = read_command_name()`
- `params = read_to(BEGIN_GROUP, balanced=False, include_tail=False, expand_mode=raw)`
- `body = read_to(END_GROUP, balanced=True, include_tail=False, expand_mode=raw)`
- `macro = make_macro(params, body)`
- `write(equitable, key, macro, scope)`

So token-list construction is still real, but it is better treated as the
internal realization of higher-level capture ops.

## 3. Typed Value Reader IR

Many TeX commands are naturally expressed as "read a typed value, then perform
some effect."

That suggests a distinct family of typed scanning operations.

### Core Operations

- `read_int()`
- `read_dimen()`
- `read_glue()`

### Likely Helper Operations

- `read_stretch()`
- `read_shrink()`
- `read_keyword(...)`
- `read_optional_signs()`

Some of these may stay internal helpers rather than public IR operations.
For example, stretch and shrink parsing may simply be part of `read_glue()`.

### Purpose

This IR family answers:

- how typed TeX values are scanned from tokens
- how assignment and command semantics receive normalized values

## 4. Parser-State IR

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

## 5. Command And Expansion Control IR

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

### Conditional Control

Conditionals deserve a more concrete submodel, because they are a major part of
TeX execution and their shape is already fairly clear.

They involve three distinct concerns:

- evaluate a branch condition
- track open conditional frames
- skip untaken branches in a nesting-aware way

#### Condition Evaluation

Typical condition-evaluation operations include:

- `test_equal(value1, value2)`
- `test_larger(value1, value2)`
- `test_odd(value)`
- `read_int()` for integer-selected branching such as `\ifcase`

So conditionals reuse the typed reader layer as part of their front end.

#### Conditional Stack

A separate if-stack tracks open conditional state:

- `push_if_frame(kind, selector)`
- `pop_if_frame()`

The selector may be:

- a boolean branch result for ordinary `\if...`
- an integer branch selector for `\ifcase`

#### Conditional Skipping

Untaken branches are not ordinary execution jumps. They require a special
nested scan mode that walks tokens until the appropriate conditional boundary.

That suggests an operation such as:

- `skip_conditional(targets)`

where `targets` may be things like:

- `[\else, \fi]`
- `[\or, \else, \fi]`
- `[\fi]`

This skipping must be aware of nested conditionals, so inner `\if...\fi`
blocks are traversed correctly without mistaking their boundaries for the outer
one.

#### Typical Shapes

An ordinary conditional can be modeled as:

1. evaluate a boolean branch
2. `push_if_frame(kind, branch)`
3. if false, `skip_conditional([\else, \fi])`
4. when `\else` is reached from the taken true branch, `skip_conditional([\fi])`
5. `\fi` performs `pop_if_frame()`

An `\ifcase`-style conditional is the integer-valued variant:

1. `selector = read_int()`
2. `push_if_frame(IFCASE, selector)`
3. skip across `\or` arms until the selected one, or to `\else` / `\fi`
4. `\fi` performs `pop_if_frame()`

So conditionals are partly input-stack control, but they are not reducible to
plain `push` and `pop`. They form a dedicated execution-control subsystem.

### Purpose

This IR family answers:

- what does this token mean right now
- is it expanded, executed, or treated as a literal token
- how do prefixes and conditionals alter execution

## 6. Execution-Time I/O IR

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

## 7. Execution-To-Layout Bridge

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
- token-capture IR
- typed value reader IR
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
2. token-capture IR
3. typed value reader IR
4. parser-state IR
5. command/expansion control IR
6. I/O IR
7. execution-to-layout bridge

And the current priority order for formalization is probably:

1. parser-state IR
2. token-flow IR
3. token-capture IR
4. typed value reader IR
5. command/expansion control IR
6. execution-to-layout bridge
7. I/O IR

## Short Version

The execution layer is not one thing.

Its main IR families are:

- token flow
- token capture
- typed value readers
- grouped parser state
- command/expansion control
- I/O side effects
- the bridge from execution into layout building

The first four are already getting relatively crisp. The rest should be
formalized next without collapsing them into one monolithic "parser IR".
