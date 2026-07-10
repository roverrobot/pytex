# High-Fidelity DOCX Backend Proposal

This note describes a possible high-fidelity DOCX backend for `pytex`.

It is a design proposal, not a claim that the current implementation already
supports the full model. The current proof of concept lives in
`pytex/docx.py` and is intentionally much narrower.

## Main Point

A faithful DOCX backend should treat TeX as the layout authority and DOCX as an
editable carrier for that chosen result.

DOCX is not a fixed-page target like PDF, but it is also not a purely semantic
reflow format like `html_reflow`. It is a structured document format with
paragraph flow, sections, headers, footers, footnotes, anchored objects, and
page-aware features. That makes it a hybrid target:

- more structured and editable than PDF
- more page-aware than semantic HTML
- still ultimately re-paginated by Word

So the backend should aim for:

1. TeX-chosen paragraph breaks and line breaks
2. TeX-sized hard objects where Word cannot be trusted to size them
3. native DOCX structures where they are faithful enough
4. explicit documentation of the places where Word may still drift

## Relationship To Existing Backend Layers

This backend fits the current multi-layer architecture:

- execution and layout remain in the existing TeX engine
- page building and the output routine still run normally
- a DOCX-specific export layer is derived from layout and page information

It should sit conceptually between the current `html_reflow` backend and the
shipout-oriented backends:

- like `html_reflow`, it needs a derived export structure rather than raw DVI
  bytecode-style output
- unlike `html_reflow`, it must preserve page semantics such as sections,
  headers, footers, and footnotes

The design should not force DOCX through the same boundary as DVI or PDF, but
it also should not pretend DOCX is page-agnostic.

## Two Products, Not One Knob

DOCX export really wants two distinct modes.

### Semantic DOCX

This mode prioritizes editability and native Word structures.

It can allow Word more freedom to compose:

- paragraphs
- native tables
- native math where acceptable
- more semantic structures

### Fidelity DOCX

This mode prioritizes TeX's chosen layout.

It should freeze more of TeX's decisions:

- paragraph and line breaks
- hyphenation decisions
- hard object dimensions
- explicit page and section breaks where needed

These modes can share machinery, but they should be documented as different
products with different guarantees.

## Paragraph Strategy

Paragraphs are the core difficulty.

### Freeze TeX line breaks

In fidelity mode:

- TeX breaks the paragraph
- the backend records the chosen lines
- DOCX receives explicit line breaks rather than asking Word to rediscover them

This is the most important way to keep the result close to TeX.

### Preserve TeX hyphenation

Automatic DOCX hyphenation should be disabled in fidelity mode.

The backend should emit only the hyphen points TeX actually used.

### Treat glue as resolved output

DOCX does not expose TeX-style glue, stretch, and shrink directly.

So the backend should export the resolved paragraph result rather than trying to
recreate TeX glue as a live abstraction.

That said, this remains an experimental area. The current practical options are:

- ordinary spaces when explicit line breaks already freeze the line structure
- run segmentation plus spacing hints
- small repair adjustments on difficult lines

This needs measurement on tight lines. The backend should explicitly allow the
possibility that some lines cannot be matched within tolerance without document
bloat.

### Current proof-of-concept direction

The current `pytex/docx.py` prototype takes a shipout-time approach:

- walk the shipped `vlist`
- detect line boxes whose `.source` chain leads to a `Paragraph`
- reconstruct one Word paragraph per TeX paragraph
- insert explicit Word line breaks between TeX lines

That is a reasonable first experiment because it tests the frozen-line part of
the fidelity story before introducing math, tables, or page furniture.

## Hard Objects And Boxing

Some objects are too risky to hand over to Word composition directly.

Important examples are:

- inline math
- display math
- alignments
- hard tables
- inserted compound sublayouts

The issue is dimensional predictability. TeX cannot safely break lines or pages
around an object whose final size is unknown until Word composes it.

### Fidelity rule

In fidelity mode, these should be treated as TeX-sized opaque boxes whenever
their Word-native realization cannot be trusted to preserve:

- width
- height
- depth
- baseline relationship

### Text boxes as the current fallback candidate

The current likely DOCX fallback is a text box or similar drawing object.

That may be:

- inline for paragraph-contained hard objects
- floating or anchored for genuinely positioned objects

But this is still a candidate, not a solved fact. Word still owns important
behavior around line height, baseline alignment, and object placement, so the
proposal should not assume that text boxes perfectly realize arbitrary TeX box
metrics until this is measured.

### Box taxonomy

The backend should distinguish:

- atomic inline spans for ordinary `\hbox`-like "do not break here" material
- inline opaque boxes for paragraph-contained hard objects
- block opaque boxes in normal flow for display material
- anchored or floating boxes only for genuinely positioned material

This matters because "unbreakable" and "positioned" are not the same thing.

## Fonts And Metrics

Matching visible glyphs alone is not enough.

TeX paragraph fitting depends on:

- widths
- ligatures
- kerning
- `\fontdimen`

So the real goal is metric compatibility close enough that TeX's chosen lines
remain credible once exported.

This is another reason to prefer TeX-chosen line breaks over Word composition.

The current DOCX implementation embeds OpenType fonts and declares
`TrueTypeBackend` as its supported font class before TeX loads document fonts.
If lookup finds only a CFF 1 font, the font backend converts it with AFDKO and
returns a TrueType-backed font to the engine. TeX therefore measures the same
glyph outlines that DOCX later embeds and obfuscates. This capability request
is DOCX-specific; the `html_reflow` backend continues to expose the
browser-supported CFF source font directly.

## Page Semantics

DOCX has real page-aware structures:

- page size and margins
- sections
- headers and footers
- page numbering variants
- footnotes and endnotes
- explicit page breaks

So the backend should retain a page-semantics layer rather than trying to infer
everything from raw visual boxes after the fact.

At minimum that layer should model:

- section boundaries
- header and footer bindings
- first / odd / even variants
- page numbering state
- explicit break instructions
- footnote/endnote associations

## Headers, Footers, And Marks

DOCX headers and footers are section-scoped, not page-scoped.

That works well for coarse page-style regions, but TeX running heads can vary
page by page from marks without any natural section boundary.

So the design should state the tradeoff explicitly:

- for ordinary documents, map page-style regions to DOCX sections
- for mark-heavy output routines, either accept many short sections or declare
  limited fidelity

This is not a theoretical corner case. It is a structural mismatch between TeX
marks and DOCX section headers.

## Pagination

In fidelity mode, pagination should remain primarily a TeX-side decision.

The backend should try to minimize Word's freedom by exporting:

- explicit paragraph structure
- explicit line breaks where needed
- explicit page and section breaks
- fixed-size hard objects where possible
- conservative use of Word features that trigger reflow surprises

But this should be described carefully. TeX-side pagination is a goal, not a
guarantee.

Even with frozen lines and fixed-size objects, Word may still drift because of:

- spacing interpretation
- font-engine differences
- header/footer realization
- object placement details
- platform-specific rendering

## Footnotes

DOCX footnotes should still be represented as true DOCX footnotes.

That is important for editability and for matching normal Word document
behavior.

But they are also a first-order fidelity risk. Word controls note composition
inside the footnote area, so page breaks chosen by TeX can still drift even if
body paragraphs are frozen.

So the design should treat footnotes as:

- native structures in the output format
- one of the main reasons pagination may remain approximate

They should not be described as "solved" just because DOCX supports them.

## Proposed DOCX Export Layer

The backend should introduce a DOCX-specific export structure between TeX
layout/page objects and DOCX XML.

### Inline layer

- runs
- atomic spans
- explicit line breaks
- hyphenation decisions
- spacing hints
- inline opaque boxes

### Block layer

- paragraphs
- display objects
- lists
- tables
- figures/captions
- in-flow block opaque boxes

### Page semantics layer

- sections
- page geometry
- header/footer bindings
- page numbering state
- footnote/endnote bindings
- explicit break instructions

### Object layer

- inline inserted objects
- text-box-like contained sublayouts
- fixed-size block objects
- floating anchored objects

## Mapping Rules

### Paragraphs

- let TeX choose paragraph and line breaks
- export explicit line endings in fidelity mode
- suppress automatic DOCX hyphenation
- preserve only the hyphen points TeX actually used

### Word spacing

- start with ordinary spaces when frozen line breaks are enough
- add spacing hints or repair passes only where needed
- measure tight lines before treating this as robust

### `\hbox`

- default mapping: atomic inline span
- do not use a text box unless the object behaves like a real contained layout

### Inline math

- treat as a fixed-size inline object from the TeX side
- use native Word math only when it preserves the dimensional contract well
  enough
- otherwise fall back to boxed realization

### Display math, alignments, and hard tables

- treat as fixed-size in-flow block objects in fidelity mode
- do not float them unless the source is genuinely positioned

### `\vbox`, `\parbox`, and `minipage`

- use text-box-like contained objects when they truly carry their own internal
  layout

### Headers and footers

- map page-style regions to DOCX sections where possible
- document that page-local mark behavior may force per-page sections or reduced
  fidelity

### Footnotes

- use true DOCX footnotes
- document pagination drift as an explicit risk

### Positioned objects

- use anchored placement only for genuinely positioned material

## Known Risks

1. Exact line fit may still drift even with the same visible font and fixed
   breakpoints.
2. Metric equivalence between TeX and Word font engines is not guaranteed.
3. Heavy use of text boxes or opaque objects may reduce editability and bloat
   documents.
4. Inline text-box behavior may not preserve TeX baseline expectations closely
   enough.
5. Footnotes remain a major pagination hazard.
6. Running heads driven by marks do not map cleanly to section-scoped DOCX
   headers.
7. Some tight lines may require too many spacing repairs to be worth it.

## Suggested Implementation Order

1. Keep the current paragraph proof of concept small and make it reliable for
   pure text paragraphs with frozen TeX lines.
2. Test spaces-only reconstruction versus spacing-hint reconstruction on narrow
   and tight paragraphs.
3. Add a minimal page-semantics layer for page geometry, explicit breaks, and
   simple section/header/footer cases.
4. Prototype inline and block boxed fallbacks for hard objects.
5. Measure pagination drift with footnotes and mark-driven headers before
   claiming high-fidelity page support.
6. Only then decide how much native math and native table support should be
   allowed in fidelity mode.

## Short Version

- TeX should remain the layout authority
- DOCX should be treated as a structured, editable, page-aware carrier
- frozen TeX lines are the most important fidelity tool
- hard objects need TeX-sized fallbacks when Word cannot size them reliably
- text boxes are the current leading fallback candidate, but still need
  empirical validation
- footnotes and running heads are the biggest remaining pagination risks
