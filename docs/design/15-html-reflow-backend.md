# HTML Reflow Backend

This note describes the current `html_reflow` backend.

It is a backend for readable, document-order HTML, not a page-faithful HTML
renderer. A separate design note describes a possible high-fidelity HTML
backend.

## Main Point

`html_reflow` keeps the normal TeX and LaTeX page lifecycle alive, but does not
use shipped page geometry as the main HTML source.

In the current code:

- the normal page builder still runs
- the normal output routine still runs
- builtin `\shipout` still runs
- `HTMLReflowBackend.shipout(box)` records shipped pages and executes whatsits
- final HTML is written once, at document close
- the final document is rendered from the outer main vertical list's preserved
  raw ownership history

So reflow is not a replacement for page building. It is a null visual shipout
backend plus an end-of-document renderer.

## Why It Works This Way

An earlier design tried to derive reflow HTML directly from page-builder input
and bypass more of TeX's page lifecycle.

That was not compatible enough with real LaTeX workflows. Packages expect the
usual page and shipout machinery to run for things such as:

- deferred `\write`
- aux replay
- bookmark and link hooks
- output-routine-installed actions
- ordinary end-of-page and `\shipout` behavior

The current design keeps that machinery alive for compatibility, then derives
reflow HTML from preserved raw document structure rather than page geometry.

## Installation And Ownership

`HTMLReflowBackend` subclasses `typeset.shipout.Shipout`, but it does not use
shipout in the same way as the DVI and PDF backends.

In practice:

- the parser still owns the normal page builder
- `parser.shipout` is set to `HTMLReflowBackend(parser)` by the entry script in
  reflow mode
- `HTMLReflowBackend.open()` is a no-op
- `HTMLReflowBackend.close()` performs the real HTML output step

So this backend participates in shipout-time execution, but its actual visible
output is delayed until document close.

## Runtime Shipout Behavior

At runtime, `shipout(box)` does only the work needed to preserve TeX behavior
and collect a small amount of auxiliary information.

Its current behavior is:

- if the shipped box is still unpacked, pack it first
- append the shipped page box to `self.pages`
- walk the page tree and execute whatsits by calling their `output(...)`
  method

It does **not** emit visual page HTML during shipout.

This is why the backend can keep `\write`, specials, and other whatsit-time
side effects honest without becoming a page-faithful HTML renderer.

## Main Document Source

The final HTML document is built from the raw ownership history of the outer
main vertical list.

In the current code:

- `VList.list` is the concrete pending content used for page building
- `VList.raw` preserves the archival owner history
- `HTMLReflowBackend.close()` reads the document from
  `parser.lists[0].rawNodes()`

The page builder is allowed to consume and rearrange the concrete contribution
list, but the outer raw owner stream must survive so reflow can still render
in document order at the end of the run.

## Relationship To Shipped Pages

Although the main HTML comes from raw owners rather than shipped pages, shipped
pages are still used for two things.

### Whatsit execution

Shipped-page traversal executes whatsits at normal shipout time so ordinary TeX
side effects still happen.

### Media detection

The backend also inspects shipped pages to detect some media containers,
especially `pdf:epdf ...` inclusions that are easiest to recognize from the
runtime box tree. Those are later turned into `<figure>` blocks in the final
HTML.

So the backend is not purely raw-owner driven. It is mostly raw-owner driven,
with shipped pages used for shipout-time effects and some media recovery.

## Block Rendering Model

The document renderer walks outer-vertical raw owners and turns them into block
HTML.

Current important cases are:

- `Paragraph` -> `<p>`
- `DisplayMathNode` -> display MathML block
- `HAlignment` -> HTML `<table>`
- `MAlignment` -> display-math block or alignment table, depending on context
- `VAdjust` -> inline expansion of its owned blocks
- rule nodes -> `<hr>`
- `\insert` nodes -> `<aside class="note">`
- whatsits and specials -> anchors, links, or hidden markers
- media containers -> `<figure>` with an embedded PDF object/link

This is document-order rendering, not page reconstruction.

## Paragraph Rendering

Paragraphs are rendered from their raw owned nodes, not from shipped line-box
fragments.

The inline renderer currently recognizes:

- character nodes
- ligatures, usually expanded back to source characters
- glue as collapsible spaces
- discretionary replacement text
- inline math owners
- specials and whatsits
- forced line breaks from `Penalty <= -10000`

Positive penalties are ignored in reflow prose.

Each paragraph receives:

- a dominant font inferred from its concrete content
- paragraph classes for indentation (`indent` or `noindent`)
- inline font-change spans when the paragraph switches font role or size

The backend intentionally does **not** infer heading semantics from font size.
A large-font paragraph is still rendered as a paragraph.

## Font Heuristics

HTML reflow does not preserve TeX font identity literally.

Instead it uses a lightweight role model:

- serif / sans-serif / monospace family
- bold weight
- italic style
- small-caps variant
- relative font-size changes

It also records the TeX font name in `data-tex-font` when a span-level font
change is emitted.

This keeps prose readable and preserves some authorial intent without requiring
page-faithful web font reconstruction.

## Specials And Hyperlinks

Special nodes are preserved and interpreted where useful.

Current special handling includes:

- `pdf: dest (...)` -> HTML anchor target via `id=...`
- dvipdfm or dvipdfmx GoTo annotations -> internal HTML links
- GoToR annotations -> external links, optionally with fragment targets
- other specials -> hidden marker spans with `data-tex-special=...`

So cross-references can become real hyperlinks even though the backend does not
render page geometry.

## Math Rendering

Math is rendered from raw math nodes, not from shipped TeX glyph boxes.

That is the most important semantic choice in the current backend.

### Why raw math nodes are used

Shipped math boxes contain concrete glyph choices and box geometry, but reflow
needs structure such as:

- atom kind
- subscript and superscript structure
- fractions
- radicals
- accents
- math alignments and matrices
- equation labels

That structure is still available in the raw math owners.

### Current math output format

The backend emits MathML and relies on browser math fonts for appearance.
The generated HTML includes a small default math font stack, for example:

- `Latin Modern Math`
- `STIX Two Math`
- `Cambria Math`
- generic `math`

So the current split is:

- TeX raw math nodes provide structure
- a small TeX-math-symbol decoder provides Unicode leaf characters
- MathML provides layout
- browser math fonts provide appearance

### Current MathML mapping

The current renderer handles at least these cases:

- `MathSymbol` -> MathML leaf token
- `InlineMathNode` -> inline `<math class="inline-math">`
- `DisplayMathNode` -> block `<math display="block" class="display-mathml">`
- `Over` -> `<mfrac>` with optional delimiters
- `Rad` -> `<msqrt>`
- `Accent` -> `<mover accent="true">`
- `Atom` scripts -> `msub`, `msup`, or `msubsup`
- math-internal `HAlignment` -> MathML `mtable`
- displayed equation alignments -> HTML table wrapper with MathML cells

Equation numbers from `\eqno` or `\leqno` are rendered as a separate label lane
beside the display math body.

### Raw math recovery inside prose

Raw paragraph streams do not always contain explicit `InlineMathNode` objects.
Sometimes they contain chars or boxes whose `.source` chain points back into a
semantic math owner.

The backend therefore examines the `.source` chain and promotes content to
inline math only when the chain passes through actual semantic math nodes. This
avoids accidentally converting arbitrary wrapper boxes into MathML.

## Alignments And Tables

`HAlignment` is used for more than one purpose in the engine, so reflow does
not force every alignment into one HTML representation.

Current behavior is:

- plain top-level `HAlignment` -> HTML `<table class="alignment">`
- `MAlignment` whose source is an `HAlignment` -> displayed equation table with
  MathML cells
- math-internal `HAlignment` -> MathML `mtable`

So the representation depends on context:

- table-like outside math -> HTML table
- matrix-like inside math -> MathML table
- aligned displayed equations -> HTML table wrapper with MathML cells

## Inserts And Notes

`\insert` material is reinterpreted for reflow as note-like content rather than
page-local footnote geometry.

The current HTML shape is intentionally simple:

- `<aside class="note">...</aside>`

This keeps note content in reading order rather than preserving page-local note
areas.

## Media And Figures

Some PDF media inclusions are detected from shipped page boxes rather than from
raw-owner structure.

The current backend looks for media containers involving `pdf:epdf ...`
specials, then emits them as figure-like blocks such as:

- `<figure>`
- nested `<object type="application/pdf">`
- fallback link to the PDF
- optional `<figcaption>` derived from surrounding text

This is one place where shipped-page inspection still contributes directly to
final HTML.

## Output Handling

The backend writes one HTML file at close time.

Current output behavior is:

- if the output target is already file-like, write there
- otherwise derive a `.html` path from the output name or jobname
- relative outputs go through `resolver.openOut(...)`

So the final HTML follows the resolver's ordinary output policy rather than
inventing a separate output path.

## What Reflow Deliberately Ignores

The current backend does not try to preserve page-faithful output features
such as:

- running headers and footers
- page geometry
- page numbers as layout furniture
- exact page-local mark behavior
- final visual shipout positioning
- general page-local reconstruction of the output routine's visual results

The normal page lifecycle still runs for compatibility, but the final HTML does
not aim to reproduce page appearance.

## Relationship To Other Notes

This backend is downstream of the parser, list-construction, typeset, and
shipout layers, but it is not a normal packed-page device backend like DVI or
PDF.

It uses:

- the ordinary page builder and output routine for runtime compatibility
- the shipout layer for whatsit execution and page collection
- the outer vertical list's raw owner history for final document rendering

A separate design note describes a possible high-fidelity HTML backend that
would instead consume shipped pages more directly.

## Short Version

The current `html_reflow` backend works like this:

- keep the normal TeX page builder and output routine alive
- use `HTMLReflowBackend.shipout(...)` only for shipped-page collection and
  whatsit execution
- preserve the outer main vertical list's raw ownership history
- render final HTML once, at close, from that raw document-order stream
- render prose from raw paragraph nodes
- render math from raw math nodes as MathML
- treat tables, aligned displays, notes, specials, and media according to
  semantic context rather than page geometry
