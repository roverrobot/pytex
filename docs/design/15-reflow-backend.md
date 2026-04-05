# Reflow Backend

This note describes the current `html_reflow` implementation.

It supersedes the earlier idea that reflow should consume the outer vertical
list contribution stream in parallel with the page builder. That earlier model
was a good semantic target, but it broke real LaTeX workflows that depend on
the normal page builder, output routine, and builtin `\shipout` lifecycle.

The current design keeps TeX/LaTeX pagination alive for compatibility, but
builds the final HTML from the preserved raw document stream.

## Main Point

`html_reflow` is now a null shipout backend plus an end-of-document renderer.

In practice:

- the normal page builder still runs
- the normal output routine still runs
- builtin `\shipout` still runs
- `html_reflow` does not emit visual page output at shipout time
- final HTML is written once, at document close, from the outer main vertical
  list's raw ownership history

So reflow is no longer a replacement for page building.

It is a compatibility-preserving backend that lets TeX finish its normal page
  lifecycle, while deriving reflow HTML from the preserved semantic stream.

## Why We Changed Direction

The earlier design tried to bypass the page builder and output routine because
reflow should not be page-driven semantically.

That turned out to be too aggressive operationally.

LaTeX packages depend on the normal end-of-page and shipout lifecycle for
things such as:

- deferred `\write`
- aux replay
- bookmark/link hooks
- output-routine-installed late actions
- allocation/opening of output streams associated with shipout hooks

Skipping that machinery caused real failures, such as bookmark-related aux
replay errors.

So the current design keeps the TeX page/output machinery alive, but simply
does not use shipped page geometry as the primary HTML source.

## Runtime Architecture

In reflow mode:

- `parser.shipout` is set to `HTMLReflowBackend`
- `parser.page_builder` remains the normal TeX page builder
- the LaTeX output routine still assembles `\box255` and calls builtin
  `\shipout`

At runtime, `HTMLReflowBackend.shipout(box)` does only two things:

- records shipped pages in `self.pages`
- walks the shipped box tree and executes whatsits

It does not emit visual HTML per page.

`open()` is intentionally a no-op for this backend.

At the end of the document, `HTMLReflowBackend.close()` renders one HTML
document from the outer main vertical list's preserved raw owners.

## Document Input For Reflow

The final reflow input is the raw ownership history of the outer main vertical
list:

- `VList.list` is the expanded pending content used for page breaking
- `VList.raw` is the archival raw history of contributed owners

The page builder is allowed to drain `VList.list`, but it must not destroy the
outer `VList.raw` history.

Reflow therefore reads the document from:

- `parser.lists[0].rawNodes()`

at document close, after TeX has finished the run.

This gives reflow a stable document-order stream while still allowing ordinary
TeX pagination to happen during the run.

## What Reflow Renders

The renderer walks raw owners and maps them to block HTML.

Current important cases are:

- `Paragraph` -> `<p>`
- `DisplayMathNode` -> block MathML container
- `HAlignment` -> HTML table
- `MAlignment` -> display math block or alignment table, depending on source
- `VAdjust` -> inline expansion of its owned blocks
- rules -> `<hr>`
- `\insert` nodes -> `<aside class="note">`
- whatsits/specials -> anchors, links, or hidden markers
- media containers -> `<figure>` with embedded object/link

This is document-order rendering, not page-order reconstruction.

## Paragraph Rendering

Paragraphs are rendered from their raw owned nodes, not from shipped page
fragments.

The inline text pass recognizes:

- character nodes
- ligatures
- glue as collapsible spaces
- discretionary replacements
- inline math owners
- specials/whatsits
- forced line breaks

Positive penalties are ignored in reflow.

Only `Penalty <= -10000` is treated as an actual break opportunity that becomes
`<br>`. This matches TeX's "break here" meaning better than treating large
positive penalties as breaks.

Paragraph font handling is approximate but useful:

- the paragraph gets a dominant font inferred from its concrete line-box list
- inline font changes become `<span>` wrappers with font metadata/styles
- section titles currently remain paragraphs; reflow does not infer heading
  semantics from font size alone

## Specials And Hyperlinks

Special nodes are preserved and interpreted where useful.

Current handling includes:

- `pdf:dest (...)` -> HTML anchor target via `id=...`
- dvipdfm/dvipdfmx GoTo annotations -> HTML links
- GoToR annotations -> external links, optionally with fragment targets
- other specials -> hidden marker spans with `data-tex-special=...`

This means cross-references can become real hyperlinks in the reflow output
without requiring page-faithful shipout graphics.

## Math Rendering

Math is rendered from raw math nodes, not from shipped TeX glyph boxes.

This is the most important implementation change compared to the earliest HTML
prototype.

### Why Raw Math Nodes

Shipped math boxes contain concrete glyphs and layout artifacts, but reflow
needs structure:

- atom kind
- delimiters
- numerator/denominator structure
- scripts
- accents
- alignment structure

The raw math nodes already carry that information.

### Math Output Format

Math is emitted as MathML and styled with a real browser math-font stack:

- `Latin Modern Math`
- `STIX Two Math`
- `Cambria Math`
- generic `math`

So the current split is:

- TeX raw math nodes provide structure
- a small TeX-math-symbol decoder provides Unicode leaf characters
- MathML provides layout
- browser math fonts provide appearance

### Symbol Decoding

Classic TeX math fonts are slot-encoded, not browser-ready text.

So reflow still needs a small mapping layer from TeX math family/code values to
Unicode characters.

That mapping currently covers the common Computer Modern math families used by
the existing parser state, such as:

- operators
- Greek letters
- relation and binary symbols
- large operator symbols

This mapping is only for leaf-symbol decoding. It is not the overall math
layout strategy.

### MathML Mapping

The current renderer maps raw math structures approximately like this:

- `MathSymbol` -> MathML leaf (`<mi>`, `<mo>`, or `<mn>` depending on atom type)
- `MathListHolder`, `Subformula`, `InlineMathNode`, `DisplayMathNode` -> grouped
  MathML content
- `Over` -> `<mfrac>` with optional delimiters
- `Rad` -> `<msqrt>`
- `Accent` -> `<mover accent="true">`
- `Atom` scripts -> `<msub>`, `<msup>`, or `<msubsup>`
- delimiter/boundary atoms -> grouped fenced MathML content

Inline math becomes:

- `<math class="inline-math">`

Display math becomes:

- `<math display="block" class="display-mathml">`

### Raw Math Recovery Inside Paragraphs

Paragraph raw streams do not always contain explicit `InlineMathNode` objects.
Sometimes they contain concrete chars or boxes whose `.source` chain points back
into math.

The renderer therefore walks the `.source` chain and only promotes such content
to inline math when the chain passes through actual semantic math nodes such as:

- `MathSymbol`
- `Atom`
- `Subformula`
- `MathListHolder`
- math/alignment owners

This avoids accidentally turning arbitrary wrapper boxes into MathML.

### Breaks Inside Math

The raw math-to-MathML conversion uses the same normalized raw segment stream as
text, but a forced break becomes:

- `<mspace linebreak="newline">`

instead of `<br>`.

### Equation Numbers

Display equations with `\eqno`/`\leqno` are rendered as a two-part block:

- centered display math body
- equation label lane on the left or right

When the label is plain numeric text, reflow wraps it as `(n)` in HTML.
Otherwise it falls back to MathML for the equation label itself.

## Alignments And Tables

`HAlignment` is used for both genuine tables and math-style alignments, so
reflow does not replace it wholesale with one representation.

Current behavior is:

- plain top-level `HAlignment` -> HTML `<table>`
- `MAlignment` with `HAlignment` source -> display alignment table whose cells
  are rendered as MathML fragments
- math-internal `HAlignment` -> MathML `<mtable>` for matrix/array-like
  structures

So the representation depends on context:

- table-like outside math -> HTML table
- matrix/array-like inside math -> MathML table
- aligned displayed equations -> HTML table wrapper with MathML cells

This is intentionally pragmatic. It preserves readable aligned displays without
forcing every `HAlignment` into MathML.

## Media And Figures

Embedded PDF-media specials are still detected from the shipped page boxes,
because those containers are easiest to identify from the runtime box tree.

The backend records shipped pages during normal `\shipout`, then scans them for
media containers and turns them into source-order-ish `<figure>` blocks in the
final document.

So media is one place where the runtime shipout walk still contributes useful
information beyond whatsit execution.

## Inserts And Notes

`\insert` content is reinterpreted for reflow as note-like anchored content, not
as page-local footnote area geometry.

The current HTML shape is intentionally simple:

- `<aside class="note">...</aside>`

This stays faithful to reading order, not page placement.

## What Reflow Deliberately Ignores

Reflow does not try to preserve page-faithful output such as:

- running headers/footers
- page geometry
- page numbers as layout furniture
- exact page-local mark behavior
- final visual shipout positioning

The normal page/output lifecycle still runs for compatibility, but the reflow
renderer intentionally ignores most page furniture when building HTML.

## Short Version

The current `html_reflow` backend works like this:

- keep the normal TeX page builder and output routine
- use a null shipout backend so whatsits, writes, aux replay, and hooks still
  run
- preserve the outer main vertical list's raw ownership history
- render final HTML once, at close, from that raw document-order stream
- render prose from raw paragraph nodes, with only forced penalties producing
  line breaks
- render math from raw math nodes as MathML, using a TeX-symbol-to-Unicode leaf
  map plus real browser math fonts
- treat tables, aligned displays, notes, specials, and media according to their
  semantic context rather than page geometry
