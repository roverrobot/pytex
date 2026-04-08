"""Minimal DOCX shipout backend for pure text paragraphs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Pt

from pytex import box as bx
from pytex import html_reflow as html_math
from pytex import mmode
from pytex import node as nd
from pytex import paragraph as pg
from pytex.dimen import Dimen
from pytex.module import Module
from pytex.typeset.shipout import Shipout

_ONE_INCH_PT = 72.0
_FIT_TEXT_SHORT_LINE_TOLERANCE_PT = 1.0
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


@dataclass
class _TextRun:
    text: str
    font: object | None
    spacing_twips: int = 0


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
    runs: list[_TextRun]
    box: object | None = None
    fit_text_twips: int | None = None


@dataclass
class _LineEvent:
    owner: object
    baseline: int
    box: object


@dataclass
class _DisplayMathSpec:
    owner: object
    box: object
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
        self._fit_text_id = 1

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
    def _pt(value):
        return float(value) if isinstance(value, Dimen) else float(Dimen(value))

    @classmethod
    def _length(cls, value):
        return Pt(cls._pt(value))

    @staticmethod
    def _nonnegative_dimen(value):
        value = value if isinstance(value, Dimen) else Dimen(value)
        return value if value >= 0 else Dimen()

    def _configure_section(self, document, page):
        section = document.sections[0]
        hsize = self.parser.layout["hsize"]
        vsize = self.parser.layout["vsize"]
        left_margin = Pt(_ONE_INCH_PT)
        right_margin = Pt(_ONE_INCH_PT)
        top_margin = Pt(_ONE_INCH_PT)
        bottom_margin = Pt(_ONE_INCH_PT)
        section.left_margin = left_margin
        section.right_margin = right_margin
        section.top_margin = top_margin
        section.bottom_margin = bottom_margin
        content_width = max(self._pt(hsize), 144.0)
        natural_height = self._pt(page.height + page.depth)
        content_height = max(self._pt(vsize), natural_height, 144.0)
        section.page_width = Pt(content_width + 2 * _ONE_INCH_PT)
        section.page_height = Pt(content_height + 2 * _ONE_INCH_PT)

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
    def _font_name(font):
        if font is None:
            return None
        backend = getattr(font, "backend", None)
        if backend is None:
            return None
        return getattr(backend, "name", None)

    def _apply_run_font(self, run, font):
        self._apply_run_font_with_options(run, font, allow_word_kerning=True)

    def _apply_run_font_with_options(self, run, font, allow_word_kerning=True):
        if font is None:
            return
        name = self._font_name(font)
        if name:
            run.font.name = name
        at = getattr(font, "at", None)
        if at is not None:
            run.font.size = self._length(at)
            if allow_word_kerning:
                self._apply_run_kerning(run, at)

    @classmethod
    def _apply_run_kerning(cls, run, size):
        half_points = int(round(cls._pt(size) * 2))
        if half_points <= 0:
            return
        rPr = run._r.get_or_add_rPr()
        kern = rPr.find(qn("w:kern"))
        if kern is None:
            kern = OxmlElement("w:kern")
            rPr.append(kern)
        kern.set(qn("w:val"), str(half_points))

    def _apply_run_fit_text(self, run, fit_text_twips, fit_text_id):
        if fit_text_twips is None or fit_text_twips <= 0:
            return
        rPr = run._r.get_or_add_rPr()
        fit_text = rPr.find(qn("w:fitText"))
        if fit_text is None:
            fit_text = OxmlElement("w:fitText")
            rPr.append(fit_text)
        fit_text.set(qn("w:id"), str(int(fit_text_id)))
        fit_text.set(qn("w:val"), str(int(fit_text_twips)))

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
            text = run.text
            if not text:
                continue
            if text.isspace() and merged and merged[-1].text.isspace():
                prev = merged[-1]
                prev.spacing_twips = self._collapsed_space_spacing(prev, run)
                prev.text = " "
                continue
            if merged and merged[-1].font is run.font and merged[-1].spacing_twips == run.spacing_twips:
                merged[-1].text += text
            else:
                merged.append(_TextRun(text, run.font, run.spacing_twips))
        return merged

    def _fit_text_runs(self, runs):
        merged = []
        for run in runs:
            text = run.text
            if not text:
                continue
            if (
                merged
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
        value = int(delta) if isinstance(delta, Dimen) else int(Dimen(delta))
        return Dimen._trunc_div(value * 20, Dimen.scale)

    @classmethod
    def _fit_text_twips(cls, width):
        value = int(width) if isinstance(width, Dimen) else int(Dimen(width))
        return max(0, Dimen._trunc_div(value * 20, Dimen.scale))

    @classmethod
    def _fit_text_for_line(cls, box, first_line_indent=Dimen(), is_first_line=False):
        width = Dimen(getattr(box, "width", 0))
        content_right = Dimen(width)
        if hasattr(box, "rightmost"):
            content_right = Dimen(box.rightmost())
        indent = Dimen(first_line_indent) if is_first_line else Dimen()
        target_width = width - indent
        content_width = content_right - indent
        if target_width <= 0 or content_width <= 0:
            return None
        tolerance = Dimen(_FIT_TEXT_SHORT_LINE_TOLERANCE_PT)
        if content_width < target_width - tolerance:
            return None
        return cls._fit_text_twips(target_width)

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
        for event in self._walk_vlist(page, 0):
            kind = event[0]
            if kind == "line":
                line = event[1]
                line_runs = self._runs_from_line_box(line.box)
                if not line_runs:
                    line_runs = self._runs_from_glyphs(line_map.get(line.baseline, ()))
                if not line_runs:
                    continue
                if current is None or line.owner is not current.owner:
                    if current is not None:
                        yield current
                    current = _ParagraphSpec(
                        owner=line.owner,
                        space_before=self._nonnegative_dimen(pending_gap),
                        first_line_indent=self._paragraph_first_indent(line.owner),
                    )
                else:
                    current.interline_gaps.append(self._nonnegative_dimen(pending_gap))
                current.lines.append(
                    _LineSpec(
                        runs=line_runs,
                        box=line.box,
                        fit_text_twips=self._fit_text_for_line(
                            line.box,
                            first_line_indent=current.first_line_indent,
                            is_first_line=not current.lines,
                        ),
                    )
                )
                pending_gap = Dimen()
                continue
            if kind == "display":
                if current is not None:
                    yield current
                    current = None
                yield _DisplayMathSpec(
                    owner=event[1],
                    box=event[2],
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
                    yield current
                    current = None
                pending_gap += amount
                continue
            if current is not None:
                yield current
                current = None
                pending_gap = Dimen()
        if current is not None:
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
        if self._printable_char(symbol.char):
            return symbol.char
        return None

    def _math_run_xml(self, text):
        if not text:
            return ""
        return f"<m:r><m:t{self._xml_space_attr(text)}>{escape(text)}</m:t></m:r>"

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

    def _omml_group_xml(self, fields):
        return "".join(self._omml_field_xml(field) for field in fields if field is not None)

    def _omml_script_xml(self, atom, base_xml):
        sub = getattr(atom, "sub", None)
        sup = getattr(atom, "sup", None)
        if sub is None and sup is None:
            return base_xml
        base = base_xml or self._math_run_xml("")
        if sub is not None and sup is not None:
            return (
                "<m:sSubSup>"
                f"<m:e>{base}</m:e>"
                f"<m:sub>{self._omml_field_xml(sub)}</m:sub>"
                f"<m:sup>{self._omml_field_xml(sup)}</m:sup>"
                "</m:sSubSup>"
            )
        if sub is not None:
            return (
                "<m:sSub>"
                f"<m:e>{base}</m:e>"
                f"<m:sub>{self._omml_field_xml(sub)}</m:sub>"
                "</m:sSub>"
            )
        return (
            "<m:sSup>"
            f"<m:e>{base}</m:e>"
            f"<m:sup>{self._omml_field_xml(sup)}</m:sup>"
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

    def _omml_atom_xml(self, atom):
        boundary = atom._boundaryInfo() if hasattr(atom, "_boundaryInfo") else None
        if boundary is not None:
            left_delim, right_delim, body_items = boundary
            base_xml = (
                self._math_run_xml(self._delimiter_text(left_delim))
                + self._omml_group_xml(body_items)
                + self._math_run_xml(self._delimiter_text(right_delim))
            )
        else:
            base_xml = self._omml_field_xml(getattr(atom, "nucleus", None))
        if getattr(atom, "left", None) is not None:
            base_xml = self._math_run_xml(self._delimiter_text(atom.left)) + base_xml
        if getattr(atom, "right", None) is not None:
            base_xml += self._math_run_xml(self._delimiter_text(atom.right))
        return self._omml_script_xml(atom, base_xml)

    def _omml_field_xml(self, field):
        if field is None or isinstance(field, mmode.StyleNode):
            return ""
        if isinstance(field, str):
            return self._math_run_xml(field)
        node_type = getattr(field, "node_type", None)
        if node_type in (
            nd.NODE_TYPE.WHATSIT,
            nd.NODE_TYPE.GLUE,
            nd.NODE_TYPE.KERN,
            nd.NODE_TYPE.PENALTY,
        ):
            return ""
        if isinstance(field, mmode.MathSymbol):
            return self._math_run_xml(self._math_symbol_text(field))
        if isinstance(field, (mmode.MathListHolder, mmode.Subformula, mmode.InlineMathNode, mmode.DisplayMathNode)):
            return self._omml_group_xml(getattr(field, "list", ()))
        if isinstance(field, mmode.Over):
            num, den, _bar, _thickness = field.nucleus
            frac_xml = (
                "<m:f>"
                f"<m:num>{self._omml_group_xml(getattr(num, 'list', ()))}</m:num>"
                f"<m:den>{self._omml_group_xml(getattr(den, 'list', ()))}</m:den>"
                "</m:f>"
            )
            if getattr(field, "delims", None) is not None:
                left_delim, right_delim = field.delims
                frac_xml = (
                    self._math_run_xml(self._delimiter_text(left_delim))
                    + frac_xml
                    + self._math_run_xml(self._delimiter_text(right_delim))
                )
            return self._omml_script_xml(field, frac_xml)
        if isinstance(field, mmode.Rad):
            base_xml = (
                "<m:rad>"
                "<m:radPr><m:degHide m:val=\"1\"/></m:radPr>"
                f"<m:e>{self._omml_field_xml(field.oprand)}</m:e>"
                "</m:rad>"
            )
            return self._omml_script_xml(field, base_xml)
        if isinstance(field, mmode.Accent):
            accent = getattr(field, "accent", None)
            base_xml = self._omml_field_xml(field.base)
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
            return self._omml_script_xml(field, base_xml)
        if isinstance(field, mmode.Atom):
            return self._omml_atom_xml(field)
        if isinstance(field, mmode.Box):
            return self._math_run_xml(self._flatten_box_text(getattr(field, "nucleus", None)))
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

    def _display_math_content_xml(self, fields, box):
        inner = self._omml_group_xml(fields)
        if inner:
            body = f"<w:p><m:oMathPara><m:oMath>{inner}</m:oMath></m:oMathPara></w:p>"
            return f"<w:txbxContent>{body}</w:txbxContent>"
        text = self._flatten_box_text(box)
        if not text:
            return "<w:txbxContent><w:p/></w:txbxContent>"
        body = (
            "<w:p><w:r><w:rPr><w:noProof/></w:rPr>"
            f"<w:t{self._xml_space_attr(text)}>{escape(text)}</w:t>"
            "</w:r></w:p>"
        )
        return f"<w:txbxContent>{body}</w:txbxContent>"

    def _display_math_run_xml(self, fields, box):
        width = max(self._pt(getattr(box, "width", 0)), 1.0)
        height = max(self._pt(getattr(box, "height", 0) + getattr(box, "depth", 0)), 1.0)
        content = self._display_math_content_xml(fields, box)
        return parse_xml(
            (
                "<w:r "
                "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
                "xmlns:v=\"urn:schemas-microsoft-com:vml\" "
                "xmlns:o=\"urn:schemas-microsoft-com:office:office\" "
                "xmlns:w10=\"urn:schemas-microsoft-com:office:word\" "
                "xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\">"
                "<w:rPr><w:noProof/></w:rPr>"
                "<w:pict>"
                f"<v:rect stroked=\"f\" filled=\"f\" o:allowincell=\"f\" style=\"width:{width:.4f}pt;height:{height:.4f}pt\">"
                f"<v:textbox inset=\"0,0,0,0\" style=\"mso-fit-text-to-shape:t\">{content}</v:textbox>"
                "<w10:wrap type=\"none\"/>"
                "</v:rect>"
                "</w:pict>"
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
                "<v:textbox inset=\"0,0,0,0\" style=\"mso-fit-text-to-shape:t\"><w:txbxContent><w:p/></w:txbxContent></v:textbox>"
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
        if gap != 0:
            segments.append(("spacer", gap, None, None))
        segments.append(("eqno", Dimen(getattr(last_box, "width", 0)), getattr(eqno_holder, "list", ()), last_box))
        return segments

    def _runs_from_line_box(self, box):
        if not self._can_use_box_runs(box):
            return []
        return self._normalize_runs(self._runs_from_box(box))

    def _runs_from_box(self, box):
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        runs = []
        for index, node in enumerate(items):
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                text = self._glyph_text(node)
                if text:
                    runs.append(_TextRun(text, getattr(node, "font", None)))
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                if not self._glue_is_text_space(items, index):
                    continue
                amount = self._effective_glue_amount(node, box, glue_state)
                if amount <= 0:
                    continue
                font = self._space_font(runs, items, index)
                nominal_width = self._space_width(font)
                delta = amount - nominal_width
                runs.append(_TextRun(" ", font, spacing_twips=self._spacing_twips(delta)))
                continue
            if node_type == nd.NODE_TYPE.KERN:
                if not self._kern_is_text_kern(items, index):
                    continue
                self._apply_text_kern(runs, node.kern)
                continue
            if node_type == nd.NODE_TYPE.DISC:
                runs.extend(self._runs_from_box(node))
                continue
        return runs

    @staticmethod
    def _can_use_box_runs(box):
        items = getattr(box, "list", None) or ()
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.MATH):
                return False
        return True

    def _glue_is_text_space(self, items, index):
        return self._has_text_before(items, index) and self._has_text_after(items, index)

    @staticmethod
    def _kern_is_text_kern(items, index):
        if index <= 0 or index + 1 >= len(items):
            return False
        prev = items[index - 1]
        nxt = items[index + 1]
        prev_type = getattr(prev, "node_type", None)
        next_type = getattr(nxt, "node_type", None)
        text_types = (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.DISC)
        return prev_type in text_types and next_type in text_types

    @staticmethod
    def _apply_text_kern(runs, amount):
        if amount == 0:
            return
        spacing = DocxBackend._spacing_twips(amount)
        if spacing == 0:
            return
        for run in reversed(runs):
            if run.text and not run.text.isspace():
                run.spacing_twips += spacing
                return

    @staticmethod
    def _has_text_before(items, index):
        for node in reversed(items[:index]):
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                return True
            if node_type == nd.NODE_TYPE.DISC:
                return True
        return False

    @staticmethod
    def _has_text_after(items, index):
        for node in items[index + 1:]:
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                return True
            if node_type == nd.NODE_TYPE.DISC:
                return True
        return False

    def _space_font(self, runs, items, index):
        for run in reversed(runs):
            if run.font is not None and not run.text.isspace():
                return run.font
        for node in items[index + 1:]:
            font = getattr(node, "font", None)
            if font is not None:
                return font
        return None

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
        for line_spec in spec.lines:
            fit_text_id = self._fit_text_id
            self._fit_text_id += 1
            line_runs = (
                self._fit_text_runs(line_spec.runs)
                if line_spec.fit_text_twips is not None
                else line_spec.runs
            )
            for chunk in line_runs:
                run = para.add_run(chunk.text)
                self._apply_run_font_with_options(
                    run,
                    chunk.font,
                    allow_word_kerning=False,
                )
                self._apply_run_spacing(run, chunk.spacing_twips)
                self._apply_run_fit_text(run, line_spec.fit_text_twips, fit_text_id)
        return para

    def _emit_display_math(self, document, spec):
        para = document.add_paragraph()
        fmt = para.paragraph_format
        fmt.alignment = WD_ALIGN_PARAGRAPH.LEFT
        fmt.space_before = self._length(self._nonnegative_dimen(spec.space_before))
        fmt.space_after = Pt(0)
        for kind, width, fields, box in self._display_math_segments(spec):
            if kind == "spacer":
                run_xml = self._display_spacer_run_xml(width)
            else:
                run_xml = self._display_math_run_xml(fields, box)
            if run_xml is not None:
                para._p.append(run_xml)
        return para

    def _build_document(self):
        document = Document()
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
    parser.shipout = DocxBackend(parser)


mod = Module(
    "docx",
    init=init,
    attributes={},
)
