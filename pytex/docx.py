"""DOCX backend backed by the generic reflow/document interface."""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from docx import Document as WordDocument
from docx.text.paragraph import Paragraph as WordParagraph
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.parts.image import ImagePart
from docx.shared import Pt, RGBColor
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


def half_pt(dimen: Dimen):
    return f"{int(float(dimen) / 72.27 * 72 * 2)}"


class Text(reflow.Text):
    def __init__(self):
        node = OxmlElement("w:t")
        node.text = ""
        super().__init__(node)

    def setChar(self, char: nd.Node):
        if char.node_type == nd.NODE_TYPE.LIGATURE:
            for child in char.source:
                self.setChar(child)
        else:
            self._node.text += char.char


class TextRun(reflow.TextRun):
    def setFont(self, font):
        self.font = font
        if font is not None:
            self._node.font.name = font.backend.name
            self._node.font.size = Pt(round(float(font.at) / 72.27 * 72 * 2) / 2)
            self._node.font.color.rgb = _color(self.color)

    def newText(self) -> Text:
        text = Text()
        self._node._element.append(text._node)
        self.nodes.append(text)
        self.text = text
        return text

    def newInlineVBox(self, box: bx.Box):
        block = Block(box, inline=True, xspacing=Dimen(), yspacing=Dimen())
        self._node.append(block._node)
        self.nodes.append(block)
        return block

    def newInlineMath(self, backend, inlinemath: mmode.InlineMathNode, nodes: list):
        return None


class Space(TextRun):
    def __init__(self, para: WordParagraph, width: Dimen, breakable: bool, font: txfont.Font):
        space = " " if breakable else "\xa0"
        run = para.add_run("\xa0")
        super().__init__(run, font)
        rPr = run._element.get_or_add_rPr()
        spacing_element = OxmlElement('w:spacing')
        # 2. Set the spacing value in twips (e.g., "40" for 2 points of spacing)
        spacing_element.set(qn('w:val'), twips(width))
        rPr.append(spacing_element)


class Line(reflow.Line):
    JUSTIFY = {
        "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        None: WD_ALIGN_PARAGRAPH.LEFT,
    }

    def __init__(self, para: WordParagraph, line_height, spacing_before, color: reflow.Color = reflow.Color.black, justify="justify"):
        super().__init__(para, line_height, color)
        self.justify = self.JUSTIFY[justify]
        para.alignment = self.justify
        fmt = para.paragraph_format
        fmt.line_spacing = Pt(float(line_height) / 72.27 * 72)
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        fmt.space_before = Pt(float(spacing_before))
        fmt.space_after = Pt(0)
        self.font = None

    def newTextRun(self, font, color) -> TextRun:
        self.font = font
        return TextRun(self._node.add_run(), font, color)

    def newSpace(self, width: Dimen, breakable: bool):
        s = Space(self._node, width, breakable, self.font)
        return s


class Paragraph(reflow.Paragraph):
    def __init__(self, story, spacing_before=Dimen(), justify="justify"):
        node = _ContainerNode()
        super().__init__(node, spacing_before, justify)
        self.story = story
        self.spacing = spacing_before

    def setJustify(self, justify):
        self.justify = justify

    def newLine(
        self,
        line_height: Dimen=Dimen(),
        color: reflow.Color=reflow.Color.black,
        force: bool=False,
        spacing_before: Dimen=Dimen(),
    ):
        para = self.story.add_paragraph()
        if self.spacing is not None:
            spacing_before += self.spacing
            self.spacing = None
        line = Line(para, line_height=line_height, spacing_before=spacing_before, color=color, justify=self.justify)
        self.append(line)
        return line


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
        node = self._node.add_table()
        table = Table(node, xspacing=xspacing, yspacing=yspacing)
        return table

    def newGraph(self, key, type, file):
        return None


class Story(reflow.Element):
    def __init__(self, document, node):
        super().__init__(node)
        self.document = document

    def newParagraph(self, spacing_before=Dimen(), justify: str = "left") -> Paragraph:
        para = Paragraph(self._node, spacing_before=spacing_before, justify=justify)
        self.nodes.append(para)
        return para

    def newTable(self, xspacing=Dimen(), yspacing=Dimen()):
        node = self._node.add_table()
        table = Table(node, xspacing=xspacing, yspacing=yspacing)
        return table

    def newGraph(self, key, type, file):
        return None


class Section:
    def __init__(self, document, spec: reflow.PageSpec):
        self.document = document
        self.spec = spec
        self._header_spec = document.part.add_header_part() # node, rel_id
        self._header = Story(document, self._header_spec[0])
        self._footer_spec = document.part.add_footer_part()
        self._footer = Story(document, self._footer_spec[0])
        self._body = Story(document, document._body)

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
            section = Section(self._node, page_spec)
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


def init(parser):
    parser.shipout = DocxBackend(parser)


mod = Module(
    "docx",
    init=init,
    attributes={},
)
