# Typeset Backends

This note summarizes the parser-owned typesetting services installed by the
`typeset` module and the IR-like contracts they currently expose.

The current code does **not** have one universal typesetting IR.

Instead, `parser.typeset` is a facade over several narrow services, each with
its own input shape and sink:

- paragraph typesetting
- math typesetting
- alignment typesetting
- page building

So the right way to describe the current state is not “the typesetter exposes
one backend-neutral IR”, but rather:

- each service exposes a small operational contract
- those contracts sit between the runtime list wrappers and later packed boxes
  or page-ready material
- shipout is downstream of these services and is described separately in the
  shipout IR note

## Installation And Ownership

The `typeset` module installs:

- `parser.typeset`
- `parser.line_breaker`
- `parser.math_typesetter`
- `parser.alignment_typesetter`
- `parser.page_builder`
- `parser.shipout`

The central object is `TypesetOps`, which constructs:

- `ParagraphTypesetter`
- `MathTypesetter`
- `AlignmentTypesetter`
- `PageBuilder`
- `Shipout`

So these services are parser-owned runtime helpers, not free-standing backend
objects.

Within that installation, the first four are the construction-oriented
realization services summarized here. `parser.shipout` is still installed by the
same module, but it is a downstream page-output layer rather than another
construction-oriented typesetter service.

## Main Boundary

The current split is:

- runtime list wrappers such as `HList`, `VList`, and `MList` own build-time
  scanning state
- parser-owned typeset services realize larger structures when list building
  needs semantic or contextual decisions
- local node or box methods still remain where the work is only packing,
  measuring, or narrowly local realization
- packed pages then flow into the separate shipout layer

This means the typeset services are not replacing every local `typeset` method.
They sit above the local packers and below the downstream shipout backends.

## Paragraph Typesetter

`ParagraphTypesetter` is the parser-owned line breaker and paragraph realizer.

Its public operational contract is:

- input: a paragraph-like horizontal-list owner plus a destination `VList`
- output: append concrete line boxes and migratory nodes to that `VList`

The main entry point is:

- `typeset(para, vlist)`

The important current behavior is:

- scan legal breakpoints
- choose line breaks
- optionally retry with hyphenation
- pack each chosen line into an `HBox`
- append line boxes to the destination vertical list
- append migratory nodes separately
- update `\prevgraf`
- optionally update display-math state through `parser.updateDisplayState(...)`

So the paragraph service does not return a standalone abstract paragraph IR.
Its effective IR is a sink-oriented one:

- paragraph owner in
- concrete line boxes out into a vertical list

The narrower helper contracts are:

- `scanBreaks(para, nodes)` -> break candidates
- `lineBreak(para, hlist, breaks=None)` -> `(working_hlist, lines)`
- `hyphenate(para, hlist=None, scan=None)` -> `(hlist, breaks)` or `None`
- `typesetFragment(chars)` -> concrete node list for a hyphenated fragment

These helpers are still paragraph-specific. They are not shared by the other
services.

## Math Typesetter

`MathTypesetter` is the parser-owned realization pipeline for math lists,
delimiters, accents, and display layout.

Its contract is broader than the paragraph one, because math currently uses a
small internal two-pass realization pipeline.

### Public Shape

The main entry points are:

- `typesetNodes(holder, packed, context, style)`
- `typesetAtom(atom, packed, context=None, style=None, atom_type=None, text_symbol=None)`
- `typesetField(field, packed, context, style)`
- `typesetHolder(holder, packed, context, style)`
- `typesetSubformula(holder, packed, context, style)`
- `typesetInlineMath(holder, packed)`
- `typesetDisplayMath(holder, packed)`

The external pattern is usually:

- input: a math holder or field, plus a destination packed-node list
- output: append concrete nodes and boxes to that destination list

So the math typesetter is also sink-oriented, but unlike the paragraph service,
it additionally carries explicit:

- `context`
- `style`

because those are essential to the realization rules.

### Internal Two-Pass IR

Internally, math typesetting currently uses a small intermediate form.

Pass 1 collects a mixed stream of:

- wrapped atoms carrying effective atom type and style
- non-atom items that should pass through directly

Pass 2 then emits concrete nodes, spacing, penalties, delimiters, and packed
boxes.

The main internal helpers are:

- `_pass1Collect(holder, context, style)`
- `_pass1AdjustAtoms(context, collected)`
- `_pass2Emit(holder, packed, context, collected)`

So the math service does have an internal IR, but it is private to the math
backend. It is not used as a common engine-wide IR.

### Specialized Math Realization Hooks

Some math constructs are centralized here rather than left on nodes:

- `emitMathSymbol(...)`
- `typesetDelimiter(...)`
- `typesetAccentNucleus(...)`

These are parser-owned because they depend on current math style, font choice,
delimiter growth rules, and similar contextual decisions.

## Alignment Typesetter

`AlignmentTypesetter` realizes `\halign`, `\valign`, and display-math
alignment results.

Its public contract is intentionally small:

- `typesetHAlignment(alignment, vlist)`
- `typesetVAlignment(alignment, packed)`
- `typesetMAlignment(alignment, vlist)`

So alignment does **not** expose one common return shape.
The sink depends on the alignment kind:

- horizontal alignment -> append row boxes into a destination `VList`
- vertical alignment -> append concrete nodes into a packed-node sink
- math alignment -> append display-oriented material into a destination `VList`

This reflects the actual role of each construct in TeX.

The alignment service is therefore best understood as a family of
alignment-specific realization backends, not as one backend-neutral alignment
IR.

## Page Builder

`PageBuilder` is the parser-owned page-building service for the outer vertical
list.

Its contract is not “pack this object”, but “consume vertical contributions and
run page breaking when needed”.

The main public entry points are:

- `contribute(pending, node)`
- `contributePending(pending)`
- `processPendingPages(pending, force=False)`
- `finish(pending)`

The current operational model is:

- the outer `VList` appends nodes normally
- when a triggering node arrives, it calls `page_builder.contribute(...)`
- the page builder moves pending nodes into its contribution list
- it runs page-breaking logic over that contribution list
- when a page is chosen, it runs the output routine or direct shipout
- carry-over material is returned to the contribution stream as needed

So the current page-builder IR is contribution-oriented:

- input: outer-vlist contributions plus page context
- output: page-ready boxes and carry-over contribution material

`PageBreaker` underneath this uses a more explicit internal breaking IR,
including insertion actions such as:

- full insertion
- deferred insertion
- split insertion

But that action structure is internal page-breaking machinery, not the public
contract of `PageBuilder`.

## Downstream Shipout Boundary

The `typeset` module also installs `parser.shipout`, but shipout is better
understood as a separate downstream layer than as another typesetter service.

The role of the first four services is:

- paragraph -> realize paragraphs into line boxes in a `VList`
- math -> realize math lists into concrete packed nodes and boxes
- alignment -> realize alignment structures into sink-specific output material
- page builder -> turn outer-vertical contributions into page-ready boxes

After that point, packed page boxes flow into shipout.

Shipout is where the current code exposes a true page-output backend IR. That
is the layer implemented by concrete output backends such as DVI and PDF, and
it is described separately in the shipout IR document.

This separation matters because DVI and PDF are not “typeset backends” in the
same sense as paragraph or math typesetters. They are shipout backends.

`HTMLReflowBackend` remains a special case. It is attached at the same runtime
hook point, but it does not use ordinary packed-page traversal as its final
export path.

## What Is Not Part Of This Note

This note is about the parser-owned construction and layout-realization
services in `pytex/typeset`. It is not a full summary of every local `typeset`
method in the codebase, and it is not the canonical description of the shipout
walker or output-device callbacks.

In particular, local methods such as:

- `HBox.typeset(...)`
- `VBox.typeset(...)`
- `VTop.typeset(...)`
- node-local math-field methods

still matter, but they are local realization helpers rather than the higher
service boundaries summarized here.

## Relationship To The Other Notes

This note fits after:

- layer separation
- module framework
- token flow
- resolver and pipe backends
- parser state and parser kernel
- assignment and list construction
- font backends

because it assumes those earlier boundaries already exist.

In particular:

- the list-construction note describes the live wrappers and structural nodes
- this note describes the parser-owned realization services that sit on top of
  those wrappers
- the separate shipout note describes the packed-page traversal layer and the
  device-facing backend IR used by DVI- and PDF-style output backends

## Short Version

The current code does not expose one universal typesetter IR.

Instead it has four construction-oriented service contracts:

- paragraph: paragraph owner -> append line boxes to a `VList`
- math: math holder + context/style -> append concrete nodes to a packed sink
- alignment: alignment object -> append boxes or nodes to a sink chosen by alignment kind
- page builder: outer-vlist contributions -> page-ready boxes and carry-over material

Packed page boxes then flow into the separate shipout IR.

Only shipout is a true output-backend IR in the narrow sense.
The others are parser-owned realization interfaces between live list
construction and later packed layout artifacts.
