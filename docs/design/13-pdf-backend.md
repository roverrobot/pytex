# ReportLab PDF Backend

This note defines the first direct-PDF shipout backend.

## Main Point

We keep the current shipout split:

1. layout and page building produce concrete boxes and nodes
2. `typeset.shipout.Shipout` walks the shipped page
3. a concrete backend implements the shipout IR

The PDF backend is that concrete backend. It should live next to `dvi`, not
replace the base walker.

For the first implementation we use ReportLab as a hard dependency.

## Why ReportLab

ReportLab already gives us:

- PDF file/object generation
- page management
- text drawing
- rectangle/rule drawing
- color operators
- font registration for OpenType/TrueType and Type 1

That means the backend can stay focused on lowering the existing shipout IR,
instead of rebuilding a PDF writer from scratch.

## Backend Shape

The backend class should mirror `pytex.dvi.DVIBackend`:

- subclass `typeset.shipout.Shipout`
- implement the shared shipout IR methods
- expose a module-level `init(parser)` that installs `parser.shipout`

The module is opt-in, just like `dvi`. The default parser shipout remains the
collector from `typeset`.

## Phase 1 Scope

The first PDF backend should fully support:

- page boundaries
- font definition and selection
- absolute positioned characters and ligatures
- rules
- color specials compiled through the existing `dvipdfm` special IR

The first PDF backend may ignore or defer:

- raw non-`pdf:` specials
- `annotate(...)`
- `xObject(...)`

Those hooks should still exist on the backend so the IR stays stable, but they
do not need a full implementation in the first patch.

## Page Model

The shipout walker already works in TeX scaled points with a DVI-like top-left
coordinate system.

ReportLab uses PDF points and a bottom-left origin.

So the backend should:

- keep the walker-facing coordinates in scaled points
- convert to PDF points only at draw time
- map:
  - `x = h`
  - `y = page_height - v`

The page size should come from:

1. `\pdfpagewidth` / `\pdfpageheight` when they are non-zero
2. otherwise, the shipped box size plus `\hoffset` / `\voffset` margins

This keeps direct PDF output aligned with pdfTeX-style page sizing when the
document sets those parameters, while still allowing plain shipouts to work.

## Font Strategy

The backend should not invent a new font model. It should consume the existing
font objects attached to `CharNode`.

### OpenType / TrueType

For fonts loaded through the OpenType backend, the PDF backend should register
the real font file with ReportLab directly.

### TFM Fonts

For classic TFM fonts, the backend should use a companion embeddable font file.

The preferred order is:

1. exact-name `.otf` / `.ttf` companion if one exists
2. matching `.afm` + `.pfb` Type 1 files

The second path is important because fonts such as `cmr10` do not have an
exact-name OpenType companion in TeX Live, but they do have matching Type 1
files.

The backend should therefore treat TFM fonts as resolvable for PDF output when
their TeX Live companion files can be found, rather than rejecting them the way
the DVI backend rejects OpenType fonts without a DVI name.

## Metrics

The backend should continue to trust the engine's existing font metrics for
layout.

ReportLab's own font metrics are not the source of truth for positioning. The
walker already gives absolute positions and node widths. So the backend may draw
each character at the exact position supplied by the walker.

This keeps the PDF backend faithful to the engine's layout model even when the
embedded font's native metrics are not byte-for-byte identical to TeX's TFM
metrics.

## Color

The existing `dvipdfm` special compiler already lowers recognized color specials
to:

- `setColor("set", ...)`
- `setColor("push", ...)`
- `setColor("pop")`
- `setColor("background", ...)`

The PDF backend should implement these directly using ReportLab color
operations. The color stack belongs in the backend, not in the walker.

`background` should paint the full page rectangle and should not permanently
change the current drawing color.

## Raw Specials

`rawSpecial(text)` should not try to reinterpret historical special dialects.

For the first PDF backend it is acceptable to ignore raw specials that are not
recognized by the `dvipdfm` compiler. The important point is that the backend
does not crash and that the typed IR path remains clean.

## Output Handling

The backend should honor the existing resolver/output conventions:

- explicit file-like object output
- explicit output name
- implicit `jobname`
- `resolver.output_in_memory`

So `shipout/pdf` should become a resolver output type, parallel to `shipout/dvi`.

## Non-goals

This first backend is not trying to solve:

- full hyperlink/annotation support
- `epdf` inclusion
- general XObject capture/reuse
- PDF object post-processing outside ReportLab

Those can be added later once we have real users of the backend-facing IR
methods beyond text, rules, and color.
