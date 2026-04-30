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

    def hasChar(self, char: str) -> bool:
        return self.glyphInfo(char) is not None

    def leftBoundaryProgram(self):
        return None

    def rightBoundaryChar(self):
        return None


_backend_classes = []
_system_font_backend_cache = {}


def registerBackend(backend_cls):
    if backend_cls not in _backend_classes:
        _backend_classes.append(backend_cls)
    return backend_cls


def resourceName(name: str, kind: str = None):
    root, ext = os.path.splitext(name)
    if not ext and (kind is None or kind == "tfm"):
        return f"{name}.tfm"
    return f"{root}{ext.lower()}"


def parseFontName(parser, name):
    return name


def _loadFontSpec(parser, spec: FontSpec, kind: str = None):
    cache_key = (kind, spec)
    cached = _system_font_backend_cache.get(cache_key)
    if cached is not None:
        return cached
    if kind == "tfm" and spec.lookup == "file":
        raise FileNotFoundError(f"tfm font {spec.name} not found")
    for backend_cls in _backend_classes:
        if kind is not None and backend_cls.kind != kind:
            continue
        try:
            backend = backend_cls.load(parser, spec)
        except FileNotFoundError:
            if kind is not None:
                raise
            continue
        if backend is None:
            continue
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
        cache_key = (kind, name)
        cached = _system_font_backend_cache.get(cache_key)
        if cached is not None:
            return cached
        for backend_cls in _backend_classes:
            if backend_cls.kind != kind:
                continue
            backend = backend_cls.load(parser, name)
            if backend is None:
                continue
            _system_font_backend_cache[cache_key] = backend
            return backend
        raise FileNotFoundError(f"{kind} font {name} not found")

    _root, ext = os.path.splitext(name)
    if ext:
        name = resourceName(name)
        cache_key = (kind, name)
        cached = _system_font_backend_cache.get(cache_key)
        if cached is not None:
            return cached
        for backend_cls in _backend_classes:
            backend = backend_cls.load(parser, name)
            if backend is None:
                continue
            _system_font_backend_cache[cache_key] = backend
            return backend
        raise FileNotFoundError(f"font {name} not found")

    cache_key = (kind, name)
    cached = _system_font_backend_cache.get(cache_key)
    if cached is not None:
        return cached
    try:
        backend = loadFontBackend(parser, name, kind="tfm")
        _system_font_backend_cache[cache_key] = backend
        return backend
    except FileNotFoundError:
        pass

    try:
        backend = loadFontBackend(parser, name, kind="opentype")
        _system_font_backend_cache[cache_key] = backend
        return backend
    except FileNotFoundError:
        pass

    if kind is None:
        raise FileNotFoundError(f"font {name} not found")
    raise FileNotFoundError(f"{kind} font {name} not found")


mod = Module("font_backend",
    attributes={
        "loadFontBackend": loadFontBackend,
        "parseFontName": parseFontName,
    },
)
