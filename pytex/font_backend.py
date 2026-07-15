from __future__ import annotations

from dataclasses import dataclass
import os
from types import SimpleNamespace

from pytex import glyph as glyph_data
from pytex import node as nd
from pytex.ligature import ligature_step, run_ligature_program
from pytex.module import Module
from pytex.serialization import Serializable


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
class FontSpec(Serializable):
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

    def saveInfo(self):
        return {
            "name": self.name,
            "lookup": self.lookup,
            "display_name": self.display_name,
            "font_number": self.font_number,
            "options": self.options,
            "features": self.features,
        }, None


class FontBackend:
    kind = None
    supports_contextual_space_shaping = False
    # XeTeX classifies classic TeX metric-backed fonts as type 0.  Native
    # layout backends override this, while conversion wrappers can preserve
    # the type of the font TeX originally selected.
    xetex_font_type = 0

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

    def xetexFeatures(self):
        """Return ``(numeric code, localized name)`` feature records."""
        return ()

    def unicodeChar(self, char: str) -> str:
        """Return the Unicode text represented by an engine character slot."""
        return char

    def hasChar(self, char: str) -> bool:
        return self.glyphInfo(char) is not None

    def leftBoundaryProgram(self):
        return None

    def rightBoundaryChar(self):
        return None

    @staticmethod
    def _shapeSource(font, source):
        source = tuple(source)
        if not all(isinstance(item, glyph_data.TextChar) for item in source):
            raise TypeError("font shaping requires TextChar source values")
        if not all(item.font is font for item in source):
            raise ValueError("font shaping source must use the selected font")
        return source

    def shape(
        self,
        font,
        source,
        *,
        parser=None,
        left_boundary=False,
        right_boundary=False,
    ):
        """Return simple one-character clusters for an unshaped backend."""
        source = self._shapeSource(font, source)
        return [
            glyph_data.GlyphCluster(
                [item],
                font[item.char],
            )
            for item in source
        ]

    def _shapeLigKern(
        self,
        font,
        source,
        *,
        parser=None,
        left_boundary=False,
        right_boundary=False,
    ):
        """Run TeX-compatible ligature/kern programs and return concrete nodes."""
        source = self._shapeSource(font, source)
        if not source:
            return []
        working = []
        state = {"lig_base": None, "in_word": False}

        def program_glyph(item, index):
            return _ProgramGlyph(font[item.char], (index,), (index,))

        def sources(node):
            return list(node.source_indices)

        def make_ligature(insert_char, replaced, step, current, nxt):
            return _ProgramGlyph(insert_char, tuple(replaced), tuple(replaced))

        def make_insert(insert_char, step, current, nxt):
            coverage = tuple(sorted(set(current.coverage) | set(nxt.coverage)))
            return _ProgramGlyph(insert_char, (), coverage)

        def make_kern(step, current, nxt):
            return nd.Kern(step.kern * font.at)

        def run(nodes):
            return run_ligature_program(
                nodes,
                make_ligature=make_ligature,
                make_kern=make_kern,
                source_nodes=sources,
                make_insert=make_insert,
            )

        def last_base(nodes):
            for node in reversed(nodes):
                if isinstance(node, _ProgramGlyph):
                    return node
                if node.node_type != nd.NODE_TYPE.KERN:
                    break
            return None

        def apply_left_boundary(node):
            program = self.leftBoundaryProgram()
            if program is None:
                return False
            boundary = _ProgramGlyph(
                SimpleNamespace(
                    char="\0",
                    font=font,
                    char_info=SimpleNamespace(program=program),
                ),
                (),
                (),
                boundary=True,
            )
            result = [
                item for item in run([boundary, node])
                if not getattr(item, "boundary", False)
            ]
            working.extend(result)
            state["lig_base"] = last_base(result)
            return True

        def apply_right_boundary():
            base = state["lig_base"]
            boundary_char = self.rightBoundaryChar()
            if base is None or boundary_char is None:
                return
            boundary = _ProgramGlyph(
                SimpleNamespace(
                    char=boundary_char,
                    font=font,
                    char_info=SimpleNamespace(program=None),
                ),
                (),
                (),
                boundary=True,
            )
            if not working or working[-1] is not base:
                raise RuntimeError("ligature base is not the last shaped glyph")
            working.pop()
            working.extend(
                item for item in run([base, boundary])
                if not getattr(item, "boundary", False)
            )

        for index, item in enumerate(source):
            node = program_glyph(item, index)
            if item.word_char:
                if not state["in_word"]:
                    state["in_word"] = True
                    state["lig_base"] = None
                    if (index > 0 or left_boundary) and apply_left_boundary(node):
                        continue
            elif state["in_word"]:
                apply_right_boundary()
                state["in_word"] = False
                state["lig_base"] = None

            base = state["lig_base"]
            if base is None:
                working.append(node)
                state["lig_base"] = node
                continue
            if not working or working[-1] is not base:
                raise RuntimeError("ligature base is not the last shaped glyph")
            if ligature_step(base, node) is None:
                working.append(node)
                state["lig_base"] = node
                continue
            working.pop()
            result = run([base, node])
            working.extend(result)
            state["lig_base"] = last_base(result)

        if state["in_word"] and right_boundary:
            apply_right_boundary()
        return self._materializeProgramShape(font, source, working, parser)

    @staticmethod
    def _materializeProgramShape(font, source, working, parser):
        output = []
        group = []
        coverage = set()
        kern_connects_next = False

        def flush_group():
            nonlocal kern_connects_next
            if not group:
                return
            indices = sorted(coverage)
            if not indices:
                raise ValueError("ligature program produced layout without logical source")
            layout_nodes = [
                node.node if isinstance(node, _ProgramGlyph) else node
                for node in group
            ]
            if len(layout_nodes) == 1:
                layout = layout_nodes[0]
            else:
                if parser is None:
                    raise ValueError("composed glyph clusters require a parser for HBox packing")
                from pytex import box as bx

                layout = bx.HBox(parser, None, None)
                layout.list = layout_nodes
                layout = layout.typeset(parser)
            output.append(
                glyph_data.GlyphCluster([source[index] for index in indices], layout)
            )
            group.clear()
            coverage.clear()
            kern_connects_next = False

        for node in working:
            if isinstance(node, _ProgramGlyph):
                if node.boundary:
                    continue
                node_coverage = set(node.coverage)
                if (
                    group
                    and not kern_connects_next
                    and not coverage.intersection(node_coverage)
                ):
                    flush_group()
                group.append(node)
                coverage.update(node_coverage)
                kern_connects_next = False
                continue
            if node.node_type != nd.NODE_TYPE.KERN:
                raise TypeError(f"unsupported font shaping node {node!r}")
            group.append(node)
            kern_connects_next = True
        flush_group()
        return output


class _ProgramGlyph:
    """Temporary CharNode-compatible value used by TeX lig/kern programs."""

    node_type = nd.NODE_TYPE.CHAR

    def __init__(self, node, source_indices, coverage, boundary=False):
        self.node = node
        self.char = node.char
        self.font = node.font
        self.char_info = node.char_info
        self.source_indices = tuple(source_indices)
        self.coverage = tuple(coverage)
        self.boundary = bool(boundary)


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
