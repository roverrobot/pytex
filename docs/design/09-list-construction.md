# List Construction

This note describes the current list-construction model in the codebase.
It is a description of the present implementation, not a redesign proposal.

The central point is that list construction is now split across three closely
related pieces:

- runtime list wrappers on `parser.lists`
- parser-owned typesetting services under `parser.typeset`
- structural nodes and boxes that hold the realized result

So the current code is not simply “parser-centric” in the sense that all
construction logic has moved onto `Parser` itself. Instead, the parser owns the
live build state and the main services, while local helper methods still remain
where they are mechanical and self-contained.

## Live Build State: `parser.lists`

The most important current boundary is between **runtime build-state wrappers**
and the **structural nodes** that they eventually produce.

The live stack is `parser.lists`, which is a `ListStack`. Pushing a wrapper onto
that stack calls its `open()` hook, and popping it calls its `close()` hook.
This keeps build-time state on the wrapper rather than on the node objects that
will later be packed, shipped out, or serialized.

The current wrappers are:

- `vmode.VList` for vertical-list construction
- `hmode.HList` for horizontal-list construction
- `mmode.MList` for math-list construction

This is a more precise description of the current code than speaking only about
“horizontal and vertical lists.” The runtime objects that live on the parser
stack are wrappers with stateful behavior, not bare Python lists and not just
finished node trees.

## Structural Result Versus Runtime Wrapper

Each wrapper serves a concrete list or node list, but it also owns temporary
state that only matters while the list is being built.

Examples:

- `HList` tracks `\spacefactor`, ligature state, and the raw/concrete split
- `VList` tracks `\prevdepth`, interline insertion behavior, raw nodes, and the
  outer-vlist handoff to the page builder
- `MList` tracks pending atom construction and alignment-related temporary state

This means the structural objects and the runtime wrappers are intentionally not
collapsed into one abstraction.

## Horizontal List Construction

`HList` is the live wrapper for unrestricted and restricted horizontal mode.
Its current job is broader than simply appending nodes.

It handles:

- updating `\spacefactor`
- forming ligatures and automatic kerns during character appends
- maintaining both a raw history and a concrete node list
- special handling for inline math, text accents, and vertical alignments

So horizontal construction is not deferred wholesale to a later packer. Some
realization already happens while the list is being built.

In particular:

- ordinary character input is converted immediately into concrete char,
  ligature, and kern nodes
- inline math is realized through `parser.typeset.math.typesetInlineMath(...)`
  and then spliced into the current horizontal list
- text accents are still handled locally by `AccentNode.typeset(...)`
- `\valign` in horizontal mode is realized through
  `parser.typeset.align.typesetVAlignment(...)`

So the current rule is not “all node-local `typeset` methods are going away.”
The actual rule is narrower: context-heavy realization is moving toward
parser-owned services, while narrowly local realization can remain on the node
or helper class.

## Paragraph Construction

A paragraph is represented by `paragraph.Paragraph`, which is a holder for the
raw and concrete horizontal material collected during paragraph building.

The parser starts a paragraph with `newParagraph(...)`, which pushes an outer
`HList` wrapper onto `parser.lists`. When the paragraph ends,
`Parser.endParagraph(...)` finalizes the horizontal material and hands the
paragraph object to the surrounding vertical list through `VList.appendParagraph(...)`.

The actual paragraph-to-lines realization is parser-owned:

- `VList.appendParagraph(...)` calls `parser.typeset.paragraph.typeset(...)`
- `typeset/paragraph.py` performs break scanning, line breaking, line packing,
  and display-state updates
- the resulting line boxes are appended back into the vertical list

So the current code treats paragraph breaking as a parser-owned typesetting
service, not as a local method on `Paragraph` itself, even though
`Paragraph` still exposes convenience methods that delegate into that service.

## Vertical List Construction

`VList` is the live vertical build-state wrapper.

Its current responsibilities include:

- maintaining the concrete vertical list being built
- maintaining a separate raw history in `raw`
- updating `\prevdepth`
- inserting interline penalties and interline glue when appropriate
- appending paragraph, display-math, alignment, and `\vadjust` contributions
- handing outer-vlist contributions to the page builder

This last point is important.

For the **outer** vertical list, page-building is no longer an implicit side
consequence hidden somewhere else. `VList` explicitly calls
`page_builder.contribute(self, node)` after relevant contributions have been
made. For realized paragraph and display-math material, the handoff happens from
`appendParagraph(...)`, `appendDisplayMath(...)`, `appendHAlignment(...)`, and
`appendMAlignment(...)`.

So the current boundary is:

- `VList` owns live vertical-list construction
- `PageBuilder` owns contribution-list accumulation and page breaking
- the handoff is explicit in the runtime code

That part of the older note was broadly right, but the current code is now
concrete enough that it is better to describe the actual methods rather than
only the architectural intent.

## Math List Construction

`MList` is the live math-mode wrapper. It is not just a passive list of atoms.
It still owns build-time state such as:

- pending atom construction for subscripts and superscripts
- normalization of appended nodes into math-appropriate forms
- temporary alignment-related state

The realized structural objects include things such as `Atom`, `Subformula`,
`InlineMathNode`, and `DisplayMathNode`.

The main realization pipeline for math now lives under
`parser.typeset.math`.

In particular:

- `MathListHolder.typeset(...)` delegates to `parser.math_typesetter`
- many math node `typeset(...)` methods now delegate into
  `parser.math_typesetter`
- delimiter selection, accent-nucleus construction, atom spacing, inline math,
  and display math are centralized in `typeset/math.py`

So the current math split is:

- `MList` owns live build-time math state
- math nodes still exist as structural objects and sometimes expose thin
  `typeset(...)` entry points
- the substantial realization logic is centralized in `MathTypesetter`

## Alignment Construction

Alignment construction is also split between a parser-owned runtime phase and a
parser-owned realization phase.

The parsing side uses alignment-specific runtime helpers such as:

- `AlignmentBuildStack`
- `RowBuildState`
- `CellBuildState`

These manage cell collection, template injection, grouping, and row completion
while the alignment is being read.

After the alignment structure has been built, realization is handled mainly by
`parser.typeset.align`:

- `typesetHAlignment(...)` realizes `\halign` into vertical material
- `typesetVAlignment(...)` realizes `\valign` into horizontal material
- `typesetMAlignment(...)` realizes display-style math alignment material

This means alignment is not just “a node that later packs itself.” The current
code has a real two-stage model:

1. runtime parsing/building of rows and cells
2. parser-owned realization into boxes and surrounding glue/penalty material

## Box Packing And Local Helpers

Local realization helpers still remain important.

The clearest examples are box packers such as:

- `HBox.typeset(...)`
- `VBox.typeset(...)`
- `VTop.typeset(...)`

These methods are still active and still central. They compute dimensions,
measure content, set glue ratios, and return packed box objects.

Similarly, some narrowly local realization still remains on node classes, such
as horizontal accent placement in `AccentNode.typeset(...)`.

So the current code does **not** follow a rule that all `typeset(...)` methods
should disappear. The actual distinction is:

- parser-owned typesetters handle context-dependent realization that depends on
  live parser layout state or larger structured input
- local helpers remain where the work is already determined and mostly
  mechanical

## Raw Versus Concrete Material

Another important current feature is the distinction between **raw** and
**concrete** list content.

This shows up most clearly in `HList` and `VList`.

- `raw` keeps a higher-level history of what was appended
- `list` keeps the concrete realized nodes used for later packing or page
  building

For the outer vertical list, `concreteNodes()` may also incorporate nodes that
have already been flushed into the page builder’s contribution list.

This distinction matters for backends such as HTML reflow and for any later work
that wants to preserve more structural provenance than a fully flattened box
list alone would provide.

## Relationship To The Surrounding Notes

This list-construction note sits between the broader layer notes and the later
backend notes.

Relative to the surrounding architecture documents, the current code can be
summarized as follows:

- the parser owns the live execution stack and the live list-build state
- runtime wrappers on `parser.lists` own mode-specific build-time state
- parser-owned typeset services realize larger structures such as paragraphs,
  math, alignments, page building, and shipout
- structural nodes and boxes remain the durable layout objects
- local packers and narrow realization helpers still remain where appropriate

## Short Version

The current list-construction model is:

- live list building happens through runtime wrappers on `parser.lists`
- `HList`, `VList`, and `MList` keep build-time state off the final node objects
- paragraphs, math, and alignments are mainly realized by parser-owned
  typesetters under `parser.typeset`
- box packing is still local to `HBox`, `VBox`, and `VTop`
- some narrow local realization, such as text accents, still remains on node
  classes
- the outer `VList` hands contributions explicitly to `PageBuilder`
- raw and concrete list histories are both preserved where needed
