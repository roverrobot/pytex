"""DOCX backend backed by the generic reflow/document interface."""

from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from docx import Document as WordDocument
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.parts.image import ImagePart
from docx.shared import Pt
from fontTools.pens.svgPathPen import SVGPathPen

from pytex import align
from pytex import box as bx
from pytex import font as txfont
from pytex import mmode
from pytex import node as nd
from pytex import paragraph as pg
from pytex.dimen import Dimen, NEG_MAX_DIMEN
from pytex.module import Module
from pytex import font_subst
from pytex import reflow


_ONE_INCH_PT = 72.0
_ONE_INCH_TEX = Dimen(72.27)
_DOCX_POINTS_PER_TEX_POINT_NUM = 7200
_DOCX_POINTS_PER_TEX_POINT_DEN = 7227
_DOCX_TWIPS_PER_TEX_POINT_NUM = 144000
_DOCX_TWIPS_PER_TEX_POINT_DEN = 7227
_DOCX_EMU_PER_TEX_POINT_NUM = 91440000
_DOCX_EMU_PER_TEX_POINT_DEN = 7227
_INLINE_TEXTBOX_PAD_PT = 0.75
_DOCX_DEFAULT_TEXT_FONT = font_subst.DEFAULT_TEXT_FONT
_MATH_FAMILY_TEXT_OVERRIDES = font_subst.MATH_FAMILY_TEXT_OVERRIDES
_MATH_OPERATORS_MAP = font_subst.MATH_OPERATORS_MAP
_MATH_LETTERS_MAP = font_subst.MATH_LETTERS_MAP
_MATH_SYMBOLS_MAP = font_subst.MATH_SYMBOLS_MAP
_MATH_LARGE_SYMBOLS_MAP = font_subst.MATH_LARGE_SYMBOLS_MAP


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
class _InlineBoxLineSpec:
    runs: list[object]
    line_height: Dimen = field(default_factory=Dimen)
    line_depth: Dimen = field(default_factory=Dimen)
    gap_before: Dimen = field(default_factory=Dimen)


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
    region: str = "body"


@dataclass
class _LineSpec:
    runs: list[object]
    box: object | None = None
    line_height: Dimen = field(default_factory=Dimen)
    gap_before: Dimen = field(default_factory=Dimen)


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
    region: str = "body"


@dataclass
class _AlignmentSpec:
    owner: object
    box: object | None = None
    space_before: Dimen = field(default_factory=Dimen)
    leading_indent: Dimen = field(default_factory=Dimen)
    display: bool = False
    region: str = "body"


@dataclass
class _StructuralBodySlot:
    parent: object | None
    index: int
    body: object
    left: Dimen = field(default_factory=Dimen)
    top: Dimen = field(default_factory=Dimen)
    path: list[tuple[object, int]] = field(default_factory=list)


class _ContainerNode:
    def append(self, child):
        # Child ownership lives in reflow.Element.nodes. This is only a neutral
        # placeholder for the DOCX IR until the final OOXML emission pass.
        pass


class TextRun(reflow.TextRun):
    def __init__(self, backend, line, font: txfont.Font, color: reflow.Color = reflow.Color.black):
        super().__init__(_ContainerNode(), font, color)
        self.backend = backend
        self.line = line
        self.chunk = _TextRun("", font)
        self.line.spec.runs.append(self.chunk)

    def setFont(self, font):
        previous = getattr(self, "font", None)
        super().setFont(font)
        chunk = getattr(self, "chunk", None)
        if chunk is not None and (
            chunk.font is None or (not chunk.text and chunk.font is previous)
        ):
            chunk.font = font

    def _restart_chunk(self):
        self.chunk = _TextRun("", self.font)
        self.line.spec.runs.append(self.chunk)

    def setKern(self, kern: Dimen):
        if kern == 0:
            return
        if self.line.spec.runs and isinstance(self.line.spec.runs[-1], (_InlineBoxRun, _InlineMathRun)):
            self.backend._append_explicit_spacing_run(self.line.spec.runs, kern, self.font)
            self._restart_chunk()
            return
        self.backend._apply_text_kern(self.line.spec.runs, kern)

    def setSpace(self, width):
        self.backend._append_explicit_spacing_run(self.line.spec.runs, width, self.font)
        self._restart_chunk()

    def setSpring(self, width, percent):
        self.setSpace(width)

    def setChar(self, char: nd.Node):
        self.chunk.text += self.backend._glyph_text(char)

    def newInlineBlock(self, box: bx.Box):
        run = _InlineBoxRun(box, [], Dimen(getattr(box, "depth", 0)))
        self.line.spec.runs.append(run)
        block = Block(self.backend, inline=True, xspacing=Dimen(), yspacing=Dimen())
        self.nodes.append(block)
        return block

    def newInlineMath(self):
        run = _InlineMathRun(box=None)
        self.line.spec.runs.append(run)
        return run


class Line(reflow.Line):
    def __init__(
        self,
        backend,
        line_height=Dimen(),
        color: reflow.Color = reflow.Color.black,
        justify="justify",
        box=None,
        gap_before=Dimen(),
    ):
        super().__init__(_ContainerNode(), line_height, color)
        self.backend = backend
        self.justify = justify
        self.spec = _LineSpec(
            runs=[],
            box=box,
            line_height=Dimen(line_height),
            gap_before=Dimen(gap_before),
        )

    def newTextRun(self, font, color) -> TextRun:
        run = TextRun(self.backend, self, font, color)
        self.nodes.append(run)
        return run

    def newInlineBlock(self, box: bx.Box):
        # Placeholder collector for the future generic inline-box path.
        run = _InlineBoxRun(box, [], Dimen(getattr(box, "depth", 0)))
        self.spec.runs.append(run)
        block = Block(self.backend, inline=True, xspacing=Dimen(), yspacing=Dimen())
        self.nodes.append(block)
        return block

    def newInlineMath(self, backend, inlinemath: mmode.InlineMathNode, nodes: list):
        return None

    def setSpace(self, width: Dimen):
        font = self.backend._space_font(self.spec.runs, (), 0)
        self.backend._append_explicit_spacing_run(self.spec.runs, width, font)


class Paragraph(reflow.Paragraph):
    def __init__(self, backend, spacing_before=Dimen(), justify="justify"):
        super().__init__(_ContainerNode(), spacing_before, justify)
        self.backend = backend
        self.spec = _ParagraphSpec(owner=None, space_before=spacing_before)

    def setJustify(self, justify):
        self.justify = justify

    def newLine(
        self,
        line_height: Dimen=Dimen(),
        color: reflow.Color=reflow.Color.black,
        force: bool=False,
        spacing_before: Dimen=Dimen(),
    ):
        line = Line(
            self.backend,
            line_height=line_height,
            color=color,
            justify=self.justify,
            gap_before=spacing_before,
        )
        self.spec.lines.append(line.spec)
        self.nodes.append(line)
        return line

    def iter_specs(self):
        yield self.spec

    def emit(self, container, page=None, normalize_space_before=False):
        if not self.spec.lines:
            return False
        original = self.spec.space_before
        if normalize_space_before:
            self.spec.space_before = Dimen()
        try:
            alignment_spec = self.backend._paragraph_alignment_spec(self.spec)
            if alignment_spec is not None:
                self.backend._emit_alignment(container, alignment_spec, page=page)
            else:
                self.backend._emit_paragraph(container, self.spec)
        finally:
            self.spec.space_before = original
        return True


class Cell(reflow.Cell):
    def __init__(self, backend, span=1, width=None, justify: str = "justify"):
        super().__init__(_ContainerNode(), span=span, width=width, justify=justify)
        self.backend = backend

    def newParagraph(self) -> Paragraph:
        para = Paragraph(self.backend, justify=self.justify)
        self.nodes.append(para)
        return para


class Row(reflow.Row):
    def __init__(self, backend):
        super().__init__(_ContainerNode())
        self.backend = backend

    def newCell(self, span=1, width=None, justify="justify") -> Cell:
        cell = Cell(self.backend, span=span, width=width, justify=justify)
        self.nodes.append(cell)
        return cell


class Table(reflow.Table):
    def __init__(self, backend, xspacing=Dimen(), yspacing=Dimen()):
        super().__init__(_ContainerNode(), xspacing=xspacing, yspacing=yspacing)
        self.backend = backend
        self.owner = None
        self.box = None
        self.space_before = Dimen(yspacing)
        self.region = "body"

    def newRow(self) -> Row:
        row = Row(self.backend)
        self.nodes.append(row)
        return row

    def iter_specs(self):
        yield self

    def emit(self, container, page=None, normalize_space_before=False):
        if self.owner is None:
            return False
        space_before = Dimen() if normalize_space_before else self.space_before
        self.backend._emit_alignment(
            container,
            _AlignmentSpec(
                owner=self.owner,
                box=self.box,
                space_before=space_before,
                region=self.region,
            ),
            page=page,
        )
        return True


class DisplayMath(reflow.Element):
    def __init__(self, backend, spec: _DisplayMathSpec):
        super().__init__(_ContainerNode())
        self.backend = backend
        self.spec = spec

    def iter_specs(self):
        yield self.spec

    def emit(self, container, page=None, normalize_space_before=False):
        original = self.spec.space_before
        if normalize_space_before:
            self.spec.space_before = Dimen()
        try:
            self.backend._emit_display_math(container, self.spec)
        finally:
            self.spec.space_before = original
        return True


class AlignmentBlock(reflow.Element):
    def __init__(self, backend, spec: _AlignmentSpec):
        super().__init__(_ContainerNode())
        self.backend = backend
        self.spec = spec

    def iter_specs(self):
        yield self.spec

    def emit(self, container, page=None, normalize_space_before=False):
        original = self.spec.space_before
        if normalize_space_before:
            self.spec.space_before = Dimen()
        try:
            self.backend._emit_alignment(container, self.spec, page=page)
        finally:
            self.spec.space_before = original
        return True


class SpecBlock(reflow.Element):
    def __init__(self, backend, spec):
        super().__init__(_ContainerNode())
        self.backend = backend
        self.spec = spec

    def iter_specs(self):
        yield self.spec

    def emit(self, container, page=None, normalize_space_before=False):
        original = getattr(self.spec, "space_before", None)
        if normalize_space_before and original is not None:
            self.spec.space_before = Dimen()
        try:
            self.backend._emit_spec(container, self.spec, page)
        finally:
            if original is not None:
                self.spec.space_before = original
        return True


class Block(reflow.Block):
    def __init__(self, backend, region="body", inline=False, xspacing=Dimen(), yspacing=Dimen()):
        super().__init__(_ContainerNode(), inline=inline, xspacing=xspacing, yspacing=yspacing)
        self.backend = backend
        self.region = region
        self._entries = []

    def addSpec(self, spec):
        if hasattr(spec, "region"):
            spec.region = self.region
        if isinstance(spec, _DisplayMathSpec):
            entry = DisplayMath(self.backend, spec)
        elif isinstance(spec, _AlignmentSpec):
            entry = AlignmentBlock(self.backend, spec)
        else:
            entry = SpecBlock(self.backend, spec)
        self._entries.append(entry)
        self.nodes.append(entry)
        return entry

    def iter_specs(self):
        for entry in self._entries:
            if hasattr(entry, "iter_specs"):
                yield from entry.iter_specs()
            else:
                yield entry

    def emit(self, container, page=None, normalize_first=False):
        emitted = False
        for entry in self._entries:
            normalize = normalize_first and not emitted
            if isinstance(entry, Block):
                current = entry.emit(container, page=page, normalize_first=normalize)
            else:
                current = entry.emit(container, page=page, normalize_space_before=normalize)
            if current:
                emitted = True
        return emitted

    def newParagraph(self, spacing_before=Dimen(), justify: str = "left") -> Paragraph:
        para = Paragraph(self.backend, spacing_before=spacing_before, justify=justify)
        para.spec.region = self.region
        self._entries.append(para)
        self.nodes.append(para)
        return para

    def newTable(self, xspacing=Dimen(), yspacing=Dimen()):
        table = Table(self.backend, xspacing=xspacing, yspacing=yspacing)
        table.region = self.region
        self._entries.append(table)
        self.nodes.append(table)
        return table

    def newBlock(self, xspacing=Dimen(), yspacing=Dimen()):
        block = Block(self.backend, region=self.region, inline=False, xspacing=xspacing, yspacing=yspacing)
        self._entries.append(block)
        self.nodes.append(block)
        return block

    def newGraph(self, key, type, file):
        return None


class Section(reflow.Element):
    def __init__(self, backend, signature, config_page=None, page_index=0):
        super().__init__(_ContainerNode())
        self.backend = backend
        self.signature = signature
        self.config_page = config_page
        self.source_page = config_page
        self.page_index = page_index
        self.shipout_count = 0
        self._is_new_for_shipout = True
        self._header = Block(backend, region="header")
        self._body = Block(backend, region="body")
        self._footer = Block(backend, region="footer")

    @property
    def header(self) -> Block:
        return self._header

    @property
    def body(self) -> Block:
        return self._body

    @property
    def footer(self) -> Block:
        return self._footer

    @property
    def is_new_for_shipout(self):
        return self._is_new_for_shipout

    def begin_shipout(self, source_page=None, is_new=False):
        self.source_page = source_page if source_page is not None else self.config_page
        self._is_new_for_shipout = is_new or self.shipout_count == 0
        self.shipout_count += 1

    def setBackgroundColor(self, color: reflow.Color):
        pass

    def emit_body(self, container):
        return self.body.emit(container, page=self.config_page)

    def emit_header_footer(self, section):
        section.header.is_linked_to_previous = False
        self.backend._clear_story_content(section.header)
        self.header.emit(section.header, page=self.config_page, normalize_first=True)

        section.footer.is_linked_to_previous = False
        self.backend._clear_story_content(section.footer)
        self.footer.emit(section.footer, page=self.config_page, normalize_first=True)

    def emit(self, document, section, section_index):
        if self.config_page is not None:
            self.backend._configure_section(section, self.config_page, page_index=self.page_index)
        self.emit_body(document)
        self.emit_header_footer(section)


class Document(reflow.Document):
    def __init__(self, backend, title: str, output=None):
        document = WordDocument()
        backend._remove_compatibility_mode(document)
        super().__init__(document, title, output)
        self.backend = backend
        self.sections: list[Section] = []
        self.current_section: Section | None = None
        self._shipout_index = 0

    @property
    def header(self) -> Block:
        return self.current_section.header

    @property
    def body(self) -> Block:
        return self.current_section.body

    @property
    def footer(self) -> Block:
        return self.current_section.footer

    def newPage(self, width: Dimen, height: Dimen, source_page=None) -> Section:
        page_index = self._shipout_index
        self._shipout_index += 1
        signature = self.backend._section_signature(source_page, width, height, page_index=page_index)
        is_new = not self.sections or self.sections[-1].signature != signature
        if is_new:
            section = Section(
                self.backend,
                signature=signature,
                config_page=source_page,
                page_index=page_index,
            )
            self.sections.append(section)
            self.nodes.append(section)
        else:
            section = self.sections[-1]
        section.begin_shipout(source_page=source_page, is_new=is_new)
        self.current_section = section
        return section

    def defineFont(self, font):
        return None

    def definePicture(self, key, type, path):
        return None

    def save(self):
        if self.sections:
            for section_index, section_model in enumerate(self.sections):
                if section_index == 0:
                    section = self._node.sections[0]
                else:
                    section = self._node.add_section(WD_SECTION_START.NEW_PAGE)
                section_model.emit(self._node, section, section_index)
        self._node.save(self.output)
        if hasattr(self.output, "close"):
            self.output.close()


class DocxBackend(reflow.Reflow):
    """
    Very small proof-of-concept DOCX backend.

    Scope intentionally stays narrow:
    - page-wise reconstruction from shipped TeX pages
    - TeX controls both paragraph and line breaks
    - paragraphs, basic alignments, and inline/display math are supported
    - images, specials, and broader page semantics remain intentionally narrow

    The backend reconstructs TeX paragraphs from shipped line boxes, emits one
    Word paragraph per TeX paragraph, inserts explicit line breaks between TeX
    lines, and uses TeX's already-computed paragraph ownership and glue as DOCX
    paragraph spacing hints.
    """

    def __init__(self, parser, output=None):
        super().__init__(parser, paginate=True)
        self.output = output
        self.file = None
        self.finished = False
        self._docx_next_drawing_id = 1
        self._docx_next_textbox_id = 1
        self.section = None

    def begin_page(self, box):
        self.section = self.document.newPage(box.width, box.height, source_page=box)

    def end_page(self, box):
        self.section = None

    def _region_vlist_nodes(self, box, target_region):
        if box is None:
            return []
        if getattr(box, "node_type", None) != nd.NODE_TYPE.VLIST:
            return [box] if target_region == "body" else []
        region_map = self._page_region_map(box)
        text_top, text_bottom = self._page_text_vertical_bounds(box)
        glue_state = self._glue_state(box)
        nodes = []
        pending = []
        v = 0
        for node in getattr(box, "list", None) or ():
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                pending.append(node)
                v += self._effective_glue_amount(node, box, glue_state)
                continue
            if node_type == nd.NODE_TYPE.KERN:
                pending.append(node)
                v += int(getattr(node, "kern", 0))
                continue
            if node_type in (nd.NODE_TYPE.PENALTY, nd.NODE_TYPE.WHATSIT):
                pending.append(node)
                continue

            height = int(getattr(node, "height", 0))
            depth = int(getattr(node, "depth", 0))
            top = v
            bottom = v + height + depth
            region = region_map.get(
                id(node),
                self._flow_region_from_bounds(top, bottom, text_top, text_bottom),
            )
            if region == target_region:
                nodes.extend(pending)
                nodes.append(node)
            pending = []
            v = bottom
        return nodes

    def _typesetPageRegion(self, tree, region, top_level=False):
        if (
            region in ("header", "footer")
            and self.section is not None
            and not self.section.is_new_for_shipout
        ):
            return
        page_box = self.section.source_page if self.section is not None else tree[-1]
        nodes = self._region_vlist_nodes(page_box, region)
        if not nodes:
            return
        container = getattr(self.document, region)
        glue_state = self._glue_state(page_box) if getattr(page_box, "node_type", None) == nd.NODE_TYPE.VLIST else None
        with reflow.Builder(self, container):
            self.typesetVList(nodes, glue_state, top_level=top_level)

    def typesetHeader(self, tree):
        self._typesetPageRegion(tree, "header", top_level=False)

    def typesetBody(self, tree):
        self._typesetPageRegion(tree, "body", top_level=True)

    def typesetFooter(self, tree):
        self._typesetPageRegion(tree, "footer", top_level=False)

    def typesetParagraph(self, para: Paragraph, source: pg.Paragraph, nodes: list, glue_state=None):
        para.spec.owner = source
        return super().typesetParagraph(para, source, nodes, glue_state)

    def _current_line(self):
        builder = self.builder
        if isinstance(builder, reflow.AnnotationBuilder):
            builder = builder.parent
        container = getattr(builder, "container", None)
        if isinstance(container, Line):
            return container
        if isinstance(container, TextRun):
            return container.line
        return None

    def typesetLine(self, line: bx.HBox, yspacing: Dimen=Dimen()):
        current = self._current_line()
        if current is not None:
            current.spec.box = line
            current.spec.line_height = max(
                Dimen(current.spec.line_height),
                Dimen(getattr(line, "height", 0) + getattr(line, "depth", 0)),
            )
        return super().typesetLine(line, yspacing)

    def typesetInlineMath(self, node: mmode.InlineMathNode, box: bx.HBox, piece: int):
        current = self._current_line()
        if current is None:
            return
        box = self._inline_math_box(getattr(box, "list", ()), line_box=current.spec.box)
        current.spec.runs.append(
            _InlineMathRun(
                box=box,
                line_depth=max(
                    Dimen(getattr(box, "depth", 0)),
                    Dimen(getattr(current.spec.box, "depth", 0)),
                ),
            )
        )

    def typesetInlineBox(self, box: bx.Box):
        current = self._current_line()
        if current is None:
            return super().typesetInlineBox(box)
        chunks = []
        if getattr(box, "node_type", None) == nd.NODE_TYPE.HLIST:
            math_state = _InlineMathState()
            chunks = self._runs_from_line_box(box, math_state)
            if not chunks:
                chunks = self._runs_from_box(box, math_state)
            chunks = self._normalize_runs(chunks)
        line_depth = Dimen(getattr(current.spec.box, "depth", 0))
        current.spec.runs.append(_InlineBoxRun(box, chunks, line_depth))
        return None

    def typesetDisplayMath(self, node, collection, yspacing: Dimen=Dimen()):
        box = None
        for candidate in collection:
            if getattr(candidate, "node_type", None) in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                box = candidate
                break
        if box is None:
            return
        add_spec = getattr(self.builder, "addSpec", None)
        if add_spec is not None:
            add_spec(
                _DisplayMathSpec(
                    owner=node,
                    box=box,
                    page=self.section.source_page if self.section is not None else None,
                    space_before=yspacing,
                )
            )

    def typesetHAlignment(self, node: align.HAlignment, collection, yspacing):
        table = self.builder.container if isinstance(self.builder.container, Table) else None
        if table is not None:
            table.owner = node
            table.box = collection[0] if collection else None
            table.space_before = Dimen(yspacing)
        return super().typesetHAlignment(node, collection, yspacing)

    def open(self):
        if self.document is not None:
            return self.document
        self._open_output()
        title = self.parser.jobname or "texput"
        return Document(self, title, output=self.file)

    def _open_output(self, output=None):
        if self.file is not None:
            return self.file
        if output is None:
            output = self.output
        if output is None:
            output = self.parser.jobname or "texput"
        if hasattr(output, "write"):
            self.file = output
            return self.file
        path = os.fspath(output)
        if os.path.isabs(path):
            if not path.endswith(".docx"):
                path += ".docx"
            self.file = open(path, "wb")
            return self.file
        if not path.endswith(".docx"):
            path += ".docx"
        self.file = self.parser.resolver.openOut(path, "shipout/docx")
        return self.file

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
    def _alignment_owner(node):
        source = getattr(node, "source", None)
        return source if isinstance(source, align.HAlignment) else None

    @staticmethod
    def _display_alignment_owner(node):
        if isinstance(node, align.MAlignment) and isinstance(getattr(node, "source", None), align.HAlignment):
            return node.source
        return None

    @staticmethod
    def _node_belongs_to_alignment(node, owner):
        source = getattr(node, "source", None)
        if source is owner:
            return True
        return source in getattr(owner, "rows", ())

    def _descendant_alignment_info(self, node):
        direct = self._alignment_owner(node)
        if direct is not None:
            return direct, node
        display = self._display_alignment_owner(node)
        if display is not None:
            return display, node
        owners = {}
        for child in getattr(node, "list", None) or ():
            if getattr(child, "node_type", None) not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                continue
            info = self._descendant_alignment_info(child)
            if info is not None:
                owners[id(info[0])] = info
        if len(owners) == 1:
            return next(iter(owners.values()))
        return None

    def _line_alignment_info(self, box):
        candidate = None
        leading_indent = Dimen()
        seen_visible = False
        glue_state = self._glue_state(box)
        for node in getattr(box, "list", None) or ():
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                if not seen_visible:
                    amount = self._effective_glue_amount(node, box, glue_state)
                    leading_indent += Dimen(integer=amount)
                continue
            if node_type == nd.NODE_TYPE.KERN:
                if not seen_visible:
                    leading_indent += Dimen(getattr(node, "kern", 0))
                continue
            if node_type == nd.NODE_TYPE.PENALTY:
                continue
            if node_type == nd.NODE_TYPE.MATH:
                continue
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.DISC):
                return None
            if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                info = self._descendant_alignment_info(node)
                if info is None:
                    if not self._node_has_inline_text(node):
                        if not seen_visible:
                            leading_indent += Dimen(getattr(node, "width", 0))
                        continue
                    return None
                seen_visible = True
                if candidate is None:
                    candidate = (info[0], info[1], leading_indent)
                    continue
                if candidate[0] is not info[0]:
                    return None
                continue
            return None
        return candidate

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
        return float(value) * _DOCX_POINTS_PER_TEX_POINT_NUM / _DOCX_POINTS_PER_TEX_POINT_DEN

    @staticmethod
    def _pt_scaled(value):
        return (
            int(value)
            * _DOCX_POINTS_PER_TEX_POINT_NUM
            / (_DOCX_POINTS_PER_TEX_POINT_DEN * Dimen.scale)
        )

    @classmethod
    def _length(cls, value):
        return Pt(cls._pt(value))

    @classmethod
    def _emu(cls, value):
        scaled = int(value) if isinstance(value, Dimen) else int(Dimen(value))
        return max(
            0,
            Dimen._round_div(
                scaled * _DOCX_EMU_PER_TEX_POINT_NUM,
                _DOCX_EMU_PER_TEX_POINT_DEN * Dimen.scale,
            ),
        )

    @staticmethod
    def _emu_points(value):
        return max(0, int(round(float(value) * 12700.0)))

    def _next_docx_drawing_ids(self):
        drawing_id = self._docx_next_drawing_id
        textbox_id = self._docx_next_textbox_id
        self._docx_next_drawing_id += 1
        self._docx_next_textbox_id += 1
        return drawing_id, textbox_id

    @staticmethod
    def _textbox_anchor_value(anchor):
        if anchor == "bottom":
            return "b"
        if anchor == "top":
            return "t"
        return "ctr"

    def _drawingml_textbox_xml(self, content, width, height, anchor=None):
        drawing_id, textbox_id = self._next_docx_drawing_ids()
        width_emu = max(1, self._emu_points(width))
        height_emu = max(1, self._emu_points(height))
        shape_name = escape(f"TextBox {drawing_id}", {'"': "&quot;"})
        anchor_value = self._textbox_anchor_value(anchor)
        return (
            "<w:drawing>"
            f"<wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">"
            f"<wp:extent cx=\"{width_emu}\" cy=\"{height_emu}\"/>"
            "<wp:effectExtent l=\"0\" t=\"0\" r=\"0\" b=\"0\"/>"
            f"<wp:docPr id=\"{drawing_id}\" name=\"{shape_name}\"/>"
            "<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect=\"1\"/></wp:cNvGraphicFramePr>"
            "<a:graphic>"
            "<a:graphicData uri=\"http://schemas.microsoft.com/office/word/2010/wordprocessingShape\">"
            "<wps:wsp>"
            "<wps:cNvSpPr txBox=\"1\"/>"
            "<wps:spPr>"
            f"<a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"{width_emu}\" cy=\"{height_emu}\"/></a:xfrm>"
            "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom>"
            "<a:noFill/>"
            "<a:ln><a:noFill/></a:ln>"
            "</wps:spPr>"
            f"<wps:txbx id=\"{textbox_id}\">{content}</wps:txbx>"
            f"<wps:bodyPr lIns=\"0\" tIns=\"0\" rIns=\"0\" bIns=\"0\" wrap=\"none\" anchor=\"{anchor_value}\">"
            "<a:noAutofit/>"
            "</wps:bodyPr>"
            "</wps:wsp>"
            "</a:graphicData>"
            "</a:graphic>"
            "</wp:inline>"
            "</w:drawing>"
        )

    @staticmethod
    def _svg_number(value):
        value = float(value)
        text = f"{value:.6f}".rstrip("0").rstrip(".")
        if text == "-0":
            return "0"
        return text or "0"

    @staticmethod
    def _svg_extend_bounds(bounds, left, top, right, bottom):
        if right <= left or bottom <= top:
            return bounds
        if bounds is None:
            return [left, top, right, bottom]
        if left < bounds[0]:
            bounds[0] = left
        if top < bounds[1]:
            bounds[1] = top
        if right > bounds[2]:
            bounds[2] = right
        if bottom > bounds[3]:
            bounds[3] = bottom
        return bounds

    def _svg_box_width(self, box):
        return max(self._textbox_box_width(box), Dimen())

    def _glyph_svg_path(self, node):
        font = getattr(node, "font", None)
        backend = getattr(font, "backend", None)
        glyph_set = getattr(backend, "_glyph_set", None)
        if glyph_set is None:
            return None
        char_info = getattr(node, "char_info", None)
        glyph_name = getattr(char_info, "glyph_name", None)
        if glyph_name is None:
            resolver = getattr(backend, "_glyphName", None)
            if callable(resolver):
                try:
                    glyph_name = resolver(getattr(node, "char", ""))
                except Exception:
                    glyph_name = None
        if glyph_name is None:
            glyph_id = getattr(char_info, "glyph_id", None)
            font_obj = getattr(backend, "font", None)
            if glyph_id is not None and font_obj is not None:
                try:
                    glyph_name = font_obj.getGlyphName(glyph_id)
                except Exception:
                    glyph_name = None
        if glyph_name is None:
            return None
        glyph = glyph_set.get(glyph_name)
        if glyph is None:
            return None
        pen = SVGPathPen(glyph_set)
        glyph.draw(pen)
        commands = pen.getCommands()
        return commands or None

    def _svg_font_attributes(self, font):
        attrs = []
        name = self._font_name(font)
        if name:
            escaped_name = escape(name, {'"': "&quot;"})
            attrs.append(f'font-family="{escaped_name}"')
        at = getattr(font, "at", None)
        if at is not None:
            attrs.append(f'font-size="{self._svg_number(self._pt(at))}pt"')
        bold, italic = self._docx_font_style(font)
        if bold:
            attrs.append('font-weight="bold"')
        if italic:
            attrs.append('font-style="italic"')
        return " ".join(attrs)

    def _svg_draw_char(self, node, h, v, out, bounds=None):
        text = self._glyph_text(node)
        if not text:
            return bounds
        font = getattr(node, "font", None)
        x = self._pt_scaled(h)
        baseline = self._pt_scaled(v)
        width = self._pt(getattr(node, "width", 0))
        top = baseline - self._pt(getattr(node, "height", 0))
        bottom = baseline + self._pt(getattr(node, "depth", 0))
        bounds = self._svg_extend_bounds(bounds, x, top, x + width, bottom)
        path = self._glyph_svg_path(node)
        if path is not None and font is not None:
            backend = getattr(font, "backend", None)
            units_per_em = float(getattr(backend, "units_per_em", 0) or 0)
            if units_per_em > 0:
                scale = self._pt(getattr(font, "at", 0)) / units_per_em
                escaped_path = escape(path, {'"': "&quot;"})
                out.append(
                    "<path "
                    f'd="{escaped_path}" '
                    f'transform="translate({self._svg_number(x)} {self._svg_number(baseline)}) '
                    f'scale({self._svg_number(scale)} {self._svg_number(-scale)})" '
                    'fill="#000000"/>'
                )
                return bounds
        attrs = self._svg_font_attributes(font)
        attrs = f" {attrs}" if attrs else ""
        out.append(
            "<text "
            f'x="{self._svg_number(x)}" '
            f'y="{self._svg_number(baseline)}"{attrs} '
            'xml:space="preserve" fill="#000000">'
            f"{escape(text)}"
            "</text>"
        )
        return bounds

    def _svg_rule_dims(self, node, box):
        def running(value):
            return int(value) <= int(NEG_MAX_DIMEN)

        if getattr(box, "node_type", None) == nd.NODE_TYPE.VLIST:
            width = int(getattr(box, "width", 0)) if running(getattr(node, "width", 0)) else int(getattr(node, "width", 0))
            height = int(getattr(node, "height", 0))
            depth = int(getattr(node, "depth", 0))
        else:
            width = int(getattr(node, "width", 0))
            height = int(getattr(box, "height", 0)) if running(getattr(node, "height", 0)) else int(getattr(node, "height", 0))
            depth = int(getattr(box, "depth", 0)) if running(getattr(node, "depth", 0)) else int(getattr(node, "depth", 0))
        return width, height, depth

    def _svg_draw_rule(self, node, box, h, v, out, bounds=None):
        width, height, depth = self._svg_rule_dims(node, box)
        if width <= 0 or height + depth <= 0:
            return bounds
        if getattr(box, "node_type", None) == nd.NODE_TYPE.HLIST:
            top = v - height
        else:
            top = v
        left_pt = self._pt_scaled(h)
        top_pt = self._pt_scaled(top)
        width_pt = self._pt_scaled(width)
        height_pt = self._pt_scaled(height + depth)
        bounds = self._svg_extend_bounds(bounds, left_pt, top_pt, left_pt + width_pt, top_pt + height_pt)
        out.append(
            "<rect "
            f'x="{self._svg_number(left_pt)}" '
            f'y="{self._svg_number(top_pt)}" '
            f'width="{self._svg_number(width_pt)}" '
            f'height="{self._svg_number(height_pt)}" '
            'fill="#000000"/>'
        )
        return bounds

    def _svg_render_hlist(self, box, h, v, out, bounds=None):
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                bounds = self._svg_draw_char(node, h, v, out, bounds)
                h += int(getattr(node, "width", 0))
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                h += self._effective_glue_amount(node, box, glue_state)
                continue
            if node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                h += int(getattr(node, "kern", 0))
                continue
            if node_type == nd.NODE_TYPE.DISC:
                h, bounds = self._svg_render_hlist(node, h, v, out, bounds)
                continue
            if node_type == nd.NODE_TYPE.RULE:
                bounds = self._svg_draw_rule(node, box, h, v, out, bounds)
                h += int(getattr(node, "width", 0))
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                shifted = int(getattr(node, "shifted", 0))
                _child_h, bounds = self._svg_render_hlist(node, h, v + shifted, out, bounds)
                h += int(getattr(node, "width", 0))
                continue
            if node_type in (nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                shifted = int(getattr(node, "shifted", 0))
                _child_v, bounds = self._svg_render_vlist(
                    node,
                    h,
                    v + shifted - int(getattr(node, "height", 0)),
                    out,
                    bounds,
                )
                h += int(getattr(node, "width", 0))
                continue
        return h, bounds

    def _svg_render_vlist(self, box, h, v, out, bounds=None):
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                v += self._effective_glue_amount(node, box, glue_state)
                continue
            if node_type == nd.NODE_TYPE.KERN:
                v += int(getattr(node, "kern", 0))
                continue
            if node_type == nd.NODE_TYPE.RULE:
                bounds = self._svg_draw_rule(node, box, h, v, out, bounds)
                v += int(getattr(node, "height", 0))
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                shifted = int(getattr(node, "shifted", 0))
                _child_h, bounds = self._svg_render_hlist(
                    node,
                    h + shifted,
                    v + int(getattr(node, "height", 0)),
                    out,
                    bounds,
                )
                v += int(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue
            if node_type in (nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                shifted = int(getattr(node, "shifted", 0))
                _child_v, bounds = self._svg_render_vlist(node, h + shifted, v, out, bounds)
                v += int(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue
        return v, bounds

    def _svg_bytes_for_box(self, box, total_height=None):
        if box is None:
            return b""
        width = self._svg_box_width(box)
        total_height = (
            Dimen(total_height)
            if total_height is not None
            else Dimen(getattr(box, "height", 0)) + Dimen(getattr(box, "depth", 0))
        )
        parts = []
        node_type = getattr(box, "node_type", None)
        if node_type == nd.NODE_TYPE.HLIST:
            self._svg_render_hlist(box, 0, int(getattr(box, "height", 0)), parts)
        elif node_type in (nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
            self._svg_render_vlist(box, 0, 0, parts)
        svg_width = self._svg_number(self._pt(width))
        svg_height = self._svg_number(self._pt(total_height))
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{svg_width}pt" height="{svg_height}pt" '
            f'viewBox="0 0 {svg_width} {svg_height}">'
            f'{"".join(parts)}</svg>'
        ).encode("utf-8")

    def _get_or_add_svg_image_part(self, story_part, svg_bytes):
        package = story_part._package
        assert package is not None
        sha1 = hashlib.sha1(svg_bytes).hexdigest()
        for image_part in package.image_parts:
            if image_part.content_type == "image/svg+xml" and image_part.sha1 == sha1:
                return story_part.relate_to(image_part, RT.IMAGE), image_part
        partname = package.image_parts._next_image_partname("svg")
        image_part = ImagePart(partname, "image/svg+xml", svg_bytes)
        image_part._package = package
        package.image_parts.append(image_part)
        return story_part.relate_to(image_part, RT.IMAGE), image_part

    def _inline_svg_picture_run_xml(self, story_part, svg_bytes, width, height, depth=None):
        width = max(Dimen(width), Dimen(1))
        height = max(Dimen(height), Dimen(1))
        rId, image_part = self._get_or_add_svg_image_part(story_part, svg_bytes)
        drawing_id, _textbox_id = self._next_docx_drawing_ids()
        width_emu = max(1, self._emu(width))
        height_emu = max(1, self._emu(height))
        filename = escape(getattr(image_part, "filename", f"image{drawing_id}.svg"), {'"': "&quot;"})
        position = -int(round(self._pt(depth) * 2.0)) if depth else None
        return parse_xml(
            (
                "<w:r "
                "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
                "xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\" "
                "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" "
                "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
                "xmlns:pic=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
                f"{self._raw_run_properties_xml(no_proof=True, position_half_points=position)}"
                "<w:drawing>"
                "<wp:inline distT=\"0\" distB=\"0\" distL=\"0\" distR=\"0\">"
                f"<wp:extent cx=\"{width_emu}\" cy=\"{height_emu}\"/>"
                "<wp:effectExtent l=\"0\" t=\"0\" r=\"0\" b=\"0\"/>"
                f"<wp:docPr id=\"{drawing_id}\" name=\"Picture {drawing_id}\"/>"
                "<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect=\"1\"/></wp:cNvGraphicFramePr>"
                "<a:graphic>"
                "<a:graphicData uri=\"http://schemas.openxmlformats.org/drawingml/2006/picture\">"
                "<pic:pic>"
                "<pic:nvPicPr>"
                f"<pic:cNvPr id=\"{drawing_id}\" name=\"{filename}\"/>"
                "<pic:cNvPicPr><a:picLocks noChangeAspect=\"1\" noChangeArrowheads=\"1\"/></pic:cNvPicPr>"
                "</pic:nvPicPr>"
                "<pic:blipFill>"
                "<a:blip>"
                "<a:extLst>"
                "<a:ext uri=\"{96DAC541-7B7A-43D3-8B79-37D633B846F1}\">"
                f"<asvg:svgBlip xmlns:asvg=\"http://schemas.microsoft.com/office/drawing/2016/SVG/main\" r:embed=\"{rId}\"/>"
                "</a:ext>"
                "<a:ext uri=\"{28A0092B-C50C-407E-A947-70E740481C1C}\">"
                "<a14:useLocalDpi xmlns:a14=\"http://schemas.microsoft.com/office/drawing/2010/main\" val=\"0\"/>"
                "</a:ext>"
                "</a:extLst>"
                "</a:blip>"
                "<a:stretch><a:fillRect/></a:stretch>"
                "</pic:blipFill>"
                "<pic:spPr>"
                f"<a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"{width_emu}\" cy=\"{height_emu}\"/></a:xfrm>"
                "<a:prstGeom prst=\"rect\"><a:avLst/></a:prstGeom>"
                "<a:noFill/>"
                "</pic:spPr>"
                "</pic:pic>"
                "</a:graphicData>"
                "</a:graphic>"
                "</wp:inline>"
                "</w:drawing>"
                "</w:r>"
            )
        )

    def _remove_compatibility_mode(self, document):
        settings = document.settings._element
        for child in list(settings):
            if child.tag != qn("w:compat"):
                continue
            for compat_child in list(child):
                if compat_child.tag != qn("w:compatSetting"):
                    continue
                if compat_child.get(qn("w:name")) == "compatibilityMode":
                    child.remove(compat_child)
            if len(child) == 0:
                settings.remove(child)

    @staticmethod
    def _nonnegative_dimen(value):
        value = value if isinstance(value, Dimen) else Dimen(value)
        return value if value >= 0 else Dimen()

    def _named_dimen(self, name):
        try:
            entry = self.parser.equitable.get(name)
        except Exception:
            return None
        if entry is None:
            return None
        accessor = getattr(entry, "value", None)
        if accessor is None:
            return None
        try:
            target = accessor.getTarget(self.parser)
            value = target.get()
        except Exception:
            return None
        try:
            return Dimen(value)
        except Exception:
            return None

    def _tex_page_size(self, page):
        origin_x = _ONE_INCH_TEX + Dimen(self.parser.layout["hoffset"])
        origin_y = _ONE_INCH_TEX + Dimen(self.parser.layout["voffset"])
        width = self._named_dimen("\\paperwidth")
        height = self._named_dimen("\\paperheight")
        try:
            width_param = self.parser.parameters["pdfpagewidth"]
        except Exception:
            width_param = None
        try:
            height_param = self.parser.parameters["pdfpageheight"]
        except Exception:
            height_param = None
        if width is None or width <= 0:
            width = Dimen(width_param) if width_param is not None else Dimen()
        if height is None or height <= 0:
            height = Dimen(height_param) if height_param is not None else Dimen()
        box_width = Dimen(getattr(page, "width", 0))
        box_height = Dimen(getattr(page, "height", 0) + getattr(page, "depth", 0))
        if width <= 0:
            width = box_width + 2 * origin_x
        if height <= 0:
            height = box_height + 2 * origin_y
        return width, height, origin_x, origin_y

    def _locate_box_in_hlist(self, box, target, x_left, baseline):
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        h = Dimen(x_left)
        baseline = Dimen(baseline)
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                h += Dimen(integer=self._effective_glue_amount(node, box, glue_state))
                continue
            if node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                h += Dimen(getattr(node, "kern", 0))
                continue
            if node_type == nd.NODE_TYPE.DISC:
                h += Dimen(getattr(node, "replace_width", 0))
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                child_x = Dimen(h)
                child_baseline = baseline + Dimen(getattr(node, "shifted", 0))
                child_top = child_baseline - Dimen(getattr(node, "height", 0))
                if node is target:
                    return child_x, child_top
                located = self._locate_box_in_hlist(node, target, child_x, child_baseline)
                if located is not None:
                    return located
                h += Dimen(getattr(node, "width", 0))
                continue
            if node_type in (nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                child_x = Dimen(h)
                child_top = baseline + Dimen(getattr(node, "shifted", 0)) - Dimen(getattr(node, "height", 0))
                if node is target:
                    return child_x, child_top
                located = self._locate_box_in_vlist(node, target, child_x, child_top)
                if located is not None:
                    return located
                h += Dimen(getattr(node, "width", 0))
                continue
            h += Dimen(getattr(node, "width", 0))
        return None

    def _locate_box_in_vlist(self, box, target, x_left, top):
        if box is target:
            return Dimen(x_left), Dimen(top)
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        v = Dimen(top)
        x_left = Dimen(x_left)
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                v += Dimen(integer=self._effective_glue_amount(node, box, glue_state))
                continue
            if node_type == nd.NODE_TYPE.KERN:
                v += Dimen(getattr(node, "kern", 0))
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                child_x = x_left + Dimen(getattr(node, "shifted", 0))
                child_top = Dimen(v)
                if node is target:
                    return child_x, child_top
                child_baseline = child_top + Dimen(getattr(node, "height", 0))
                located = self._locate_box_in_hlist(node, target, child_x, child_baseline)
                if located is not None:
                    return located
                v += Dimen(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue
            if node_type in (nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                child_x = x_left + Dimen(getattr(node, "shifted", 0))
                child_top = Dimen(v)
                if node is target:
                    return child_x, child_top
                located = self._locate_box_in_vlist(node, target, child_x, child_top)
                if located is not None:
                    return located
                v += Dimen(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue
        return None

    def _structural_body_geometry(self, page):
        slot = self._find_structural_body_slot(page)
        if slot is None:
            return None
        body = slot.body
        body_left, body_top = slot.left, slot.top
        body_width = Dimen(getattr(body, "width", 0))
        body_height = Dimen(getattr(body, "height", 0) + getattr(body, "depth", 0))
        if body_width <= 0 or body_height <= 0:
            return None
        return body_left, body_top, body_width, body_height

    def _section_geometry(self, page, page_index=0):
        hsize = Dimen(self.parser.layout["hsize"])
        vsize = Dimen(self.parser.layout["vsize"])
        if page is None:
            page_width = Dimen()
            page_height = Dimen()
            origin_x = _ONE_INCH_TEX + Dimen(self.parser.layout["hoffset"])
            origin_y = _ONE_INCH_TEX + Dimen(self.parser.layout["voffset"])
            box_width = hsize
            box_height = vsize
        else:
            page_width, page_height, origin_x, origin_y = self._tex_page_size(page)
            box_width = Dimen(getattr(page, "width", 0))
            box_height = Dimen(getattr(page, "height", 0) + getattr(page, "depth", 0))

        body_geometry = self._structural_body_geometry(page) if page is not None else None
        if body_geometry is not None:
            body_left, body_top, text_width, text_height = body_geometry
            left_margin = self._nonnegative_dimen(origin_x + body_left)
            top_margin = self._nonnegative_dimen(origin_y + body_top)
        else:
            text_width_cmd = self._named_dimen("\\textwidth")
            text_width = text_width_cmd if text_width_cmd is not None and text_width_cmd > 0 else (hsize if hsize > 0 else box_width)
            text_height = vsize if vsize > 0 else box_height

            side_name = "\\evensidemargin" if page_index % 2 == 1 else "\\oddsidemargin"
            side_margin = self._named_dimen(side_name)
            left_margin = self._nonnegative_dimen(origin_x + (side_margin if side_margin is not None else Dimen()))
            top_margin = self._nonnegative_dimen(origin_y)
        right_margin = self._nonnegative_dimen(page_width - left_margin - text_width)
        bottom_margin = self._nonnegative_dimen(page_height - top_margin - text_height)
        header_distance, footer_distance = (None, None)
        if page is not None:
            header_distance, footer_distance = self._header_footer_distances(page)
        return {
            "page_width": self._nonnegative_dimen(page_width),
            "page_height": self._nonnegative_dimen(page_height),
            "left_margin": left_margin,
            "right_margin": right_margin,
            "top_margin": top_margin,
            "bottom_margin": bottom_margin,
            "header_distance": header_distance,
            "footer_distance": footer_distance,
        }

    def _section_signature(self, page, width=None, height=None, page_index=0):
        geometry = self._section_geometry(page, page_index=page_index)
        if geometry["page_width"] <= 0 and width is not None:
            geometry["page_width"] = self._nonnegative_dimen(width)
        if geometry["page_height"] <= 0 and height is not None:
            geometry["page_height"] = self._nonnegative_dimen(height)

        def key(value):
            if value is None:
                return None
            return int(value)

        return tuple(
            key(geometry[name])
            for name in (
                "page_width",
                "page_height",
                "left_margin",
                "right_margin",
                "top_margin",
                "bottom_margin",
                "header_distance",
                "footer_distance",
            )
        )

    def _configure_section(self, section, page, page_index=0):
        geometry = self._section_geometry(page, page_index=page_index)
        section.left_margin = self._length(geometry["left_margin"])
        section.right_margin = self._length(geometry["right_margin"])
        section.top_margin = self._length(geometry["top_margin"])
        section.bottom_margin = self._length(geometry["bottom_margin"])
        section.page_width = self._length(geometry["page_width"])
        section.page_height = self._length(geometry["page_height"])
        header_distance = geometry["header_distance"]
        footer_distance = geometry["footer_distance"]
        if header_distance is not None:
            section.header_distance = self._length(header_distance)
        if footer_distance is not None:
            section.footer_distance = self._length(footer_distance)

    def _topskip_dimen(self):
        try:
            topskip = self.parser.layout["topskip"]
        except Exception:
            return Dimen()
        if hasattr(topskip, "dimen"):
            return Dimen(getattr(topskip, "dimen", 0))
        return Dimen(topskip)

    def _page_text_vertical_bounds(self, page):
        body_geometry = self._structural_body_geometry(page)
        if body_geometry is not None:
            _left, top, _width, height = body_geometry
            return int(top), int(top + height)
        vsize = Dimen(self.parser.layout["vsize"])
        box_height = Dimen(getattr(page, "height", 0) + getattr(page, "depth", 0))
        text_height = vsize if vsize > 0 else box_height
        inner_top = box_height - text_height if box_height > text_height else Dimen()
        topskip = self._topskip_dimen()
        top = int(inner_top - topskip) if inner_top > topskip else 0
        bottom = int(inner_top + text_height)
        return top, bottom

    def _top_region_boundary_slop(self):
        return max(0, int(self._topskip_dimen()))

    def _flow_region_from_bounds(self, top, bottom, text_top, text_bottom):
        top_slop = self._top_region_boundary_slop()
        if bottom < text_top - top_slop:
            return "header"
        if top >= text_bottom:
            return "footer"
        return "body"

    def _header_footer_distances(self, page):
        _page_width, page_height, _origin_x, origin_y = self._tex_page_size(page)
        text_top, text_bottom = self._page_text_vertical_bounds(page)
        region_map = self._page_region_map(page)

        header_baselines = []
        footer_baselines = []
        for event in self._walk_vlist(page, 0):
            if event[0] != "line":
                continue
            line = event[1]
            line_top, line_bottom = self._line_vertical_bounds(line)
            region = region_map.get(
                id(line.box),
                self._flow_region_from_bounds(line_top, line_bottom, text_top, text_bottom),
            )
            if region == "header":
                header_baselines.append(Dimen(integer=int(line.baseline)))
            elif region == "footer":
                footer_baselines.append(Dimen(integer=int(line.baseline)))

        header_distance = None
        footer_distance = None
        if header_baselines:
            # Distance from physical page top to the lowest header baseline.
            # Uses only walked shipout geometry plus TeX origin shift.
            header_distance = self._nonnegative_dimen(origin_y + max(header_baselines))
        if footer_baselines:
            # Distance from physical page bottom to the lowest footer baseline.
            footer_distance = self._nonnegative_dimen(page_height - (origin_y + max(footer_baselines)))
        return header_distance, footer_distance

    @staticmethod
    def _line_vertical_bounds(line):
        height = int(getattr(line.box, "height", 0))
        depth = int(getattr(line.box, "depth", 0))
        return line.baseline - height, line.baseline + depth

    @staticmethod
    def _is_box_node(node):
        node_type = getattr(node, "node_type", None)
        return node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT)

    @staticmethod
    def _normalize_glue_name(name):
        if name is None:
            return ""
        return str(name).lstrip("\\").lower()

    def _is_topskip_glue(self, node):
        if getattr(node, "node_type", None) != nd.NODE_TYPE.GLUE:
            return False
        return "topskip" in self._normalize_glue_name(getattr(node, "name", None))

    def _box_has_direct_topskip(self, node):
        if getattr(node, "node_type", None) != nd.NODE_TYPE.VLIST:
            return False
        for child in getattr(node, "list", None) or ():
            if self._is_topskip_glue(child):
                return True
        return False

    def _subtree_has_topskip(self, node, memo=None):
        if memo is None:
            memo = {}
        key = id(node)
        cached = memo.get(key)
        if cached is not None:
            return cached
        if self._is_topskip_glue(node):
            memo[key] = True
            return True
        for child in getattr(node, "list", None) or ():
            if self._subtree_has_topskip(child, memo):
                memo[key] = True
                return True
        memo[key] = False
        return False

    def _iter_box_children_with_positions(self, box, left, top):
        node_type = getattr(box, "node_type", None)
        left = Dimen(left)
        top = Dimen(top)
        if node_type in (nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
            items = getattr(box, "list", None) or ()
            glue_state = self._glue_state(box)
            v = Dimen(top)
            x = Dimen(left)
            for index, node in enumerate(items):
                child_type = getattr(node, "node_type", None)
                if child_type == nd.NODE_TYPE.GLUE:
                    v += Dimen(integer=self._effective_glue_amount(node, box, glue_state))
                    continue
                if child_type == nd.NODE_TYPE.KERN:
                    v += Dimen(getattr(node, "kern", 0))
                    continue
                if child_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                    continue
                child_left = x + Dimen(getattr(node, "shifted", 0))
                child_top = Dimen(v)
                yield index, node, child_left, child_top
                v += Dimen(getattr(node, "height", 0) + getattr(node, "depth", 0))
            return
        if node_type != nd.NODE_TYPE.HLIST:
            return
        items = getattr(box, "list", None) or ()
        glue_state = self._glue_state(box)
        h = Dimen(left)
        baseline = top + Dimen(getattr(box, "height", 0))
        for index, node in enumerate(items):
            child_type = getattr(node, "node_type", None)
            if child_type == nd.NODE_TYPE.GLUE:
                h += Dimen(integer=self._effective_glue_amount(node, box, glue_state))
                continue
            if child_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                h += Dimen(getattr(node, "kern", 0))
                continue
            if child_type == nd.NODE_TYPE.DISC:
                h += Dimen(getattr(node, "replace_width", 0))
                continue
            width = Dimen(getattr(node, "width", 0))
            if child_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                child_left = Dimen(h)
                child_top = baseline + Dimen(getattr(node, "shifted", 0)) - Dimen(getattr(node, "height", 0))
                yield index, node, child_left, child_top
            h += width

    def _subtree_has_flow_content(self, node):
        node_type = getattr(node, "node_type", None)
        if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.ALIGNMENT):
            return True
        if node_type == nd.NODE_TYPE.HLIST and self._display_math_owner(node) is not None:
            return True
        for child in getattr(node, "list", None) or ():
            if self._subtree_has_flow_content(child):
                return True
        return False

    def _mark_region_subtree(self, node, region, mapping, allow_override=True):
        if not self._is_box_node(node):
            return
        key = id(node)
        if allow_override or mapping.get(key) != "body":
            mapping[key] = region
        for child in getattr(node, "list", None) or ():
            self._mark_region_subtree(child, region, mapping, allow_override=allow_override)

    def _find_structural_body_slot(self, root):
        by_topskip = self._find_structural_body_slot_by_topskip(root)
        if by_topskip is not None:
            return by_topskip
        explicit = self._find_structural_body_slot_by_page_partition(root)
        if explicit is not None:
            return explicit
        return self._find_structural_body_slot_by_vsize(root)

    def _find_structural_body_slot_by_topskip(self, root):
        target_h = int(Dimen(self.parser.layout["vsize"]))
        target_w = int(Dimen(self.parser.layout["hsize"]))
        topskip_cache = {}

        def score(node, depth, allow_nested_topskip):
            direct_topskip = self._box_has_direct_topskip(node)
            has_topskip = direct_topskip or (
                allow_nested_topskip and self._subtree_has_topskip(node, topskip_cache)
            )
            if not has_topskip:
                return None
            has_content = self._subtree_has_flow_content(node)
            height = int(getattr(node, "height", 0) + getattr(node, "depth", 0))
            width = int(getattr(node, "width", 0))
            height_penalty = abs(height - target_h) if target_h > 0 else 0
            width_penalty = abs(width - target_w) if target_w > 0 else 0
            content_penalty = 0 if has_content else 1_000_000
            return (
                1 if direct_topskip else 0,
                1 if has_content else 0,
                depth,
                -(height_penalty + width_penalty + content_penalty),
            )

        def collect(allow_nested_topskip):
            best = None

            def walk(box, left, top, path):
                nonlocal best
                if not self._is_box_node(box):
                    return
                for index, child, child_left, child_top in self._iter_box_children_with_positions(box, left, top):
                    child_path = path + [(box, index)]
                    if getattr(child, "node_type", None) == nd.NODE_TYPE.VLIST:
                        candidate_score = score(child, len(child_path), allow_nested_topskip)
                        if candidate_score is not None:
                            slot = _StructuralBodySlot(
                                parent=box,
                                index=index,
                                body=child,
                                left=child_left,
                                top=child_top,
                                path=child_path,
                            )
                            if best is None or candidate_score > best[0]:
                                best = (candidate_score, slot)
                    walk(child, child_left, child_top, child_path)

            root_score = None
            if getattr(root, "node_type", None) == nd.NODE_TYPE.VLIST:
                root_score = score(root, 0, allow_nested_topskip)
            if root_score is not None:
                best = (
                    root_score,
                    _StructuralBodySlot(parent=None, index=-1, body=root, left=Dimen(), top=Dimen(), path=[]),
                )
            walk(root, Dimen(), Dimen(), [])
            return best[1] if best is not None else None

        slot = collect(False)
        if slot is not None:
            return slot
        return collect(True)

    def _find_structural_body_slot_by_page_partition(self, root):
        """
        Prefer the shipped-page structure:
        header(vlist) + glue + glue + body(vlist) + footer...
        """
        best = None
        target_h = int(Dimen(self.parser.layout["vsize"]))

        def walk(node, depth=0):
            nonlocal best
            if getattr(node, "node_type", None) != nd.NODE_TYPE.VLIST:
                for child in getattr(node, "list", None) or ():
                    if self._is_box_node(child):
                        walk(child, depth + 1)
                return

            items = list(getattr(node, "list", None) or ())
            if len(items) >= 4:
                a, b, c, d = items[0], items[1], items[2], items[3]
                if (
                    getattr(a, "node_type", None) == nd.NODE_TYPE.VLIST
                    and getattr(b, "node_type", None) == nd.NODE_TYPE.GLUE
                    and getattr(c, "node_type", None) == nd.NODE_TYPE.GLUE
                    and getattr(d, "node_type", None) == nd.NODE_TYPE.VLIST
                ):
                    body_h = int(getattr(d, "height", 0) + getattr(d, "depth", 0))
                    if target_h > 0:
                        penalty = abs(body_h - target_h)
                    else:
                        penalty = 0
                    score = (depth, -penalty)
                    if best is None or score > best[0]:
                        best = (score, node, 3, d)
            for child in items:
                if self._is_box_node(child):
                    walk(child, depth + 1)

        walk(root)
        if best is None:
            return None
        _score, parent, index, body = best
        located = self._locate_box_in_vlist(root, body, Dimen(), Dimen())
        if located is None:
            left, top = Dimen(), Dimen()
        else:
            left, top = located
        return _StructuralBodySlot(parent=parent, index=index, body=body, left=left, top=top, path=[(parent, index)])

    def _find_structural_body_slot_by_vsize(self, root):
        target_h = int(Dimen(self.parser.layout["vsize"]))
        target_w = int(Dimen(self.parser.layout["hsize"]))
        if target_h <= 0:
            return None

        best = None

        def walk(node, depth=0):
            nonlocal best
            if getattr(node, "node_type", None) != nd.NODE_TYPE.VLIST:
                for child in getattr(node, "list", None) or ():
                    if self._is_box_node(child):
                        walk(child, depth + 1)
                return
            items = list(getattr(node, "list", None) or ())
            for idx, child in enumerate(items):
                if getattr(child, "node_type", None) != nd.NODE_TYPE.VLIST:
                    continue
                child_h = int(getattr(child, "height", 0) + getattr(child, "depth", 0))
                if child_h != target_h:
                    continue
                child_w = int(getattr(child, "width", 0))
                width_penalty = abs(child_w - target_w) if target_w > 0 and child_w > 0 else 0
                # Prefer deeper exact-vsize matches with body-like content.
                content_bonus = 0 if self._subtree_has_flow_content(child) else 1_000_000
                score = (depth, -(width_penalty + content_bonus))
                if best is None or score > best[0]:
                    best = (score, node, idx, child)
            for child in items:
                if self._is_box_node(child):
                    walk(child, depth + 1)

        walk(root)
        if best is None:
            return None
        _score, parent, index, body = best
        located = self._locate_box_in_vlist(root, body, Dimen(), Dimen())
        if located is None:
            left, top = Dimen(), Dimen()
        else:
            left, top = located
        return _StructuralBodySlot(parent=parent, index=index, body=body, left=left, top=top, path=[(parent, index)])

    def _page_region_map(self, page):
        slot = self._find_structural_body_slot(page)
        mapping = {}
        if slot is None:
            return mapping
        self._mark_region_subtree(slot.body, "body", mapping)
        for parent, child_index in reversed(slot.path):
            siblings = list(getattr(parent, "list", None) or ())
            parent_type = getattr(parent, "node_type", None)
            if parent_type in (nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                for sibling in siblings[:child_index]:
                    if self._subtree_has_flow_content(sibling):
                        self._mark_region_subtree(sibling, "header", mapping, allow_override=False)
                for sibling in siblings[child_index + 1:]:
                    if self._subtree_has_flow_content(sibling):
                        self._mark_region_subtree(sibling, "footer", mapping, allow_override=False)
                continue
            if parent_type == nd.NODE_TYPE.HLIST:
                for sibling in siblings[:child_index]:
                    if self._subtree_has_flow_content(sibling):
                        self._mark_region_subtree(sibling, "body", mapping, allow_override=False)
                for sibling in siblings[child_index + 1:]:
                    if self._subtree_has_flow_content(sibling):
                        self._mark_region_subtree(sibling, "body", mapping, allow_override=False)
        return mapping

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

    @staticmethod
    def _docx_font_style(font):
        backend = getattr(font, "backend", None)
        source_name = (
            getattr(backend, "docx_style_source_name", None)
            or getattr(backend, "name", None)
            or ""
        )
        name = source_name.lower()
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
        explicit = getattr(backend, "docx_font_name", None)
        if explicit and cls._docx_usable_font_name(explicit):
            return explicit
        name = getattr(backend, "name", None)
        if getattr(backend, "kind", None) == "opentype" and cls._docx_usable_font_name(name):
            return name
        return _DOCX_DEFAULT_TEXT_FONT

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

    def _line_run_plain_text(self, run):
        if isinstance(run, _TextRun):
            return run.text
        if isinstance(run, _InlineBoxRun):
            return self._inline_box_text(run)
        return ""

    def _can_use_visual_text_runs(self, runs):
        has_inline_box = False
        for run in runs:
            if isinstance(run, _TextRun):
                continue
            if isinstance(run, _InlineBoxRun):
                has_inline_box = True
                if self._inline_box_contains_math(run):
                    return False
                if self._inline_box_multiline_specs(run):
                    return False
                if self._math_source_field(run.box) is not None:
                    return False
                continue
            return False
        return has_inline_box

    @staticmethod
    def _compact_order_text(text):
        return "".join(ch for ch in text if not ch.isspace())

    def _visual_text_runs_for_line(self, line_spec, line_runs):
        if not self._can_use_visual_text_runs(line_runs):
            return None
        box = getattr(line_spec, "box", None)
        if box is None:
            return None
        glyphs: list[_Glyph] = []
        self._capture_hlist(box, 0, 0, glyphs)
        if not glyphs:
            return None
        current = self._compact_order_text(
            "".join(self._line_run_plain_text(run) for run in line_runs)
        )
        visual = self._compact_order_text(
            "".join(g.text for g in sorted(glyphs, key=lambda g: (g.x, g.y)))
        )
        if not current or current == visual:
            return None
        return self._runs_from_glyphs(glyphs)

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
    def _clamp_char_spacing_twips(value):
        value = int(value)
        if value > 31680:
            return 31680
        if value < -31680:
            return -31680
        return value

    @staticmethod
    def _line_has_fixed_segments(runs):
        return any(isinstance(run, (_InlineBoxRun, _InlineMathRun)) for run in runs)

    @staticmethod
    def _docx_alignment(alignment):
        if alignment == WD_ALIGN_PARAGRAPH.JUSTIFY:
            return WD_ALIGN_PARAGRAPH.LEFT
        return alignment

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
        spacing.set(
            qn("w:val"),
            str(DocxBackend._clamp_char_spacing_twips(spacing_twips)),
        )

    def _collapsed_space_spacing(self, left, right):
        font = left.font or right.font
        nominal = self._space_width(font)
        total_spaces = len(left.text) + len(right.text)
        removed_spaces = max(0, total_spaces - 1)
        removed_twips = self._spacing_twips(removed_spaces * nominal)
        return left.spacing_twips + right.spacing_twips + removed_twips

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
            yield ("display", display_owner, box, int(baseline))
            return
        items = getattr(box, "list", None) or ()
        has_inline = self._box_has_direct_inline_content(box)
        has_inline_tree = self._node_has_inline_text(box)
        has_vlist_child = any(getattr(node, "node_type", None) == nd.NODE_TYPE.VLIST for node in items)
        # If this HLIST already carries direct inline material, keep it atomic.
        # Descending into nested VLISTs in this case tears inline math fractions
        # into fake paragraph lines.
        if has_inline:
            yield ("line", _LineEvent(owner=owner, baseline=int(baseline), box=box))
            return
        # Treat inline-text hbox wrappers (including ownerless \box/\copy material)
        # as atomic lines when they don't carry nested vertical structure.
        if has_inline_tree and not has_vlist_child:
            yield ("line", _LineEvent(owner=owner, baseline=int(baseline), box=box))
            return
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
        # Keep paragraph-owner wrappers (which may contain nested line boxes only)
        # and ownerless inline headline/footline boxes as standalone lines.
        if not emitted_descendant and (owner is not None or has_inline or has_inline_tree):
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
        active_alignment = None
        for node in items:
            if active_alignment is not None and not self._node_belongs_to_alignment(node, active_alignment):
                active_alignment = None
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.ALIGNMENT:
                owner = self._display_alignment_owner(node)
                if owner is not None:
                    yield ("alignment", owner, True, node, int(v))
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                amount = self._effective_glue_amount(node, box, glue_state)
                if active_alignment is None:
                    yield ("glue", node, Dimen(integer=amount))
                v += amount
                continue
            if node_type == nd.NODE_TYPE.KERN:
                amount = int(node.kern)
                if active_alignment is None:
                    yield ("kern", node, Dimen(integer=amount))
                v += amount
                continue
            if node_type == nd.NODE_TYPE.PENALTY:
                if active_alignment is None:
                    yield ("penalty", node)
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                owner = self._alignment_owner(node)
                if owner is not None:
                    if active_alignment is None:
                        yield ("alignment", owner, False, node, int(v))
                        active_alignment = owner
                    v += int(getattr(node, "height", 0) + getattr(node, "depth", 0))
                    continue
                shifted = int(getattr(node, "shifted", 0))
                baseline = v + int(getattr(node, "height", 0))
                yield from self._walk_hlist(node, baseline)
                v += int(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue
            if node_type == nd.NODE_TYPE.VLIST:
                yield from self._walk_vlist(node, v)
                v += int(getattr(node, "height", 0) + getattr(node, "depth", 0))
                continue

    @staticmethod
    def _xml_space_attr(text):
        return ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""

    @staticmethod
    def _xml_safe_text(text):
        if not text:
            return ""
        out = []
        for ch in text:
            code = ord(ch)
            if ch in ("\t", "\n", "\r"):
                out.append(ch)
                continue
            if 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF:
                out.append(ch)
        return "".join(out)

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
            text = _MATH_OPERATORS_MAP.get(code)
            if text is not None:
                return text
        elif symbol.fam == 1:
            text = _MATH_LETTERS_MAP.get(code)
            if text is not None:
                return text
        elif symbol.fam == 2:
            text = _MATH_SYMBOLS_MAP.get(code)
            if text is not None:
                return text
        elif symbol.fam == 3:
            text = _MATH_LARGE_SYMBOLS_MAP.get(code)
            if text is not None:
                return text
            text = _MATH_SYMBOLS_MAP.get(code)
            if text is not None:
                return text
        if self._printable_char(symbol.char):
            return symbol.char
        return None

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

    def _delimiter_text(self, delim):
        if delim is None:
            return ""
        symbol = getattr(delim, "small", None) or getattr(delim, "large", None)
        if symbol is None:
            return ""
        text = self._math_symbol_text(symbol)
        return "" if text is None else text

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

    def _display_math_run_xml(self, story_part, box, line_depth=None, total_height=None):
        effective_depth = Dimen(getattr(box, "depth", 0))
        if line_depth is not None and line_depth > effective_depth:
            effective_depth = Dimen(line_depth)
        total_height = Dimen(total_height) if total_height is not None else Dimen(getattr(box, "height", 0)) + effective_depth
        svg_bytes = self._svg_bytes_for_box(box, total_height=total_height)
        return self._inline_svg_picture_run_xml(
            story_part,
            svg_bytes,
            self._svg_box_width(box),
            total_height,
            depth=effective_depth,
        )

    def _display_spacer_run_xml(self, width):
        width = max(self._pt(width), 0.0)
        if width <= 0:
            return None
        return parse_xml(
            (
                "<w:r "
                "xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\" "
                "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" "
                "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
                "xmlns:wps=\"http://schemas.microsoft.com/office/word/2010/wordprocessingShape\">"
                "<w:rPr><w:noProof/></w:rPr>"
                f"{self._drawingml_textbox_xml('<w:txbxContent><w:p/></w:txbxContent>', width, 1.0)}"
                "</w:r>"
            )
        )

    def _display_item_width(self, node, box=None, glue_state=None):
        node_type = getattr(node, "node_type", None)
        if node_type == nd.NODE_TYPE.KERN:
            return Dimen(getattr(node, "kern", 0))
        if node_type == nd.NODE_TYPE.GLUE:
            if box is not None and hasattr(box, "glue_ratio"):
                return Dimen(integer=self._effective_glue_amount(node, box, glue_state))
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
        glue_state = self._glue_state(spec.box)
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
            gap += self._display_item_width(item, box=spec.box, glue_state=glue_state)
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

    def _unwrap_passthrough_hlist(self, box):
        current = box
        while getattr(current, "node_type", None) == nd.NODE_TYPE.HLIST:
            items = list(getattr(current, "list", None) or ())
            if self._box_has_direct_inline_content(current):
                break
            if len(items) != 1:
                break
            child = items[0]
            if getattr(child, "node_type", None) != nd.NODE_TYPE.HLIST:
                break
            if Dimen(getattr(current, "shifted", 0)) != 0:
                break
            if Dimen(getattr(current, "width", 0)) != Dimen(getattr(child, "width", 0)):
                break
            if Dimen(getattr(current, "height", 0)) != Dimen(getattr(child, "height", 0)):
                break
            if Dimen(getattr(current, "depth", 0)) != Dimen(getattr(child, "depth", 0)):
                break
            current = child
        return current

    def _runs_from_line_box(self, box, math_state=None):
        target = self._unwrap_passthrough_hlist(box)
        if not self._can_use_box_runs(target):
            return []
        runs = self._runs_from_box(target, math_state)
        if math_state is not None and math_state.has_nodes():
            runs.extend(self._finalize_inline_math_state(math_state, keep_open=True, line_box=target))
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
                    child_items = list(getattr(node, "list", None) or ())
                    if (
                        not self._box_has_direct_inline_content(node)
                        and len(child_items) == 1
                        and getattr(child_items[0], "node_type", None) == nd.NODE_TYPE.HLIST
                        and Dimen(getattr(node, "width", 0)) == Dimen(getattr(child_items[0], "width", 0))
                        and Dimen(getattr(node, "height", 0)) == Dimen(getattr(child_items[0], "height", 0))
                        and Dimen(getattr(node, "depth", 0)) == Dimen(getattr(child_items[0], "depth", 0))
                        and Dimen(getattr(node, "shifted", 0)) == 0
                    ):
                        runs.extend(child_runs)
                        index += 1
                        continue
                    runs.append(
                        _InlineBoxRun(
                            node,
                            self._normalize_runs(child_runs),
                            Dimen(getattr(box, "depth", 0)),
                        )
                    )
                    index += 1
                    continue
                if self._box_has_extent(node):
                    runs.append(
                        _InlineBoxRun(
                            node,
                            [],
                            Dimen(getattr(box, "depth", 0)),
                        )
                    )
                    index += 1
                    continue
                index += 1
                continue
            if node_type == nd.NODE_TYPE.VLIST:
                has_payload = (
                    bool(getattr(node, "list", None))
                    or Dimen(getattr(node, "width", 0)) > 0
                    or Dimen(getattr(node, "height", 0)) > 0
                    or Dimen(getattr(node, "depth", 0)) > 0
                )
                if has_payload:
                    runs.append(
                        _InlineBoxRun(
                            node,
                            [],
                            Dimen(getattr(box, "depth", 0)),
                        )
                    )
                index += 1
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                amount = self._effective_glue_amount(node, box, glue_state)
                if amount <= 0:
                    index += 1
                    continue
                font = self._space_font(runs, items, index)
                self._append_explicit_spacing_run(runs, Dimen(integer=amount), font)
                index += 1
                continue
            if node_type == nd.NODE_TYPE.KERN:
                amount = Dimen(getattr(node, "kern", 0))
                if self._kern_is_text_kern(items, index):
                    self._apply_text_kern(runs, node.kern)
                    index += 1
                    continue
                if amount > 0:
                    self._append_explicit_spacing_run(
                        runs,
                        amount,
                        self._space_font(runs, items, index),
                    )
                index += 1
                continue
            if node_type == nd.NODE_TYPE.DISC:
                runs.extend(self._runs_from_box(node))
                index += 1
                continue
            index += 1
        return runs

    @staticmethod
    def _box_has_extent(node):
        if getattr(node, "node_type", None) not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            return False
        return (
            Dimen(getattr(node, "width", 0)) > 0
            or Dimen(getattr(node, "height", 0)) > 0
            or Dimen(getattr(node, "depth", 0)) > 0
        )

    @staticmethod
    def _coerce_dimen(value):
        if isinstance(value, Dimen):
            return value
        if isinstance(value, int):
            return Dimen(integer=value)
        return Dimen(value)

    def _append_explicit_spacing_run(self, runs, width, font):
        width = self._coerce_dimen(width)
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
    def _node_has_inline_anchor(node):
        node_type = getattr(node, "node_type", None)
        if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.DISC, nd.NODE_TYPE.RULE):
            return True
        if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            if (
                Dimen(getattr(node, "width", 0)) > 0
                or Dimen(getattr(node, "height", 0)) > 0
                or Dimen(getattr(node, "depth", 0)) > 0
            ):
                return True
            for child in getattr(node, "list", None) or ():
                if DocxBackend._node_has_inline_anchor(child):
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
            if isinstance(run, (_InlineBoxRun, _InlineMathRun)):
                return
            if isinstance(run, _TextRun) and run.text and not run.text.isspace():
                run.spacing_twips += spacing
                return

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
        hbox.typeset(self.parser)
        cursor = Dimen()
        rightmost = Dimen()
        height = Dimen()
        depth = Dimen()
        source_box = line_box if line_box is not None else hbox
        glue_state = self._glue_state(source_box)

        def _consume_advance(advance, node=None):
            nonlocal cursor, rightmost
            advance = Dimen(advance)
            extent = advance
            if node is not None:
                rightmost_fn = getattr(node, "rightmost", None)
                if callable(rightmost_fn):
                    try:
                        candidate = Dimen(rightmost_fn())
                    except Exception:
                        candidate = None
                    if candidate is not None and candidate > extent:
                        extent = candidate
            if cursor + extent > rightmost:
                rightmost = cursor + extent
            cursor += advance

        for node in nodes:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                _consume_advance(Dimen(integer=self._effective_glue_amount(node, source_box, glue_state)))
                continue
            if node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                _consume_advance(Dimen(getattr(node, "kern", 0)))
                continue
            if node_type == nd.NODE_TYPE.DISC:
                _consume_advance(Dimen(getattr(node, "replace_width", 0)))
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
            _consume_advance(Dimen(node_width), node=node)
            height = max(height, Dimen(getattr(node, "height", 0)) - shifted)
            depth = max(depth, Dimen(getattr(node, "depth", 0)) + shifted)
        if line_box is not None:
            natural = getattr(line_box, "natural", None)
            if natural is not None:
                hbox.natural = natural
            if hasattr(line_box, "glue_ratio"):
                hbox.glue_ratio = line_box.glue_ratio
            if hasattr(line_box, "spread"):
                hbox.spread = getattr(line_box, "spread")
        hbox.width = max(cursor, rightmost)
        hbox.height = height
        hbox.depth = depth
        span_width = self._line_node_span_width(line_box, nodes) if line_box is not None else None
        if span_width is not None:
            hbox.width = span_width
        return hbox

    def _line_node_span_width(self, line_box, nodes):
        if line_box is None or not nodes:
            return None
        items = getattr(line_box, "list", None) or ()
        if not items:
            return None
        wanted = {id(node) for node in nodes}
        glue_state = self._glue_state(line_box)
        cursor = Dimen()
        span_start = None
        span_end = None
        for node in items:
            advance, extent = self._line_item_advance_and_extent(node, line_box, glue_state)
            if id(node) in wanted:
                if span_start is None:
                    span_start = Dimen(cursor)
                node_end = cursor + extent
                if span_end is None or node_end > span_end:
                    span_end = node_end
            cursor += advance
        if span_start is None or span_end is None:
            return None
        span = span_end - span_start
        return span if span > 0 else Dimen()

    def _line_item_advance_and_extent(self, node, line_box, glue_state):
        node_type = getattr(node, "node_type", None)
        if node_type == nd.NODE_TYPE.GLUE:
            amount = Dimen(integer=self._effective_glue_amount(node, line_box, glue_state))
            return amount, amount
        if node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
            amount = Dimen(getattr(node, "kern", 0))
            return amount, amount
        if node_type == nd.NODE_TYPE.DISC:
            amount = Dimen(getattr(node, "replace_width", 0))
            return amount, amount
        advance = Dimen(getattr(node, "width", 0))
        extent = advance
        rightmost_fn = getattr(node, "rightmost", None)
        if callable(rightmost_fn):
            try:
                rightmost = Dimen(rightmost_fn())
                if rightmost > extent:
                    extent = rightmost
            except Exception:
                pass
        return advance, extent

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
        runs = []
        self._append_explicit_spacing_run(runs, leading_kern, font)
        runs.append(
            _InlineMathRun(
                box=box,
                line_depth=line_depth,
            )
        )
        self._append_explicit_spacing_run(runs, trailing_kern, font)
        return runs

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
    def _is_text_run_nonempty(run):
        return isinstance(run, _TextRun) and bool(run.text)

    def _vbox_inline_line_runs(self, box):
        lines = []
        for node in getattr(box, "list", None) or ():
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.HLIST:
                runs = self._runs_from_line_box(node, _InlineMathState())
                if not runs:
                    runs = self._runs_from_box(node, _InlineMathState())
                runs = self._normalize_runs(runs)
                if runs and any(self._is_text_run_nonempty(run) or isinstance(run, (_InlineBoxRun, _InlineMathRun)) for run in runs):
                    lines.append(runs)
                continue
            if node_type == nd.NODE_TYPE.VLIST:
                lines.extend(self._vbox_inline_line_runs(node))
        return lines

    def _vbox_inline_line_boxes(self, box):
        line_boxes = []
        for node in getattr(box, "list", None) or ():
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.HLIST:
                line_boxes.append(node)
                continue
            if node_type == nd.NODE_TYPE.VLIST:
                line_boxes.extend(self._vbox_inline_line_boxes(node))
        return line_boxes

    def _vbox_inline_line_specs(self, box):
        alignment_specs = self._vbox_inline_alignment_line_specs(box)
        if alignment_specs:
            return alignment_specs
        specs = []
        pending_gap = Dimen()
        glue_state = self._glue_state(box)
        for node in getattr(box, "list", None) or ():
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                pending_gap += Dimen(integer=self._effective_glue_amount(node, box, glue_state))
                continue
            if node_type == nd.NODE_TYPE.KERN:
                pending_gap += Dimen(getattr(node, "kern", 0))
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                runs = self._runs_from_line_box(node, _InlineMathState())
                if not runs:
                    runs = self._runs_from_box(node, _InlineMathState())
                runs = self._normalize_runs(runs)
                if not runs:
                    continue
                if not any(
                    self._is_text_run_nonempty(run) or isinstance(run, (_InlineBoxRun, _InlineMathRun))
                    for run in runs
                ):
                    continue
                specs.append(
                    _InlineBoxLineSpec(
                        runs=runs,
                        line_height=Dimen(getattr(node, "height", 0) + getattr(node, "depth", 0)),
                        line_depth=Dimen(getattr(node, "depth", 0)),
                        gap_before=self._nonnegative_dimen(pending_gap),
                    )
                )
                pending_gap = Dimen()
                continue
            if node_type == nd.NODE_TYPE.VLIST:
                child_specs = self._vbox_inline_line_specs(node)
                if child_specs:
                    child_specs[0].gap_before = self._nonnegative_dimen(
                        child_specs[0].gap_before + pending_gap
                    )
                    pending_gap = Dimen()
                    specs.extend(child_specs)
                continue
        return specs

    def _vbox_inline_alignment_line_specs(self, box):
        items = list(getattr(box, "list", None) or ())
        dominant_owner = None
        row_count = 0
        for node in items:
            if getattr(node, "node_type", None) != nd.NODE_TYPE.HLIST:
                continue
            owner = self._alignment_owner(node)
            if owner is None:
                continue
            if dominant_owner is None:
                dominant_owner = owner
                row_count = 1
                continue
            if owner is dominant_owner:
                row_count += 1
        if dominant_owner is None or row_count < 2:
            return []

        specs = []
        pending_gap = Dimen()
        glue_state = self._glue_state(box)
        for node in items:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                pending_gap += Dimen(integer=self._effective_glue_amount(node, box, glue_state))
                continue
            if node_type == nd.NODE_TYPE.KERN:
                pending_gap += Dimen(getattr(node, "kern", 0))
                continue
            if node_type == nd.NODE_TYPE.RULE:
                # For now, keep alignment rows faithful and ignore rule thickness;
                # rules can later map to textbox borders/cell borders.
                continue
            if node_type == nd.NODE_TYPE.VLIST:
                child_specs = self._vbox_inline_alignment_line_specs(node)
                if child_specs:
                    child_specs[0].gap_before = self._nonnegative_dimen(
                        child_specs[0].gap_before + pending_gap
                    )
                    pending_gap = Dimen()
                    specs.extend(child_specs)
                continue
            if node_type != nd.NODE_TYPE.HLIST:
                continue
            if self._alignment_owner(node) is not dominant_owner:
                continue
            runs = self._runs_from_line_box(node, _InlineMathState())
            if not runs:
                runs = self._runs_from_box(node, _InlineMathState())
            runs = self._normalize_runs(runs)
            if not runs:
                continue
            specs.append(
                _InlineBoxLineSpec(
                    runs=runs,
                    line_height=Dimen(getattr(node, "height", 0) + getattr(node, "depth", 0)),
                    line_depth=Dimen(getattr(node, "depth", 0)),
                    gap_before=self._nonnegative_dimen(pending_gap),
                )
            )
            pending_gap = Dimen()
        return specs

    def _inline_box_multiline_specs(self, box_run):
        box = box_run.box
        node_type = getattr(box, "node_type", None)
        if node_type == nd.NODE_TYPE.VLIST:
            return self._vbox_inline_line_specs(box)
        if node_type != nd.NODE_TYPE.HLIST:
            return []
        specs = []
        for child in getattr(box, "list", None) or ():
            if getattr(child, "node_type", None) != nd.NODE_TYPE.VLIST:
                continue
            specs.extend(self._vbox_inline_line_specs(child))
        return specs

    @staticmethod
    def _font_line_measure(font):
        at = getattr(font, "at", None)
        return Dimen(at) if at is not None else Dimen()

    def _inline_chunk_line_measure(self, chunk):
        if isinstance(chunk, _TextRun):
            return self._font_line_measure(chunk.font)
        if isinstance(chunk, _InlineBoxRun):
            return self._inline_box_line_measure(chunk)
        if isinstance(chunk, _InlineMathRun):
            return Dimen(getattr(chunk.box, "height", 0) + getattr(chunk.box, "depth", 0))
        return Dimen()

    def _inline_box_line_measure(self, box_run):
        required = Dimen(getattr(box_run.box, "height", 0) + getattr(box_run.box, "depth", 0))
        for chunk in box_run.chunks:
            required = max(required, self._inline_chunk_line_measure(chunk))
        return required

    def _inline_box_contains_math(self, box_run):
        for chunk in box_run.chunks:
            if isinstance(chunk, _InlineMathRun):
                return True
            if isinstance(chunk, _InlineBoxRun) and self._inline_box_contains_math(chunk):
                return True
        return False

    def _line_run_line_measure(self, run):
        if isinstance(run, _InlineBoxRun):
            return self._inline_box_line_measure(run)
        return self._inline_chunk_line_measure(run)

    def _line_spec_line_measure(self, line_spec):
        required = Dimen()
        for run in getattr(line_spec, "runs", ()) or ():
            required = max(required, self._line_run_line_measure(run))
        return required

    def _inline_box_has_renderable_content(self, box_run):
        return (
            Dimen(getattr(box_run.box, "width", 0)) > 0
            or bool(box_run.chunks)
            or bool(self._inline_box_multiline_specs(box_run))
            or bool(self._inline_box_text(box_run))
        )

    def _inline_box_has_visible_content(self, box_run):
        if self._inline_box_multiline_specs(box_run):
            return True
        text = self._inline_box_text(box_run)
        return bool(text and text.strip())

    def _run_is_visible(self, run):
        if isinstance(run, _TextRun):
            text = self._xml_safe_text(run.text)
            return bool(text and text.strip())
        if isinstance(run, _InlineMathRun):
            return True
        if isinstance(run, _InlineBoxRun):
            return self._inline_box_has_visible_content(run)
        return False

    def _line_spec_will_emit(self, line_spec):
        runs = getattr(line_spec, "runs", ()) or ()
        return any(self._run_is_visible(run) for run in runs)

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
        font = self._first_font(box_run.box)
        line_height = self._inline_box_line_measure(box_run)
        depth_half_points = int(round(self._pt(getattr(box_run.box, "depth", 0)) * 2.0))
        alignment, left_indent, right_indent = self._box_inline_layout(box_run.box)
        jc = "left"
        if alignment == WD_ALIGN_PARAGRAPH.CENTER:
            jc = "center"
        elif alignment == WD_ALIGN_PARAGRAPH.RIGHT:
            jc = "right"
        ind_parts = []
        left_twips = self._fit_text_twips(left_indent)
        right_twips = self._fit_text_twips(right_indent)
        if left_twips > 0:
            ind_parts.append(f"w:left=\"{left_twips}\"")
        if right_twips > 0:
            ind_parts.append(f"w:right=\"{right_twips}\"")
        ind_xml = f"<w:ind {' '.join(ind_parts)}/>" if ind_parts else ""
        multiline_specs = self._inline_box_multiline_specs(box_run)
        if multiline_specs:
            paragraphs_xml = []
            for line_spec in multiline_specs:
                measured = line_spec.line_height if line_spec.line_height > 0 else line_height
                line_twips = self._fit_text_twips(measured)
                before_twips = self._fit_text_twips(self._nonnegative_dimen(line_spec.gap_before))
                line_depth_half_points = int(round(self._pt(line_spec.line_depth) * 2.0)) if line_spec.line_depth > 0 else 0
                ppr = (
                    "<w:pPr>"
                    f"<w:spacing w:before=\"{before_twips}\" w:after=\"0\" w:lineRule=\"exact\" w:line=\"{line_twips}\"/>"
                    f"<w:jc w:val=\"{jc}\"/>"
                    f"{ind_xml}"
                    "<w:textAlignment w:val=\"baseline\"/>"
                    "</w:pPr>"
                )
                runs_xml = []
                for chunk in line_spec.runs:
                    xml = self._inline_box_chunk_xml(
                        chunk,
                        default_font=self._first_font(box_run.box),
                        position_half_points=line_depth_half_points,
                    )
                    if xml:
                        runs_xml.append(xml)
                paragraphs_xml.append(f"<w:p>{ppr}{''.join(runs_xml)}</w:p>")
            if not paragraphs_xml:
                return "<w:txbxContent><w:p/></w:txbxContent>"
            return f"<w:txbxContent>{''.join(paragraphs_xml)}</w:txbxContent>"
        runs_xml = []
        if not multiline_specs:
            if box_run.chunks:
                for chunk in box_run.chunks:
                    xml = self._inline_box_chunk_xml(
                        chunk,
                        default_font=font,
                        position_half_points=depth_half_points,
                    )
                    if xml:
                        runs_xml.append(xml)
            else:
                text = self._inline_box_text(box_run)
                if not text:
                    return "<w:txbxContent><w:p/></w:txbxContent>"
                runs_xml.append(
                    "<w:r>"
                    f"{self._raw_run_properties_xml(font=font, no_proof=True, position_half_points=depth_half_points)}"
                    f"<w:t{self._xml_space_attr(text)}>{escape(text)}</w:t>"
                    "</w:r>"
                )
            if not runs_xml:
                return "<w:txbxContent><w:p/></w:txbxContent>"
        line_twips = self._fit_text_twips(line_height)
        ppr = (
            "<w:pPr>"
            f"<w:spacing w:before=\"0\" w:after=\"0\" w:lineRule=\"exact\" w:line=\"{line_twips}\"/>"
            f"<w:jc w:val=\"{jc}\"/>"
            f"{ind_xml}"
            "<w:textAlignment w:val=\"baseline\"/>"
            "</w:pPr>"
        )
        return f"<w:txbxContent><w:p>{ppr}{''.join(runs_xml)}</w:p></w:txbxContent>"

    def _explicit_space_run_xml(self, width, font=None, position_half_points=None):
        width = Dimen(width)
        if width <= 0:
            return ""
        nominal_width = Dimen(integer=self._space_width(font))
        delta = int(width - nominal_width)
        spacing_twips = self._spacing_twips(delta)
        text = " "
        return (
            "<w:r>"
            f"{self._raw_run_properties_xml(font=font, spacing_twips=spacing_twips, no_proof=True, position_half_points=position_half_points)}"
            f"<w:t{self._xml_space_attr(text)}>{escape(text)}</w:t>"
            "</w:r>"
        )

    def _inline_box_chunk_xml(self, chunk, default_font=None, position_half_points=None):
        if isinstance(chunk, _TextRun):
            text = self._xml_safe_text(chunk.text)
            if not text:
                return ""
            return (
                "<w:r>"
                f"{self._raw_run_properties_xml(font=chunk.font or default_font, spacing_twips=chunk.spacing_twips, no_proof=True, position_half_points=position_half_points)}"
                f"<w:t{self._xml_space_attr(text)}>{escape(text)}</w:t>"
                "</w:r>"
            )
        if isinstance(chunk, _InlineMathRun):
            text = self._xml_safe_text("".join(self._flatten_math_text(field) for field in chunk.fields))
            if not text:
                text = self._xml_safe_text(self._flatten_box_text(chunk.box))
            if not text:
                return ""
            run_font = self._first_font(chunk.box) or default_font
            target_width = Dimen(getattr(chunk.box, "width", 0))
            text_width = self._text_run_width(text, run_font)
            spacing_twips = self._spacing_twips(int(target_width - text_width))
            return (
                "<w:r>"
                f"{self._raw_run_properties_xml(font=run_font, spacing_twips=spacing_twips, no_proof=True, position_half_points=position_half_points)}"
                f"<w:t{self._xml_space_attr(text)}>{escape(text)}</w:t>"
                "</w:r>"
            )
        if isinstance(chunk, _InlineBoxRun):
            run_font = self._first_font(chunk.box) or default_font
            target_width = Dimen(getattr(chunk.box, "width", 0))
            if chunk.chunks:
                pieces = []
                for subchunk in chunk.chunks:
                    subxml = self._inline_box_chunk_xml(
                        subchunk,
                        default_font=run_font,
                        position_half_points=position_half_points,
                    )
                    if subxml:
                        pieces.append(subxml)
                if pieces:
                    return "".join(pieces)
                return self._explicit_space_run_xml(target_width, run_font, position_half_points)
            text = self._xml_safe_text(self._inline_box_text(chunk))
            if not text:
                return self._explicit_space_run_xml(target_width, run_font, position_half_points)
            text_width = self._text_run_width(text, run_font)
            spacing_twips = self._spacing_twips(int(target_width - text_width))
            return (
                "<w:r>"
                f"{self._raw_run_properties_xml(font=run_font, spacing_twips=spacing_twips, no_proof=True, position_half_points=position_half_points)}"
                f"<w:t{self._xml_space_attr(text)}>{escape(text)}</w:t>"
                "</w:r>"
            )
        return ""

    @staticmethod
    def _textbox_box_width(box):
        width = Dimen(getattr(box, "width", 0))
        rightmost_fn = getattr(box, "rightmost", None)
        if callable(rightmost_fn):
            try:
                rightmost = Dimen(rightmost_fn())
            except Exception:
                rightmost = width
            if rightmost > width:
                width = rightmost
        return width

    def _inline_textbox_run_xml(self, content, box, line_depth=None, anchor="bottom"):
        width = max(self._pt(self._textbox_box_width(box)), 1.0)
        depth = Dimen(getattr(box, "depth", 0))
        extra_pad = (
            Dimen(_INLINE_TEXTBOX_PAD_PT)
            if depth > 0 and anchor == "bottom"
            else Dimen()
        )
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
                "xmlns:wp=\"http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing\" "
                "xmlns:a=\"http://schemas.openxmlformats.org/drawingml/2006/main\" "
                "xmlns:wps=\"http://schemas.microsoft.com/office/word/2010/wordprocessingShape\" "
                "xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\">"
                f"{self._raw_run_properties_xml(no_proof=True, position_half_points=position)}"
                f"{self._drawingml_textbox_xml(content, width, total_height, anchor=anchor)}"
                "</w:r>"
            )
        )

    def _inline_box_run_xml(self, story_part, box_run):
        if not self._inline_box_has_renderable_content(box_run):
            return None
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
        if self._inline_box_contains_math(box_run):
            depth = Dimen(getattr(adjusted_box, "depth", 0))
            total_height = Dimen(getattr(adjusted_box, "height", 0)) + depth
            svg_bytes = self._svg_bytes_for_box(adjusted_box, total_height=total_height)
            return self._inline_svg_picture_run_xml(
                story_part,
                svg_bytes,
                self._svg_box_width(adjusted_box),
                total_height,
                depth=depth,
            )
        return self._inline_textbox_run_xml(
            self._inline_box_content_xml(box_run),
            adjusted_box,
            line_depth=getattr(box_run, "line_depth", 0),
            anchor="top",
        )

    def _inline_math_run_xml(self, story_part, math_run):
        box = math_run.box
        effective_depth = max(
            Dimen(getattr(box, "depth", 0)),
            Dimen(getattr(math_run, "line_depth", 0)),
        )
        total_height = Dimen(getattr(box, "height", 0)) + effective_depth
        svg_bytes = self._svg_bytes_for_box(box, total_height=total_height)
        return self._inline_svg_picture_run_xml(
            story_part,
            svg_bytes,
            self._svg_box_width(box),
            total_height,
            depth=effective_depth,
        )

    def _append_run_chunks(self, para, chunks):
        for chunk in chunks:
            if isinstance(chunk, _InlineBoxRun):
                run_xml = self._inline_box_run_xml(para.part, chunk)
                if run_xml is not None:
                    para._p.append(run_xml)
                continue
            if isinstance(chunk, _InlineMathRun):
                para._p.append(self._inline_math_run_xml(para.part, chunk))
                continue
            text = self._xml_safe_text(chunk.text)
            if not text:
                continue
            run = para.add_run(text)
            self._apply_run_font_with_options(
                run,
                chunk.font,
                allow_word_kerning=False,
            )
            self._apply_run_spacing(run, chunk.spacing_twips)

    def _paragraph_alignment_spec(self, spec):
        owner = None
        box = None
        leading_indent = Dimen()
        for line_spec in spec.lines:
            if line_spec.box is None:
                if self._line_spec_will_emit(line_spec):
                    return None
                continue
            info = self._line_alignment_info(line_spec.box)
            if info is None:
                if self._line_spec_will_emit(line_spec):
                    return None
                continue
            if owner is None:
                owner, box, leading_indent = info
                continue
            if info[0] is not owner:
                return None
        if owner is None:
            return None
        return _AlignmentSpec(
            owner=owner,
            box=box,
            display=self._alignment_is_math(owner),
            space_before=spec.space_before,
            leading_indent=self._nonnegative_dimen(leading_indent),
            region=spec.region,
        )

    def _emit_paragraph(self, document, spec):
        para = document.add_paragraph()
        fmt = para.paragraph_format
        fmt.alignment = WD_ALIGN_PARAGRAPH.LEFT
        # Derive paragraph alignment from TeX edge glues on each line:
        # no edge glues on both sides -> justify both sides; otherwise compare
        # glue orders to choose left/right/center.
        line_alignments = []
        for line_spec in spec.lines:
            if not self._line_spec_will_emit(line_spec):
                continue
            box = getattr(line_spec, "box", None)
            if box is None:
                continue
            line_alignments.append(self._line_paragraph_alignment(box))
        dominant_alignment = None
        if line_alignments and all(aln == line_alignments[0] for aln in line_alignments):
            dominant_alignment = line_alignments[0]
            fmt.alignment = self._docx_alignment(dominant_alignment)
        fmt.space_before = self._length(self._nonnegative_dimen(spec.space_before))
        fmt.space_after = Pt(0)
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        baseline = self.parser.layout["baselineskip"].dimen
        line_spacing = None
        if baseline > 0:
            line_spacing = self._nonnegative_dimen(baseline)
        elif spec.interline_gaps:
            line_spacing = self._nonnegative_dimen(spec.interline_gaps[0])
        # Respect TeX line box height when inline carriers (including empty
        # H/V boxes used as struts/kerns) require a taller line.
        line_box_height = Dimen()
        for line_spec in spec.lines:
            if not self._line_spec_will_emit(line_spec):
                continue
            box = getattr(line_spec, "box", None)
            if box is None:
                box_required = Dimen()
            else:
                box_required = Dimen(getattr(box, "height", 0) + getattr(box, "depth", 0))
            line_box_height = max(line_box_height, box_required, self._line_spec_line_measure(line_spec))
        if line_box_height > 0:
            line_spacing = line_box_height if line_spacing is None else max(line_spacing, line_box_height)
        if line_spacing is not None:
            fmt.line_spacing = self._length(line_spacing)
        if spec.first_line_indent != 0:
            fmt.first_line_indent = self._length(self._nonnegative_dimen(spec.first_line_indent))
        # Ownerless single-line paragraphs (header/footer and standalone \box/\copy
        # material) should honor TeX leading/trailing glue as paragraph layout.
        if spec.owner is None and len(spec.lines) == 1 and spec.lines[0].box is not None:
            alignment, left_indent, right_indent = self._box_inline_layout(spec.lines[0].box)
            fmt.alignment = self._docx_alignment(alignment)
            fmt.left_indent = self._length(left_indent)
            fmt.right_indent = self._length(right_indent)
        wrote_line = False
        for line_spec in spec.lines:
            if not self._line_spec_will_emit(line_spec):
                continue
            if wrote_line:
                para._p.append(self._line_break_run_xml())
            line_runs = list(line_spec.runs)
            visual_runs = self._visual_text_runs_for_line(line_spec, line_runs)
            if visual_runs is not None:
                line_runs = visual_runs
            if dominant_alignment is not None:
                line_runs = self._trim_runs_for_alignment(
                    line_runs,
                    self._docx_alignment(dominant_alignment),
                )
            segments = self._segment_mixed_line_runs(line_runs)
            if segments:
                for segment in segments:
                    self._append_run_chunks(para, segment.runs)
            else:
                self._append_run_chunks(para, line_runs)
            wrote_line = True
        return para

    @staticmethod
    def _trim_runs_for_alignment(line_runs, alignment):
        line_runs = list(line_runs)
        drop_leading = alignment in (WD_ALIGN_PARAGRAPH.RIGHT, WD_ALIGN_PARAGRAPH.CENTER)
        drop_trailing = alignment in (WD_ALIGN_PARAGRAPH.LEFT, WD_ALIGN_PARAGRAPH.CENTER)
        while drop_leading and line_runs and isinstance(line_runs[0], _TextRun):
            trimmed = line_runs[0].text.lstrip()
            if trimmed == line_runs[0].text:
                break
            if trimmed:
                line_runs[0] = _TextRun(trimmed, line_runs[0].font, line_runs[0].spacing_twips)
                break
            line_runs.pop(0)
        while drop_trailing and line_runs and isinstance(line_runs[-1], _TextRun):
            trimmed = line_runs[-1].text.rstrip()
            if trimmed == line_runs[-1].text:
                break
            if trimmed:
                line_runs[-1] = _TextRun(trimmed, line_runs[-1].font, line_runs[-1].spacing_twips)
                break
            line_runs.pop()
        return line_runs

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
                    para.part,
                    box,
                    line_depth=line_depth,
                    total_height=math_total_height if kind == "math" else None,
                )
            if run_xml is not None:
                para._p.append(run_xml)
        return para

    def _alignment_entries(self, owner):
        rows, widths, tabskips = owner._collectEntries(self.parser)
        return rows, widths, tabskips

    def _alignment_content_alignment(self, rows):
        alignments = []
        for _row, entries in rows:
            for entry in entries:
                cell = entry.get("cell")
                if cell is None:
                    continue
                if self._flatten_box_text(cell).strip() == "":
                    continue
                alignment, _left, _right = self._box_inline_layout(cell)
                alignments.append(alignment)
        if not alignments:
            return WD_ALIGN_PARAGRAPH.LEFT
        if all(aln == alignments[0] for aln in alignments):
            return alignments[0]
        return WD_ALIGN_PARAGRAPH.LEFT

    @staticmethod
    def _alignment_cell_raw_nodes(cell):
        raw = getattr(cell, "raw", None)
        if raw is not None:
            return raw
        return getattr(cell, "list", ()) or ()

    def _alignment_is_math(self, owner):
        for row in getattr(owner, "rows", ()):
            for cell in getattr(row, "cells", ()):
                raw_nodes = self._alignment_cell_raw_nodes(cell)
                fields = self._fragment_math_fields(raw_nodes)
                if any(not isinstance(field, str) for field in fields):
                    return True
        return False

    @classmethod
    def _is_alignment_tag_cell(cls, cell):
        raw = list(cls._alignment_cell_raw_nodes(cell))
        if not raw:
            return False
        if getattr(raw[0], "node_type", None) != nd.NODE_TYPE.KERN:
            return False
        non_kern = [node for node in raw if getattr(node, "node_type", None) != nd.NODE_TYPE.KERN]
        if len(non_kern) > 1:
            return False
        for node in raw[:-len(non_kern) or None]:
            if getattr(node, "node_type", None) != nd.NODE_TYPE.KERN:
                return False
        return True

    def _alignment_tag_text(self, cell):
        raw = list(self._alignment_cell_raw_nodes(cell))
        non_kern = [node for node in raw if getattr(node, "node_type", None) != nd.NODE_TYPE.KERN]
        if not non_kern:
            return ""
        fields = self._fragment_math_fields(non_kern)
        text = "".join(self._flatten_math_text(field) for field in fields).strip()
        if text:
            return text
        node = non_kern[0]
        node_type = getattr(node, "node_type", None)
        if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
            return self._glyph_text(node)
        return self._flatten_box_text(node).strip()

    def _text_run_width(self, text, font):
        if not text:
            return Dimen()
        width = Dimen()
        fallback = Dimen(integer=self._space_width(font)) if font is not None else Dimen(6)
        for ch in text:
            if ch == " ":
                width += Dimen(integer=self._space_width(font))
                continue
            if font is not None:
                try:
                    glyph = font[ch]
                except Exception:
                    glyph = None
                if glyph is not None:
                    width += Dimen(getattr(glyph, "width", 0))
                    continue
            width += fallback
        return width

    @classmethod
    def _node_visible_width(cls, node):
        visible = Dimen(getattr(node, "width", 0))
        rightmost = getattr(node, "rightmost", None)
        if callable(rightmost):
            try:
                visible = max(visible, Dimen(rightmost()))
            except Exception:
                pass
        for child in getattr(node, "list", None) or ():
            if getattr(child, "node_type", None) == nd.NODE_TYPE.KERN:
                continue
            visible = max(visible, cls._node_visible_width(child))
        return visible

    def _alignment_cell_visible_width(self, cell):
        width = Dimen(getattr(cell, "width", 0))
        if width > 0:
            return width
        if not self._is_alignment_tag_cell(cell):
            return width
        raw = list(self._alignment_cell_raw_nodes(cell))
        visible = Dimen()
        for node in raw:
            if getattr(node, "node_type", None) == nd.NODE_TYPE.KERN:
                continue
            visible = max(visible, self._node_visible_width(node))
        if visible <= 0:
            visible = self._text_run_width(self._alignment_tag_text(cell), self._first_font(cell))
        return visible

    def _box_inline_layout(self, box):
        if getattr(box, "node_type", None) == nd.NODE_TYPE.HLIST:
            box = self._unwrap_passthrough_hlist(box)
        if getattr(box, "node_type", None) == nd.NODE_TYPE.VLIST:
            alignments = []
            for node in getattr(box, "list", None) or ():
                node_type = getattr(node, "node_type", None)
                if node_type == nd.NODE_TYPE.HLIST:
                    alignments.append(self._line_paragraph_alignment(node))
                    continue
                if node_type == nd.NODE_TYPE.VLIST:
                    child_alignment, _li, _ri = self._box_inline_layout(node)
                    alignments.append(child_alignment)
            if alignments and all(aln == alignments[0] for aln in alignments):
                alignment = alignments[0]
                if alignment == WD_ALIGN_PARAGRAPH.JUSTIFY:
                    alignment = WD_ALIGN_PARAGRAPH.LEFT
                return alignment, Dimen(), Dimen()
            return WD_ALIGN_PARAGRAPH.LEFT, Dimen(), Dimen()
        items = getattr(box, "list", None) or ()
        if not items:
            return WD_ALIGN_PARAGRAPH.LEFT, Dimen(), Dimen()
        glue_state = self._glue_state(box)

        def node_width(node):
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                return Dimen(integer=self._effective_glue_amount(node, box, glue_state))
            if node_type == nd.NODE_TYPE.KERN:
                return Dimen(getattr(node, "kern", 0))
            if node_type == nd.NODE_TYPE.RULE:
                return Dimen(getattr(node, "width", 0))
            if node_type == nd.NODE_TYPE.DISC:
                return Dimen(getattr(node, "replace_width", 0))
            return Dimen(getattr(node, "width", 0))

        def stretch_order(node):
            if getattr(node, "node_type", None) != nd.NODE_TYPE.GLUE:
                return None
            glue = getattr(node, "glue", None)
            if glue is None:
                return None
            stretch = getattr(glue, "stretch", None)
            if stretch is not None and getattr(stretch, "factor", 0) != 0:
                return int(getattr(stretch, "order", 0))
            # Fixed nonzero edge glue still counts as order-0 alignment glue.
            if Dimen(getattr(glue, "dimen", 0)) != 0:
                return 0
            return None

        def edge_order(nodes):
            order = None
            for node in nodes:
                current = stretch_order(node)
                if current is None:
                    continue
                if order is None or current > order:
                    order = current
            return order

        anchor_indexes = [
            index for index, node in enumerate(items) if self._node_has_inline_anchor(node)
        ]
        if len(anchor_indexes) == 1:
            anchor_index = anchor_indexes[0]
            anchor = items[anchor_index]
            if getattr(anchor, "node_type", None) in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                child_alignment, child_left, child_right = self._box_inline_layout(anchor)
                if child_alignment != WD_ALIGN_PARAGRAPH.JUSTIFY:
                    outer_left = Dimen()
                    outer_right = Dimen()
                    for node in items[:anchor_index]:
                        outer_left += node_width(node)
                    for node in items[anchor_index + 1:]:
                        outer_right += node_width(node)
                    return (
                        child_alignment,
                        self._nonnegative_dimen(outer_left + child_left),
                        self._nonnegative_dimen(outer_right + child_right),
                    )

        start = 0
        end = len(items) - 1
        while start <= end and not self._node_has_inline_anchor(items[start]):
            start += 1
        while end >= start and not self._node_has_inline_anchor(items[end]):
            end -= 1
        if start > end:
            return WD_ALIGN_PARAGRAPH.LEFT, Dimen(), Dimen()

        left_indent = Dimen()
        right_indent = Dimen()
        for node in items[:start]:
            left_indent += node_width(node)
        for node in items[end + 1:]:
            right_indent += node_width(node)
        left_order = edge_order(items[:start])
        right_order = edge_order(items[end + 1:])
        if left_order is None:
            alignment = WD_ALIGN_PARAGRAPH.LEFT
        elif right_order is None:
            alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif left_order > right_order:
            alignment = WD_ALIGN_PARAGRAPH.RIGHT
        elif right_order > left_order:
            alignment = WD_ALIGN_PARAGRAPH.LEFT
        else:
            alignment = WD_ALIGN_PARAGRAPH.CENTER
        return alignment, self._nonnegative_dimen(left_indent), self._nonnegative_dimen(right_indent)

    @staticmethod
    def _edge_glue_order(nodes):
        has_glue = False
        order = None
        for node in nodes:
            if getattr(node, "node_type", None) != nd.NODE_TYPE.GLUE:
                continue
            glue = getattr(node, "glue", None)
            if glue is None:
                continue
            stretch = getattr(glue, "stretch", None)
            if stretch is not None and getattr(stretch, "factor", 0) != 0:
                current = int(getattr(stretch, "order", 0))
            elif Dimen(getattr(glue, "dimen", 0)) != 0:
                current = 0
            else:
                continue
            has_glue = True
            if order is None or current > order:
                order = current
        return has_glue, order

    def _line_paragraph_alignment(self, box):
        line_box = self._unwrap_passthrough_hlist(box)
        items = list(getattr(line_box, "list", None) or ())
        if not items:
            return WD_ALIGN_PARAGRAPH.JUSTIFY
        start = 0
        end = len(items) - 1
        while start <= end and not self._node_has_inline_anchor(items[start]):
            start += 1
        while end >= start and not self._node_has_inline_anchor(items[end]):
            end -= 1
        if start > end:
            return WD_ALIGN_PARAGRAPH.JUSTIFY
        has_left, left_order = self._edge_glue_order(items[:start])
        has_right, right_order = self._edge_glue_order(items[end + 1:])
        if not has_left and not has_right:
            return WD_ALIGN_PARAGRAPH.JUSTIFY
        if not has_left:
            return WD_ALIGN_PARAGRAPH.LEFT
        if not has_right:
            return WD_ALIGN_PARAGRAPH.RIGHT
        if left_order > right_order:
            return WD_ALIGN_PARAGRAPH.RIGHT
        if right_order > left_order:
            return WD_ALIGN_PARAGRAPH.LEFT
        return WD_ALIGN_PARAGRAPH.CENTER

    def _alignment_row_layout(self, node, owner):
        items = getattr(node, "list", None) or ()
        row_boxes = []
        row_gaps = []
        pending_gap = Dimen()
        glue_state = self._glue_state(node) if getattr(node, "node_type", None) in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST) else None
        for child in items:
            node_type = getattr(child, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                if glue_state is not None:
                    amount = self._effective_glue_amount(child, node, glue_state)
                else:
                    amount = int(getattr(getattr(child, "glue", None), "dimen", 0))
                pending_gap += Dimen(integer=amount)
                continue
            if node_type == nd.NODE_TYPE.KERN:
                pending_gap += Dimen(getattr(child, "kern", 0))
                continue
            owner_match = self._node_belongs_to_alignment(child, owner)
            if owner_match:
                row_boxes.append(child)
                row_gaps.append(pending_gap)
                pending_gap = Dimen()
                continue
        if len(row_boxes) == len(getattr(owner, "rows", ())):
            return row_boxes, row_gaps
        for child in items:
            if getattr(child, "node_type", None) not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.ALIGNMENT):
                continue
            found = self._alignment_row_layout(child, owner)
            if found is not None:
                return found
        return None

    def _alignment_effective_tabskips(self, tabskips, row_layout):
        natural = [self._nonnegative_dimen(getattr(skip, "dimen", 0)) for skip in tabskips]
        if row_layout is None:
            return natural
        row_boxes, _row_gaps = row_layout
        measured = [None] * len(natural)
        for row_box in row_boxes:
            values = []
            glue_state = self._glue_state(row_box)
            for node in getattr(row_box, "list", None) or ():
                if getattr(node, "node_type", None) != nd.NODE_TYPE.GLUE:
                    continue
                if getattr(node, "name", None) != "\\tabskip":
                    continue
                if glue_state is not None:
                    amount = self._effective_glue_amount(node, row_box, glue_state)
                else:
                    amount = int(getattr(getattr(node, "glue", None), "dimen", 0))
                values.append(self._nonnegative_dimen(Dimen(integer=amount)))
            if len(values) != len(natural):
                continue
            for index, value in enumerate(values):
                current = measured[index]
                if current is None or value > current:
                    measured[index] = value
        if not any(value is not None for value in measured):
            return natural
        return [
            measured[index] if measured[index] is not None else natural[index]
            for index in range(len(natural))
        ]

    @staticmethod
    def _glue_alignment_order(glue):
        if glue is None:
            return None
        stretch = getattr(glue, "stretch", None)
        if stretch is not None and getattr(stretch, "factor", 0) != 0:
            return int(getattr(stretch, "order", 0))
        if Dimen(getattr(glue, "dimen", 0)) != 0:
            return 0
        return None

    def _alignment_outer_alignment(self, tabskips):
        if not tabskips:
            return WD_ALIGN_PARAGRAPH.LEFT
        left_order = self._glue_alignment_order(tabskips[0])
        right_order = self._glue_alignment_order(tabskips[-1])
        if left_order is None:
            return WD_ALIGN_PARAGRAPH.LEFT
        if right_order is None:
            return WD_ALIGN_PARAGRAPH.RIGHT
        if left_order > right_order:
            return WD_ALIGN_PARAGRAPH.RIGHT
        if right_order > left_order:
            return WD_ALIGN_PARAGRAPH.LEFT
        return WD_ALIGN_PARAGRAPH.CENTER

    def _trim_outer_tabskips(self, tabskip_widths, tabskips):
        if not tabskip_widths:
            return []
        trimmed = [self._nonnegative_dimen(width) for width in tabskip_widths]
        if not tabskips:
            return trimmed
        left_order = self._glue_alignment_order(tabskips[0])
        right_order = self._glue_alignment_order(tabskips[-1])
        has_left = left_order is not None
        has_right = right_order is not None
        if has_left and has_right:
            if left_order == right_order:
                trimmed[0] = Dimen()
                trimmed[-1] = Dimen()
            elif left_order > right_order:
                trimmed[0] = Dimen()
            else:
                trimmed[-1] = Dimen()
        elif has_left:
            trimmed[0] = Dimen()
        elif has_right:
            trimmed[-1] = Dimen()
        return trimmed

    @staticmethod
    def _clear_cell(cell):
        tc = cell._tc
        for child in list(tc):
            if child.tag != qn("w:tcPr"):
                tc.remove(child)
        tc.append(parse_xml("<w:p xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\"/>"))

    @staticmethod
    def _set_table_cell_margins_zero(table):
        tbl_pr = table._tbl.tblPr
        tbl_cell_mar = tbl_pr.find(qn("w:tblCellMar"))
        if tbl_cell_mar is None:
            tbl_cell_mar = OxmlElement("w:tblCellMar")
            tbl_pr.append(tbl_cell_mar)
        for side in ("top", "left", "bottom", "right"):
            child = tbl_cell_mar.find(qn(f"w:{side}"))
            if child is None:
                child = OxmlElement(f"w:{side}")
                tbl_cell_mar.append(child)
            child.set(qn("w:w"), "0")
            child.set(qn("w:type"), "dxa")

    @classmethod
    def _set_table_cell_width(cls, cell, width):
        tc_pr = cell._tc.get_or_add_tcPr()
        tc_w = tc_pr.find(qn("w:tcW"))
        if tc_w is None:
            tc_w = OxmlElement("w:tcW")
            tc_pr.append(tc_w)
        tc_w.set(qn("w:type"), "dxa")
        tc_w.set(qn("w:w"), str(cls._fit_text_twips(width)))

    @classmethod
    def _set_table_indent(cls, table, indent):
        tbl_pr = table._tbl.tblPr
        tbl_ind = tbl_pr.find(qn("w:tblInd"))
        twips = cls._fit_text_twips(indent)
        if twips <= 0:
            if tbl_ind is not None:
                tbl_pr.remove(tbl_ind)
            return
        if tbl_ind is None:
            tbl_ind = OxmlElement("w:tblInd")
            tbl_pr.append(tbl_ind)
        tbl_ind.set(qn("w:type"), "dxa")
        tbl_ind.set(qn("w:w"), str(twips))

    def _text_block_width(self, page=None):
        hsize = Dimen(self.parser.layout["hsize"])
        if hsize > 0:
            return hsize
        if page is not None:
            return Dimen(getattr(page, "width", 0))
        return Dimen(300)

    def _add_table(self, container, rows, cols, page=None):
        try:
            return container.add_table(rows=rows, cols=cols)
        except TypeError:
            return container.add_table(
                rows=rows,
                cols=cols,
                width=self._length(self._nonnegative_dimen(self._text_block_width(page))),
            )

    @staticmethod
    def _alignment_display_indent(spec):
        if not getattr(spec, "display", False):
            return Dimen()
        return Dimen(getattr(getattr(spec, "box", None), "shifted", 0))

    @staticmethod
    def _alignment_box_shift(spec):
        if getattr(spec, "display", False):
            return Dimen()
        return Dimen(getattr(getattr(spec, "box", None), "shifted", 0))

    def _populate_table_cell(self, cell, box, line_measure=None):
        self._clear_cell(cell)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.BOTTOM
        para = cell.paragraphs[0]
        fmt = para.paragraph_format
        if getattr(box, "node_type", None) == nd.NODE_TYPE.HLIST:
            alignment = self._line_paragraph_alignment(box)
            left_indent = Dimen()
            right_indent = Dimen()
        else:
            alignment, left_indent, right_indent = self._box_inline_layout(box)
        docx_alignment = self._docx_alignment(alignment)
        fmt.alignment = docx_alignment
        fmt.left_indent = self._length(left_indent)
        fmt.right_indent = self._length(right_indent)
        fmt.space_before = Pt(0)
        fmt.space_after = Pt(0)
        total_height = (
            self._nonnegative_dimen(line_measure)
            if line_measure is not None
            else Dimen(getattr(box, "height", 0) + getattr(box, "depth", 0))
        )
        if total_height > 0:
            fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
            fmt.line_spacing = self._length(total_height)
        runs = self._runs_from_line_box(box, _InlineMathState()) or self._runs_from_box(box, _InlineMathState())
        if runs:
            runs = self._trim_runs_for_alignment(runs, docx_alignment)
            segments = self._segment_mixed_line_runs(runs)
            if segments:
                for segment in segments:
                    self._append_run_chunks(para, segment.runs)
            else:
                self._append_run_chunks(para, runs)
            return
        text = self._flatten_box_text(box)
        if text:
            para.add_run(text)

    def _populate_display_alignment_math_cell(self, cell, box):
        self._clear_cell(cell)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        para = cell.paragraphs[0]
        fmt = para.paragraph_format
        alignment, left_indent, right_indent = self._box_inline_layout(box)
        fmt.alignment = self._docx_alignment(alignment)
        fmt.left_indent = self._length(left_indent)
        fmt.right_indent = self._length(right_indent)
        fmt.space_before = Pt(0)
        fmt.space_after = Pt(0)
        if self._is_alignment_tag_cell(box):
            text = self._alignment_tag_text(box)
            if not text:
                return False
            fmt.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            fmt.left_indent = self._length(Dimen())
            fmt.right_indent = self._length(Dimen())
            run = para.add_run(text)
            self._apply_run_font_with_options(
                run,
                self._first_font(box),
                allow_word_kerning=False,
            )
            return True
        raw_nodes = self._alignment_cell_raw_nodes(box)
        fields = self._fragment_math_fields(raw_nodes)
        if not fields or not any(not isinstance(field, str) for field in fields):
            return False
        math_total_height = Dimen(getattr(box, "height", 0)) + Dimen(getattr(box, "depth", 0))
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.line_spacing = self._length(self._nonnegative_dimen(math_total_height))
        run_xml = self._display_math_run_xml(
            para.part,
            box,
            line_depth=getattr(box, "depth", 0),
            total_height=math_total_height,
        )
        if run_xml is None:
            return False
        para._p.append(run_xml)
        return True

    def _alignment_entry_reboxed_cell(self, spec, entry, adjusted_widths, adjusted_tabskips):
        start = entry["start"]
        span = entry["span"]
        if span <= 0:
            return entry["cell"]
        end = start + span - 1
        target = Dimen()
        for index in range(start, end + 1):
            target += adjusted_widths[index]
        for index in range(start + 1, end + 1):
            if index < len(adjusted_tabskips):
                target += adjusted_tabskips[index]
        try:
            reboxed = spec.owner.reboxEntry(self.parser, entry["cell"], target)
        except Exception:
            return entry["cell"]
        original = entry["cell"]
        original_raw = tuple(self._alignment_cell_raw_nodes(original))
        if not getattr(reboxed, "raw", None) and original_raw:
            reboxed.raw = original_raw
        if getattr(reboxed, "source", None) is None and getattr(original, "source", None) is not None:
            reboxed.source = original.source
        return reboxed

    def _emit_alignment(self, container, spec, page=None):
        rows, widths, tabskips = self._alignment_entries(spec.owner)
        if not rows or not widths:
            return None
        row_layout = self._alignment_row_layout(spec.box, spec.owner) if spec.box is not None else None
        block_gap = self._nonnegative_dimen(spec.space_before)
        adjusted_widths = [Dimen(width) for width in widths]
        adjusted_tabskips = self._alignment_effective_tabskips(tabskips, row_layout)
        if not spec.display:
            adjusted_tabskips = self._trim_outer_tabskips(adjusted_tabskips, tabskips)
        for _row, entries in rows:
            for entry in entries:
                start = entry["start"]
                span = entry["span"]
                if span != 1 or start < 0 or start >= len(adjusted_widths):
                    continue
                if spec.display and self._is_alignment_tag_cell(entry["cell"]):
                    # TeX keeps display eqno cells at nominal zero width and positions
                    # the visible tag against surrounding tabskip glue.
                    continue
                visible_width = self._alignment_cell_visible_width(entry["cell"])
                if visible_width <= adjusted_widths[start]:
                    continue
                delta = visible_width - adjusted_widths[start]
                adjusted_widths[start] = visible_width
                if spec.display and self._is_alignment_tag_cell(entry["cell"]):
                    gap_index = min(start, len(adjusted_tabskips) - 1)
                    reduce = min(adjusted_tabskips[gap_index], delta)
                    adjusted_tabskips[gap_index] -= reduce
        effective_widths = []
        for index, width in enumerate(adjusted_widths):
            effective_widths.append(adjusted_tabskips[index])
            effective_widths.append(width)
        effective_widths.append(adjusted_tabskips[len(adjusted_widths)])
        table = self._add_table(container, rows=len(rows), cols=len(effective_widths), page=page)
        table_alignment = WD_TABLE_ALIGNMENT.LEFT
        if not spec.display:
            block_alignment = WD_ALIGN_PARAGRAPH.LEFT
            if spec.box is not None:
                block_box = self._unwrap_passthrough_hlist(spec.box)
                block_alignment, _left_indent, _right_indent = self._box_inline_layout(block_box)
            outer_alignment = self._alignment_outer_alignment(tabskips)
            content_alignment = self._alignment_content_alignment(rows)
            if block_alignment == WD_ALIGN_PARAGRAPH.CENTER:
                table_alignment = WD_TABLE_ALIGNMENT.CENTER
            elif block_alignment == WD_ALIGN_PARAGRAPH.RIGHT:
                table_alignment = WD_TABLE_ALIGNMENT.RIGHT
            elif outer_alignment == WD_ALIGN_PARAGRAPH.CENTER:
                table_alignment = WD_TABLE_ALIGNMENT.CENTER
            elif outer_alignment == WD_ALIGN_PARAGRAPH.RIGHT:
                table_alignment = WD_TABLE_ALIGNMENT.RIGHT
            elif content_alignment == WD_ALIGN_PARAGRAPH.CENTER:
                table_alignment = WD_TABLE_ALIGNMENT.CENTER
            elif content_alignment == WD_ALIGN_PARAGRAPH.RIGHT:
                table_alignment = WD_TABLE_ALIGNMENT.RIGHT
        table.alignment = table_alignment
        table.autofit = False
        table_indent = self._nonnegative_dimen(
            spec.leading_indent
            + self._alignment_box_shift(spec)
            + self._alignment_display_indent(spec)
        )
        if table_alignment != WD_TABLE_ALIGNMENT.LEFT:
            table_indent = Dimen()
        self._set_table_indent(table, table_indent)
        self._set_table_cell_margins_zero(table)
        for index, width in enumerate(effective_widths):
            table.columns[index].width = self._length(width)
        for row in table.rows:
            for index, cell in enumerate(row.cells):
                self._set_table_cell_width(cell, effective_widths[index])
        for row_index, (_, entries) in enumerate(rows):
            row = table.rows[row_index]
            row_cells = row.cells
            gap_before = Dimen()
            if row_layout is not None:
                row_boxes, row_gaps = row_layout
                row_height = Dimen(getattr(row_boxes[row_index], "height", 0) + getattr(row_boxes[row_index], "depth", 0))
                gap_before = row_gaps[row_index]
            else:
                row_height = Dimen()
                for entry in entries:
                        row_height = max(
                            row_height,
                            Dimen(getattr(entry["cell"], "height", 0) + getattr(entry["cell"], "depth", 0)),
                        )
            if row_index == 0:
                gap_before += block_gap
            if row_height > 0:
                row.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY
                row.height = self._length(row_height + self._nonnegative_dimen(gap_before))
            occupied = set()
            for entry in entries:
                start = 2 * entry["start"] + 1
                span = entry["span"]
                end = 2 * (entry["start"] + span - 1) + 1
                if spec.display and span == 1 and self._is_alignment_tag_cell(entry["cell"]):
                    # For zero-width eqno columns, render the visible label in the
                    # preceding tabskip column so the right edge matches TeX anchor.
                    gap_col = start - 1
                    if gap_col >= 0 and effective_widths[gap_col] > 0:
                        gap_target = row_cells[gap_col]
                        self._set_table_cell_width(gap_target, effective_widths[gap_col])
                        occupied.add(gap_col)
                        self._populate_display_alignment_math_cell(gap_target, entry["cell"])
                        continue
                target = row_cells[start]
                if end > start:
                    target = target.merge(row_cells[end])
                merged_width = Dimen()
                for index in range(start, end + 1):
                    merged_width += effective_widths[index]
                self._set_table_cell_width(target, merged_width)
                occupied.update(range(start, end + 1))
                cell_box = self._alignment_entry_reboxed_cell(
                    spec,
                    entry,
                    adjusted_widths,
                    adjusted_tabskips,
                )
                if spec.display and self._populate_display_alignment_math_cell(target, cell_box):
                    continue
                self._populate_table_cell(
                    target,
                    cell_box,
                    line_measure=row_height,
                )
            for col_index, target in enumerate(row_cells):
                if col_index in occupied:
                    continue
                self._clear_cell(target)
        return table

    @staticmethod
    def _clear_story_content(story):
        element = getattr(story, "_element", None)
        if element is None:
            return
        for child in list(element):
            element.remove(child)

    def _emit_spec(self, container, spec, page):
        if isinstance(spec, _ParagraphSpec) and spec.lines:
            alignment_spec = self._paragraph_alignment_spec(spec)
            if alignment_spec is not None:
                self._emit_alignment(container, alignment_spec, page=page)
                return
            self._emit_paragraph(container, spec)
            return
        if isinstance(spec, _DisplayMathSpec):
            self._emit_display_math(container, spec)
            return
        if isinstance(spec, _AlignmentSpec):
            self._emit_alignment(container, spec, page=page)
            return
        if isinstance(spec, Table) and spec.owner is not None:
            self._emit_alignment(
                container,
                _AlignmentSpec(
                    owner=spec.owner,
                    box=spec.box,
                    space_before=spec.space_before,
                    region=spec.region,
                ),
                page=page,
            )

    def close(self):
        if self.finished:
            return
        self.finished = True
        if self.document is None:
            self.document = self.open()
        self.document.save()
        self.document = None
        self.file = None


def init(parser):
    parser.shipout = DocxBackend(parser)


mod = Module(
    "docx",
    init=init,
    attributes={},
)
