from __future__ import annotations

from dataclasses import dataclass
import os
from pytex.module import Module


@dataclass
class GlyphAssemblyPart:
    glyph: str
    start_connector: float = 0
    end_connector: float = 0
    full_advance: float = 0
    extender: bool = False


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


@dataclass
class GlyphInfo:
    char: str
    width: float
    height: float
    depth: float
    italic: float = 0
    glyph_name: str | None = None
    glyph_id: int | None = None
    program: dict[int, object] | None = None
    next_larger: str | None = None
    assembly: GlyphAssembly | None = None


@dataclass(frozen=True)
class FontSpec:
    """
    Parsed engine-specific font lookup information.

    ``lookup`` is one of:
    - ``auto``: legacy behavior, trying TeX metrics and then native fonts.
    - ``file``: force a file lookup, as XeTeX does for bracketed font names.
    - ``system``: force a system font-name lookup.
    """
    name: str
    lookup: str = "auto"
    display_name: str | None = None
    font_number: int = 0
    options: str = ""
    features: str = ""

    @property
    def backend_name(self):
        return self.display_name if self.display_name is not None else self.name


class FontBackend:
    kind = None

    @classmethod
    def load(cls, parser, name: str):
        raise NotImplementedError

    @property
    def name(self) -> str:
        raise NotImplementedError

    @property
    def dvi_name(self) -> str | None:
        return self.name

    @property
    def design_size(self):
        raise NotImplementedError

    @property
    def checksum(self) -> int:
        return 0

    @property
    def fontdimen(self):
        return ()

    def glyphInfo(self, char: str):
        raise NotImplementedError

    def glyphInfos(self):
        raise NotImplementedError

    def fallbackGlyphInfo(self, char: str):
        return None

    def unicodeChar(self, char: str) -> str:
        """Return the Unicode text represented by an engine character slot."""
        return char

    def hasChar(self, char: str) -> bool:
        return self.glyphInfo(char) is not None

    def leftBoundaryProgram(self):
        return None

    def rightBoundaryChar(self):
        return None


_backend_classes = []
_font_converters = []
_system_font_backend_cache = {}


def registerBackend(backend_cls):
    if backend_cls not in _backend_classes:
        _backend_classes.append(backend_cls)
    return backend_cls


def registerFontConverter(source_cls, target_cls):
    def register(converter):
        item = (source_cls, target_cls, converter)
        if item not in _font_converters:
            _font_converters.append(item)
        return converter
    return register


def registerSupportedFontClasses(parser, *backend_classes):
    """Restrict font lookup to concrete backend classes supported by output."""
    parser.supported_font_classes = tuple(backend_classes) or None


def _supportedFontClasses(parser):
    return getattr(parser, "supported_font_classes", None)


def _supportsBackend(parser, backend):
    supported = _supportedFontClasses(parser)
    return supported is None or isinstance(backend, supported)


def _selectBackend(parser, candidates):
    if not candidates:
        return None
    supported = _supportedFontClasses(parser)
    if supported is None:
        return candidates[0]
    for backend in candidates:
        if isinstance(backend, supported):
            return backend
    for backend in candidates:
        for source_cls, target_cls, converter in _font_converters:
            if not isinstance(backend, source_cls):
                continue
            if not any(issubclass(target_cls, allowed) for allowed in supported):
                continue
            converted = converter(parser, backend)
            if converted is not None and isinstance(converted, supported):
                return converted
    return candidates[0]


def _cacheKey(parser, kind, name):
    return kind, name, _supportedFontClasses(parser)


def _loadCandidates(parser, name, kind=None):
    candidates = []
    for backend_cls in _backend_classes:
        if kind is not None and backend_cls.kind != kind:
            continue
        try:
            backend = backend_cls.load(parser, name)
        except FileNotFoundError:
            if kind is not None:
                raise
            continue
        if backend is None:
            continue
        candidates.append(backend)
        if _supportsBackend(parser, backend):
            break
    return candidates


def resourceName(name: str, kind: str = None):
    root, ext = os.path.splitext(name)
    if not ext and (kind is None or kind == "tfm"):
        return f"{name}.tfm"
    return f"{root}{ext.lower()}"


def parseFontName(parser, name):
    return name


def _loadFontSpec(parser, spec: FontSpec, kind: str = None):
    cache_key = _cacheKey(parser, kind, spec)
    cached = _system_font_backend_cache.get(cache_key)
    if cached is not None:
        return cached
    if kind == "tfm" and spec.lookup == "file":
        raise FileNotFoundError(f"tfm font {spec.name} not found")
    candidates = _loadCandidates(parser, spec, kind=kind)
    backend = _selectBackend(parser, candidates)
    if backend is not None:
        _system_font_backend_cache[cache_key] = backend
        return backend
    if kind is None:
        raise FileNotFoundError(f"font {spec.name} not found")
    raise FileNotFoundError(f"{kind} font {spec.name} not found")


def loadFontBackend(parser, name: str, kind: str = None):
    if isinstance(name, FontSpec):
        return _loadFontSpec(parser, name, kind=kind)

    if kind is not None:
        name = resourceName(name, kind=kind)
        cache_key = _cacheKey(parser, kind, name)
        cached = _system_font_backend_cache.get(cache_key)
        if cached is not None:
            return cached
        backend = _selectBackend(parser, _loadCandidates(parser, name, kind=kind))
        if backend is not None:
            _system_font_backend_cache[cache_key] = backend
            return backend
        raise FileNotFoundError(f"{kind} font {name} not found")

    _root, ext = os.path.splitext(name)
    if ext:
        name = resourceName(name)
        cache_key = _cacheKey(parser, kind, name)
        cached = _system_font_backend_cache.get(cache_key)
        if cached is not None:
            return cached
        backend = _selectBackend(parser, _loadCandidates(parser, name))
        if backend is not None:
            _system_font_backend_cache[cache_key] = backend
            return backend
        raise FileNotFoundError(f"font {name} not found")

    cache_key = _cacheKey(parser, kind, name)
    cached = _system_font_backend_cache.get(cache_key)
    if cached is not None:
        return cached
    candidates = []
    for candidate_kind in ("tfm", "opentype"):
        try:
            normalized = resourceName(name, kind=candidate_kind)
            candidates.extend(_loadCandidates(parser, normalized, kind=candidate_kind))
        except FileNotFoundError:
            continue
        if candidates and _supportsBackend(parser, candidates[-1]):
            break
    backend = _selectBackend(parser, candidates)
    if backend is not None:
        _system_font_backend_cache[cache_key] = backend
        return backend

    if kind is None:
        raise FileNotFoundError(f"font {name} not found")
    raise FileNotFoundError(f"{kind} font {name} not found")


mod = Module("font_backend",
    attributes={
        "loadFontBackend": loadFontBackend,
        "parseFontName": parseFontName,
        "registerSupportedFontClasses": registerSupportedFontClasses,
        "supported_font_classes": None,
    },
)
