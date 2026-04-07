# Token Flow Layer

This note describes the input or “mouth” side of the current engine: how
characters become tokens, how token sources are stacked, how unread and token
list replay are handled, and how the parser obtains the next expanded token.

The goal is to describe the current token-flow machinery without mixing it with
full execution semantics, grouped state mutation, or layout construction.

## Scope

This note covers:

- `Tokenizer` as the concrete lexical source
- `InputStack` as the active token-source scheduler
- the saved-token buffer used for `unread` and token-list replay
- `parser.token_expand()` as the parser-facing token-flow helper
- structural token readers such as `readTo(...)` and `readGeneralText(...)`
- macro definition reading and macro expansion only insofar as they manipulate
  token flow
- EOF behavior at the tokenizer and input-stack boundaries

This note does not cover:

- grouped parser state in general
- assignment semantics in general
- list, box, or math construction
- page building or shipout

## Main Picture

In the current code, the token-flow layer has three main parts:

1. `Tokenizer`, which reads from a string or file-like object and emits tokens
   under the current catcodes and related parser state.
2. `InputStack`, which schedules active tokenizers and also carries a saved
   token buffer in front of the current tokenizer.
3. `parser.token_expand()`, which repeatedly reads tokens from the input stack
   and performs ordinary expandable-token processing until a non-expanded token
   is ready for the execution layer.

So the current input layer is not just `parser.input`. It is `parser.input`
plus the parser-facing expansion step that sits directly on top of it.

## `Tokenizer`

`Tokenizer` is now the concrete lexical source object.

It accepts either:

- a string, which is wrapped in `io.StringIO`
- a file-like object

There is no longer a separate active “scanner” object sitting above a text
backstore. Source-file reading, string reading, line management, endline
handling, and lexical tokenization are all consolidated into `Tokenizer`.

The tokenizer owns:

- the current source object
- line iteration
- the current line character iterator
- current position information
- the current parser catcode table
- access to the control-sequence table for command-token entry lookup
- the current `endlinechar`

### Line handling

For each physical line, `Tokenizer`:

- strips a trailing newline if present
- appends `endlinechar` when it is in range
- skips leading spaces and ignored characters according to the current catcodes
- remembers source position for diagnostics

When the source is exhausted, `Tokenizer` closes the source if needed and then
raises `EOFError` from `read()`.

### Tokenization behavior

`Tokenizer.read()` performs the ordinary TeX-like lexical work:

- `^^` expansion via `charExpand()`
- collapsing runs of spaces into a single space token
- turning end-of-line into either a space token or `\par`, depending on line
  state
- creating active-character tokens and command tokens with stable `entry`
  references into `parser.equitable`
- creating ordinary character tokens for non-escape, non-ignored input

So tokenization is still stateful and depends on mutable parser state,
particularly catcodes and `endlinechar`.

## `InputStack`

`InputStack` is the scheduler for active token sources.

Its current structure is:

- `top`: the active `Tokenizer`
- `stack`: a stack of suspended outer `(top, saved)` pairs
- `saved`: a plain token buffer that is read before the active tokenizer

A key point is that the active stack contains only `Tokenizer` frames. The old
idea of separate token-list scanner frames is gone.

### Push and pop

`InputStack.push(tokenizer)` requires a `Tokenizer` instance. Pushing a new
input source saves both the previous active tokenizer and the previous saved
buffer, then starts the new tokenizer with a fresh empty saved buffer.

`InputStack.pop()` restores the previous `(top, saved)` pair. If there is no
outer frame left, it raises `EOFError`.

This means nested file or string inputs are still stack-based, but token-list
replay is no longer represented as its own scanner frame.

### Saved-token buffer

The `saved` buffer now handles three related jobs:

- `unread(token)` pushes back one token
- `pushTokenList(toks)` splices an ordinary token list in front of the current
  input
- token-list-based expansion reuses the same mechanism instead of creating a
  separate token-list scanner

This is the main consolidation in the current code: token-list scanning is now
implemented directly by the saved-token buffer on `InputStack`.

Because `saved` is checked before the current tokenizer, token replay and macro
replacement insertion naturally take precedence over further source reading.

### Meaning refresh on read

`InputStack.read()` also refreshes the meaning of command-like tokens on every
read.

If the token has an `entry`, then after reading it the input stack checks
whether `t.definition` still matches `entry.value`. If not, it updates the
cached definition from the entry.

So command tokens carry stable table entries, but their current meaning is
refreshed when they are read.

## EOF behavior

The current EOF behavior is already cleaner than the older design note.

`Tokenizer.read()` raises `EOFError` when that tokenizer’s source is exhausted.
`InputStack.read()` catches that local EOF, pops the exhausted tokenizer frame,
and continues reading from the restored outer frame.

As a result, higher parser code sees `EOFError` only when the whole input stack
is exhausted.

So the current behavior is:

- tokenizer-local exhaustion stays inside token flow
- input-source switching is handled inside `InputStack.read()`
- parser-facing callers generally see EOF only at true end of input

This is why many parser helpers can treat EOF as a real boundary condition
instead of threading `None` through every token read.

## `parser.token_expand()`

`parser.token_expand()` is the parser-facing helper that sits immediately above
raw token flow.

Its job is simple:

- read the next token from `self.token` (which is `self.input.read`)
- if the token is expandable, run its `expand(self)` method
- if that expansion yields no immediate token, keep reading
- otherwise return the next token that should be seen by ordinary execution

So the input layer in practice is not only raw tokenization. It also includes
this token-expansion step, because most of the execution layer consumes tokens
through `token_expand()` rather than directly through `InputStack.read()`.

### What counts as token-flow work here

This layer is still about scheduling future tokens, not about performing later
semantic effects such as layout or assignment.

Typical expandable commands at this level work by manipulating future token
flow:

- pushing replacement token lists
- postponing one token and expanding another first
- reading ahead and then restoring the original token order
- returning a literal token to be executed next

## Raw reads versus expanded reads

The parser uses two different entry points depending on context:

- `parser.token()` for raw token reads from the input stack
- `parser.token_expand()` for ordinary expanded reads

Syntax readers that need literal tokens, delimiter matching, or exact macro
argument behavior often use `parser.token()`.

Ordinary execution and many semantic readers use `parser.token_expand()`.

That distinction is important because TeX syntax often depends on whether a
reader is supposed to observe the literal upcoming tokens or the expanded
stream.

## Structural token readers

### `readTo(...)`

`readTo(parser, stop, toks=None, expand=False)` is the main structural token
reader for balanced text.

Its current behavior is:

- read tokens until a stop catcode is found at nesting level zero
- track raw `{` and `}` nesting by catcode
- return `(tokens, end_token)`
- optionally use expansion while collecting the token list

The returned stop token is kept separate from the collected list. That matters
for callers such as macro definition readers, where the stopping `{` or `}` may
have syntactic significance beyond merely ending the scan.

When `expand=False`, `readTo(...)` reads through `parser.token()`.

When `expand=True`, it still reads one token at a time, but collects into an
`ExpandBuilder`, which applies token-list-style expansion policy while leaving
`readTo(...)` itself as the structural balanced reader.

### `ExpandBuilder`

`ExpandBuilder` is the current token-list expansion helper.

Its policy is:

- ordinary non-command tokens are appended unchanged
- undefined commands raise an error
- protected or non-expandable commands are appended as tokens
- commands with `expanded(parser)` contribute a whole token list
- commands with only `expand(parser)` are expanded through the parser, and any
  immediate returned token is appended

If `expand(parser)` injects future tokens through `pushTokenList(...)` and
returns `None`, those inserted tokens will simply be read on subsequent
iterations of `readTo(...)`.

### `readGeneralText(...)`

`readGeneralText(parser, expand=True)` reads TeX general text:

- skip filler (`spaces` and `\relax`)
- require a begin-group token, with alias-aware checking in the expanded case
- read the balanced body with `readTo(CATCODE.END_GROUP, ...)`

This is the helper used by commands such as `\uppercase`, `\lowercase`, and
similar token-list-oriented operations.

## Macro definition reading

Macro definitions are now normalized at read time.

The main helper is `MacroBodyBuilder`, which is the boundary where `#` syntax
is interpreted for macro definitions.

Its current behavior is:

- direct `#1` through `#9` become parameter tokens with numeric parameter
  indices
- direct `##` becomes an escaped hash token
- malformed parameter syntax raises an error
- token lists inserted through `extend(...)` are copied through as tokens rather
  than being reinterpreted as fresh definition syntax

This distinction matters because inserted token lists may come from expansion,
and the builder should not pretend that they were literally scanned as new `#`
syntax.

### Pattern and replacement reading

The current macro-definition path is:

1. read the parameter pattern with `readTo(BEGIN_GROUP, expand=False, toks=MacroBodyBuilder(..., pattern=True))`
2. close the pattern builder
3. read the replacement text with `readTo(END_GROUP, expand=expand_body, toks=MacroBodyBuilder(..., pattern=False))`
4. close the replacement builder
5. build a `Macro(pattern, replacement)` object

There is one important current detail: if the pattern builder ends with a
pending `#` and the stop token is `{`, then that stop token becomes part of the
pattern and is also returned as a tail token to be appended to the replacement.
This handles the TeX `#{` edge case directly at definition-read time.

So the stored macro pattern and replacement are already normalized token
streams, not raw source text.

## Macro compilation and expansion

Macros still have a stored form and a compiled execution form.

The stored form is:

- `pattern`
- `replacement`

The compiled form is:

- `calls`, which read the arguments at expansion time
- `replacement_pieces`, which encode literal pieces and parameter splice points

### Compiled argument readers

The normalized parameter pattern is compiled once into call objects such as:

- `MatchStartCaller`
- `ReadArgUnDelimCaller`
- `ReadArgDelim1Caller`
- `ReadArgDelim2Caller`

These objects perform runtime argument reading directly from token flow, mostly
through `parser.token()` and `readTo(...)`.

### Replacement insertion

Replacement expansion no longer needs a token-list scanner object.

At expansion time, the macro:

1. reads its arguments using the compiled callers
2. assembles the replacement token list from `replacement_pieces`
3. inserts that token list with `parser.input.pushTokenList(...)`

So macro expansion is now directly a token-flow operation over the saved-token
buffer.

## Token scheduling primitives

Some primitives manipulate token order directly.

### `\expandafter`

The current implementation of `\expandafter` works directly with raw token
reads and unread operations:

- read one raw token and postpone it
- read the next raw token
- if that second token is expandable, expand it now
- then restore the postponed token in front of the resulting stream

This is implemented directly in the command logic. There is no longer a generic
`current_value` or scratch-register abstraction for this.

### `\futurelet`

`\futurelet` is likewise implemented directly through raw token flow.

Its accessor reads two raw tokens, unread them in reverse order, and returns
the meaning of the second token as the assigned value.

So the looked-ahead token is observed without changing the eventual token order.
Again, this is handled directly with token reads and unread operations rather
than through a separate generic token-scratch IR.

## Boundary to the execution layer

The token-flow layer stops at producing the next token stream seen by the
parser.

That includes:

- tokenization from strings and files
- source stacking
- unread and token-list replay
- token-list-oriented expansion helpers
- macro replacement insertion
- parser-facing token expansion through `token_expand()`

What it does not include is the later semantic interpretation of those tokens
as assignments, group boundaries, conditionals, node creation, or box/list
construction.

Those belong to later layers.

## Current Summary

The current token-flow layer is centered on:

- `Tokenizer` for lexical reading from strings or file-like sources
- `InputStack` for tokenizer scheduling and saved-token replay
- `parser.token_expand()` for parser-facing expanded token reads

The main current design points are:

- source reading and lexical work are consolidated into `Tokenizer`
- active stack frames are only `Tokenizer` frames
- `InputStack.saved` now handles unread tokens and token-list scanning
- EOF is raised to parser code only when the whole input stack is exhausted
- `readTo(...)`, `ExpandBuilder`, and `readGeneralText(...)` provide the main
  structural token-list readers
- macro definitions are normalized when read
- macro expansion is implemented by inserting replacement tokens directly into
  `InputStack.saved`
- token-order primitives such as `\expandafter` and `\futurelet` are handled
  directly with token reads and unread operations

This gives a compact description of the current input layer without mixing it
with the later semantics that consume the resulting token stream.
