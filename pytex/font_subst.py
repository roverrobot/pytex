"""
Font substitution module

This module substitutes tfm/type1 fonts to ttf/otf fonts
"""

from pytex.dimen import Dimen
from pytex import font as fnt
from pytex.font_backend import FontSpec
from pytex.glue import Glue, Stretchness
from pytex.module import Module
from pytex import node as nd
import types
import os

DEFAULT_TEXT_FONT = "Times New Roman"
TEXT_FONT_CANDIDATES = (
    DEFAULT_TEXT_FONT,
    "Cambria",
    "Calibri",
)
MATH_FONT_CANDIDATES = (
    "STIXTwoMath-input.ttf",
    "Latin Modern Math",
    "STIX Two Math",
    "XITS Math",
    "Libertinus Math",
    "Cambria Math",
)
MATH_FAMILY_TEXT_OVERRIDES = {
    0: {
        0x3A: ".",
        0x3B: ",",
    },
    1: {
        0x3A: ".",
        0x3B: ",",
    },
}
MATH_OPERATORS_MAP = {
    0x00: "Γ",
    0x01: "Δ",
    0x02: "Θ",
    0x03: "Λ",
    0x04: "Ξ",
    0x05: "Π",
    0x06: "Σ",
    0x07: "Υ",
    0x08: "Φ",
    0x09: "Ψ",
    0x0A: "Ω",
}
MATH_LETTERS_MAP = {
    0x0B: "α",
    0x0C: "β",
    0x0D: "γ",
    0x0E: "δ",
    0x0F: "ε",
    0x10: "ζ",
    0x11: "η",
    0x12: "θ",
    0x13: "ι",
    0x14: "κ",
    0x15: "λ",
    0x16: "μ",
    0x17: "ν",
    0x18: "ξ",
    0x19: "π",
    0x1A: "ρ",
    0x1B: "σ",
    0x1C: "τ",
    0x1D: "υ",
    0x1E: "φ",
    0x1F: "χ",
    0x20: "ψ",
    0x21: "ω",
    0x22: "ε",
    0x23: "ϑ",
    0x24: "ϖ",
    0x25: "ϱ",
    0x26: "ς",
    0x27: "φ",
    0x40: "∂",
    0x60: "ℓ",
    0x7B: "ı",
    0x7C: "ȷ",
    0x7D: "℘",
}
MATH_SYMBOLS_MAP = {
    0x00: "−",
    0x01: "·",
    0x02: "×",
    0x03: "*",
    0x04: "÷",
    0x06: "±",
    0x07: "∓",
    0x08: "⊕",
    0x09: "⊖",
    0x0A: "⊗",
    0x0B: "⊘",
    0x0C: "⊙",
    0x0D: "◯",
    0x0E: "∘",
    0x0F: "•",
    0x10: "≍",
    0x11: "≡",
    0x12: "⊆",
    0x13: "⊇",
    0x14: "≤",
    0x15: "≥",
    0x18: "∼",
    0x19: "≈",
    0x1A: "⊂",
    0x1B: "⊃",
    0x1C: "≪",
    0x1D: "≫",
    0x1E: "≺",
    0x1F: "≻",
    0x20: "←",
    0x21: "→",
    0x22: "↑",
    0x23: "↓",
    0x24: "↔",
    0x25: "↗",
    0x26: "↘",
    0x28: "⇐",
    0x29: "⇒",
    0x2A: "⇑",
    0x2B: "⇓",
    0x2C: "⇔",
    0x2D: "↖",
    0x2E: "↙",
    0x2F: "∝",
    0x30: "′",
    0x31: "∞",
    0x32: "∈",
    0x33: "∋",
    0x34: "△",
    0x35: "▽",
    0x38: "∀",
    0x39: "∃",
    0x3A: "¬",
    0x3B: "∅",
    0x3C: "ℜ",
    0x3D: "ℑ",
    0x3E: "⊤",
    0x3F: "⊥",
    0x40: "ℵ",
    0x5B: "∪",
    0x5C: "∩",
    0x5D: "⊎",
    0x5E: "∧",
    0x5F: "∨",
    0x60: "⊢",
    0x61: "⊣",
    0x62: "⌊",
    0x63: "⌋",
    0x64: "⌈",
    0x65: "⌉",
    0x66: "{",
    0x67: "}",
    0x68: "⟨",
    0x69: "⟩",
    0x6A: "|",
    0x6B: "∥",
    0x6E: "\\",
    0x71: "∐",
    0x72: "∇",
    0x73: "∫",
    0x74: "⊔",
    0x75: "⊓",
    0x76: "⊑",
    0x77: "⊒",
    0x78: "§",
    0x79: "†",
    0x7A: "‡",
    0x7B: "¶",
    0x7C: "♣",
    0x7D: "♢",
    0x7E: "♡",
    0x7F: "♠",
}
MATH_LARGE_SYMBOLS_MAP = {
    0x46: "⨆",
    0x48: "∮",
    0x4A: "⨀",
    0x4C: "⨁",
    0x4E: "⨂",
    0x50: "∑",
    0x51: "∏",
    0x52: "∫",
    0x53: "⋃",
    0x54: "⋂",
    0x55: "⨄",
    0x56: "⋀",
    0x57: "⋁",
    0x60: "∐",
}


def requestFontName(name):
    if isinstance(name, FontSpec):
        return name.backend_name
    return name


def usableFontName(name):
    name = requestFontName(name)
    if not name:
        return False
    if os.sep in name or "/" in name or "\\" in name:
        return False
    lowered = name.lower()
    return not lowered.endswith((".ttf", ".otf", ".ttc", ".otc"))


def fontBackendName(backend):
    explicit = getattr(backend, "subst_font_name", None)
    if explicit and usableFontName(explicit):
        return explicit
    name = getattr(backend, "name", None)
    if usableFontName(name):
        return name
    font = getattr(backend, "font", None)
    table = font.get("name") if font is not None else None
    if table is not None:
        for name_id in (16, 1, 4, 6):
            for record in table.names:
                if record.nameID != name_id:
                    continue
                try:
                    text = record.toUnicode().strip()
                except Exception:
                    continue
                if usableFontName(text):
                    return text
    return None


def mathSlotText(family, code):
    override = MATH_FAMILY_TEXT_OVERRIDES.get(family, {}).get(code)
    if override is not None:
        return override
    if family == 0:
        text = MATH_OPERATORS_MAP.get(code)
        if text is not None:
            return text
    elif family == 1:
        text = MATH_LETTERS_MAP.get(code)
        if text is not None:
            return text
    elif family == 2:
        text = MATH_SYMBOLS_MAP.get(code)
        if text is not None:
            return text
    elif family == 3:
        text = MATH_LARGE_SYMBOLS_MAP.get(code)
        if text is not None:
            return text
        text = MATH_SYMBOLS_MAP.get(code)
        if text is not None:
            return text
    if 0x20 <= code < 0x7F:
        return chr(code)
    return None


def mathFontDimen(backend, family):
    provider = getattr(backend, "mathFontdimen", None)
    if callable(provider):
        params = provider(family)
        if params is not None:
            return list(params)

    base = list(getattr(backend, "fontdimen", ()) or ())
    slant = base[0] if len(base) > 0 else 0.0
    space = base[1] if len(base) > 1 else 0.0
    stretch = base[2] if len(base) > 2 else 0.0
    shrink = base[3] if len(base) > 3 else 0.0
    x_height = base[4] if len(base) > 4 else 0.0
    extra = base[6] if len(base) > 6 else shrink
    quad = 1.0

    def constant(name, default=0.0, scale=True):
        getter = getattr(backend, "mathConstant", None)
        if callable(getter):
            return getter(name, default, scale=scale)
        return default

    if family == 2:
        num_display = constant("FractionNumeratorDisplayStyleShiftUp")
        num_text = constant("FractionNumeratorShiftUp", num_display)
        denom_display = constant("FractionDenominatorDisplayStyleShiftDown")
        denom_text = constant("FractionDenominatorShiftDown", denom_display)
        sup_up = constant("SuperscriptShiftUp")
        sup_up_cramped = constant("SuperscriptShiftUpCramped", sup_up)
        sub_down = constant("SubscriptShiftDown")
        return [
            slant,
            space,
            stretch,
            shrink,
            x_height,
            quad,
            extra,
            num_display,
            num_text,
            num_text,
            denom_display,
            denom_text,
            sup_up,
            sup_up,
            sup_up_cramped,
            sub_down,
            sub_down,
            constant("SuperscriptBaselineDropMax"),
            constant("SubscriptBaselineDropMin"),
            constant("DisplayOperatorMinHeight", constant("DelimitedSubFormulaMinHeight")),
            constant("DelimitedSubFormulaMinHeight"),
            constant("AxisHeight"),
        ]

    if family == 3:
        return [
            slant,
            space,
            stretch,
            shrink,
            x_height,
            quad,
            extra,
            constant("FractionRuleThickness"),
            constant("UpperLimitGapMin"),
            constant("UpperLimitBaselineRiseMin"),
            constant("LowerLimitGapMin"),
            constant("LowerLimitBaselineDropMin"),
            constant("SpaceAfterScript", constant("FractionRuleThickness")),
        ]

    return base


class MathFont(fnt.Font):
    def __init__(self, backend, at, family, template=None):
        self.family = family
        self._template = template
        self.backend = backend
        self.at = at if isinstance(at, Dimen) else Dimen(at)
        raw_param = mathFontDimen(backend, family)
        self.param = [0] * len(raw_param)
        if self.param:
            self.param[0] = Dimen(raw_param[0])
            for i in range(1, len(raw_param)):
                self.param[i] = raw_param[i] * self.at
        self.charnode = {}
        zero = Dimen()
        space = self.param[1] if len(self.param) > 1 else zero
        stretch = self.param[2] if len(self.param) > 2 else zero
        shrink = self.param[3] if len(self.param) > 3 else zero
        self.spaceglue = Glue(
            space,
            Stretchness(stretch, 0),
            Stretchness(shrink, 0),
        )
        self.fontchar = {"skewchar": 0, "hyphenchar": 0}
        if template is not None:
            self.fontchar.update(getattr(template, "fontchar", {}))
            if getattr(template, "name", None) is not None:
                self.name = template.name

    def _mapped_char(self, char):
        if not isinstance(char, str) or len(char) != 1:
            return None
        return mathSlotText(self.family, ord(char))

    def glyphInfo(self, char):
        mapped = self._mapped_char(char)
        if mapped is None:
            return self.backend.glyphInfo(char)
        return self.backend.glyphInfo(mapped)

    def _charNode(self, char):
        node = self.charnode.get(char)
        if node is not None:
            return node
        mapped = self._mapped_char(char)
        char_info = self.glyphInfo(char)
        if char_info is None:
            char_info = self.fallbackGlyphInfo(char)
        if char_info is None:
            return None
        node = nd.CharNode(mapped if mapped is not None else char, self, char_info=char_info)
        self.charnode[char] = node
        return node

    def glyphInfos(self):
        seen = set()
        for code in range(256):
            mapped = mathSlotText(self.family, code)
            if mapped is None or mapped in seen:
                continue
            seen.add(mapped)
            info = self.backend.glyphInfo(mapped)
            if info is not None:
                yield info

    def fallbackGlyphInfo(self, char):
        mapped = self._mapped_char(char)
        if mapped is None:
            return self.backend.fallbackGlyphInfo(char)
        return self.backend.fallbackGlyphInfo(mapped)

    def hasCharCode(self, code: int):
        try:
            mapped = mathSlotText(self.family, code)
        except ValueError:
            return False
        if mapped is None:
            return False
        return self.backend.hasChar(mapped)


def resolveMathFontBackend(parser):
    cached = getattr(parser, "math_font_backend", None)
    if cached is not None:
        if cached is not False:
            display_name = fontBackendName(cached)
            if display_name:
                cached.subst_font_name = display_name
        return cached
    try:
        from pytex import opentype  # noqa: F401
    except Exception:
        parser.math_font_backend = False
        return None
    for name in MATH_FONT_CANDIDATES:
        try:
            backend = parser.loadFontBackend(name)
        except Exception:
            continue
        if getattr(backend, "kind", None) != "opentype":
            continue
        if not getattr(backend, "hasMathTable", lambda: False)():
            continue
        display_name = fontBackendName(backend)
        if display_name:
            backend.subst_font_name = display_name
        parser.math_font_backend = backend
        return backend
    parser.math_font_backend = False
    return None


class MathFontArray(fnt.MathFontArray):
    __slots__ = ("_backend",)

    def __init__(self, name: str, state=None, default=None):
        super().__init__(name, state=state, default=default)
        self._backend = None

    def _mathBackend(self):
        if self._backend is False:
            return None
        if self._backend is not None:
            return self._backend
        parser = self.state
        backend = resolveMathFontBackend(parser) if parser is not None else None
        self._backend = backend if backend is not None else False
        return backend

    def _wrapMathFont(self, index, value):
        if index not in (0, 1, 2, 3):
            return value
        if not isinstance(value, fnt.Font) or isinstance(value, fnt.NullFont):
            return value
        if isinstance(value, MathFont) and value.family == index:
            return value
        backend = self._mathBackend()
        if backend is None:
            return value
        wrapped = MathFont(backend, value.at, index, template=value)
        return wrapped

    def __setitem__(self, index, value):
        super().__setitem__(index, self._wrapMathFont(index, value))

    def setGlobal(self, index, value):
        super().setGlobal(index, self._wrapMathFont(index, value))


class SubstituteFontBackend:
    def __init__(self, backend, style_source_name=None, requested_backend=None):
        self._backend = backend
        self._requested_backend = requested_backend
        self.docx_style_source_name = style_source_name
        self.subst_font_name = getattr(backend, "name", None)
        self.kind = getattr(backend, "kind", None)

    @property
    def name(self):
        return getattr(self._backend, "name", None)

    @property
    def dvi_name(self):
        requested = getattr(self._requested_backend, "dvi_name", None)
        return requested if requested is not None else getattr(self._backend, "dvi_name", None)

    @property
    def design_size(self):
        requested = getattr(self._requested_backend, "design_size", None)
        return requested if requested is not None else getattr(self._backend, "design_size", None)

    @property
    def checksum(self):
        requested = getattr(self._requested_backend, "checksum", None)
        return requested if requested is not None else getattr(self._backend, "checksum", 0)

    @property
    def fontdimen(self):
        return getattr(self._backend, "fontdimen", ())

    def glyphInfo(self, char):
        return self._backend.glyphInfo(char)

    def glyphInfos(self):
        return self._backend.glyphInfos()

    def fallbackGlyphInfo(self, char):
        return self._backend.fallbackGlyphInfo(char)

    def hasChar(self, char):
        return self._backend.hasChar(char)

    def leftBoundaryProgram(self):
        return self._backend.leftBoundaryProgram()

    def rightBoundaryChar(self):
        return self._backend.rightBoundaryChar()

    def __getattr__(self, name):
        return getattr(self._backend, name)


def resolveTextBackend(parser):
    cached = getattr(parser, "_docx_text_backend", None)
    if cached is not None:
        return cached
    original = getattr(parser, "_docx_original_loadFontBackend", None) or getattr(parser, "loadFontBackend", None)
    if original is None:
        parser._docx_text_backend = False
        return None
    for name in TEXT_FONT_CANDIDATES:
        try:
            backend = original(name, kind="opentype")
        except Exception:
            continue
        if getattr(backend, "kind", None) != "opentype":
            continue
        parser._docx_text_backend = backend
        return backend
    parser._docx_text_backend = False
    return None


def shouldSubstituteBackend(name, kind, backend):
    if backend is None:
        return False
    if getattr(backend, "kind", None) == "opentype":
        return False
    if kind not in (None, "tfm"):
        return False
    backend_name = (requestFontName(getattr(backend, "name", "")) or "").lower()
    request_name = (requestFontName(name) or "").lower()
    if backend_name == "nullfont" or request_name == "nullfont":
        return False
    return True


def substituteBackend(parser, requested_name, kind, backend):
    if not shouldSubstituteBackend(requested_name, kind, backend):
        return backend
    wrapped = wrappedDefaultBackend(
        parser,
        getattr(backend, "name", None) or requestFontName(requested_name),
        requested_backend=backend,
    )
    if wrapped is None:
        return backend
    return wrapped


def wrappedDefaultBackend(parser, style_source_name, requested_backend=None):
    fallback = resolveTextBackend(parser)
    if fallback is None:
        return None
    cache = getattr(parser, "_docx_backend_substitution_cache", None)
    if cache is None:
        cache = {}
        parser._docx_backend_substitution_cache = cache
    style_source = requestFontName(style_source_name) or getattr(fallback, "name", None)
    key = (
        id(fallback),
        style_source,
        getattr(requested_backend, "design_size", None),
        getattr(requested_backend, "checksum", None),
    )
    wrapped = cache.get(key)
    if wrapped is None:
        wrapped = SubstituteFontBackend(
            fallback,
            style_source_name=style_source,
            requested_backend=requested_backend,
        )
        cache[key] = wrapped
    return wrapped


def installFontSubstitution(parser):
    if getattr(parser, "_font_substitution_installed", False):
        return
    original = getattr(parser, "loadFontBackend", None)
    if original is None:
        return

    parser._original_loadFontBackend = original

    def _load_with_substitution(self, name, kind=None):
        ext = os.path.splitext(name)[1].lower() if isinstance(name, str) else ""
        if kind == "opentype" or ext in (".otf", ".ttf", ".ttc", ".otc"):
            return self._original_loadFontBackend(name, kind=kind)

        if kind == "tfm" or ext == ".tfm":
            backend = self._original_loadFontBackend(name, kind=kind)
            return substituteBackend(self, name, kind, backend)

        if kind is None and not ext:
            try:
                return self._original_loadFontBackend(name, kind="opentype")
            except Exception:
                backend = self._original_loadFontBackend(name, kind=kind)
                return substituteBackend(self, name, kind, backend)

        backend = self._original_loadFontBackend(name, kind=kind)
        return substituteBackend(self, name, kind, backend)

    parser.loadFontBackend = types.MethodType(_load_with_substitution, parser)
    parser._font_substitution_installed = True


def installMathFontArrays(parser):
    for name in ("textfont", "scriptfont", "scriptscriptfont"):
        current = getattr(parser, name, None)
        if isinstance(current, MathFontArray):
            continue
        wrapped = MathFontArray(name, state=parser, default=fnt.nullfont)
        if current is not None:
            wrapped.list[:] = list(getattr(current, "list", wrapped.list))
            wrapped.dict.update(getattr(current, "dict", {}))
        setattr(parser, name, wrapped)
        parser.arrays[name] = wrapped
        accessor = parser.builtin.get("\\" + name)
        if accessor is not None:
            accessor.domain = wrapped
