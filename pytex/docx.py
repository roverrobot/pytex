"""DOCX backend backed by the generic reflow/document interface."""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from docx import Document as WordDocument
from docx.table import Table as WordTable
from docx.text.paragraph import Paragraph as WordParagraph
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.parts.image import ImagePart
from docx.shared import Pt, RGBColor, Twips
from fontTools.pens.svgPathPen import SVGPathPen

from pytex import align
from pytex import box as bx
from pytex.font import Font
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
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_WPS_NS = "http://schemas.microsoft.com/office/word/2010/wordprocessingShape"


def _color(color: reflow.Color):
    r, g, b, a = color.rgba
    return RGBColor(
        max(0, min(255, round(r * 255))),
        max(0, min(255, round(g * 255))),
        max(0, min(255, round(b * 255))),
    )


class _ContainerNode:
    def append(self, child):
        pass

def twips(dimen: Dimen):
    return f"{int(float(dimen) / 72.27 * 72 * 20)}"


def _twips(dimen: Dimen):
    return int(float(dimen) / 72.27 * 72 * 20)


def _length(dimen: Dimen):
    return Twips(_twips(dimen))


def _emu(dimen: Dimen):
    return max(1, int(round(float(dimen) * _DOCX_EMU_PER_TEX_POINT_NUM / _DOCX_EMU_PER_TEX_POINT_DEN)))


def half_pt(dimen: Dimen):
    return f"{int(float(dimen) / 72.27 * 72 * 2)}"


def _textbox_xml(cx: int, cy: int, drawing_id: int):
    return f"""
<w:drawing
    xmlns:w="{_W_NS}"
    xmlns:wp="{_WP_NS}"
    xmlns:a="{_A_NS}"
    xmlns:wps="{_WPS_NS}">
  <wp:inline distT="0" distB="0" distL="0" distR="0">
    <wp:extent cx="{cx}" cy="{cy}"/>
    <wp:effectExtent l="0" t="0" r="0" b="0"/>
    <wp:docPr id="{drawing_id}" name="Inline VBox {drawing_id}"/>
    <wp:cNvGraphicFramePr>
      <a:graphicFrameLocks noChangeAspect="1"/>
    </wp:cNvGraphicFramePr>
    <a:graphic>
      <a:graphicData uri="{_WPS_NS}">
        <wps:wsp>
          <wps:cNvSpPr txBox="1"/>
          <wps:spPr>
            <a:xfrm>
              <a:off x="0" y="0"/>
              <a:ext cx="{cx}" cy="{cy}"/>
            </a:xfrm>
            <a:prstGeom prst="rect">
              <a:avLst/>
            </a:prstGeom>
            <a:noFill/>
            <a:ln>
              <a:noFill/>
            </a:ln>
          </wps:spPr>
          <wps:txbx>
            <w:txbxContent/>
          </wps:txbx>
          <wps:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0">
            <a:noAutofit/>
          </wps:bodyPr>
        </wps:wsp>
      </a:graphicData>
    </a:graphic>
  </wp:inline>
</w:drawing>
"""


def _story_document(story):
    document = getattr(story, "document", None)
    if document is not None:
        return document
    table = getattr(story, "table", None)
    if table is not None:
        return table.document
    raise AttributeError(f"{type(story).__name__} is not attached to a DOCX document")


class Text(reflow.Text):
    XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

    def __init__(self, preserve_space=False):
        node = OxmlElement("w:t")
        if preserve_space:
            node.set(self.XML_SPACE, "preserve")
        node.text = ""
        super().__init__(node)

    def setChar(self, char: nd.Node):
        if char.node_type == nd.NODE_TYPE.LIGATURE:
            for child in char.source:
                self.setChar(child)
        else:
            self._node.text += char.char


class TextBoxStory(reflow.Block):
    def __init__(self, document, drawing, node, box: bx.Box):
        super().__init__(node, inline=True)
        self.document = document
        self.drawing = drawing
        self.box = box

    @property
    def line_id(self):
        return self.document.line_id

    @property
    def part(self):
        return self.document._node.part

    def _new_word_paragraph(self):
        node = OxmlElement("w:p")
        self._node.append(node)
        return WordParagraph(node, self)

    def _new_word_table(self):
        node = CT_Tbl.new_tbl(0, 0, Twips(0))
        self._node.append(node)
        return WordTable(node, self)

    def newParagraph(self, spacing_before=Dimen(), justify: str = "left") -> "Paragraph":
        para = Paragraph(self, spacing_before=spacing_before, justify=justify)
        self.nodes.append(para)
        return para

    def newTable(self, xspacing=Dimen(), yspacing=Dimen()):
        table = Table(
            self.document,
            self._new_word_table(),
            xspacing=xspacing,
            yspacing=yspacing,
            full_width=self.box.width,
        )
        self.nodes.append(table)
        return table

    def newGraph(self, key, type, file):
        return None

    def finalizeContent(self):
        for node in self.nodes:
            if isinstance(node, Table):
                node.setFullWidth(self.box.width)


class TextRun(reflow.TextRun):
    def __init__(self, line, text="", font = None, color = reflow.Color.black, preserve_space=False):
        node = line._node.add_run()
        self.line = line
        super().__init__(node, font, color)
        self.preserve_space = preserve_space
        t = self.newText()
        t._node.text = text
        rPr = node._r.get_or_add_rPr()
        kern = OxmlElement("w:kern")
        rPr.append(kern)
        kern.set(qn("w:val"), "1")
        lig = OxmlElement("w14:ligatures")
        rPr.append(lig)
        lig.set(qn("w14:val"), "standard")

    def setFont(self, font):
        self.font = font
        self.line.font = font
        if font is not None:
            self._node.font.name = font.backend.name
            self._node.font.size = Pt(round(float(font.at) / 72.27 * 72 * 2) / 2)
            self._node.font.color.rgb = _color(self.color)

    def newText(self) -> Text:
        text = Text(self.preserve_space)
        self._node._element.append(text._node)
        self.nodes.append(text)
        self.text = text
        return text

    def newInlineVBox(self, box: bx.Box):
        self.text = None
        document = _story_document(self.line.story)
        drawing_id = document.nextDrawingId()
        drawing = parse_xml(_textbox_xml(_emu(box.width), _emu(box.height + box.depth), drawing_id))
        content = drawing.find(f".//{{{_W_NS}}}txbxContent")
        if content is None:
            raise ValueError("DOCX inline textbox template is missing w:txbxContent")
        block = TextBoxStory(document, drawing, content, box)
        self._node._element.append(drawing)
        self.nodes.append(block)
        return block

    def newInlineMath(self, backend, inlinemath: mmode.InlineMathNode, nodes: list):
        return None


class Space(TextRun):
    def __init__(self, line, width: Dimen, breakable: bool, font: Font):
        space = " " if breakable else "\xa0"
        super().__init__(line, space, font, preserve_space=True)
        diff = width-font.backend._spaceWidth()
        if int(diff) != 0:
            rPr = self._node._r.get_or_add_rPr()
            spacing_element = OxmlElement('w:spacing')
            spacing_element.set(qn('w:val'), twips(diff))
            rPr.append(spacing_element)


class Line(reflow.Line):
    JUSTIFY = {
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        None: WD_ALIGN_PARAGRAPH.LEFT,
    }

    def __init__(
        self,
        para: WordParagraph,
        line_id: int,
        line_spec: reflow.LineSpec,
        justify="justify",
        story=None,
    ):
        super().__init__(para, line_spec)
        self.story = story
        self.justify = self.JUSTIFY[justify]
        para.alignment = self.justify
        fmt = para.paragraph_format
        fmt.line_spacing = Twips(max(1, _twips(line_spec.line_box.height + line_spec.line_box.depth)))
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.space_before = Twips(_twips(line_spec.spacing_before))
        fmt.space_after = Pt(0)
        self.font = line_spec.default_font
        self.width = line_spec.line_box.rightmost()
        self.line_id = line_id

    def newTextRun(self, font, color) -> TextRun:
        return TextRun(self, font=font, color=color)

    def newSpace(self, width: Dimen, breakable: bool):
        s = Space(self, width, breakable, self.font)
        return s


class Paragraph(reflow.Paragraph):
    def __init__(self, story, spacing_before=Dimen(), justify="justify"):
        node = _ContainerNode()
        super().__init__(node, spacing_before, justify)
        self.story = story
        self.spacing = spacing_before

    def setJustify(self, justify):
        self.justify = justify

    def newLine(self, line_spec: reflow.LineSpec) -> Line:
        para = self.story._new_word_paragraph()
        if self.spacing is not None:
            line_spec.spacing_before += self.spacing
            self.spacing = None
        line = Line(para, self.story.line_id, line_spec, justify=self.justify, story=self.story)
        self.append(line)
        return line


class Cell(reflow.Cell):
    def __init__(self, row, node, span=1, width=None, justify: str = "justify"):
        super().__init__(node, span=span, width=width, justify=justify)
        self.row = row
        self.table = row.table
        self._used_initial_paragraph = False
        self._used_row_spacing = False
        node.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
        self._setWidth(width)

    @property
    def line_id(self):
        return self.table.line_id

    def _new_word_paragraph(self):
        if not self._used_initial_paragraph:
            self._used_initial_paragraph = True
            paragraphs = self._node.paragraphs
            if paragraphs and not paragraphs[0].text and not paragraphs[0].runs:
                return paragraphs[0]
        return self._node.add_paragraph()

    def _setWidth(self, width):
        if width is None:
            return
        tcPr = self._node._tc.get_or_add_tcPr()
        tcW = tcPr.tcW
        if tcW is None:
            tcW = OxmlElement("w:tcW")
            tcPr.append(tcW)
        if isinstance(width, Dimen):
            tcW.set(qn("w:type"), "dxa")
            tcW.set(qn("w:w"), twips(width))
            return
        if isinstance(width, (int, float)):
            tcW.set(qn("w:type"), "pct")
            tcW.set(qn("w:w"), str(int(float(width) * 5000)))

    def newParagraph(self) -> Paragraph:
        spacing_before = Dimen()
        if not self._used_row_spacing:
            spacing_before = self.row.spacing_before
            self._used_row_spacing = True
        para = Paragraph(self, spacing_before=spacing_before, justify=self.justify)
        self.nodes.append(para)
        return para


class Row(reflow.Row):
    def __init__(self, table, node, row_box=None, spacing_before=Dimen()):
        super().__init__(node)
        self.table = table
        self._cell_index = 0
        self.spacing_before = Dimen(spacing_before)
        self.row_box = row_box
        self._setHeight(row_box, self.spacing_before)

    def _setHeight(self, row_box, spacing_before):
        if row_box is None:
            return
        height = row_box.height + row_box.depth + spacing_before
        self._node.height = Twips(max(1, _twips(height)))
        self._node.height_rule = WD_ROW_HEIGHT_RULE.EXACTLY

    def newCell(self, span=1, width=None, justify="justify") -> Cell:
        node = self.table._wordCell(self._node, self._cell_index, span, width)
        self._cell_index += span
        cell = Cell(self, node, span=span, width=width, justify=justify)
        self.nodes.append(cell)
        return cell


class Table(reflow.Table):
    ALIGNMENT = {
        "left": WD_TABLE_ALIGNMENT.LEFT,
        "center": WD_TABLE_ALIGNMENT.CENTER,
        "right": WD_TABLE_ALIGNMENT.RIGHT,
    }

    def __init__(
        self,
        document,
        node,
        xspacing=Dimen(),
        yspacing=Dimen(),
        full_width=None,
        alignment="left",
    ):
        super().__init__(node, xspacing=xspacing, yspacing=yspacing)
        self.document = document
        self.owner = None
        self.box = None
        self.space_before = Dimen(yspacing)
        self.region = "body"
        self.full_width = None if full_width is None else Dimen(full_width)
        self.alignment = alignment
        self._node.autofit = self.full_width is None
        self._setAlignment()
        self._setCellMargins()
        if self.full_width is not None:
            self._setTableWidth("dxa", twips(self.full_width))

    @property
    def line_id(self):
        return self.document.line_id

    def _setAlignment(self):
        self._node.alignment = self.ALIGNMENT.get(self.alignment, WD_TABLE_ALIGNMENT.LEFT)

    def _setCellMargins(self):
        tblPr = self._node._tbl.tblPr
        cellMar = tblPr.first_child_found_in("w:tblCellMar")
        if cellMar is None:
            cellMar = OxmlElement("w:tblCellMar")
            tblPr.append(cellMar)
        for side in ("top", "left", "bottom", "right"):
            existing = cellMar.find(qn(f"w:{side}"))
            if existing is not None:
                cellMar.remove(existing)
            margin = OxmlElement(f"w:{side}")
            margin.set(qn("w:w"), "0")
            margin.set(qn("w:type"), "dxa")
            cellMar.append(margin)

    def _setTableWidth(self, width_type, width):
        tblPr = self._node._tbl.tblPr
        tblW = tblPr.first_child_found_in("w:tblW")
        if tblW is None:
            tblW = OxmlElement("w:tblW")
            tblPr.insert(0, tblW)
        tblW.set(qn("w:type"), width_type)
        tblW.set(qn("w:w"), str(width))

    @staticmethod
    def _columnWidth(width=None):
        if isinstance(width, Dimen):
            return Twips(max(1, _twips(width)))
        if isinstance(width, (int, float)):
            return Twips(max(1, int(1440 * float(width))))
        return Twips(1)

    def _setColumnWidth(self, index, width):
        if width is None:
            return
        width = self._columnWidth(width)
        column = self._node.columns[index]
        if column.width is None or int(column.width) < int(width):
            column.width = width

    def _ensureColumns(self, count, width=None):
        while len(self._node.columns) < count:
            self._node.add_column(self._columnWidth(width))

    def _wordCell(self, row, index, span=1, width=None):
        span = max(1, int(span))
        column_width = width
        if isinstance(width, Dimen) and span > 1:
            column_width = width / span
        self._ensureColumns(index + span, column_width)
        for column_index in range(index, index + span):
            self._setColumnWidth(column_index, column_width)
        cell = row.cells[index]
        if span > 1:
            cell = cell.merge(row.cells[index + span - 1])
        return cell

    def setFullWidth(self, width):
        self.full_width = Dimen(width)
        self._node.autofit = False
        self._setTableWidth("dxa", twips(self.full_width))
        grid = self._node._tbl.tblGrid
        columns = list(grid.gridCol_lst)
        if not columns:
            return
        current = []
        for column in columns:
            value = column.get(qn("w:w"))
            current.append(max(1, int(value)) if value is not None else 1)
        total = sum(current)
        if total <= 0:
            current = [1] * len(columns)
        for column, value in zip(columns, current):
            column.set(qn("w:w"), str(value))
        self._setCellWidths(current)

    def _setCellWidths(self, columns):
        for row in self._node._tbl.tr_lst:
            column_index = 0
            for cell in row.tc_lst:
                tcPr = cell.get_or_add_tcPr()
                grid_span = tcPr.gridSpan
                span = int(grid_span.val) if grid_span is not None else 1
                width = sum(columns[column_index:column_index + span])
                tcW = tcPr.tcW
                if tcW is None:
                    tcW = OxmlElement("w:tcW")
                    tcPr.append(tcW)
                tcW.set(qn("w:type"), "dxa")
                tcW.set(qn("w:w"), str(max(1, width)))
                column_index += span

    def newRow(self, row_box=None, spacing_before=Dimen()) -> Row:
        row = Row(self, self._node.add_row(), row_box=row_box, spacing_before=spacing_before)
        self.nodes.append(row)
        return row

    def iter_specs(self):
        yield self


class Block(reflow.Block):
    def __init__(self, backend, region="body", inline=False, xspacing=Dimen(), yspacing=Dimen()):
        super().__init__(_ContainerNode(), inline=inline, xspacing=xspacing, yspacing=yspacing)
        self.backend = backend
        self.region = region
        self._entries = []

    def newParagraph(self, spacing_before=Dimen(), justify: str = "left") -> Paragraph:
        para = Paragraph(self._node, spacing_before=spacing_before, justify=justify)
        self.append(para)
        return para

    def newTable(self, xspacing=Dimen(), yspacing=Dimen()):
        raise NotImplementedError("DOCX inline block tables need a real story container")

    def newGraph(self, key, type, file):
        return None


class Story(reflow.Element):
    def __init__(self, document, node):
        super().__init__(node)
        self.document = document

    def newParagraph(self, spacing_before=Dimen(), justify: str = "left") -> Paragraph:
        para = Paragraph(self, spacing_before=spacing_before, justify=justify)
        self.nodes.append(para)
        return para

    def _new_word_paragraph(self):
        return self._node.add_paragraph()

    def _new_word_table(self):
        try:
            return self._node.add_table(rows=0, cols=0, width=Twips(0))
        except TypeError:
            return self._node.add_table(rows=0, cols=0)

    def newTable(self, xspacing=Dimen(), yspacing=Dimen()):
        table = Table(self.document, self._new_word_table(), xspacing=xspacing, yspacing=yspacing)
        self.nodes.append(table)
        return table

    def newGraph(self, key, type, file):
        return None
    
    @property
    def line_id(self):
        return self.document.line_id


class Section:
    def __init__(self, document, spec: reflow.PageSpec):
        self.document = document
        self.spec = spec
        self._section = document._node.sections[-1]
        self._apply_spec()
        self._header_spec = document._node.part.add_header_part() # node, rel_id
        self._header = Story(document, self._header_spec[0])
        self._footer_spec = document._node.part.add_footer_part()
        self._footer = Story(document, self._footer_spec[0])
        self._body = Story(document, document._node._body)

    def _apply_spec(self):
        section = self._section
        section.page_width = _length(self.spec.width)
        section.page_height = _length(self.spec.height)
        section.left_margin = _length(self.spec.margin_left)
        section.top_margin = _length(self.spec.margin_top)
        section.right_margin = _length(self.spec.margin_right)
        section.bottom_margin = _length(self.spec.margin_bottom)

    @property
    def header(self) -> Block:
        return self._header

    @property
    def body(self) -> Block:
        return self._body

    @property
    def footer(self) -> Block:
        return self._footer

    def close(self, document, last_page):
        document.add_section(WD_SECTION_START.NEW_PAGE)


class Document(reflow.Document):
    def __init__(self, title: str, output=None):
        document = WordDocument()
        super().__init__(document, title, output)
        self.sections = []
        self._line_id = 0
        self._drawing_id = 0

    @property
    def line_id(self):
        self._line_id += 1
        return self._line_id

    def nextDrawingId(self):
        self._drawing_id += 1
        return self._drawing_id

    @property
    def header(self) -> Block:
        return self.sections[-1].header

    @property
    def body(self) -> Block:
        return self.sections[-1].body

    @property
    def footer(self) -> Block:
        return self.sections[-1].footer

    def newPage(self, page_spec: reflow.PageSpec) -> Section:
        section_index = len(self.sections)
        if section_index == 0:
            is_new = True
        else:
            current_section: Section = self.sections[-1]
            is_new = current_section.spec.signature() != page_spec.signature()
        if is_new:
            if section_index > 0:
                self.sections[-1].close(self._node, last_page=False)
            section = Section(self, page_spec)
            self.sections.append(section)
            return section
        return self.sections[-1]

    def defineFont(self, font):
        return None

    def definePicture(self, key, type, path):
        return None

    def save(self):
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
        self.docx_path = None
    
    def open(self):
        output = self.parser.jobname
        output = os.fspath(output)
        if output.startswith("./"):
            output = output[2:]
        if not output.endswith(".docx"):
            output += ".docx"
        if not self.parser.resolver.output_in_memory:
            self.docx_path = Path(self.parser.resolver._outputPath(output))
        return Document(self.parser.jobname, self.parser.resolver.openOut(output, "shipout/docx"))

    def typesetInlineVBox(self, box: bx.Box):
        block = super().typesetInlineVBox(box)
        if isinstance(block, TextBoxStory):
            block.finalizeContent()
        return block


def init(parser):
    parser.shipout = DocxBackend(parser)
    parser.font_size_in_bp = True


mod = Module(
    "docx",
    init=init,
    attributes={},
)
