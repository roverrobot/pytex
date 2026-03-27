# Font Backends

This note locks in the first step of the font-backend split.

## Goals

- Keep the existing `TFM` path working unchanged for plain TeX and the current
  LaTeX format.
- Introduce a common `FontBackend` interface so `TTF`/`OTF` support can be
  added without rewriting the `Font` command again.
- Avoid baking new code into `TFM`-specific assumptions like `font.tfm` or a
  contiguous `bc..ec` range.

## Backend Selection

The `\font` command reads a file name and asks registered backends to load it.

- `TFMBackend` handles names with no extension and names ending in `.tfm`.
- Future `OpenTypeBackend` will handle `.ttf` and `.otf`.
- A backend class method `load(parser, name)` returns a backend instance, or
  `None` if the backend does not support that name.

This keeps backend selection local to the filename, not to the parser.

Resolved backend objects may be shared across parsers through a process-wide
cache when the backend can provide a stable `systemCacheKey()`. This is
intended for immutable system resources such as parsed font data, while
parser-local or in-memory resources can simply return `None`.

## First Draft Interface

The first draft is intentionally small and biased toward the information the
 current engine already consumes:

```python
@dataclass
class GlyphInfo:
    char: str
    width: float
    height: float
    depth: float
    italic: float = 0
    program: dict[int, object] | None = None
    next_larger: str | None = None
    assembly: GlyphAssembly | None = None


@dataclass
class GlyphAssembly:
    parts: list[GlyphAssemblyPart] | None = None
    top: int | None = None
    middle: int | None = None
    bottom: int | None = None
    repeat: int | None = None
    vertical: bool = True
    italic: float = 0
    min_connector_overlap: float = 0


class FontBackend:
    kind: str

    @classmethod
    def load(cls, parser, name): ...

    @property
    def name(self): ...

    @property
    def design_size(self): ...

    @property
    def checksum(self): ...

    @property
    def fontdimen(self): ...

    def glyphInfo(self, char): ...

    def glyphInfos(self): ...

    def hasChar(self, char): ...

    def fallbackGlyphInfo(self, char): ...

    def leftBoundaryProgram(self): ...

    def rightBoundaryChar(self): ...

    def systemCacheKey(self): ...
```

## TFM Mapping

`TFMBackend` wraps the parsed `TFM` object and maps it into the common
interface:

- `name`, `design_size`, `checksum`, and `fontdimen` come straight from the
  `TFM` header and parameter table.
- `glyphInfo(char)` translates one existing `TFM` character record into
  `GlyphInfo`.
- `glyphInfos()` iterates the existing glyphs.
- `LIST_TAG` becomes `next_larger`.
- `EXT_TAG` becomes `GlyphAssembly`.
- left/right boundary ligature data stays available via
  `leftBoundaryProgram()` and `rightBoundaryChar()`.

## Deferred Work

- `OTF`/`TTF` loading.
- A common shaping IR for TeX ligature programs and OpenType `GSUB`/`GPOS`.
- A backend-neutral shipout path. The current DVI writer still assumes data
  that only `TFMBackend` naturally provides.
- Generalized font serialization for non-`TFM` font definitions.
