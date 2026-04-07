# DVIPDFm Special IR

This note describes the current handling of `dvipdfm`-style `\special`
commands in pytex.

It follows the shipout IR note. The special IR is not a separate layout layer.
It sits inside shipout, at the point where a `Special` whatsit is emitted to the
output device.

The focus here is the currently implemented `dvipdfm` `pdf:` subset.

## Main Point

The current design keeps `Special` nodes raw through list construction and page
building, and interprets only a small recognized `pdf:` subset at shipout time.

So the current boundary is:

1. raw `Special` whatsit in the layout tree
2. `Special.output(...)` converts stored text or expanded token lists into a string
3. `Shipout.special(text)` tries the `DVIPDFmSpecialParser`
4. recognized commands lower into a small typed backend interface
5. otherwise the text falls through to `rawSpecial(text)`

This means:

- ordinary layout still uses the existing node/list/box IR
- `Special` nodes are preserved as raw TeX-side artifacts until output time
- only some `pdf:` specials are compiled into typed operations
- unrecognized or unsupported specials remain raw

## Why This Boundary

By shipout time, almost everything else on the page is already concrete:

- characters are `CharNode` or ligature nodes
- rules are rule nodes
- glue, kerns, lists, and boxes are already layout structures
- whatsits are dispatched in output order

So the natural place for a special-specific IR is at the shipout boundary, not
inside list construction.

That is also how the current code is organized:

- `node.Special.output(...)` calls `device.special(text)`
- `typeset.shipout.Shipout.special(...)` owns the `dvipdfm` parser hook
- concrete backends implement the typed operations and raw fallback

## Scope

This note covers the currently implemented `dvipdfm` `pdf:` subset only.

Currently recognized command families are:

- color commands
- annotation commands
- XObject and image commands

Currently out of scope for the typed special IR are things like:

- transforms
- generic PDF object construction
- outline entries
- catalog or info updates
- arbitrary page-content injection
- non-`pdf:` special dialects such as TPIC or raw PostScript

Those remain either unsupported or backend-specific raw specials.

## Current Pipeline

The current execution path is:

```text
Special whatsit
  -> Special.output(parser, device)
  -> Shipout.special(text)
  -> DVIPDFmSpecialParser.emit(text)
  -> typed backend method calls
  -> backend-specific lowering
```

If parsing fails or the command is not in the recognized subset, the path is:

```text
Special whatsit
  -> Special.output(parser, device)
  -> Shipout.special(text)
  -> rawSpecial(text)
```

So the parser for `pdf:` specials is owned by the shipout layer, not by the
parser kernel and not by the layout layer.

## Why `Special` Stays Raw

`Special` is a TeX-level whatsit. It records that a `\special{...}` occurred at
some position in the page content.

It stays raw because:

- only a subset needs structured interpretation
- the output-facing context belongs to shipout
- different backends may lower the same recognized operation differently
- many specials should still pass through unchanged

That is why the current code stores `Special.text` directly and only turns it
into a string when the whatsit is output.

## Current Front End

The current shipout-time compiler lives in `pytex/typeset/dvipdfm.py`.

The front end is intentionally small. It:

- checks for a `pdf:` prefix
- reads the command word
- normalizes historical aliases immediately
- parses only the small envelope needed by the current subset
- calls typed device methods on success
- returns failure so shipout can fall back to `rawSpecial(...)`

So this layer is closer to a tiny command compiler than to a full PDF syntax
parser.

## Current Recognized Command Families

### Color

The current recognized color aliases normalize to four semantic modes:

- `set`
- `push`
- `pop`
- `background`

These come from spellings such as:

- `setcolor`, `scolor`, `sc`
- `begincolor`, `bcolor`, `bc`
- `endcolor`, `ecolor`, `ec`
- `bgcolor`, `bbc`, `bgc`

The parser currently recognizes gray, RGB, and CMYK-style arguments.

### Annotation

The current recognized annotation kinds normalize to:

- `fixed`
- `begin`
- `end`

These come from spellings such as:

- `annotate`, `annot`, `ann`
- `beginann`, `bann`, `bannot`
- `endann`, `eann`, `eannot`

The parser currently supports:

- an optional annotation name beginning with `@`
- optional dimensions `width`, `height`, and `depth`
- a trailing raw payload string

For fixed annotations, dimensions are currently required.

### XObject And Image Commands

The current recognized XObject-related kinds normalize to:

- `begin`
- `end`
- `use`
- `image`
- `epdf`

These come from spellings such as:

- `beginxobj`, `bxobj`
- `endxobj`, `exobj`
- `usexobj`, `uxobj`
- `image`
- `epdf`

The current option envelope supports:

- dimensions: `width`, `height`, `depth`
- transforms as raw options: `scale`, `xscale`, `yscale`, `rotate`
- box selection: `bbox`, `page`, `pagebox`, `clip`

These are parsed as options for XObject-like operations, but there is not yet a
separate transform IR.

## Current Typed Special IR

The currently implemented special-facing backend surface is:

- `rawSpecial(text)`
- `setColor(mode, space=None, values=None)`
- `annotate(kind, name=None, dimensions=None, payload=None)`
- `xObject(kind, name=None, options=None, source=None)`

This sits on top of the shared shipout IR described separately. So the special
IR is an extension of shipout, not an independent backend layer.

## What The IR Means

### `rawSpecial(text)`

This is the fallback path.

It receives:

- non-`pdf:` specials
- unrecognized `pdf:` commands
- malformed recognized commands
- recognized commands that the current compiler does not lower

Backends are free to pass these through, ignore them, or interpret some of them
backend-specifically.

### `setColor(...)`

This carries semantic color-stack operations, not raw spellings.

The mode is one of:

- `set`
- `push`
- `pop`
- `background`

The current parser normalizes the color space to one of:

- `gray`
- `rgb`
- `cmyk`

with the numeric values kept as strings.

### `annotate(...)`

This carries the normalized annotation family:

- `fixed`
- `begin`
- `end`

The payload is currently left mostly raw. The special IR standardizes the outer
command envelope, not the full PDF annotation dictionary syntax.

### `xObject(...)`

This carries normalized image/XObject commands:

- `begin`
- `end`
- `use`
- `image`
- `epdf`

Options are passed through as parsed key/value pairs. They are not yet lowered
into a more normalized graphics or transform IR.

## Current Raw Fallback Policy

The base `Shipout.special(text)` method does this:

1. try `DVIPDFmSpecialParser.emit(text)`
2. if that succeeds, stop
3. otherwise call `rawSpecial(text)`

So malformed recognized commands currently do **not** raise shipout-time parse
errors. They fall back to raw handling.

That keeps the current implementation incremental and low risk.

## Backend Lowering Today

### DVI

`DVIBackend` participates in the typed IR but lowers it back into `pdf:`
special strings.

So the current DVI path for recognized specials is:

```text
raw special text
  -> DVIPDFmSpecialParser
  -> typed special IR
  -> serialize_* helpers
  -> DVI special bytes
```

This means DVI acts as a full consumer of the typed special IR even though its
final encoding is still raw `pdf:` special text.

### Direct PDF

`PDFBackend` lowers part of the special IR natively:

- `setColor(...)` maps to ReportLab/PDF color operations
- `annotate(...)` maps a small supported subset to links and annotations
- `xObject(...)` handles image placement and queued embedded-PDF overlays

At the same time, `PDFBackend.rawSpecial(...)` still has backend-specific raw
handling for some specials that are **not** part of the current typed IR,
notably:

- `pdf: pagesize width ... height ...`
- `pdf: dest (...) [ @thispage /XYZ @xpos @ypos null ]`

So the current special architecture is partly typed and partly raw.

### HTML Reflow

`HTMLReflowBackend` is a special case.

It does not use normal packed-page shipout rendering as its final export path,
and it does not implement the typed special IR as a primary rendering surface.
Instead, during final HTML generation, it inspects raw special text from the
main vertical list's ownership history.

In particular, it currently recognizes some raw special patterns for things
like:

- destinations
- begin/end link annotations

So for HTML reflow, special handling is currently a separate raw-text path, not
primarily a consumer of the shipout special IR.

## What Is Not Yet In The Current IR

The old design sketch talked about transform operations such as:

- `pushTransform()`
- `popTransform()`
- `concatTransform(matrix)`

That is **not** part of the current code yet.

Today, transform-like words such as `rotate` are only parsed as option tokens in
XObject-related commands. There is no standalone typed transform family in the
current special IR.

So the current special IR should be described as:

- raw special fallback
- color
- annotation
- XObject/image placement

and no more.

## Error Policy

The current behavior is simple:

- recognized and successfully parsed commands lower to typed IR calls
- everything else falls back to `rawSpecial(text)`

So the current implementation does not yet draw a strong semantic distinction
between:

- unknown command
- malformed recognized command
- unsupported recognized command

Those all collapse to raw fallback at shipout.

## Relationship To The Shipout IR Note

The shipout IR note describes the shared page walker and the basic backend
methods for positioned page output.

This note is narrower. It describes only the extra typed interface used for the
currently recognized `dvipdfm` `pdf:` subset.

So the relation is:

- shipout IR: page traversal and ordinary device operations
- special IR: typed lowering for a small recognized family of `\special`
  payloads

## Short Version

- `Special` whatsits stay raw until output
- shipout owns the `dvipdfm` special parser
- the current typed special IR is only:
  - `rawSpecial`
  - `setColor`
  - `annotate`
  - `xObject`
- transforms are not yet a separate IR family
- DVI consumes the IR and reserializes it to `pdf:` specials
- PDF consumes part of it natively, but still handles some raw `pdf:` specials
  directly
- HTML reflow currently uses a separate raw-special path rather than the typed
  shipout special IR
