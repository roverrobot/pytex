import io
import re
import zipfile

import pytest
from docx import Document as WordDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH

from pytex import align
from pytex import docx
from pytex import font as txfont
from pytex import mmode
from pytex import node as nd
from pytex import paragraph as pg
from pytex import reflow
from pytex.dimen import Dimen
from pytex.font_backend import GlyphInfo
from pytex.glue import Glue, Stretchness
from pytex.parser import Parser
from pytex.token import CATCODE


@pytest.fixture()
def parser(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = Parser()
    p.resolver.output_in_memory = True
    for ch, cat in [
        ("{", CATCODE.BEGIN_GROUP),
        ("}", CATCODE.END_GROUP),
        ("$", CATCODE.MATH_SHIFT),
        ("&", CATCODE.ALIGNMENT_TAB),
        ("#", CATCODE.PARAMETER),
        ("^", CATCODE.SUPERSCRIPT),
        ("_", CATCODE.SUBSCRIPT),
    ]:
        p.catcode[ord(ch)] = cat
    p.layout["hsize"] = Dimen(200)
    p.layout["vsize"] = Dimen(300)
    yield p
    p.close()


class _FakeBackend:
    def __init__(self, name="Fake Roman"):
        self.name = name
        self.kind = "fake"
        self.fontdimen = [0.0, 0.5, 0.25, 0.15, 0.7, 1.0, 0.0]

    def glyphInfo(self, char):
        return GlyphInfo(char=char, width=0.5, height=0.7, depth=0.2, italic=0)

    def fallbackGlyphInfo(self, char):
        return self.glyphInfo(char)

    def hasChar(self, char):
        return True

    def _spaceWidth(self):
        return Dimen(5)


class _FakeFont(txfont.Font):
    def __init__(self, name="Fake Roman", size=10):
        super().__init__(_FakeBackend(name), Dimen(size))


class _FakeHBox:
    node_type = nd.NODE_TYPE.HLIST

    def __init__(
        self,
        items,
        source=None,
        width=80,
        height=7,
        depth=2,
        rightmost_value=None,
        natural=None,
        glue_ratio=None,
    ):
        self.list = items
        self.source = source
        self.width = Dimen(width)
        self.height = Dimen(height)
        self.depth = Dimen(depth)
        self.to = Dimen(width)
        self.spread = Dimen()
        self.natural = Glue() if natural is None else natural
        self.glue_ratio = Dimen() if glue_ratio is None else glue_ratio
        self.shifted = Dimen()
        self._rightmost_value = self.width if rightmost_value is None else Dimen(rightmost_value)

    def rightmost(self):
        return self._rightmost_value


class _FakeVBox:
    node_type = nd.NODE_TYPE.VLIST

    def __init__(self, items, width=200, height=120, depth=0):
        self.list = items
        self.source = None
        self.width = Dimen(width)
        self.height = Dimen(height)
        self.depth = Dimen(depth)
        self.to = Dimen(height)
        self.spread = Dimen()
        self.natural = Glue()
        self.glue_ratio = Dimen()
        self.shifted = Dimen()


def _char_nodes(text, font):
    return [nd.CharNode(ch, font) for ch in text]


def _line_box(text, source, font=None, width=80):
    font = _FakeFont() if font is None else font
    nodes = []
    for ch in text:
        if ch == " ":
            nodes.append(nd.Glue(Glue(font.param[1]), None))
        else:
            nodes.append(nd.CharNode(ch, font))
    return _FakeHBox(nodes, source=source, width=width)


def _page_box(items):
    return _FakeVBox([nd.Glue(Glue(Dimen(10)), "\\topskip"), *items])


def _docx_bytes(parser, backend):
    backend.close()
    return parser.resolver.in_memory_files["texput.docx"].content


def _word_document(parser, backend):
    return WordDocument(io.BytesIO(_docx_bytes(parser, backend)))


def _document_xml(data):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read("word/document.xml").decode("utf-8")


def _install_font(parser, font=None):
    font = _FakeFont() if font is None else font
    parser.parameters["currentfont"] = font
    return font


def _math_atom(char, fam=0, atom_type=mmode.ATOM_TYPE.ORD):
    atom = mmode.Atom(atom_type)
    atom.nucleus = mmode.MathSymbol((atom_type.value << 12) | (fam << 8) | ord(char), -1)
    return atom


def _alignment_cell(text, font, width=20):
    box = _FakeHBox(_char_nodes(text, font), width=width, rightmost_value=width)
    box.span = 1
    return box


def test_docx_init_selects_reflow_backend_and_bp_font_sizes(parser):
    docx.init(parser)

    assert isinstance(parser.shipout, docx.DocxBackend)
    assert parser.font_size_in_bp is True


def test_docx_document_interface_uses_pagespec_sections(parser):
    backend = docx.DocxBackend(parser)
    document = backend.open()

    section = document.newPage(
        reflow.PageSpec(
            width=Dimen(100),
            height=Dimen(200),
            margin_left=Dimen(10),
            margin_top=Dimen(20),
            margin_right=Dimen(10),
            margin_bottom=Dimen(20),
        )
    )

    assert isinstance(document, reflow.Document)
    assert isinstance(section.body, reflow.Element)
    assert document.body is section.body


def test_docx_shipout_writes_one_word_paragraph_per_tex_line(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    para1 = pg.Paragraph(parser, indent=False)
    para2 = pg.Paragraph(parser, indent=False)

    backend.shipout(
        _page_box(
            [
                _line_box("Hello world", para1, font),
                nd.Penalty(0),
                nd.Glue(Glue(Dimen(3)), "\\baselineskip"),
                _line_box("Again soon", para1, font),
                nd.Glue(Glue(Dimen(8)), "\\parskip"),
                _line_box("Second paragraph", para2, font),
            ]
        )
    )

    document = _word_document(parser, backend)
    assert [p.text.replace("\u00a0", " ") for p in document.paragraphs] == [
        "Hello world",
        "Again soon",
        "Second paragraph",
    ]


def test_docx_empty_hbox_width_becomes_nonbreaking_spacing(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    para = pg.Paragraph(parser, indent=False)
    empty = _FakeHBox([], width=12, height=0, depth=0, rightmost_value=12)
    line = _FakeHBox([nd.CharNode("A", font), empty, nd.CharNode("B", font)], para)

    backend.shipout(_page_box([line]))

    document = _word_document(parser, backend)
    assert document.paragraphs[0].text == "A\u00a0B"


def test_docx_explicit_glue_emits_preserved_space_with_spacing_hint(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    para = pg.Paragraph(parser, indent=False)
    line = _FakeHBox(
        [
            nd.CharNode("A", font),
            nd.Glue(Glue(Dimen(9)), None),
            nd.CharNode("B", font),
        ],
        para,
    )

    backend.shipout(_page_box([line]))

    xml = _document_xml(_docx_bytes(parser, backend))
    assert 'xml:space="preserve"' in xml
    assert f'w:val="{docx.twips(Dimen(4))}"' in xml


def test_docx_centered_hbox_sets_word_paragraph_alignment(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    para = pg.Paragraph(parser, indent=False)
    fill = Stretchness(Dimen(1), 1)
    left = nd.Glue(Glue(Dimen(), fill), None)
    right = nd.Glue(Glue(Dimen(), fill), None)
    natural = Glue(Dimen(5), Stretchness(Dimen(2), 1))
    line = _FakeHBox(
        [left, nd.CharNode("A", font), right],
        para,
        natural=natural,
        glue_ratio=(1, int(Dimen(20)), int(Dimen(2))),
    )

    backend.shipout(_page_box([line]))

    document = _word_document(parser, backend)
    assert document.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER


@pytest.mark.xfail(reason="DOCX inline math is not implemented in the reflow backend yet", strict=True)
def test_docx_inline_math_should_emit_formula_content(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    para = pg.Paragraph(parser, indent=False)
    owner = mmode.InlineMathNode(nodes=[_math_atom("x")])
    on = nd.MathShift(True)
    on.source = owner
    on.kern = Dimen()
    off = nd.MathShift(False)
    off.source = owner
    off.kern = Dimen()
    line = _FakeHBox(
        [nd.CharNode("A", font), on, nd.CharNode("x", font), off, nd.CharNode("B", font)],
        para,
    )

    backend.shipout(_page_box([line]))

    document = _word_document(parser, backend)
    assert document.paragraphs[0].text == "AxB"


@pytest.mark.xfail(reason="DOCX display math is not implemented in the reflow backend yet", strict=True)
def test_docx_display_math_should_emit_formula_content(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    _install_font(parser)
    owner = mmode.DisplayMathNode()
    owner.list.append(_math_atom("x"))
    display_box = _FakeHBox([], source=owner)

    backend.shipout(_page_box([display_box]))

    document = _word_document(parser, backend)
    assert document.paragraphs[0].text == "x"


def test_docx_alignment_should_emit_word_table(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    owner = align.HAlignment()
    owner.tabskips = [Glue(Dimen(0)), Glue(Dimen(0)), Glue(Dimen(0))]
    row1 = align.Row()
    row1.cells = [_alignment_cell("a", font), _alignment_cell("b", font)]
    row2 = align.Row()
    row2.cells = [_alignment_cell("c", font), _alignment_cell("d", font)]
    owner.rows = [row1, row2]

    backend.shipout(_page_box([_FakeHBox([], source=owner)]))

    data = _docx_bytes(parser, backend)
    document = WordDocument(io.BytesIO(data))
    assert len(document.tables) == 1
    assert document.tables[0].cell(0, 1).text == "a"
    assert document.tables[0].cell(0, 3).text == "b"
    assert document.tables[0].cell(1, 1).text == "c"
    assert document.tables[0].cell(1, 3).text == "d"
    xml = _document_xml(data)
    assert "<w:tblCellMar>" in xml
    assert xml.count('w:w="0" w:type="dxa"') >= 4


def test_docx_alignment_span_merges_word_cells(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    owner = align.HAlignment()
    owner.tabskips = []
    row = align.Row()
    cell = _alignment_cell("wide", font)
    cell.span = 2
    row.cells = [cell]
    owner.rows = [row]

    backend.shipout(_page_box([_FakeHBox([], source=owner)]))

    data = _docx_bytes(parser, backend)
    document = WordDocument(io.BytesIO(data))
    assert len(document.tables[0].columns) == 2
    assert document.tables[0].cell(0, 0).text == "wide"
    assert 'w:gridSpan w:val="2"' in _document_xml(data)


def test_docx_alignment_row_heights_include_tex_interline_spacing(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    owner = align.HAlignment()
    owner.tabskips = []
    row1 = align.Row()
    row1.cells = [_alignment_cell("a", font, width=15)]
    row2 = align.Row()
    row2.cells = [_alignment_cell("b", font, width=15)]
    owner.rows = [row1, row2]
    rowbox1 = _FakeHBox([], source=owner, height=8, depth=2)
    rowbox2 = _FakeHBox([], source=owner, height=7, depth=3)
    interline = nd.Glue(Glue(Dimen(5)), "\\baselineskip")
    interline.source = rowbox2

    backend.shipout(_FakeVBox([rowbox1, interline, rowbox2]))

    xml = _document_xml(_docx_bytes(parser, backend))
    heights = [
        int(value)
        for value in re.findall(r'<w:trHeight\b[^>]*\bw:val="(\d+)"', xml)
    ]
    assert heights == [int(docx.twips(Dimen(10))), int(docx.twips(Dimen(15)))]
    assert f'w:before="{docx.twips(Dimen(5))}"' in xml
