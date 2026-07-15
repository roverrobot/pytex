# Font Backends

This note describes the current font-backend split in the codebase.

The old version treated OpenType support as deferred work. That is no longer
accurate. The current code has a common backend interface in
`pytex/font_backend.py`, a working `TFMBackend` in `pytex/tfm.py`, and a
working `OpenTypeBackend` in `pytex/opentype.py`.

The split is now real, but it is not fully symmetric across all output paths.
TFM remains the TeX-native path, while OpenType currently works mainly for
parser/layout use and for direct PDF output.

## Main Point

The `\font` command no longer loads TFM files directly.

Instead, it asks the parser for a `FontBackend`, and then wraps that backend in
an ordinary `Font` command object. The backend supplies glyph metrics,
`fontdimen` defaults, and any backend-specific glyph data such as ligature or
extensible-character programs.

So the current split is:

- `FontBackend`: shared font resource and metrics provider
- `Font`: parser-facing font value at a chosen size
- backend-specific loaders: `TFMBackend` and `OpenTypeBackend`
- concrete OpenType outline classes: `TrueTypeBackend` and `CFFBackend`
- shipout backends: consume the resulting `Font` objects according to their own
  capabilities

## Backend Interface

The common interface lives in `pytex/font_backend.py`.

The important pieces are:

- `kind`
- `load(parser, name)`
- `name`
- `dvi_name`
- `design_size`
- `checksum`
- `fontdimen`
- `glyphInfo(char)`
- `glyphInfos()`
- `fallbackGlyphInfo(char)`
- `leftBoundaryProgram()`
- `rightBoundaryChar()`

The common glyph-facing dataclasses are:

- `GlyphInfo`
- `GlyphAssembly`
- `GlyphAssemblyPart`

This interface is intentionally close to what the current engine actually uses:
character metrics, ligature/kern programs, larger-character chains, extensible
assembly information, and a small amount of DVI-facing metadata.

## Backend Registration And Loading

Backend loaders are registered process-wide with `registerBackend(...)`.

The parser receives the loader as a module-installed attribute:

- `parser.loadFontBackend(name, kind=None)`

The loader keeps a process-wide cache of backend objects. The cache key is based
on backend kind, normalized resource name, and the output backend's registered
font classes. This prevents an unrestricted CFF lookup from satisfying a later
DOCX lookup that requires a converted TrueType backend.

### Output capability registration

A shipout backend can declare concrete font classes through
`supported_font_classes`. The base shipout constructor registers those classes
with `parser.registerSupportedFontClasses(...)` before TeX loads document fonts.

If no shipout backend registers classes, lookup retains the unrestricted legacy
behavior. If classes are registered, lookup continues past unsupported results
in case another loader can provide a supported font. Only after that search is
exhausted does it try a converter registered with `registerFontConverter(...)`.

This ordering is important: conversion happens before `Font` is constructed,
so glyph widths, bounds, `fontdimen`, line breaking, and page breaking all use
the same concrete font that shipout later embeds.

The normalization rule is currently:

- bare names default to `.tfm` only when the requested kind is `tfm`, or when
  no kind is given and the TFM path is being tried
- explicit extensions are preserved and lowercased

So:

- `cmr10` and `cmr10.tfm` share the same TFM backend resource
- `foo.otf` and `foo.ttf` stay distinct
- a bare OpenType family name such as `Times New Roman` is cached separately
  from file-based names

## Selection Rules

The current selection rules are:

### Explicit kind

If a caller passes `kind`, only backends with that exact `kind` are tried.

This path is important for deserialization, because `Font.saveInfo()` stores
both backend name and backend kind.

### Explicit extension

If the requested name has an extension, every registered backend is asked in
registration order whether it can load that name.

In practice:

- `.tfm` goes to `TFMBackend`
- `.otf` and `.otc` go to `OpenTypeBackend` as OpenType resources
- `.ttf` and `.ttc` go to `OpenTypeBackend` as TrueType resources

### Bare name

If the requested name has no extension and no explicit kind is given, the
loader currently tries:

1. `kind="tfm"`
2. `kind="opentype"`

So the current preference order is:

- TeX-native TFM first
- OpenType second

For OpenType, a bare name is treated as a system-font name lookup rather than a
resolver-managed file path.

## `TFMBackend`

`TFMBackend` is the TeX-native backend.

It is registered from `pytex/tfm.py`, and that module is already imported by
`pytex/font.py` because `\nullfont` is built from a TFM-based null backend.
So TFM support is always present once the normal font module is loaded.

### Resolution

`TFMBackend` accepts names ending in `.tfm`, and opens them through:

- `parser.resolver.openIn(name, "fonts/tfm")`

### Data Provided

`TFMBackend` exposes:

- design size from the TFM header
- checksum from the TFM header
- raw `fontdimen` values from the TFM parameter table
- glyph widths, heights, depths, and italic corrections
- ligature/kern programs
- `LIST_TAG` larger-character chains through `next_larger`
- `EXT_TAG` extensible recipes through `GlyphAssembly`
- left and right boundary ligature programs

It also provides a zero-metric `fallbackGlyphInfo(...)` for missing characters.

### DVI Name

For TFM, `dvi_name` defaults to `name`, so TFM fonts can be written directly
into DVI font definitions.

## `OpenTypeBackend`

`OpenTypeBackend` is implemented in `pytex/opentype.py`. It is the registered
loader and common implementation; loaded fonts are represented by concrete
subclasses according to their outline tables:

- `TrueTypeBackend` for `glyf` outlines
- `CFFBackend` for CFF 1 outlines

Unlike TFM, it is not imported automatically by `parser.py`. A caller must
import `pytex.opentype` before constructing the parser if OpenType loading is
wanted. The example entry script does exactly that.

### Resolution

OpenType currently supports two lookup modes.

#### File-based lookup

When the requested name has one of these extensions:

- `.otf`
- `.otc`
- `.ttf`
- `.ttc`

`OpenTypeBackend` resolves it through the parser resolver using:

- `fonts/opentype` for `.otf` and `.otc`
- `fonts/truetype` for `.ttf` and `.ttc`

#### System-font lookup

When the requested name has no recognized extension, `OpenTypeBackend` treats
it as a system-font name and searches platform font directories.

The current implementation indexes font family names, full names, and
PostScript names, normalizes them case-insensitively, and prefers more direct
matches and more regular styles.

This is the path that supports declarations such as:

```tex
\font\myfont="Times New Roman"
```

provided the OpenType module has been imported.

### Data Provided

OpenType currently provides:

- glyph widths from `hmtx`
- glyph height and depth from outline bounds
- GSUB/GPOS shaping through HarfBuzz, including ligatures, pair positioning,
  multiple substitutions, and positioned marks
- XeTeX `script`, `language`, and OpenType feature settings on native font
  requests
- fixed-layout `GlyphCluster` results whose boxes preserve HarfBuzz advances
  and horizontal/vertical offsets
- a default design size of `10pt`
- a checksum from the font `head` table
- synthetic `fontdimen` defaults derived from italic angle, x-height, and the
  HarfBuzz advance of an isolated U+0020 under the font request's script,
  language, and feature settings
- `next_larger` chains and extensible assemblies when the font supplies an
  OpenType MATH table

Native OpenType fonts deliberately do **not** expose TeX ligature/kern programs;
they shape through HarfBuzz instead. Type 1 fonts converted for outline output
retain their source TFM programs behind the same common shaping interface.

### CFF to TrueType conversion

`pytex.opentype` registers an AFDKO converter from `CFFBackend` to
`TrueTypeBackend`. DOCX declares `TrueTypeBackend` as its supported font class,
so a CFF-only result is converted during font lookup. The converted `TTFont`
and its serialized bytes stay together on the returned backend: TeX measures
the converted glyphs, and DOCX later embeds those same bytes.

Other output backends currently register no font restriction, so they keep the
original CFF font. In particular, `html_reflow` continues to rely on browser
CFF support and does not request conversion.

### DVI Name

`OpenTypeBackend.dvi_name` is `None`.

So OpenType fonts cannot currently be emitted directly by the DVI writer.

## The `Font` Wrapper

Backends are shared resources. The parser-facing `Font` object adds TeX font
state on top of a backend:

- chosen size `at`
- scaled `fontdimen` parameters
- cached `CharNode` objects
- `\hyphenchar` and `\skewchar`
- a prebuilt `spaceglue`

The current scaling rule is:

- `fontdimen[1]` in TeX numbering, stored internally as `param[0]`, is kept
  unscaled because it is the slant parameter
- remaining parameters are multiplied by the chosen font size

So one backend resource can back multiple `Font` values at different sizes.

## `\font` And Related Commands

The main loader path is in `FontDefineAccessor.readValue(...)`.

The current behavior is:

1. read the font name with `parser.readFileName()`
2. load the backend with `parser.loadFontBackend(name)`
3. read optional `at` or `scaled`
4. otherwise use backend design size multiplied by `\mag`
5. construct `Font(backend, at)`
6. initialize `\hyphenchar` and `\skewchar` from the parser defaults

So backend choice is now fully centralized in the loader rather than inside the
`\font` command itself.

Related font commands still live in `pytex/font.py`, including:

- `\font`
- `\fontdimen`
- `\fontname`
- `\hyphenchar`
- `\skewchar`
- `\nullfont`
- the math font family arrays `\textfont`, `\scriptfont`, and
  `\scriptscriptfont`

## Serialization

Font serialization is no longer TFM-specific.

`Font.saveInfo()` stores:

- backend name
- backend kind
- chosen size

plus local font state such as parameters and font characters.

That means a serialized font can be reconstructed by calling:

- `parser.loadFontBackend(name, kind=kind)`

So the backend split is already reflected in the format/state serialization
path.

## Output Backends

The font-backend split is real, but output support is still uneven.

### DVI

The DVI writer requires `backend.dvi_name`.

That works for TFM, but not for OpenType. So direct DVI shipout currently
supports TFM-backed fonts only.

### Direct PDF

The direct PDF backend supports both current backend kinds, but in different
ways.

- for `opentype`, it registers the actual OpenType/TrueType font with
  ReportLab
- for `tfm`, it looks for a companion outline font, first as `.otf` or `.ttf`,
  and otherwise as `.afm` plus `.pfb`

So direct PDF output is currently the main backend path that can use
OpenType-backed fonts directly.

## Current Limits

The main current limits are:

- OpenType is not directly writable to DVI
- native OpenType does not expose TeX-style ligature/kern programs because its
  GSUB/GPOS processing is handled by HarfBuzz
- the synthetic OpenType `fontdimen` table only supplies the basic seven text
  parameters

That last point matters for math fonts. The math font family arrays validate
that family 2 and family 3 fonts have enough `fontdimen` parameters for TeX
math typesetting. So ordinary OpenType fonts are currently better suited to
text use than to full TeX math-family replacement.

## Summary

The current font-backend design is no longer a first draft.

What exists now is:

- a shared `FontBackend` interface
- a working TFM backend
- a working OpenType backend
- process-wide backend registration and caching
- parser-side loading through `parser.loadFontBackend(...)`
- font serialization that records backend kind
- uneven shipout support, with TFM still the TeX-native path and OpenType best
  supported in direct PDF output

So the present code already has a genuine backend split, but it is still a
split inside a TeX-first engine rather than a completely backend-neutral font
system.
