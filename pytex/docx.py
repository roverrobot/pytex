"""Minimal DOCX shipout backend for pure text paragraphs."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from docx import Document
from docx.enum.text import WD_BREAK, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt

from pytex import box as bx
from pytex import node as nd
from pytex import paragraph as pg
from pytex.dimen import Dimen
from pytex.module import Module
from pytex.typeset.shipout import Shipout

_ONE_INCH_PT = 72.0


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
    lines: list[list[_TextRun]] = field(default_factory=list)
    interline_gaps: list[Dimen] = field(default_factory=list)
    space_before: Dimen = field(default_factory=Dimen)
    first_line_indent: Dimen = field(default_factory=Dimen)


@dataclass
class _LineEvent:
    owner: object
    baseline: int
    box: object


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
        if font is None:
            return
        name = self._font_name(font)
        if name:
            run.font.name = name
        at = getattr(font, "at", None)
        if at is not None:
            run.font.size = self._length(at)
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

    @classmethod
    def _spacing_twips(cls, delta):
        if not delta:
            return 0
        pt = cls._pt(Dimen(integer=int(delta)))
        return int(round(pt * 20))

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

    def _page_paragraphs(self, page, glyphs):
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
                current.lines.append(line_runs)
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
        first = True
        for line_runs in spec.lines:
            if not first:
                para.add_run().add_break(WD_BREAK.LINE)
            first = False
            for chunk in line_runs:
                run = para.add_run(chunk.text)
                self._apply_run_font(run, chunk.font)
                self._apply_run_spacing(run, chunk.spacing_twips)
        return para

    def _build_document(self):
        document = Document()
        if not self.pages:
            return document
        if len(self.pages) > 1:
            raise NotImplementedError("DOCX proof-of-concept backend only supports a single shipped page")
        page = self.pages[0]
        glyphs = self._captured_pages[0] if self._captured_pages else []
        if not glyphs and any(getattr(node, "node_type", None) == nd.NODE_TYPE.HLIST for node in getattr(page, "list", ())):
            raise ValueError(
                "DOCX backend captured no text glyphs from the shipped page; "
                "the document may have been typeset with nullfont or contain only unsupported content"
            )
        self._configure_section(document, page)
        for spec in self._page_paragraphs(page, glyphs):
            if spec.lines:
                self._emit_paragraph(document, spec)
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
