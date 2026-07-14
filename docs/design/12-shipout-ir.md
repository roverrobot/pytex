# Shipout IR

This note describes the current shipout layer.

It sits **after** page building and **after** packing. Its job is to walk a
shipped page box and lower it into a small device-facing interface.

This is a different boundary from the typeset services described in the
`typeset-backends` note. Paragraph, math, alignment, and page building are
construction-oriented runtime services. Shipout is the downstream page-output
layer.

## Main point

The current code uses a shared `Shipout` base class as the backend-neutral page
walker.

The base class owns:

- page traversal over packed `HLIST` and `VLIST` boxes
- current shipout position (`h`, `v`)
- a position stack for recursive box traversal
- glue realization during shipout
- one-time font-definition tracking
- dispatch of whatsits through `node.output(...)`
- parsing of a small `dvipdfm` special subset into typed callbacks

Concrete output backends then implement the device-facing methods.

So the current split is:

- **`Shipout`**: shared traversal and lowering
- **DVI/PDF backends**: concrete page-output devices
- **HTML reflow**: a special subclass that participates in shipout-time side
  effects, but does not use ordinary packed-page rendering as its final export
  path

## Current place in the pipeline

The current downstream order is roughly:

1. parser-owned list construction
2. parser-owned paragraph/math/alignment realization
3. page building over the outer vertical list
4. shipout of packed page boxes
5. backend-specific file output

So shipout is not part of token flow, parser state, or list construction. It
consumes the result of those earlier layers.

## What `Shipout` consumes

The current `Shipout.shipout(box)` method expects a page box.

If the box is not yet packed (`box.width is None`), the base class packs it by
calling `box.typeset(parser, packed)` and taking the last packed box.

After that it:

- records the page in `self.pages`
- calls `begin_page(box)`
- initializes the starting shipout position from `\hoffset` and `\voffset`
- walks the page recursively
- calls `end_page(box)`

So the practical input boundary is a packed page box, even though the base class
can perform a last-minute pack when needed.

## Shared traversal responsibilities

The base walker currently owns all of the following.

### 1. Recursive list walking

It traverses:

- character and ligature nodes
- glyph clusters and their fixed-layout glyph/box contents
- nested `HLIST` / `VLIST` boxes
- rules
- glue and kerns
- discretionary node contents in horizontal lists
- whatsits

### 2. Position management

The base class computes logical placement and keeps the current point in TeX
scaled points.

It also manages a position stack so that nested box traversal can temporarily
shift position and then restore it.

### 3. Glue realization

Shipout is responsible for turning already-computed box glue settings into
actual movement amounts.

The current code handles both:

- tuple-form glue ratios, and
- spread-based fallback logic

This is intentionally part of the page walker rather than of individual
backends.

### 4. Font definition tracking

The base class keeps `_defined_fonts` and ensures that each concrete backend
sees:

- `define_font(font)` at most once per backend font object, then
- `select_font(font)` when that font becomes active

### 5. Whatsit dispatch

Whatsits are emitted in list order by calling:

- `node.output(parser, shipout_backend)`

So shipout is also the runtime point where backend-facing specials, annotations,
file-writing whatsits, and similar side effects become concrete.

### 6. Special parsing

The base `special(text)` method does **not** immediately hand raw text to the
backend.

Instead it first runs the current small `dvipdfm` special parser. If the text is
recognized, it is lowered into typed callbacks such as color, annotation, or
XObject/image operations. If not, it falls back to `rawSpecial(text)`.

This is the main place where shipout touches the special IR.

## Current backend-facing interface

Concrete shipout backends currently implement this method family:

- `open()`
- `close()`
- `begin_page(box)`
- `end_page(box)`
- `define_font(font)`
- `select_font(font)`
- `move_to(h, v)`
- `set_char(node)`
- `set_glyph(node)`
- `set_rule(node, box, move)`
- `rawSpecial(text)`
- `setColor(mode, space=None, values=None)`
- `annotate(kind, name=None, dimensions=None, payload=None)`
- `xObject(kind, name=None, options=None, source=None)`

That is the current shipout IR in the code.

## Meaning of the current callbacks

### `open()` / `close()`

These manage backend output lifetime.

In the current code:

- DVI opens and finalizes a `.dvi` stream
- PDF opens and finalizes a ReportLab canvas and post-processes overlays
- HTML reflow delays final HTML emission until `close()` after normal TeX
  execution has ended

### `begin_page(box)` / `end_page(box)`

These delimit one shipped page.

They are responsible for page-local initialization such as:

- DVI BOP/EOP records
- PDF page size, origin, and page-local color or annotation state
- page-local overlay accumulation in the PDF backend

### `define_font(font)` / `select_font(font)`

These separate one-time backend font setup from active font switching.

That matters because backends identify and realize fonts differently:

- DVI writes font definitions and font-number selections
- PDF ensures a ReportLab font name is available and selects it on the canvas

### `move_to(h, v)`

The base walker computes logical placement. The backend chooses how to track or
encode that position.

In the current code:

- DVI converts it to relative DVI horizontal and vertical motion
- PDF stores the logical point and uses it when drawing

### `set_char(node)`

This emits one shipped character or ligature node at the current position.

The base class ensures the right font is selected first.

### `set_glyph(node)`

This emits one backend glyph identity from inside a `GlyphCluster`. The shared
walker has already applied the cluster's boxes, kerns, advances, and vertical
shifts. Character-addressed backends may delegate to `set_char(...)`; native
OpenType backends use the glyph ID or glyph name directly.

The cluster is one measured node in its parent horizontal list. A one-glyph
cluster emits that glyph directly; a composed cluster delegates its packed
`HBox` payload to the ordinary box walker. Concrete backends do not rerun
GSUB/GPOS or implement cluster positioning.

### `set_rule(node, box, move)`

Rules remain a first-class primitive.

The current signature intentionally keeps the backend aware of:

- the parent box kind, and
- whether TeX rule movement semantics should advance after emission

This preserves the current DVI-compatible rule behavior.

### `rawSpecial(text)`

This is the fallback path for specials that are not recognized by the shared
`dvipdfm` special parser.

Current behavior differs by backend:

- DVI serializes the raw special string into `xxx` commands
- PDF recognizes a very small extra raw subset such as page-size and named
  destination specials, and otherwise ignores the special with a PDF comment
- HTML reflow does not use raw packed-page rendering as its final output path

### `setColor(...)`, `annotate(...)`, `xObject(...)`

These are typed special-facing callbacks.

They sit at the boundary between shipout traversal and the special IR.

The exact syntax, normalization rules, and supported families should be
explained in a separate special-IR note. This document only records that shipout
currently exposes typed callbacks for:

- color changes
- annotations / links
- external objects such as images and embedded PDF pages

## Current special-IR relationship

Shipout should mention the special IR, but it should not fully define it.

The current division is:

- **shipout IR**: page traversal plus typed callback points for backend-facing
  effects
- **special IR**: the meaning and normalization of recognized special families
  such as `dvipdfm` color, annotation, and XObject commands

In the current code, the bridge is the `DVIPDFmSpecialParser` used by
`Shipout.special(...)`.

So the right documentation split is:

- this note explains where special handling enters shipout
- a separate special-IR note should explain what the typed special families mean

## Current concrete backends

### DVI backend

`DVIBackend` is the clearest direct implementation of the shipout IR.

It:

- writes the DVI preamble and postamble
- assigns DVI font IDs
- converts `move_to(...)` into DVI movement opcodes
- emits characters and rules directly as DVI commands
- serializes typed special callbacks back into `dvipdfm`-style raw specials

So for DVI, the typed special callbacks are mainly a normalization layer before
re-serialization.

### PDF backend

`PDFBackend` also implements the same shipout IR, but interprets more of it
natively.

It:

- draws characters and rules directly on a ReportLab canvas
- realizes typed color operations directly
- turns some annotation payloads into actual PDF links
- handles image and embedded-PDF placement through `xObject(...)`
- keeps page-local overlay state for embedded PDF pages

So for PDF, the same typed callbacks are closer to real device operations.

### HTML reflow backend

`HTMLReflowBackend` subclasses `Shipout`, but it is not a normal packed-page
rendering backend.

At runtime shipout, it only walks shipped pages far enough to execute whatsits.
Its final HTML output is produced later at `close()` from the outer vertical
list's raw ownership history.

So HTML reflow belongs near the shipout boundary operationally, but it should be
understood as a special downstream consumer rather than as a normal page-device
backend.

## What this note does not cover

This note does not try to define:

- token-flow or parser execution
- list construction
- page-builder decisions before a page is shipped
- the full special IR
- semantic/reflow export structure

Those belong to separate notes.

## Short version

The current shipout layer is:

- a backend-neutral `Shipout` page walker
- operating on packed page boxes after page building
- responsible for traversal, position, glue realization, font definition
  tracking, whatsit dispatch, and shared `dvipdfm` special parsing
- lowered into a device-facing callback family implemented by DVI and PDF
  backends
- adjacent to, but not identical with, the special IR

That is why it makes sense to document shipout separately from the typeset
services, while still letting the shipout note point to a later special-IR
note.
