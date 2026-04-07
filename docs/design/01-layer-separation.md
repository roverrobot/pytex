# Layer Separation

This note describes the layer split that exists in the current codebase around
input handling, parser execution, layout construction, page building, and
backend output.

The main point is that the code does have meaningful boundaries, but they are
not all formal IR boundaries yet. The parser is still the runtime center, and
some parts of token flow, execution, and layout construction remain
intentionally interleaved.

## Current Picture

Today the code is best understood as having five practical layers:

1. the input layer
2. the parser execution layer
3. the layout-construction layer
4. the page-building and output-routine layer
5. the backend shipout layer

This is a real split in the code, but it is not yet a split into five fully
independent, uniformly abstracted interfaces.

In particular:

- there is no single universal IR for all backends
- there is no standalone general export IR yet
- the clearest existing backend boundary is the shipout walker in
  `pytex/typeset/shipout.py`
- detailed token-flow mechanics belong in a separate token-flow note rather than
  being repeated in full here

## 1. Input Layer

The current parser has a distinct input or “mouth” layer centered on
`parser.input`, which is a `lexer.InputStack`.

This layer is responsible for the flow of tokens into execution. It includes at
least:

- stacked token sources and tokenizer frames
- file and string tokenization under the current catcodes
- line handling, endline processing, and `^^` character expansion
- unread and reinserted tokens
- direct token-list injection such as `pushTokenList(...)`
- parser-facing token-flow helpers built on top of the input stack, especially
  `parser.token_expand()`

So this layer is not only raw character-to-token conversion. It also includes
the token-flow interface that execution uses to obtain the next relevant token.
In the current code, `parser.token` is just `parser.input.read`, while
`parser.token_expand()` sits on top of that and repeatedly pulls from the input
stack until it gets a token that should be returned to the caller.

That means the input layer already includes two closely related services:

- raw token flow from `InputStack`
- expanded token flow through `parser.token_expand()`

The second service is used heavily by the execution layer. It does consult
command meanings while deciding whether the next token should expand, so it sits
near the boundary between input and execution. Still, as a practical matter, it
belongs with token flow: it is the parser’s main interface for obtaining the
next token from the mouth in executable form.

This note only marks that boundary. The detailed behavior of tokenizers,
scanner frames, unread tokens, token-list scanners, and related mechanisms
should be described in the separate token-flow document.

## 2. Parser Execution Layer

`Parser` is the live execution kernel.

It owns the stateful TeX machinery around expansion control, grouped state,
assignment parsing, and command dispatch. In the current code this includes at
least:

- grouped domains such as `equitable`, `parameters`, `layout`, and registered
  arrays
- the group stack and group lifecycle
- the if-stack
- the current list stack
- the current token and related runtime state
- parser-owned typesetting services installed under `parser.typeset`

So the execution layer is broader than grouped state alone. It is the active
machine that takes tokens from the input layer, resolves meanings, parses values
and assignment targets, and dispatches command semantics.

This layer is centered in `parser.py`, with supporting machinery in `state.py`
and in the command modules.

## 3. Layout Construction Layer

The layout layer exists, but in the current code it is split between runtime
list wrappers, structural node objects, and parser-owned typesetting services.

### Runtime list wrappers

While TeX material is being read, the parser works with runtime list objects on
`parser.lists`, such as vertical, horizontal, and math list states.

These wrappers hold build-time state that should not live on the final node
objects. For example, `VList` tracks things such as `\prevdepth`, page-builder
contributions, and raw versus concrete list ownership.

So the current code already distinguishes between:

- runtime build state
- structural objects that will later be packed or shipped

### Structural layout objects

The structural side of layout is represented by nodes, lists, boxes,
paragraph-like objects, alignment objects, math holders, and related
structures.

These are the objects that later typesetting and shipout code consume.

The split is not a pure builder IR versus object IR in the abstract, but there
is a practical distinction in the code:

- commands and mode handlers build list content incrementally
- the resulting node and box structures are then typeset, packed, page-broken,
  or shipped

### Parser-owned typesetting services

The current code makes this boundary clearer through `parser.typeset`, which is
installed from `pytex/typeset/__init__.py`.

That facade currently owns separate services for:

- paragraph typesetting
- math typesetting
- alignment typesetting
- page building
- shipout

This means layout-related work is no longer just an undifferentiated part of
`Parser`, even though command execution still drives it directly.

## 4. Page Building And Output Routine

The page layer is now more explicit than the older note suggests.

Page building is handled by `pytex/typeset/page.py`, while common vertical
breaking logic still lives in `pytex/page.py`.

The important point is that page building is not treated as a passive final pass
over an already finished document. Instead, the parser's main vertical list
contributes nodes incrementally to the page builder while execution continues.

In practice this means:

- the outer `VList` reports contributions to `parser.page_builder`
- the page builder maintains contribution state and pending page material
- page breaking uses the shared vertical breaker logic from `pytex/page.py`
- the output routine is still executed through nested parser activity
- shipped pages are realized from that process rather than reconstructed later

So there is a genuine page layer, but it is tightly coupled to ongoing parser
execution, as in TeX itself.

## 5. Backend Shipout Layer

The clearest backend boundary in the current code is the shipout layer.

`pytex/typeset/shipout.py` provides a backend-neutral walker over shipped boxes.
It reduces shipped material to a small operational interface involving things
such as:

- page begin and end
- positioning
- font definition and selection
- character output
- rule output
- specials

Concrete backends implement this interface.

At present, the main concrete backends are:

- `pytex/dvi.py` for DVI output
- `pytex/pdf.py` for PDF output
- `pytex/html_reflow.py` for reflow-style HTML output

This shipout interface is therefore the most explicit IR-like boundary that the
current code already has.

## Specials

Specials are handled as part of the shipout/backend layer rather than as a
separate top-level execution IR.

In particular, the base shipout layer includes support for `dvipdfm`-style
special parsing through `pytex/typeset/dvipdfm.py`, and concrete backends can
choose whether to handle a special in typed form or fall back to raw special
output.

So specials are already treated as a partially typed backend channel, but they
are attached to shipout, not to a general early command IR.

## HTML Reflow Is A Special Case

The current HTML reflow path does not consume a shared export IR.

Instead, `HTMLReflowBackend` subclasses the shipout backend base class, but it
uses a different final boundary from DVI and PDF. It still allows the normal
page builder, output routine, deferred writes, and shipped whatsit hooks to run,
but the final HTML document is produced at `close()` from the main vertical
list's raw ownership history.

This is why the outer `VList` keeps both:

- concrete nodes used for page building and normal TeX behavior
- raw owner objects used later for reflow rendering

That design is already useful, but it is not yet a reusable general export
layer. It is a backend-specific derivation path.

## What Is Not Fully Separated Yet

The old note was right that there are several meaningful boundaries, but some of
its wording still reads more like a target architecture than the current code.

What is not yet fully separated today includes:

- token flow, expansion control, and command semantics are still closely
  interleaved in `Parser` and the command modules
- layout building is only partly formalized as a separate service boundary;
  many commands still append directly to the active list state
- there is no standalone general page IR beyond the shipped boxes and the page
  builder's own runtime structures
- there is no shared export IR for semantic or reflow backends

So the current architecture is layered, but some of those layers are practical
code boundaries rather than fully abstract interfaces.

## Backend Guidance In The Current Code

If we describe the current code rather than a future design, the backend
boundaries look like this:

- DVI and PDF primarily target the shipout layer
- page breaking and output routine behavior happen before that, through the page
  builder and shipped boxes
- HTML reflow currently derives its final document from the main vertical list's
  raw history and source ownership links, while still letting normal TeX page
  mechanics run

That is more accurate than saying all backends should target one common early IR
or that there is already a shared export layer.

## Short Version

The current code does have layer separation, but it is not organized around one
universal IR.

The most accurate picture today is:

- the input layer is centered on `parser.input` and includes the parser-facing
  token-flow helper `parser.token_expand()`
- `Parser` is the execution kernel that consumes that token flow
- layout construction is split across runtime list wrappers, structural node and
  box objects, and `parser.typeset` services
- page building is an explicit parser-owned subsystem
- the clearest backend boundary is the shipout walker
- HTML reflow uses its own derived path from raw outer-vlist ownership rather
  than a shared export IR

That is the layer split the code currently implements.
