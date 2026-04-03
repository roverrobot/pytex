# Token Flow Layer

This note describes the execution layer just above parser state and just below
command/layout semantics: scanners plus the input stack.

The goal is to isolate how tokens are produced and scheduled, without mixing
that mechanism with grouped state mutation or layout construction.

## Scope

This note covers:

- concrete scanner kinds
- scanner end-of-input behavior
- input-stack push/pop operations
- `unread` as a derived operation
- macro expansion viewed as token-source manipulation
- the boundary between token flow and later semantic effects

This note does not cover:

- grouped parser state itself
- assignment semantics
- layout/node construction
- page building or shipout

## Core Model

At this layer, the runtime objects are:

- tokenizers, which produce tokens from active text input
- text sources/backstores, which feed tokenizers line by line
- an input stack, which schedules tokenizers/sources plus unread token buffers

The important abstraction is that token flow is composed from:

- active lexical state in a tokenizer
- source/backstore state that can provide the next physical line
- a small unread/saved token buffer for already-tokenized input

## Tokenizer / Source IR

The common token-source behavior is:

- `emit(token)`
- `eof`

Conceptually, a scanner repeatedly emits tokens and eventually signals that it
is exhausted.

This means the token-flow layer is very small. Most complexity comes from how
tokenizers are fed and resumed, not from the token protocol itself.

## Current Kinds

The current design needs these concrete forms:

- a line-based tokenizer over source text
- a text source/backstore over string/file input
- a saved token buffer on the input stack

### Tokenizer

`Tokenizer` reads characters from one physical line and tokenizes them under
the current parser state, especially catcodes and related scanner settings.

This is the component that makes TeX unusual: it is not a pure lexical front end,
because the tokenization behavior depends on mutable runtime state.

### Text Source / Backstore

`Scanner` in the current code is best understood as a line source/backstore:

- it reads the next physical line from a file or string
- appends `endlinechar`
- creates a `Tokenizer`
- and hands control to that tokenizer

So the actual lexical work is already concentrated in `Tokenizer`, while the
source object mostly manages line feeding and source lifetime.

### Saved Token Buffer

Stored token lists, unread tokens, and compiled macro replacement results are
no longer modeled as a distinct scanner kind.

Instead they are lowered into the input stack's saved-token buffer:

- `unread(token)` pushes one token into `saved`
- `pushTokenList(toks)` splices a token list into `saved`

There is no longer a `TokenListScanner` in the design.

## `readTo`

The main structural scanner helper is `readTo(stop_catcode, ..., expand=False)`.

Its job is:

- read tokens until a matching raw stop token is found
- track raw `{` / `}` nesting
- return `(tokens, end_token)`

The important design point is that `readTo` itself is structural:

- raw begin-group and end-group tokens control nesting
- the returned token list excludes the stopping token
- the stopping token is returned separately so callers can decide whether it is
  syntax or payload

This helper replaces the older family of balanced-token readers.

### Why The Stop Token Is Separate

Returning the stop token separately is important for macro definitions.

For the parameter text of `\def`, the terminating `{` is not part of the
pattern itself, but it still matters:

- it ends the pattern scan
- if the pattern ended with a pending `#`, the `{` becomes the delimiter token

So the macro reader needs access to that token without having it mixed into the
ordinary collected token list by default.

## Expanded Reads

When `readTo(..., expand=True)` is used, token acquisition still happens one
token at a time, but the destination list is wrapped in `ExpandBuilder`.

`ExpandBuilder` is responsible for the token-list-specific expansion policy:

- undefined commands still error
- protected commands are left as tokens
- non-expandable commands are left as tokens
- commands with `expanded(parser)` contribute an entire token list via
  `extend(...)`
- commands with only `expand(parser)` contribute a single token via `append(...)`

So expansion policy lives in the builder, while `readTo` remains the structural
balanced-token reader.

This is also the same expander shape used by file-writing paths that need token
list expansion without invoking the normal parser execution loop.

## Macro Definition Reading

Macro definitions add one more builder layer: `MacroBodyBuilder`.

`MacroBodyBuilder` is the normalization boundary for macro `#` syntax.

Direct input tokens appended through `append(...)` are interpreted as current
definition syntax:

- `#1` .. `#9` become parameter tokens with `parameter >= 0`
- `##` becomes an escaped parameter token with `parameter == -1`
- bad trailing or malformed `#` syntax raises an error

Token lists inserted through `extend(...)` are not reinterpreted as fresh input
syntax. They are copied through as provided by the expander.

This boundary is important because only the scanner phase knows whether a token
came from:

- direct source input
- an expanded token list such as `\the`

Later compilation cannot reconstruct that provenance reliably.

### Pattern And Replacement Reads

Macro reading is now:

1. read the pattern with `readTo(BEGIN_GROUP, expand=False, toks=MacroBodyBuilder(..., pattern=True))`
2. close the builder, which also resolves the special `#{` tail case
3. read the replacement with `readTo(END_GROUP, expand=expand_body, toks=MacroBodyBuilder(..., pattern=False))`
4. close the replacement builder
5. construct `Macro(pattern, replacement)`

So `Macro.pattern` and `Macro.replacement` are already normalized macro-body
token streams, not raw source text.

## Macro Compilation

`Macro` keeps two representations:

- canonical stored form:
  - `pattern`
  - `replacement`
- compiled execution form:
  - `calls`
  - `replacement_pieces`

The stored form is used for:

- serialization
- equality
- `meaning()`

The compiled form is used for:

- argument reading
- runtime expansion

### Compiled Calls

`_compileCalls(pattern)` turns the normalized parameter text into executable
call objects:

- `MatchStartCaller`
- `ReadArgUnDelimCaller`
- `ReadArgDelim1Caller`
- `ReadArgDelim2Caller`

These objects are the runtime argument-reading program for the macro.

So the old "read brackets every time the macro expands" model is gone. The
parameter text is compiled once when the macro is defined.

### Compiled Replacement Pieces

`_compileReplacementPieces(replacement, arg_count)` lowers the replacement text
into:

- one leading literal token list
- followed by `(arg_index, trailing_literal)` pairs

This means runtime expansion does not rescan the replacement token-by-token for
`#1`, `#2`, and so on.

Instead, expansion becomes:

1. read arguments using `calls`
2. start from the leading literal piece
3. splice each captured argument list
4. append the following literal piece
5. splice the assembled result into the input stack with `pushTokenList(...)`

Escaped `#` in replacement compilation is lowered back to an ordinary literal
parameter token, so the emitted token stream matches the next-layer TeX input
that would have been seen from the original source.

## Why Shared-Token Mutation Is Forbidden

One subtle but important invariant is that macro-body normalization must not
mutate tokens that may later be reused by compiled macro replacements.

If a helper macro containing `##1` is expanded multiple times, mutating the
shared `#` token in place would corrupt later expansions, turning the second use
into `#11` instead of `#1`.

So `MacroBodyBuilder` normalizes by appending fresh parameter tokens rather than
editing the original input token object in place.

## Input-Stack IR

The input stack has two essential operations:

- `push(source_or_tokenizer)`
- `pop()`

This is enough to describe:

- entering a macro expansion
- entering a nested text source
- resuming an outer token source when an inner one finishes

The stack is therefore the control structure that composes scanners into one
effective token stream.

## `unread`

`unread(token)` is a useful derived operation.

Conceptually:

- `unread(token)` = push a one-token source in front of the current stream

So it does not need to be a primitive source kind in the core algebra, but it
is important enough operationally that it is worth naming explicitly.

In implementation, this does not need to allocate a fresh one-token scanner.
It is often better modeled as a small saved-token buffer on the input stack,
for example:

- `input_stack.saved.append(token)`

with input retrieval checking `saved` before consulting the active scanner.

So the design distinction is:

- semantic model: `unread(token)` behaves like pushing a one-token source
- implementation model: `unread` can be handled directly by input-stack-local saved tokens

## EOF And Pop

### Current State

In the current implementation, source/tokenizer exhaustion is represented by
returning `None`.

Operationally this means:

- tokenizer returns `token` -> continue
- tokenizer/source returns `None` -> this frame is exhausted, so the input stack pops it
- if the whole stack empties, parser-facing code also sees `None`

So `None` currently plays two roles:

- local frame exhaustion
- true end of input

This works, but it leaks end-of-input control flow into many downstream token
readers.

### Locked Direction

The next lexer/input-stack refactor should preserve the current tokenization
cost profile inside `Tokenizer`, but simplify downstream EOF handling.

The intended direction is:

- `Tokenizer` remains responsible for low-level character and line handling
- `None` remains an internal tokenizer/source signal
- true end-of-input should be represented by an EOF exception raised by the
  input stack when the whole stack is exhausted

More precisely:

- tokenizer/source-local exhaustion is handled inside the token-flow layer
- `InputStack.read()` should only raise EOF when there is no outer source left
- normal token reads should remain exception-free
- EOF exceptions should therefore be rare, occurring only at true source
  boundaries

This keeps exceptions off the per-token hot path while removing most
downstream `if t is None` checks whose only purpose is to thread EOF.

### Caller Categories

Under that design, callers split into three groups.

#### 1. Outer parse flow

High-level parser control flow should catch EOF once and stop cleanly.

This includes:

- the main parser loop
- possibly `token_expand()` if we decide to make EOF an exceptional exit there

#### 2. Optional/probe readers

Readers whose job is "try to read something, otherwise report absence" should
catch EOF and convert it to the existing absence result.

Examples:

- keyword readers
- internal-value probes
- assignment-head probes

These should continue to return things like:

- `None`
- `(None, None)`

rather than surfacing EOF as a syntax error.

#### 3. Mandatory syntax readers

Readers that are in the middle of scanning required syntax may catch EOF only
to improve the resulting error message.

Examples:

- undelimited macro arguments
- integer digit readers
- dimen/glue/rule specification readers
- balanced/general-text readers
- conditionals that are already committed to a syntactic form

These are places where EOF is not "absence", but "unexpected end of input".

### Why This Is Still Cheap

The key point is that the tokenizer already performs `None` checks internally
while reading characters and lines. So this design does not try to remove that
low-level cost.

Instead, it pushes EOF handling to the right abstraction boundary:

- tokenizer/source handles local exhaustion
- input stack handles source switching
- parser/higher layers see EOF only at true input exhaustion or when a reader
  explicitly chooses to treat it as syntax failure

So the main benefit is cleaner downstream control flow, not faster low-level
lexing.

## Tokenizer-Only Stack Direction

The current code is already close to a tokenizer-centric model:

- `Tokenizer` does the lexical work
- `Scanner` mostly feeds lines and creates tokenizers
- token lists/unread are handled by `saved`

So the preferred direction is to consolidate toward:

- an input stack of active tokenizers
- each tokenizer owning a text source/backstore for subsequent lines

In that model:

- tokenizers become the only active lexical frames on the stack
- sources/backstores become private implementation details of tokenizers
- saved tokens remain outside that mechanism as the direct implementation of
  unread and token-list splicing

This should simplify the input stack further without reintroducing a
token-list-scanner abstraction.

## Relationship To Expansion

Expansion at this level is best understood as token-source manipulation.

An expandable token usually does not directly produce layout or assignment
effects. Instead, it typically produces one or more input-stack operations,
such as:

- push a replacement token list
- push macro arguments in the right order
- possibly emit no later effect at all beyond changing what tokens come next

So one important part of "execution" in TeX is really just reconfiguring the
future token stream.

## Token Scheduling Primitives

Some expandable primitives are not well described by scanner push/pop alone.

In particular, `\expandafter` and `\futurelet` need a small amount of
execution-local token scheduling state.

There are two reasonable ways to model this:

- introduce dedicated IR operations for each primitive
- introduce a tiny generic token scratch mechanism and lower those primitives to it

The second option is cleaner.

### Scratch-Token Model

A useful execution-local model is:

- a tagged `current_value` holder
- one `scratch` holder

with operations like:

- `read_next_raw() -> current_value`
- `store(scratch)`
- `expand_current_once()`
- `unread(current_value)`
- `unread(scratch)`

This does not need to be exposed as part of the scanner protocol itself. It is
better understood as a token-control layer that sits on top of scanners and the
input stack.

The important point is that tokens can use the same holder convention as other
execution values. We do not need a separate dedicated family of token registers.

### `\expandafter`

Under the scratch-token model, `\expandafter` can be described as:

1. `read_next_raw() -> current_value`
2. `store(scratch)`
3. `read_next_raw() -> current_value`
4. `expand_current_once()`
5. `unread(scratch)`

The important behavior is that one token is postponed while the following token
is expanded first.

### `\futurelet`

`\futurelet` needs the same token-scheduling machinery plus one semantic step
that assigns a control sequence from the observed future token.

Its shape is:

1. `read_next_raw() -> current_value`
2. `store(scratch)`
3. `read_next_raw() -> current_value`
4. `let_from_token(target, current_value)`
5. `unread(current_value)`
6. `unread(scratch)`

So `\futurelet` is not just a parser-state assignment and not just a scanner
operation. It is a mixed token-control operation:

- read ahead without losing the upcoming tokens
- bind a meaning from the looked-ahead token
- restore the original token stream order

### Why This Matters

This suggests that the execution layer has a small token-control sub-IR in
addition to pure scanner/input-stack mechanics.

So the token-related part of execution is not only:

- scanner `emit/eof`
- input-stack `push/pop`

It also includes:

- read-ahead
- postponement
- single-step expansion of a chosen token
- token restoration via unread

## Relationship To Token Semantics

Tokens themselves are not yet the semantic IR for the whole engine.

A token occurrence is interpreted under current state and lowered into zero or
more later effects.

Examples:

- `{` -> `begin_group(...)`
- `}` -> `end_group(...)`
- expandable control sequence -> usually `push(...)` operations
- assignment command -> parser-state operations
- ordinary character token -> layout-building operations, depending on mode
- some tokens -> no lower-level effect after expansion

So the token-flow layer should be kept separate from the later layers that
consume tokens semantically.

## Proposed Summary

The token-flow layer has a very small core:

- `Tokenizer`, which performs lexical work under current parser state
- text sources/backstores, which feed physical lines to tokenizers
- an input stack, which schedules active tokenizers plus the saved-token buffer

Useful derived structure:

- `unread(token)` as a push into the saved-token buffer
- `pushTokenList(toks)` as direct token-list splicing into that same buffer
- `readTo(...)` as a structural balanced-token reader
- `ExpandBuilder` as the token-list expander used by `readTo(..., expand=True)`
- macro compilation into argument-reading calls plus replacement pieces
- token-control lowering for primitives such as `\expandafter` and `\futurelet`

The locked direction for EOF handling is:

- local tokenizer/source exhaustion stays inside the token-flow layer
- `InputStack.read()` should eventually raise EOF only when the whole stack is
  exhausted
- optional readers catch EOF and convert it to absence
- mandatory readers may catch EOF only to improve syntax errors

And the main boundary is:

- tokenizers, sources, and the input stack produce token flow
- token dispatch lowers token occurrences into parser-state, expansion, or
  layout effects

This gives us a compact IR for token flow without confusing token production
with the later semantics of those tokens.
