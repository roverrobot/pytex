"""Minimal DOCX shipout backend for pure text paragraphs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Pt

from pytex import box as bx
from pytex import font as txfont
from pytex import html_reflow as html_math
from pytex import mmode
from pytex import node as nd
from pytex import paragraph as pg
from pytex.dimen import Dimen
from pytex.font_backend import GlyphInfo
from pytex.module import Module
from pytex.typeset.shipout import Shipout

_ONE_INCH_PT = 72.0
_ONE_INCH_TEX = Dimen(72.27)
_DOCX_POINTS_PER_TEX_POINT_NUM = 7200
_DOCX_POINTS_PER_TEX_POINT_DEN = 7227
_DOCX_TWIPS_PER_TEX_POINT_NUM = 144000
_DOCX_TWIPS_PER_TEX_POINT_DEN = 7227
_INLINE_TEXTBOX_PAD_PT = 0.75
_DOCX_DEFAULT_TEXT_FONT = "Times New Roman"
_LOCAL_STIX_TTF = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", ".cache", "fonts", "STIXTwoMath-input.ttf")
)
_DOCX_MATH_FONT_CANDIDATES = (
    _LOCAL_STIX_TTF,
    "Latin Modern Math",
    "STIX Two Math",
    "XITS Math",
    "Libertinus Math",
    "Cambria Math",
)
_MATH_FAMILY_TEXT_OVERRIDES = {
    0: {
        0x3A: ".",
        0x3B: ",",
    },
    1: {
        0x3A: ".",
        0x3B: ",",
    },
}


def _docx_math_slot_text(family, code):
    override = _MATH_FAMILY_TEXT_OVERRIDES.get(family, {}).get(code)
    if override is not None:
        return override
    if family == 0:
        text = html_math._MATH_OPERATORS_MAP.get(code)
        if text is not None:
            return text
    elif family == 1:
        text = html_math._MATH_LETTERS_MAP.get(code)
        if text is not None:
            return text
    elif family == 2:
        text = html_math._MATH_SYMBOLS_MAP.get(code)
        if text is not None:
            return text
    elif family == 3:
        text = html_math._MATH_LARGE_SYMBOLS_MAP.get(code)
        if text is not None:
            return text
        text = html_math._MATH_SYMBOLS_MAP.get(code)
        if text is not None:
            return text
    if 0x20 <= code < 0x7F:
        return chr(code)
    return None


def _resolve_parser_docx_math_backend(parser):
    cached = getattr(parser, "_docx_math_backend", None)
    if cached is not None:
        return cached
    try:
        from pytex import opentype  # noqa: F401
    except Exception:
        parser._docx_math_backend = False
        return None
    for name in _DOCX_MATH_FONT_CANDIDATES:
        try:
            backend = parser.loadFontBackend(name)
        except Exception:
            continue
        if getattr(backend, "kind", None) != "opentype":
            continue
        if not getattr(backend, "hasMathTable", lambda: False)():
            continue
        parser._docx_math_backend = backend
        return backend
    parser._docx_math_backend = False
    return None


def _docx_math_fontdimen(backend, family):
    provider = getattr(backend, "docxMathFontdimen", None)
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


class _DocxMathFont(txfont.Font):
    def __init__(self, backend, at, family, template=None):
        self.family = family
        self._template = template
        self.backend = backend
        self.at = at if isinstance(at, Dimen) else Dimen(at)
        raw_param = _docx_math_fontdimen(backend, family)
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
        self.spaceglue = txfont.Glue(
            space,
            txfont.Stretchness(stretch, 0),
            txfont.Stretchness(shrink, 0),
        )
        self.fontchar = {"skewchar": 0, "hyphenchar": 0}
        if template is not None:
            self.fontchar.update(getattr(template, "fontchar", {}))
            if getattr(template, "name", None) is not None:
                self.name = template.name

    def _mapped_char(self, char):
        if not isinstance(char, str) or len(char) != 1:
            return None
        return _docx_math_slot_text(self.family, ord(char))

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
            mapped = _docx_math_slot_text(self.family, code)
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
            mapped = _docx_math_slot_text(self.family, code)
        except ValueError:
            return False
        if mapped is None:
            return False
        return self.backend.hasChar(mapped)


class _DocxMathFontArray(txfont.MathFontArray):
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
        backend = _resolve_parser_docx_math_backend(parser) if parser is not None else None
        self._backend = backend if backend is not None else False
        return backend

    def _wrapMathFont(self, index, value):
        if index not in (2, 3):
            return value
        if not isinstance(value, txfont.Font) or isinstance(value, txfont.NullFont):
            return value
        if isinstance(value, _DocxMathFont) and value.family == index:
            return value
        backend = self._mathBackend()
        if backend is None:
            return value
        wrapped = _DocxMathFont(backend, value.at, index, template=value)
        return wrapped

    def __setitem__(self, index, value):
        super().__setitem__(index, self._wrapMathFont(index, value))

    def setGlobal(self, index, value):
        super().setGlobal(index, self._wrapMathFont(index, value))


def _install_docx_math_font_arrays(parser):
    for name in ("textfont", "scriptfont", "scriptscriptfont"):
        current = getattr(parser, name, None)
        if isinstance(current, _DocxMathFontArray):
            continue
        wrapped = _DocxMathFontArray(name, state=parser, default=txfont.nullfont)
        if current is not None:
            wrapped.list[:] = list(getattr(current, "list", wrapped.list))
            wrapped.dict.update(getattr(current, "dict", {}))
        setattr(parser, name, wrapped)
        parser.arrays[name] = wrapped
        accessor = parser.builtin.get("\\" + name)
        if accessor is not None:
            accessor.domain = wrapped


@dataclass
class _TextRun:
    text: str
    font: object | None
    spacing_twips: int = 0


@dataclass
class _InlineBoxRun:
    box: object
    chunks: list[object] = field(default_factory=list)
    line_depth: Dimen = field(default_factory=Dimen)


@dataclass
class _InlineMathRun:
    box: object
    fields: list[object] = field(default_factory=list)
    line_depth: Dimen = field(default_factory=Dimen)


@dataclass
class _InlineMathState:
    in_math: bool = False
    nodes: list[object] = field(default_factory=list)
    leading_kern: Dimen = field(default_factory=Dimen)
    line_depth: Dimen = field(default_factory=Dimen)
    spacing_font: object | None = None

    def active(self):
        return self.in_math or bool(self.nodes)

    def has_nodes(self):
        return bool(self.nodes)

    def clear(self):
        self.in_math = False
        self.nodes.clear()
        self.leading_kern = Dimen()
        self.line_depth = Dimen()
        self.spacing_font = None


@dataclass
class _Glyph:
    text: str
    font: object | None
    x: int
    y: int
    width: int


@dataclass
class _ParagraphSpec:
    owner: object | None
    lines: list[object] = field(default_factory=list)
    interline_gaps: list[Dimen] = field(default_factory=list)
    space_before: Dimen = field(default_factory=Dimen)
    first_line_indent: Dimen = field(default_factory=Dimen)


@dataclass
class _LineSpec:
    runs: list[object]
    box: object | None = None
    segments: list[object] = field(default_factory=list)


@dataclass
class _LineSegment:
    runs: list[object]


@dataclass
class _LineEvent:
    owner: object
    baseline: int
    box: object


@dataclass
class _DisplayMathSpec:
    owner: object
    box: object
    page: object | None = None
    space_before: Dimen = field(default_factory=Dimen)


class DocxBackend(Shipout):
    """
    Very small proof-of-concept DOCX backend.

    Scope intentionally stays narrow:
    - single-page documents
    - pure text only
    - TeX controls both paragraph and line breaks
    - page semantics, math, alignments, images, specials, etc. are ignored

    The backend reconstructs TeX paragraphs from shipped line boxes, emits one
    Word paragraph per TeX paragraph, inserts explicit line breaks between TeX
    lines, and uses TeX's already-computed paragraph ownership and glue as DOCX
    paragraph spacing hints.
    """

    def __init__(self, parser, output=None):
        super().__init__(parser, output)
        self.file = None
        self.finished = False
        self._captured_pages: list[list[_Glyph]] = []
        self._docx_math_font = None

    def shipout(self, box):
        if box.width is None:
            packed = []
            box.typeset(self.parser, packed)
            box = packed[-1]
        self.pages.append(box)
        self._captured_pages.append(self._capture_page(box))

    def open(self, output=None):
        if self.file is not None:
            return
        if output is None:
            output = self.output
        if output is None:
            output = self.parser.jobname or "texput"
        if hasattr(output, "write"):
            self.file = output
            return
        path = os.fspath(output)
        if os.path.isabs(path):
            if not path.endswith(".docx"):
                path += ".docx"
            self.file = open(path, "wb")
            return
        if not path.endswith(".docx"):
            path += ".docx"
        self.file = self.parser.resolver.openOut(path, "shipout/docx")

    @staticmethod
    def _paragraph_owner(node):
        source = getattr(node, "source", None)
        seen = set()
        while source is not None and not isinstance(source, (list, tuple)):
            if isinstance(source, pg.Paragraph):
                return source
            key = id(source)
            if key in seen:
                break
            seen.add(key)
            source = getattr(source, "source", None)
        return None

    @staticmethod
    def _display_math_owner(node):
        source = getattr(node, "source", None)
        return source if isinstance(source, mmode.DisplayMathNode) else None

    @staticmethod
    def _is_math_field(field):
        return isinstance(
            field,
            (
                mmode.MathSymbol,
                mmode.MathListHolder,
                mmode.Subformula,
                mmode.InlineMathNode,
                mmode.DisplayMathNode,
                mmode.Over,
                mmode.Rad,
                mmode.Accent,
                mmode.Atom,
            ),
        )

    @staticmethod
    def _pt(value):
        scaled = int(value) if isinstance(value, Dimen) else int(Dimen(value))
        return (
            scaled
            * _DOCX_POINTS_PER_TEX_POINT_NUM
            / (_DOCX_POINTS_PER_TEX_POINT_DEN * Dimen.scale)
        )

    @classmethod
    def _length(cls, value):
        return Pt(cls._pt(value))

    @staticmethod
    def _textbox_style(anchor=None):
        parts = [
            "mso-fit-shape-to-text:f",
            "mso-fit-text-to-shape:f",
        ]
        if anchor == "bottom":
            parts.append("v-text-anchor:bottom")
        elif anchor == "top":
            parts.append("v-text-anchor:top")
        return ";".join(parts)

    def _vml_textbox_xml(self, content, width, height, anchor=None):
        return (
            "<w:pict>"
            f"<v:rect stroked=\"f\" filled=\"f\" o:allowincell=\"f\" style=\"width:{width:.4f}pt;height:{height:.4f}pt\">"
            f"<v:textbox inset=\"0,0,0,0\" style=\"{self._textbox_style(anchor=anchor)}\">{content}</v:textbox>"
            "<w10:wrap type=\"none\"/>"
            "</v:rect>"
            "</w:pict>"
        )

    def _resolve_docx_math_font(self):
        if self._docx_math_font is not None:
            return self._docx_math_font
        backend = _resolve_parser_docx_math_backend(self.parser)
        if backend is not None:
            self._docx_math_font = backend.name
            return self._docx_math_font
        self._docx_math_font = ""
        return self._docx_math_font

    def _configure_math_settings(self, document):
        font_name = self._resolve_docx_math_font()
        if not font_name:
            return
        settings = document.settings._element
        for child in list(settings):
            if child.tag == qn("m:mathPr"):
                settings.remove(child)
        escaped_name = escape(font_name, {'"': "&quot;"})
        settings.append(
            parse_xml(
                (
                    "<m:mathPr "
                    "xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\">"
                    f"<m:mathFont m:val=\"{escaped_name}\"/>"
                    "</m:mathPr>"
                )
            )
        )

    @staticmethod
    def _nonnegative_dimen(value):
        value = value if isinstance(value, Dimen) else Dimen(value)
        return value if value >= 0 else Dimen()

    def _tex_page_size(self, page):
        origin_x = _ONE_INCH_TEX + Dimen(self.parser.layout["hoffset"])
        origin_y = _ONE_INCH_TEX + Dimen(self.parser.layout["voffset"])
        try:
            width_param = self.parser.parameters["pdfpagewidth"]
        except Exception:
            width_param = None
        try:
            height_param = self.parser.parameters["pdfpageheight"]
        except Exception:
            height_param = None
        width = Dimen(width_param) if width_param is not None else Dimen()
        height = Dimen(height_param) if height_param is not None else Dimen()
        box_width = Dimen(getattr(page, "width", 0))
        box_height = Dimen(getattr(page, "height", 0) + getattr(page, "depth", 0))
        if width <= 0:
            width = box_width + 2 * origin_x
        if height <= 0:
            height = box_height + 2 * origin_y
        return width, height, origin_x, origin_y

    def _configure_section(self, document, page):
        section = document.sections[0]
        hsize = Dimen(self.parser.layout["hsize"])
        vsize = Dimen(self.parser.layout["vsize"])
        page_width, page_height, origin_x, origin_y = self._tex_page_size(page)
        box_width = Dimen(getattr(page, "width", 0))
        box_height = Dimen(getattr(page, "height", 0) + getattr(page, "depth", 0))

        text_width = hsize if hsize > 0 else box_width
        text_height = vsize if vsize > 0 else box_height

        inner_left = box_width - text_width if box_width > text_width else Dimen()
        inner_top = box_height - text_height if box_height > text_height else Dimen()

        left_margin = self._nonnegative_dimen(origin_x + inner_left)
        top_margin = self._nonnegative_dimen(origin_y + inner_top)
        right_margin = self._nonnegative_dimen(page_width - left_margin - text_width)
        bottom_margin = self._nonnegative_dimen(page_height - top_margin - text_height)

        section.left_margin = self._length(left_margin)
        section.right_margin = self._length(right_margin)
        section.top_margin = self._length(top_margin)
        section.bottom_margin = self._length(bottom_margin)
        section.page_width = self._length(self._nonnegative_dimen(page_width))
        section.page_height = self._length(self._nonnegative_dimen(page_height))

    @staticmethod
    def _glyph_text(node):
        if getattr(node, "node_type", None) == nd.NODE_TYPE.LIGATURE:
            source = getattr(node, "source", None) or []
            if source:
                return "".join(getattr(child, "char", "") for child in source)
        return getattr(node, "char", "")

    def _effective_glue_amount(self, node, box, state=None):
        if not hasattr(box, "glue_ratio"):
            return int(node.glue.dimen)
        return self._glue_amount(node, box, state)

    def _capture_hlist(self, box, h, v, out):
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                text = self._glyph_text(node)
                if text:
                    out.append(
                        _Glyph(
                            text=text,
                            font=getattr(node, "font", None),
                            x=int(h),
                            y=int(v),
                            width=int(getattr(node, "width", 0)),
                        )
                    )
                h += int(getattr(node, "width", 0))
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                h += self._effective_glue_amount(node, box, glue_state)
                continue
            if node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                h += int(node.kern)
                continue
            if node_type == nd.NODE_TYPE.DISC:
                h = self._capture_hlist(node, h, v, out)
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                shifted = int(getattr(node, "shifted", 0))
                self._capture_hlist(node, h, v + shifted, out)
                h += int(getattr(node, "width", 0))
                continue
            if node_type == nd.NODE_TYPE.VLIST:
                shifted = int(getattr(node, "shifted", 0))
                self._capture_vlist(node, h, v + shifted - int(getattr(node, "height", 0)), out)
                h += int(getattr(node, "width", 0))
                continue
        return h

    def _capture_vlist(self, box, h, v, out):
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                v += self._effective_glue_amount(node, box, glue_state)
                continue
            if node_type == nd.NODE_TYPE.KERN:
                v += int(node.kern)
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                shifted = int(getattr(node, "shifted", 0))
                self._capture_hlist(node, h + shifted, v + int(getattr(node, "height", 0)), out)
                v += int(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue
            if node_type == nd.NODE_TYPE.VLIST:
                shifted = int(getattr(node, "shifted", 0))
                self._capture_vlist(node, h + shifted, v, out)
                v += int(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue
        return v

    def _capture_page(self, page):
        glyphs: list[_Glyph] = []
        self._capture_vlist(page, 0, 0, glyphs)
        return glyphs

    @staticmethod
    def _docx_font_style(font):
        backend = getattr(font, "backend", None)
        name = (getattr(backend, "name", None) or "").lower()
        bold = any(tag in name for tag in ("bx", "bold", "semibold", "demibold"))
        italic = any(tag in name for tag in ("it", "italic", "sl", "oblique"))
        return bold, italic

    @staticmethod
    def _docx_usable_font_name(name):
        if not name:
            return False
        if os.sep in name or "/" in name or "\\" in name:
            return False
        lowered = name.lower()
        return not lowered.endswith((".ttf", ".otf", ".ttc", ".otc"))

    @classmethod
    def _font_name(cls, font):
        if font is None:
            return None
        backend = getattr(font, "backend", None)
        if backend is None:
            return None
        name = getattr(backend, "name", None)
        if getattr(backend, "kind", None) == "opentype" and cls._docx_usable_font_name(name):
            return name
        return _DOCX_DEFAULT_TEXT_FONT

    def _apply_run_font(self, run, font):
        self._apply_run_font_with_options(run, font, allow_word_kerning=True)

    def _apply_run_font_with_options(self, run, font, allow_word_kerning=True):
        if font is None:
            return
        name = self._font_name(font)
        if name:
            run.font.name = name
        bold, italic = self._docx_font_style(font)
        if bold:
            run.bold = True
        if italic:
            run.italic = True
        at = getattr(font, "at", None)
        if at is not None:
            run.font.size = self._length(at)
            if allow_word_kerning:
                self._apply_run_kerning(run, at)

    @classmethod
    def _font_half_points(cls, size):
        scaled = int(size) if isinstance(size, Dimen) else int(Dimen(size))
        return max(
            0,
            Dimen._round_div(
                scaled * _DOCX_POINTS_PER_TEX_POINT_NUM * 2,
                _DOCX_POINTS_PER_TEX_POINT_DEN * Dimen.scale,
            ),
        )

    @classmethod
    def _apply_run_kerning(cls, run, size):
        half_points = cls._font_half_points(size)
        if half_points <= 0:
            return
        rPr = run._r.get_or_add_rPr()
        kern = rPr.find(qn("w:kern"))
        if kern is None:
            kern = OxmlElement("w:kern")
            rPr.append(kern)
        kern.set(qn("w:val"), str(half_points))

    @staticmethod
    def _space_width(font):
        if font is None:
            return 0
        info = None
        try:
            info = font.glyphInfo(" ")
        except Exception:
            info = None
        at = getattr(font, "at", None)
        if info is None or at is None:
            return 0
        return int(info.width * at)

    def _runs_from_glyphs(self, glyphs):
        if not glyphs:
            return []
        glyphs = sorted(glyphs, key=lambda g: g.x)
        runs: list[_TextRun] = []
        prev_end = None
        prev_font = None
        for glyph in glyphs:
            if prev_end is not None:
                gap = glyph.x - prev_end
                space_width = self._space_width(prev_font or glyph.font)
                threshold = max(1, int(round(space_width * 0.4))) if space_width > 0 else 1
                if gap > threshold:
                    count = 1
                    nominal_width = max(space_width, 0)
                    delta = gap - nominal_width
                    runs.append(
                        _TextRun(
                            " " * count,
                            prev_font or glyph.font,
                            spacing_twips=self._spacing_twips(delta),
                        )
                    )
            runs.append(_TextRun(glyph.text, glyph.font))
            prev_end = glyph.x + glyph.width
            prev_font = glyph.font
        return self._normalize_runs(runs)

    def _normalize_runs(self, runs):
        merged = []
        for run in runs:
            if isinstance(run, _InlineBoxRun):
                if run.chunks:
                    run.chunks = self._normalize_runs(run.chunks)
                merged.append(run)
                continue
            if isinstance(run, _InlineMathRun):
                merged.append(run)
                continue
            text = run.text
            if not text:
                continue
            if (
                text.isspace()
                and merged
                and isinstance(merged[-1], _TextRun)
                and merged[-1].text.isspace()
            ):
                prev = merged[-1]
                prev.spacing_twips = self._collapsed_space_spacing(prev, run)
                prev.text = " "
                continue
            if (
                merged
                and isinstance(merged[-1], _TextRun)
                and merged[-1].font is run.font
                and merged[-1].spacing_twips == run.spacing_twips
            ):
                merged[-1].text += text
            else:
                merged.append(_TextRun(text, run.font, run.spacing_twips))
        return merged

    @classmethod
    def _spacing_twips(cls, delta):
        if not delta:
            return 0
        value = int(delta)
        return Dimen._round_div(
            value * _DOCX_TWIPS_PER_TEX_POINT_NUM,
            _DOCX_TWIPS_PER_TEX_POINT_DEN * Dimen.scale,
        )

    @classmethod
    def _fit_text_twips(cls, width):
        value = int(width)
        return max(
            0,
            Dimen._round_div(
                value * _DOCX_TWIPS_PER_TEX_POINT_NUM,
                _DOCX_TWIPS_PER_TEX_POINT_DEN * Dimen.scale,
            ),
        )

    @staticmethod
    def _line_has_fixed_segments(runs):
        return any(isinstance(run, (_InlineBoxRun, _InlineMathRun)) for run in runs)

    def _segment_mixed_line_runs(self, runs):
        if not self._line_has_fixed_segments(runs):
            return []
        segments = []
        text_runs = []

        def flush_text():
            nonlocal text_runs
            if not text_runs:
                return
            segments.append(_LineSegment(runs=list(text_runs)))
            text_runs = []

        for run in runs:
            if isinstance(run, _TextRun):
                text_runs.append(run)
                continue
            flush_text()
            segments.append(_LineSegment(runs=[run]))
        flush_text()
        return segments

    @staticmethod
    def _apply_run_spacing(run, spacing_twips):
        if spacing_twips == 0:
            return
        rPr = run._r.get_or_add_rPr()
        spacing = rPr.find(qn("w:spacing"))
        if spacing is None:
            spacing = OxmlElement("w:spacing")
            rPr.append(spacing)
        spacing.set(qn("w:val"), str(int(spacing_twips)))

    def _collapsed_space_spacing(self, left, right):
        font = left.font or right.font
        nominal = self._space_width(font)
        total_spaces = len(left.text) + len(right.text)
        removed_spaces = max(0, total_spaces - 1)
        removed_twips = self._spacing_twips(removed_spaces * nominal)
        return left.spacing_twips + right.spacing_twips + removed_twips

    def _glyphs_by_baseline(self, glyphs):
        lines = {}
        for glyph in glyphs:
            lines.setdefault(glyph.y, []).append(glyph)
        return lines

    @staticmethod
    def _paragraph_first_indent(owner):
        items = getattr(owner, "list", None) or ()
        if not items:
            return Dimen()
        first = items[0]
        if isinstance(first, bx.IndentBox):
            return Dimen(first.width)
        return Dimen()

    @staticmethod
    def _line_starts_with_indent_box(line_box, indent_width):
        if indent_width <= 0:
            return False
        items = getattr(line_box, "list", None) or ()
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY):
                continue
            if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                width = Dimen(getattr(node, "width", 0))
                if width == indent_width and not DocxBackend._node_has_inline_text(node):
                    return True
            return False
        return False

    def _walk_hlist(self, box, baseline):
        """
        Yield paragraph-owned line events in reading order.

        Important: a wrapper HLIST may itself carry a paragraph-ish ``source``
        while still containing the actual shipped line boxes as nested HLISTs.
        So we recurse first; only if no descendant line events are found do we
        treat the current box itself as a line.
        """
        owner = self._paragraph_owner(box)
        display_owner = self._display_math_owner(box)
        if display_owner is not None and getattr(box, "display", False):
            yield ("display", display_owner, box)
            return
        if owner is not None and self._box_has_direct_inline_content(box):
            yield ("line", _LineEvent(owner=owner, baseline=int(baseline), box=box))
            return
        items = getattr(box, "list", None) or ()
        emitted_descendant = False
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.HLIST:
                shifted = int(getattr(node, "shifted", 0))
                for event in self._walk_hlist(node, baseline + shifted):
                    emitted_descendant = True
                    yield event
            elif node_type == nd.NODE_TYPE.VLIST:
                shifted = int(getattr(node, "shifted", 0))
                child_top = baseline + shifted - int(getattr(node, "height", 0))
                for event in self._walk_vlist(node, child_top):
                    emitted_descendant = True
                    yield event
        if not emitted_descendant and owner is not None:
            yield ("line", _LineEvent(owner=owner, baseline=int(baseline), box=box))

    @staticmethod
    def _box_has_direct_inline_content(box):
        items = getattr(box, "list", None) or ()
        inline_types = {
            nd.NODE_TYPE.CHAR,
            nd.NODE_TYPE.LIGATURE,
            nd.NODE_TYPE.DISC,
            nd.NODE_TYPE.GLUE,
            nd.NODE_TYPE.KERN,
            nd.NODE_TYPE.PENALTY,
            nd.NODE_TYPE.MATH,
        }
        return any(getattr(node, "node_type", None) in inline_types for node in items)

    def _walk_vlist(self, box, v=0):
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        v = int(v)
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                amount = self._effective_glue_amount(node, box, glue_state)
                yield ("glue", node, Dimen(integer=amount))
                v += amount
                continue
            if node_type == nd.NODE_TYPE.KERN:
                amount = int(node.kern)
                yield ("kern", node, Dimen(integer=amount))
                v += amount
                continue
            if node_type == nd.NODE_TYPE.PENALTY:
                yield ("penalty", node)
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                shifted = int(getattr(node, "shifted", 0))
                baseline = v + int(getattr(node, "height", 0))
                yield from self._walk_hlist(node, baseline)
                v += int(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue
            if node_type == nd.NODE_TYPE.VLIST:
                yield from self._walk_vlist(node, v)
                v += int(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue

    def _page_flow_specs(self, page, glyphs):
        current = None
        pending_gap = Dimen()
        line_map = self._glyphs_by_baseline(glyphs)
        paragraph_math_state = None
        for event in self._walk_vlist(page, 0):
            kind = event[0]
            if kind == "line":
                line = event[1]
                if current is None or line.owner is not current.owner:
                    if current is not None:
                        self._flush_pending_inline_math(current, paragraph_math_state)
                        yield current
                    first_line_indent = self._paragraph_first_indent(line.owner)
                    if self._line_starts_with_indent_box(line.box, first_line_indent):
                        first_line_indent = Dimen()
                    current = _ParagraphSpec(
                        owner=line.owner,
                        space_before=self._nonnegative_dimen(pending_gap),
                        first_line_indent=first_line_indent,
                    )
                    paragraph_math_state = _InlineMathState()
                else:
                    current.interline_gaps.append(self._nonnegative_dimen(pending_gap))
                line_runs = self._runs_from_line_box(line.box, paragraph_math_state)
                if not line_runs:
                    line_runs = self._runs_from_glyphs(line_map.get(line.baseline, ()))
                if not line_runs:
                    continue
                line_segments = self._segment_mixed_line_runs(line_runs)
                current.lines.append(
                    _LineSpec(
                        runs=line_runs,
                        box=line.box,
                        segments=line_segments,
                    )
                )
                pending_gap = Dimen()
                continue
            if kind == "display":
                if current is not None:
                    self._flush_pending_inline_math(current, paragraph_math_state)
                    yield current
                    current = None
                    paragraph_math_state = None
                yield _DisplayMathSpec(
                    owner=event[1],
                    box=event[2],
                    page=page,
                    space_before=self._nonnegative_dimen(pending_gap),
                )
                pending_gap = Dimen()
                continue
            if kind == "penalty":
                continue
            if kind in ("glue", "kern"):
                node = event[1]
                amount = event[2]
                if current is not None and kind == "glue" and getattr(node, "name", None) == "parskip":
                    self._flush_pending_inline_math(current, paragraph_math_state)
                    yield current
                    current = None
                    paragraph_math_state = None
                pending_gap += amount
                continue
            if current is not None:
                self._flush_pending_inline_math(current, paragraph_math_state)
                yield current
                current = None
                paragraph_math_state = None
                pending_gap = Dimen()
        if current is not None:
            self._flush_pending_inline_math(current, paragraph_math_state)
            yield current

    @staticmethod
    def _xml_space_attr(text):
        return ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""

    @staticmethod
    def _printable_char(char):
        return isinstance(char, str) and len(char) == 1 and char.isprintable() and ord(char) >= 0x20

    def _math_symbol_text(self, symbol):
        if symbol is None:
            return None
        code = ord(symbol.char)
        override = _MATH_FAMILY_TEXT_OVERRIDES.get(symbol.fam, {}).get(code)
        if override is not None:
            return override
        if symbol.fam == 0:
            text = html_math._MATH_OPERATORS_MAP.get(code)
            if text is not None:
                return text
        elif symbol.fam == 1:
            text = html_math._MATH_LETTERS_MAP.get(code)
            if text is not None:
                return text
        elif symbol.fam == 2:
            text = html_math._MATH_SYMBOLS_MAP.get(code)
            if text is not None:
                return text
        elif symbol.fam == 3:
            text = html_math._MATH_LARGE_SYMBOLS_MAP.get(code)
            if text is not None:
                return text
            text = html_math._MATH_SYMBOLS_MAP.get(code)
            if text is not None:
                return text
        if self._printable_char(symbol.char):
            return symbol.char
        return None

    def _math_run_xml(self, text, normal=False):
        if not text:
            return ""
        rpr = "<m:rPr><m:nor/></m:rPr>" if normal else ""
        return f"<m:r>{rpr}<m:t{self._xml_space_attr(text)}>{escape(text)}</m:t></m:r>"

    def _flatten_math_text(self, field):
        if field is None:
            return ""
        if isinstance(field, str):
            return field
        if isinstance(field, mmode.MathSymbol):
            return self._math_symbol_text(field) or ""
        if isinstance(field, (mmode.MathListHolder, mmode.Subformula, mmode.InlineMathNode, mmode.DisplayMathNode)):
            return "".join(self._flatten_math_text(item) for item in getattr(field, "list", ()))
        if isinstance(field, mmode.Over):
            num, den, _bar, _thickness = field.nucleus
            return (
                self._flatten_math_text(num)
                + "/"
                + self._flatten_math_text(den)
            )
        if isinstance(field, mmode.Rad):
            return self._flatten_math_text(field.oprand)
        if isinstance(field, mmode.Accent):
            return self._flatten_math_text(field.base)
        if isinstance(field, mmode.Atom):
            boundary = field._boundaryInfo() if hasattr(field, "_boundaryInfo") else None
            if boundary is not None:
                left_delim, right_delim, body_items = boundary
                return (
                    self._delimiter_text(left_delim)
                    + "".join(self._flatten_math_text(item) for item in body_items)
                    + self._delimiter_text(right_delim)
                )
            return self._flatten_math_text(getattr(field, "nucleus", None))
        if isinstance(field, mmode.Box):
            return self._flatten_box_text(getattr(field, "nucleus", None))
        return ""

    def _omml_group_xml(self, fields, normal=False, display_style=False):
        return "".join(
            self._omml_field_xml(field, normal=normal, display_style=display_style)
            for field in fields
            if field is not None
        )

    def _omml_script_xml(self, atom, base_xml, display_style=False):
        sub = getattr(atom, "sub", None)
        sup = getattr(atom, "sup", None)
        if sub is None and sup is None:
            return base_xml
        base = base_xml or self._math_run_xml("")
        if sub is not None and sup is not None:
            return (
                "<m:sSubSup>"
                f"<m:e>{base}</m:e>"
                f"<m:sub>{self._omml_field_xml(sub, display_style=display_style)}</m:sub>"
                f"<m:sup>{self._omml_field_xml(sup, display_style=display_style)}</m:sup>"
                "</m:sSubSup>"
            )
        if sub is not None:
            return (
                "<m:sSub>"
                f"<m:e>{base}</m:e>"
                f"<m:sub>{self._omml_field_xml(sub, display_style=display_style)}</m:sub>"
                "</m:sSub>"
            )
        return (
            "<m:sSup>"
            f"<m:e>{base}</m:e>"
            f"<m:sup>{self._omml_field_xml(sup, display_style=display_style)}</m:sup>"
            "</m:sSup>"
        )

    def _delimiter_text(self, delim):
        if delim is None:
            return ""
        symbol = getattr(delim, "small", None) or getattr(delim, "large", None)
        if symbol is None:
            return ""
        text = self._math_symbol_text(symbol)
        return "" if text is None else text

    def _omml_op_xml(self, atom):
        symbol = getattr(atom, "nucleus", None)
        if not isinstance(symbol, mmode.MathSymbol):
            return None
        op_text = self._math_symbol_text(symbol)
        if not op_text:
            return None
        op_text_attr = escape(op_text, {'"': "&quot;"})
        style = getattr(atom, "typeset_style", None)
        if style is None or style.style != mmode.MATH_STYLE.D:
            return None
        use_limits = atom._rule13UseLimits(style)
        pieces = [
            "<m:nary>",
            "<m:naryPr>",
            f"<m:chr m:val=\"{op_text_attr}\"/>",
            f"<m:limLoc m:val=\"{'undOvr' if use_limits else 'subSup'}\"/>",
            "<m:grow m:val=\"1\"/>",
            "</m:naryPr>",
        ]
        sub = getattr(atom, "sub", None)
        sup = getattr(atom, "sup", None)
        if sub is not None:
            pieces.append(f"<m:sub>{self._omml_field_xml(sub)}</m:sub>")
        if sup is not None:
            pieces.append(f"<m:sup>{self._omml_field_xml(sup)}</m:sup>")
        pieces.append("<m:e><m:r><m:t xml:space=\"preserve\">&#160;</m:t></m:r></m:e>")
        pieces.append("</m:nary>")
        return "".join(pieces)

    def _omml_atom_xml(self, atom, display_style=False):
        if isinstance(atom, mmode.Op):
            nary_xml = self._omml_op_xml(atom)
            if nary_xml:
                return nary_xml
        operator_text = isinstance(atom, mmode.Op) and not isinstance(getattr(atom, "nucleus", None), mmode.MathSymbol)
        boundary = atom._boundaryInfo() if hasattr(atom, "_boundaryInfo") else None
        if boundary is not None:
            left_delim, right_delim, body_items = boundary
            base_xml = (
                self._math_run_xml(self._delimiter_text(left_delim), normal=operator_text)
                + self._omml_group_xml(body_items, normal=operator_text, display_style=display_style)
                + self._math_run_xml(self._delimiter_text(right_delim), normal=operator_text)
            )
        else:
            base_xml = self._omml_field_xml(
                getattr(atom, "nucleus", None),
                normal=operator_text,
                display_style=display_style,
            )
        if getattr(atom, "left", None) is not None:
            base_xml = self._math_run_xml(self._delimiter_text(atom.left), normal=operator_text) + base_xml
        if getattr(atom, "right", None) is not None:
            base_xml += self._math_run_xml(self._delimiter_text(atom.right), normal=operator_text)
        return self._omml_script_xml(atom, base_xml, display_style=display_style)

    def _omml_field_xml(self, field, normal=False, display_style=False):
        if field is None or isinstance(field, mmode.StyleNode):
            return ""
        if isinstance(field, str):
            return self._math_run_xml(field, normal=normal)
        node_type = getattr(field, "node_type", None)
        if node_type in (
            nd.NODE_TYPE.WHATSIT,
            nd.NODE_TYPE.PENALTY,
        ):
            return ""
        if node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
            return ""
        if isinstance(field, mmode.MathSymbol):
            return self._math_run_xml(self._math_symbol_text(field), normal=normal)
        if isinstance(field, (mmode.MathListHolder, mmode.Subformula, mmode.InlineMathNode, mmode.DisplayMathNode)):
            return self._omml_group_xml(getattr(field, "list", ()), normal=normal, display_style=display_style)
        if isinstance(field, mmode.Over):
            num, den, _bar, _thickness = field.nucleus
            frac_xml = (
                "<m:f>"
                f"<m:num>{self._omml_group_xml(getattr(num, 'list', ()), display_style=display_style)}</m:num>"
                f"<m:den>{self._omml_group_xml(getattr(den, 'list', ()), display_style=display_style)}</m:den>"
                "</m:f>"
            )
            if getattr(field, "delims", None) is not None:
                left_delim, right_delim = field.delims
                frac_xml = (
                    self._math_run_xml(self._delimiter_text(left_delim), normal=normal)
                    + frac_xml
                    + self._math_run_xml(self._delimiter_text(right_delim), normal=normal)
                )
            return self._omml_script_xml(field, frac_xml, display_style=display_style)
        if isinstance(field, mmode.Rad):
            base_xml = (
                "<m:rad>"
                "<m:radPr><m:degHide m:val=\"1\"/></m:radPr>"
                f"<m:e>{self._omml_field_xml(field.oprand, display_style=display_style)}</m:e>"
                "</m:rad>"
            )
            return self._omml_script_xml(field, base_xml, display_style=display_style)
        if isinstance(field, mmode.Accent):
            accent = getattr(field, "accent", None)
            base_xml = self._omml_field_xml(field.base, display_style=display_style)
            if not base_xml:
                return ""
            if accent is not None:
                accent_char = escape(accent.char, {'"': "&quot;"})
                base_xml = (
                    "<m:acc>"
                    f"<m:accPr><m:chr m:val=\"{accent_char}\"/></m:accPr>"
                    f"<m:e>{base_xml}</m:e>"
                    "</m:acc>"
                )
            return self._omml_script_xml(field, base_xml, display_style=display_style)
        if isinstance(field, mmode.Atom):
            return self._omml_atom_xml(field, display_style=display_style)
        if isinstance(field, mmode.Box):
            return self._math_run_xml(self._flatten_box_text(getattr(field, "nucleus", None)), normal=normal)
        return ""

    def _flatten_box_text(self, box):
        if box is None:
            return ""
        parts = []
        for node in getattr(box, "list", ()) or ():
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                parts.append(self._glyph_text(node))
                continue
            if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                parts.append(self._flatten_box_text(node))
        return "".join(parts)

    def _display_math_content_xml(self, fields, box, line_depth=None, total_height=None):
        effective_depth = Dimen(getattr(box, "depth", 0))
        if line_depth is not None and line_depth > effective_depth:
            effective_depth = Dimen(line_depth)
        ppr = "<w:pPr><w:spacing w:before=\"0\" w:after=\"0\"/></w:pPr>"
        inner = self._omml_group_xml(fields)
        prefix = ""
        first_field = next((field for field in fields if field is not None), None)
        if (
            isinstance(first_field, mmode.Op)
            and isinstance(getattr(first_field, "nucleus", None), mmode.MathSymbol)
            and getattr(getattr(first_field, "typeset_style", None), "style", None) == mmode.MATH_STYLE.D
        ):
            prefix = (
                "<w:r>"
                "<w:rPr><w:noProof/><w:vanish/></w:rPr>"
                "<w:t xml:space=\"preserve\"> </w:t>"
                "</w:r>"
            )
        if inner:
            body = f"<w:p>{ppr}{prefix}<m:oMathPara><m:oMath>{inner}</m:oMath></m:oMathPara></w:p>"
            return f"<w:txbxContent>{body}</w:txbxContent>"
        text = self._flatten_box_text(box)
        if not text:
            return "<w:txbxContent><w:p/></w:txbxContent>"
        body = (
            f"<w:p>{ppr}<w:r><w:rPr><w:noProof/></w:rPr>"
            f"<w:t{self._xml_space_attr(text)}>{escape(text)}</w:t>"
            "</w:r></w:p>"
        )
        return f"<w:txbxContent>{body}</w:txbxContent>"

    def _display_math_run_xml(self, fields, box, line_depth=None, total_height=None):
        width = max(self._pt(getattr(box, "width", 0)), 1.0)
        effective_depth = Dimen(getattr(box, "depth", 0))
        if line_depth is not None and line_depth > effective_depth:
            effective_depth = Dimen(line_depth)
        total_height = Dimen(total_height) if total_height is not None else Dimen(getattr(box, "height", 0)) + effective_depth
        height = max(self._pt(total_height), 1.0)
        position = -int(round(self._pt(effective_depth) * 2.0)) if effective_depth else None
        content = self._display_math_content_xml(fields, box, line_depth=effective_depth, total_height=total_height)
        return parse_xml(
            (
                "<w:r "
                "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
                "xmlns:v=\"urn:schemas-microsoft-com:vml\" "
                "xmlns:o=\"urn:schemas-microsoft-com:office:office\" "
                "xmlns:w10=\"urn:schemas-microsoft-com:office:word\" "
                "xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\">"
                f"{self._raw_run_properties_xml(no_proof=True, position_half_points=position)}"
                f"{self._vml_textbox_xml(content, width, height, anchor='top')}"
                "</w:r>"
            )
        )

    def _display_spacer_run_xml(self, width):
        width = max(self._pt(width), 0.0)
        if width <= 0:
            return None
        return parse_xml(
            (
                "<w:r "
                "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
                "xmlns:v=\"urn:schemas-microsoft-com:vml\" "
                "xmlns:o=\"urn:schemas-microsoft-com:office:office\" "
                "xmlns:w10=\"urn:schemas-microsoft-com:office:word\">"
                "<w:rPr><w:noProof/></w:rPr>"
                "<w:pict>"
                f"<v:rect stroked=\"f\" filled=\"f\" o:allowincell=\"f\" style=\"width:{width:.4f}pt;height:1.0000pt\">"
                f"<v:textbox inset=\"0,0,0,0\" style=\"{self._textbox_style()}\"><w:txbxContent><w:p/></w:txbxContent></v:textbox>"
                "<w10:wrap type=\"none\"/>"
                "</v:rect>"
                "</w:pict>"
                "</w:r>"
            )
        )

    @staticmethod
    def _display_item_width(node):
        node_type = getattr(node, "node_type", None)
        if node_type == nd.NODE_TYPE.KERN:
            return Dimen(getattr(node, "kern", 0))
        if node_type == nd.NODE_TYPE.GLUE:
            return Dimen(getattr(getattr(node, "glue", None), "dimen", 0))
        width = getattr(node, "width", None)
        if width is not None:
            return Dimen(width)
        return Dimen()

    def _display_math_segments(self, spec):
        segments = []
        shifted = self._nonnegative_dimen(getattr(spec.box, "shifted", Dimen()))
        if shifted != 0:
            segments.append(("spacer", shifted, None, None))
        items = list(getattr(spec.box, "list", ()) or ())
        box_items = [
            (index, item)
            for index, item in enumerate(items)
            if getattr(item, "node_type", None) in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST)
        ]
        if not box_items:
            segments.append(("math", Dimen(getattr(spec.box, "width", 0)), getattr(spec.owner, "list", ()), spec.box))
            return segments
        if getattr(spec.owner, "eqno", None) is None or len(box_items) < 2:
            formula_box = box_items[0][1]
            if self._display_item_width(formula_box) <= 0:
                formula_box = spec.box
            segments.append(("math", Dimen(getattr(formula_box, "width", 0)), getattr(spec.owner, "list", ()), formula_box))
            return segments
        eqno_holder, left = spec.owner.eqno
        first_index, first_box = box_items[0]
        last_index, last_box = box_items[-1]
        gap = Dimen()
        for item in items[first_index + 1:last_index]:
            gap += self._display_item_width(item)
        if left:
            segments.append(("eqno", Dimen(getattr(first_box, "width", 0)), getattr(eqno_holder, "list", ()), first_box))
            if gap != 0:
                segments.append(("spacer", gap, None, None))
            segments.append(("math", Dimen(getattr(last_box, "width", 0)), getattr(spec.owner, "list", ()), last_box))
            return segments
        segments.append(("math", Dimen(getattr(first_box, "width", 0)), getattr(spec.owner, "list", ()), first_box))
        segments.append(("tab", Dimen(getattr(spec.box, "width", 0)) + shifted, None, None))
        segments.append(("eqno", Dimen(getattr(last_box, "width", 0)), getattr(eqno_holder, "list", ()), last_box))
        return segments

    @staticmethod
    def _display_tab_run_xml():
        return parse_xml(
            (
                "<w:r xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                "<w:tab/>"
                "</w:r>"
            )
        )

    @staticmethod
    def _line_break_run_xml():
        return parse_xml(
            (
                "<w:r xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                "<w:br/>"
                "</w:r>"
            )
        )

    def _runs_from_line_box(self, box, math_state=None):
        if not self._can_use_box_runs(box):
            return []
        runs = self._runs_from_box(box, math_state)
        if math_state is not None and math_state.has_nodes():
            runs.extend(self._finalize_inline_math_state(math_state, keep_open=True, line_box=box))
        return self._normalize_runs(runs)

    def _runs_from_box(self, box, math_state=None):
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        runs = []
        if math_state is None:
            math_state = _InlineMathState()
        index = 0
        while index < len(items):
            node = items[index]
            node_type = getattr(node, "node_type", None)
            if math_state.in_math:
                if node_type == nd.NODE_TYPE.MATH and not node.on:
                    math_state.in_math = False
                    runs.extend(self._finalize_inline_math_state(math_state, node.kern, line_box=box))
                    index += 1
                    continue
                math_state.nodes.append(node)
                math_state.line_depth = max(math_state.line_depth, Dimen(getattr(box, "depth", 0)))
                index += 1
                continue
            if node_type == nd.NODE_TYPE.MATH:
                if node.on:
                    math_state.in_math = True
                    math_state.leading_kern = Dimen(getattr(node, "kern", 0))
                    math_state.line_depth = Dimen(getattr(box, "depth", 0))
                    if math_state.spacing_font is None:
                        math_state.spacing_font = self._space_font(runs, items, index)
                elif node.kern != 0:
                    self._append_explicit_spacing_run(runs, node.kern, self._space_font(runs, items, index))
                index += 1
                continue
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                text = self._glyph_text(node)
                if text:
                    runs.append(_TextRun(text, getattr(node, "font", None)))
                index += 1
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                child_runs = self._runs_from_box(node)
                if child_runs:
                    runs.append(
                        _InlineBoxRun(
                            node,
                            self._normalize_runs(child_runs),
                            Dimen(getattr(box, "depth", 0)),
                        )
                    )
                    index += 1
                    continue
                width = Dimen(getattr(node, "width", 0))
                if width > 0:
                    self._append_box_spacing_run(runs, width, items, index)
                index += 1
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                if not self._glue_is_text_space(items, index):
                    index += 1
                    continue
                amount = self._effective_glue_amount(node, box, glue_state)
                if amount <= 0:
                    index += 1
                    continue
                font = self._space_font(runs, items, index)
                nominal_width = self._space_width(font)
                delta = amount - nominal_width
                runs.append(_TextRun(" ", font, spacing_twips=self._spacing_twips(delta)))
                index += 1
                continue
            if node_type == nd.NODE_TYPE.KERN:
                if not self._kern_is_text_kern(items, index):
                    index += 1
                    continue
                self._apply_text_kern(runs, node.kern)
                index += 1
                continue
            if node_type == nd.NODE_TYPE.DISC:
                runs.extend(self._runs_from_box(node))
                index += 1
                continue
            index += 1
        return runs

    def _append_box_spacing_run(self, runs, width, items, index):
        font = self._space_font(runs, items, index)
        nominal_width = self._space_width(font)
        delta = int(width) - nominal_width
        runs.append(_TextRun(" ", font, spacing_twips=self._spacing_twips(delta)))

    def _append_explicit_spacing_run(self, runs, width, font):
        width = Dimen(width)
        if width <= 0:
            return
        nominal_width = self._space_width(font)
        delta = int(width) - nominal_width
        runs.append(_TextRun(" ", font, spacing_twips=self._spacing_twips(delta)))

    @classmethod
    def _can_use_box_runs(cls, box):
        items = getattr(box, "list", None) or ()
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                if cls._math_source_field(node) is not None:
                    continue
                if node_type == nd.NODE_TYPE.HLIST and cls._can_use_box_runs(node):
                    continue
                return False
        return True

    def _glue_is_text_space(self, items, index):
        return self._has_text_before(items, index) and self._has_text_after(items, index)

    @staticmethod
    def _node_has_inline_text(node):
        node_type = getattr(node, "node_type", None)
        if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.DISC):
            return True
        if node_type != nd.NODE_TYPE.HLIST:
            return False
        for child in getattr(node, "list", None) or ():
            if DocxBackend._node_has_inline_text(child):
                return True
        return False

    @staticmethod
    def _kern_is_text_kern(items, index):
        if index <= 0 or index + 1 >= len(items):
            return False
        prev = items[index - 1]
        nxt = items[index + 1]
        return DocxBackend._node_has_inline_text(prev) and DocxBackend._node_has_inline_text(nxt)

    @staticmethod
    def _apply_text_kern(runs, amount):
        if amount == 0:
            return
        spacing = DocxBackend._spacing_twips(amount)
        if spacing == 0:
            return
        for run in reversed(runs):
            if isinstance(run, _InlineBoxRun):
                return
            if run.text and not run.text.isspace():
                run.spacing_twips += spacing
                return

    @classmethod
    def _has_text_before(cls, items, index):
        for node in reversed(items[:index]):
            if cls._node_has_inline_text(node):
                return True
        return False

    @classmethod
    def _has_text_after(cls, items, index):
        for node in items[index + 1:]:
            if cls._node_has_inline_text(node):
                return True
        return False

    def _space_font(self, runs, items, index):
        for run in reversed(runs):
            if isinstance(run, _InlineBoxRun):
                font = self._first_font(run.box)
                if font is not None:
                    return font
                continue
            if isinstance(run, _InlineMathRun):
                font = self._first_font(run.box)
                if font is not None:
                    return font
                continue
            if run.font is not None and not run.text.isspace():
                return run.font
        for node in items[index + 1:]:
            font = self._first_font(node)
            if font is not None:
                return font
        return None

    @classmethod
    def _first_font(cls, node):
        font = getattr(node, "font", None)
        if font is not None:
            return font
        for child in getattr(node, "list", None) or ():
            font = cls._first_font(child)
            if font is not None:
                return font
        return None

    @staticmethod
    def _math_source_field(node):
        source = getattr(node, "source", None)
        seen = set()
        while source is not None and not isinstance(source, (list, tuple)):
            key = id(source)
            if key in seen:
                break
            seen.add(key)
            if DocxBackend._is_math_field(source):
                return source
            source = getattr(source, "source", None)
        return None

    def _fragment_math_fields(self, nodes, box=None):
        fields = []
        seen = set()
        for node in nodes:
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.PENALTY, nd.NODE_TYPE.WHATSIT):
                continue
            if node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
                continue
            field = self._math_source_field(node)
            if field is not None and not isinstance(field, mmode.InlineMathNode):
                key = id(field)
                if key not in seen:
                    seen.add(key)
                    fields.append(field)
                continue
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                text = self._glyph_text(node)
                if text:
                    fields.append(text)
                continue
            children = getattr(node, "list", None) or ()
            if children:
                for child in self._fragment_math_fields(children, box=node):
                    if not isinstance(child, str):
                        key = id(child)
                        if key in seen:
                            continue
                        seen.add(key)
                    fields.append(child)
        return fields

    def _inline_math_box(self, nodes, line_box=None):
        hbox = bx.HBox(self.parser, None, None)
        hbox.list[:] = list(nodes)
        width = Dimen()
        height = Dimen()
        depth = Dimen()
        source_box = line_box if line_box is not None else hbox
        glue_state = self._glue_state(source_box)
        for node in nodes:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                width += Dimen(integer=self._effective_glue_amount(node, source_box, glue_state))
                continue
            if node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                width += Dimen(getattr(node, "kern", 0))
                continue
            if node_type == nd.NODE_TYPE.DISC:
                width += Dimen(getattr(node, "replace_width", 0))
                for child in getattr(node, "replace", ()) or ():
                    child_height = getattr(child, "height", None)
                    child_depth = getattr(child, "depth", None)
                    if child_height is not None:
                        height = max(height, Dimen(child_height))
                    if child_depth is not None:
                        depth = max(depth, Dimen(child_depth))
                continue
            node_width = getattr(node, "width", None)
            if node_width is None:
                continue
            shifted = Dimen(getattr(node, "shifted", 0))
            width += Dimen(node_width)
            height = max(height, Dimen(getattr(node, "height", 0)) - shifted)
            depth = max(depth, Dimen(getattr(node, "depth", 0)) + shifted)
        hbox.width = width
        hbox.height = height
        hbox.depth = depth
        hbox._packed = hbox
        return hbox

    def _finalize_inline_math_state(self, state, trailing_kern=Dimen(), keep_open=False, line_box=None):
        if not state.active():
            return []
        nodes = list(state.nodes)
        line_depth = Dimen(state.line_depth)
        leading_kern = Dimen(state.leading_kern)
        spacing_font = state.spacing_font
        state.nodes.clear()
        state.leading_kern = Dimen()
        state.line_depth = Dimen()
        if not keep_open:
            state.in_math = False
            state.spacing_font = None
        if not nodes:
            runs = []
            self._append_explicit_spacing_run(runs, leading_kern, spacing_font)
            self._append_explicit_spacing_run(runs, trailing_kern, spacing_font)
            return runs
        box = self._inline_math_box(nodes, line_box=line_box)
        font = spacing_font or self._first_font(box)
        fields = self._fragment_math_fields(nodes, box)
        runs = []
        self._append_explicit_spacing_run(runs, leading_kern, font)
        runs.append(
            _InlineMathRun(
                box=box,
                fields=fields,
                line_depth=line_depth,
            )
        )
        self._append_explicit_spacing_run(runs, trailing_kern, font)
        return runs

    def _flush_pending_inline_math(self, spec, math_state):
        if spec is None or not spec.lines or math_state is None:
            return
        if math_state.has_nodes():
            spec.lines[-1].runs.extend(self._finalize_inline_math_state(math_state, line_box=spec.lines[-1].box))
        math_state.clear()

    def _chunk_text(self, chunk):
        if isinstance(chunk, _TextRun):
            return chunk.text
        if isinstance(chunk, _InlineBoxRun):
            return self._flatten_box_text(chunk.box)
        return ""

    def _inline_box_text(self, box_run):
        text = "".join(self._chunk_text(chunk) for chunk in box_run.chunks)
        return text or self._flatten_box_text(box_run.box)

    @staticmethod
    def _font_line_measure(font):
        at = getattr(font, "at", None)
        return Dimen(at) if at is not None else Dimen()

    def _inline_chunk_line_measure(self, chunk):
        if isinstance(chunk, _TextRun):
            return self._font_line_measure(chunk.font)
        if isinstance(chunk, (_InlineBoxRun, _InlineMathRun)):
            return Dimen(getattr(chunk.box, "height", 0) + getattr(chunk.box, "depth", 0))
        return Dimen()

    def _inline_box_line_measure(self, box_run):
        required = Dimen(getattr(box_run.box, "height", 0) + getattr(box_run.box, "depth", 0))
        for chunk in box_run.chunks:
            required = max(required, self._inline_chunk_line_measure(chunk))
        return required

    def _raw_run_properties_xml(
        self,
        font=None,
        spacing_twips=0,
        allow_word_kerning=False,
        no_proof=False,
        position_half_points=None,
    ):
        parts = []
        if no_proof:
            parts.append("<w:noProof/>")
        name = self._font_name(font)
        if name:
            escaped_name = escape(name, {'"': "&quot;"})
            parts.append(f"<w:rFonts w:ascii=\"{escaped_name}\" w:hAnsi=\"{escaped_name}\"/>")
        if font is not None:
            bold, italic = self._docx_font_style(font)
            if bold:
                parts.append("<w:b/>")
            if italic:
                parts.append("<w:i/>")
        at = getattr(font, "at", None)
        if at is not None:
            half_points = self._font_half_points(at)
            if half_points > 0:
                parts.append(f"<w:sz w:val=\"{half_points}\"/>")
                if allow_word_kerning:
                    parts.append(f"<w:kern w:val=\"{half_points}\"/>")
        if spacing_twips:
            parts.append(f"<w:spacing w:val=\"{int(spacing_twips)}\"/>")
        if position_half_points:
            parts.append(f"<w:position w:val=\"{int(position_half_points)}\"/>")
        if not parts:
            return ""
        return f"<w:rPr>{''.join(parts)}</w:rPr>"

    def _inline_box_content_xml(self, box_run):
        text = self._inline_box_text(box_run)
        if not text:
            return "<w:txbxContent><w:p/></w:txbxContent>"
        font = self._first_font(box_run.box)
        line_height = self._inline_box_line_measure(box_run)
        line_twips = self._fit_text_twips(line_height)
        depth_half_points = int(round(self._pt(getattr(box_run.box, "depth", 0)) * 2.0))
        text = "\u00A0" * len(text) if text.isspace() else text
        run = (
            "<w:r>"
            f"{self._raw_run_properties_xml(font=font, no_proof=True, position_half_points=depth_half_points)}"
            f"<w:t{self._xml_space_attr(text)}>{escape(text)}</w:t>"
            "</w:r>"
        )
        ppr = (
            "<w:pPr>"
            f"<w:spacing w:before=\"0\" w:after=\"0\" w:lineRule=\"exact\" w:line=\"{line_twips}\"/>"
            "<w:textAlignment w:val=\"baseline\"/>"
            "</w:pPr>"
        )
        return f"<w:txbxContent><w:p>{ppr}{run}</w:p></w:txbxContent>"

    def _inline_textbox_run_xml(self, content, box, line_depth=None, anchor="bottom"):
        width = max(self._pt(getattr(box, "width", 0)), 1.0)
        depth = Dimen(getattr(box, "depth", 0))
        extra_pad = Dimen(_INLINE_TEXTBOX_PAD_PT) if depth > 0 else Dimen()
        total_height = max(
            self._pt(getattr(box, "height", 0) + depth + extra_pad),
            1.0,
        )
        own_depth = self._pt(depth)
        position = -int(round(own_depth * 2.0)) if own_depth else None
        return parse_xml(
            (
                "<w:r "
                "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
                "xmlns:v=\"urn:schemas-microsoft-com:vml\" "
                "xmlns:o=\"urn:schemas-microsoft-com:office:office\" "
                "xmlns:w10=\"urn:schemas-microsoft-com:office:word\" "
                "xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\">"
                f"{self._raw_run_properties_xml(no_proof=True, position_half_points=position)}"
                f"{self._vml_textbox_xml(content, width, total_height, anchor=anchor)}"
                "</w:r>"
            )
        )

    def _inline_box_run_xml(self, box_run):
        line_measure = self._inline_box_line_measure(box_run)
        original_height = Dimen(getattr(box_run.box, "height", 0))
        original_depth = Dimen(getattr(box_run.box, "depth", 0))
        tex_total = original_height + original_depth
        adjusted_box = box_run.box
        if line_measure > tex_total:
            adjusted_box = bx.HBox(self.parser, None, None)
            adjusted_box.list[:] = list(getattr(box_run.box, "list", ()) or ())
            adjusted_box.width = Dimen(getattr(box_run.box, "width", 0))
            adjusted_box.height = original_height
            adjusted_box.depth = max(original_depth, line_measure - original_height)
            adjusted_box.source = getattr(box_run.box, "source", None)
            adjusted_box._packed = adjusted_box
        return self._inline_textbox_run_xml(
            self._inline_box_content_xml(box_run),
            adjusted_box,
            line_depth=getattr(box_run, "line_depth", 0),
            anchor="top",
        )

    def _inline_math_content_xml(self, math_run):
        box = math_run.box
        inner = self._omml_group_xml(math_run.fields)
        line_height = Dimen(getattr(box, "height", 0) + getattr(box, "depth", 0))
        line_twips = self._fit_text_twips(line_height)
        ppr = (
            "<w:pPr>"
            f"<w:spacing w:before=\"0\" w:after=\"0\" w:lineRule=\"exact\" w:line=\"{line_twips}\"/>"
            "</w:pPr>"
        )
        if inner:
            return f"<w:txbxContent><w:p>{ppr}<m:oMath>{inner}</m:oMath></w:p></w:txbxContent>"
        text = self._flatten_box_text(box)
        if not text:
            return "<w:txbxContent><w:p/></w:txbxContent>"
        run = (
            "<w:r>"
            f"{self._raw_run_properties_xml(font=self._first_font(box), no_proof=True)}"
            f"<w:t{self._xml_space_attr(text)}>{escape(text)}</w:t>"
            "</w:r>"
        )
        return f"<w:txbxContent><w:p>{ppr}{run}</w:p></w:txbxContent>"

    def _inline_math_run_xml(self, math_run):
        return self._inline_textbox_run_xml(
            self._inline_math_content_xml(math_run),
            math_run.box,
            line_depth=getattr(math_run, "line_depth", 0),
            anchor="bottom",
        )

    def _emit_paragraph(self, document, spec):
        para = document.add_paragraph()
        fmt = para.paragraph_format
        fmt.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        fmt.space_before = self._length(self._nonnegative_dimen(spec.space_before))
        fmt.space_after = Pt(0)
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        baseline = self.parser.layout["baselineskip"].dimen
        if baseline > 0:
            fmt.line_spacing = self._length(self._nonnegative_dimen(baseline))
        elif spec.interline_gaps:
            fmt.line_spacing = self._length(self._nonnegative_dimen(spec.interline_gaps[0]))
        if spec.first_line_indent != 0:
            fmt.first_line_indent = self._length(self._nonnegative_dimen(spec.first_line_indent))
        for line_index, line_spec in enumerate(spec.lines):
            if line_spec.segments:
                for segment in line_spec.segments:
                    for chunk in segment.runs:
                        if isinstance(chunk, _InlineBoxRun):
                            para._p.append(self._inline_box_run_xml(chunk))
                            continue
                        if isinstance(chunk, _InlineMathRun):
                            para._p.append(self._inline_math_run_xml(chunk))
                            continue
                        text = chunk.text
                        run = para.add_run(text)
                        self._apply_run_font_with_options(
                            run,
                            chunk.font,
                            allow_word_kerning=False,
                        )
                        self._apply_run_spacing(run, chunk.spacing_twips)
                if line_index + 1 < len(spec.lines):
                    para._p.append(self._line_break_run_xml())
                continue
            for chunk in line_spec.runs:
                if isinstance(chunk, _InlineBoxRun):
                    para._p.append(self._inline_box_run_xml(chunk))
                    continue
                if isinstance(chunk, _InlineMathRun):
                    para._p.append(self._inline_math_run_xml(chunk))
                    continue
                text = chunk.text
                run = para.add_run(text)
                self._apply_run_font_with_options(
                    run,
                    chunk.font,
                    allow_word_kerning=False,
                )
                self._apply_run_spacing(run, chunk.spacing_twips)
            if line_index + 1 < len(spec.lines):
                para._p.append(self._line_break_run_xml())
        return para

    def _emit_display_math(self, document, spec):
        para = document.add_paragraph()
        fmt = para.paragraph_format
        fmt.alignment = WD_ALIGN_PARAGRAPH.LEFT
        fmt.space_before = self._length(self._nonnegative_dimen(spec.space_before))
        fmt.space_after = Pt(0)
        line_depth = getattr(spec.box, "depth", 0)
        math_total_height = Dimen(getattr(spec.box, "height", 0)) + Dimen(getattr(spec.box, "depth", 0))
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.line_spacing = self._length(self._nonnegative_dimen(math_total_height))
        for kind, width, fields, box in self._display_math_segments(spec):
            if kind == "spacer":
                run_xml = self._display_spacer_run_xml(width)
            elif kind == "tab":
                fmt.tab_stops.add_tab_stop(self._length(width), alignment=WD_TAB_ALIGNMENT.RIGHT)
                run_xml = self._display_tab_run_xml()
            else:
                run_xml = self._display_math_run_xml(
                    fields,
                    box,
                    line_depth=line_depth,
                    total_height=math_total_height if kind == "math" else None,
                )
            if run_xml is not None:
                para._p.append(run_xml)
        return para

    def _build_document(self):
        document = Document()
        self._configure_math_settings(document)
        if not self.pages:
            return document
        if len(self.pages) > 1:
            raise NotImplementedError("DOCX proof-of-concept backend only supports a single shipped page")
        page = self.pages[0]
        glyphs = self._captured_pages[0] if self._captured_pages else []
        flow_specs = list(self._page_flow_specs(page, glyphs))
        if not glyphs and not flow_specs and any(getattr(node, "node_type", None) == nd.NODE_TYPE.HLIST for node in getattr(page, "list", ())):
            raise ValueError(
                "DOCX backend captured no text glyphs from the shipped page; "
                "the document may have been typeset with nullfont or contain only unsupported content"
            )
        self._configure_section(document, page)
        for spec in flow_specs:
            if isinstance(spec, _ParagraphSpec) and spec.lines:
                self._emit_paragraph(document, spec)
            elif isinstance(spec, _DisplayMathSpec):
                self._emit_display_math(document, spec)
        return document

    def close(self):
        if self.finished:
            return
        self.finished = True
        self.open()
        document = self._build_document()
        document.save(self.file)
        if hasattr(self.file, "close"):
            self.file.close()
        self.file = None


def init(parser):
    _install_docx_math_font_arrays(parser)
    parser.shipout = DocxBackend(parser)


mod = Module(
    "docx",
    init=init,
    attributes={},
)
