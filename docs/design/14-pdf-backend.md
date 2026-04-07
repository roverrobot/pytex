# Direct PDF Backend

This note describes the current direct-PDF shipout backend in `pytex/pdf.py`.
It supersedes the older design note that described a first ReportLab-backed PDF
backend mostly as a plan.

The current code already has a working direct PDF backend. It sits downstream of
layout construction and shipout traversal:

1. layout and page building produce concrete boxes and nodes
2. `typeset.shipout.Shipout` walks the shipped page
3. `PDFBackend` lowers the shipout IR to PDF output

This note is about that concrete backend.

## Main point

`PDFBackend` is a shipout backend, not a typeset backend.

It subclasses `typeset.shipout.Shipout` and implements the current shipout IR,
plus the current typed special IR used for the supported `dvipdfm` `pdf:`
special subset.

The implementation is centered on two libraries:

- ReportLab for ordinary PDF page generation
- `pypdf` for post-processing tasks such as `epdf` page overlays

So the backend is not a full handwritten PDF writer. It lowers pytex's shipout
and special IR into those libraries.

## How it is installed

The backend is opt-in through the module framework.

Importing `pytex.pdf` registers a module whose `init(parser)` hook installs:

- `parser.shipout = PDFBackend(parser)`

So the usual activation path is:

- import `pytex.pdf` before constructing `Parser`
- let module initialization attach the backend

This is the pattern used by the current `examples/tex.py` entry script when the
selected output format is PDF.

If the module is not imported, the parser keeps its default shipout object.

## Output ownership

The backend follows the current resolver-oriented output policy.

It can write to:

- an explicit binary file-like object
- an explicit output path or output stem
- the parser jobname through resolver-managed output opening

Relative output paths go through:

- `resolver.openOut(name, "shipout/pdf")`

So PDF output participates in the same output conventions as the other shipout
backends.

## Page model

The backend keeps the walker-facing coordinate model in TeX scaled points.
Conversion to PDF points happens only at draw time.

The backend uses a top-left logical origin, but ReportLab uses bottom-left PDF
coordinates. So the backend converts positions as it emits drawing commands.

The page size is determined as follows:

1. use `\pdfpagewidth` and `\pdfpageheight` when they are positive
2. otherwise derive the page size from the shipped box plus margins

The current margin origin is:

- `1in + \hoffset` horizontally
- `1in + \voffset` vertically

So plain shipped pages work even when the document does not set the PDF page
size parameters explicitly.

## Shipout IR implemented by the backend

`PDFBackend` implements the current shared shipout interface from the shipout
layer:

- `open()`
- `close()`
- `begin_page(box)`
- `end_page(box)`
- `define_font(font)`
- `select_font(font)`
- `move_to(h, v)`
- `set_char(node)`
- `set_rule(node, box, move)`
- `special(text)` through the inherited `Shipout.special(...)` dispatcher
- `rawSpecial(text)`

It also implements the current typed special IR hooks that `Shipout.special(...)`
may call through `DVIPDFmSpecialParser`:

- `setColor(mode, space=None, values=None)`
- `annotate(kind, name=None, dimensions=None, payload=None)`
- `xObject(kind, name=None, options=None, source=None)`

That means the PDF backend participates in both:

- the core page-output IR
- the current special IR subset

## Font handling

The backend does not invent a second layout metric system.

Positioning still comes from the engine's own layout results. The PDF backend
uses the positions supplied by the shipout walker and does not ask ReportLab to
recompute TeX layout.

The backend supports two font backend kinds.

### OpenType fonts

When a font comes from the OpenType backend:

- the backend registers the real font file with ReportLab
- the backend requires a filesystem-backed path
- TTC collections are handled through the stored `font_number` when present

So direct PDF output is the main path that can use pytex OpenType fonts
natively.

### TFM fonts

When a font comes from the TFM backend, the PDF backend looks for an embeddable
outline companion.

The current order is:

1. `<name>.otf`
2. `<name>.ttf`
3. `<name>.afm` plus `<name>.pfb`

This allows classic TeX fonts such as Computer Modern to work in direct PDF
output when TeX Live companion outline files are available.

### Current caveat

ReportLab still has known issues with some non-BMP Unicode characters. The
backend therefore warns once per code point when it encounters a non-BMP
character during direct PDF output.

## What ordinary shipout currently supports

The backend currently supports the main ordinary page-output primitives:

- page start and end
- font definition and selection
- absolute-positioned character output
- rule drawing
- color changes through the special IR

This is already enough for ordinary text pages, rules, and the currently
supported `pdf:` special subset.

## Current special support

The backend supports part of the current `dvipdfm` special IR and also handles a
small number of raw `pdf:` specials directly.

### Typed special IR support

Through the typed special IR, the backend currently supports:

- color stack operations
- link-like annotations
- raster image placement
- `epdf` inclusion as a page overlay

#### Color

`setColor(...)` supports:

- `set`
- `push`
- `pop`
- `background`

The backend keeps its own color stack and lowers the current color to ReportLab
fill and stroke color operations.

`background` paints the full page rectangle and then restores the previous
current color.

#### Annotations

`annotate(...)` currently supports:

- breakable begin/end annotations
- fixed rectangle annotations

But only some payload families are realized semantically.

The current implemented annotation payloads are:

- GoTo links
- URI links

Other annotation dictionaries are currently ignored after parsing, with the
backend emitting a harmless PDF comment noting that they were ignored.

#### XObjects and images

`xObject(...)` currently supports:

- `image` for raster image placement through ReportLab
- `epdf` for inclusion of PDF page content as an overlay

The parser for specials can also emit `begin`, `end`, and `use` XObject-like
operations, but the current PDF backend does not realize those forms yet.

### Raw-special handling

Some `pdf:` specials are still handled directly in `rawSpecial(...)` rather than
through the typed special IR.

The current backend-specific raw handlers are:

- `pdf: pagesize width ... height ...`
- `papersize=...,...`
- `pdf: dest (...) [@thispage /XYZ @xpos @ypos null]`

So the backend currently has a mixed model:

- some `pdf:` specials are compiled by the typed special IR
- some still go through backend-specific raw-special handling
- everything else is ignored safely

Unknown raw specials are not reinterpreted. The backend writes a sanitized PDF
comment instead of failing.

## `epdf` inclusion model

`pdf: epdf ...` is supported, but not by immediate drawing through ReportLab.

Instead, the current backend:

1. records an overlay request while shipping the page
2. finishes the ReportLab PDF normally
3. reopens the generated PDF with `pypdf`
4. merges the selected source PDF page onto the output page
5. writes the final PDF bytes

So `epdf` support is currently a post-processing overlay step, not a normal
ReportLab drawing primitive.

This is also why the backend keeps per-page overlay queues and a cache of source
PDF readers.

## What the backend ignores today

The backend is already useful, but it is not a full pdfTeX-compatible PDF
engine.

Current gaps include:

- general raw special dialects outside the supported subset
- annotation payloads other than the currently recognized link forms
- `beginxobj`, `usexobj`, and `endxobj`
- a fully typed IR for destinations and page size specials
- richer PDF object manipulation beyond the current subset

So the backend is best understood as:

- a working direct PDF backend
- with solid text, rule, color, image, and basic link support
- but still only partial coverage of the broader `pdf:` special space

## Relationship to the other notes

This note sits after:

- the typeset-services note
- the shipout IR note
- the special IR note

The intended split is:

- the shipout IR note describes the shared page-output contract
- the special IR note describes the current typed `pdf:`-special subset
- this note describes how the direct PDF backend realizes those contracts today

## Short version

The current PDF backend is no longer a proposal.

It is a working shipout backend that:

- subclasses `Shipout`
- uses ReportLab for ordinary PDF output
- uses `pypdf` for `epdf` overlays
- supports both OpenType and TFM-based fonts for direct PDF output
- implements the current color, annotation, image, and `epdf` special subset
- still handles some `pdf:` specials directly in `rawSpecial(...)`
- intentionally ignores unsupported cases safely rather than pretending to be a
  complete PDF feature implementation
