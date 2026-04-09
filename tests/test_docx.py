import io
import re
import zipfile
from types import SimpleNamespace

from docx import Document
from docx.oxml.ns import qn
import pytest

from pytex import docx
from pytex import align
from pytex import box as bx
from pytex import font as txfont
from pytex import mmode
from pytex import node as nd
from pytex import paragraph as pg
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
    p.layout["baselineskip"] = Glue(Dimen(12))
    yield p
    p.close()


class _FakeBackend:
    def __init__(self, name="Fake Roman"):
        self.name = name
        self.kind = "fake"
        self.fontdimen = [0.0, 0.5, 0.0, 0.0, 0.7, 1.0, 0.0]

    def glyphInfo(self, char):
        return GlyphInfo(char=char, width=0.5, height=0.7, depth=0.2, italic=0)

    def fallbackGlyphInfo(self, char):
        return self.glyphInfo(char)

    def hasChar(self, char):
        return True


class _FakeMathBackend(_FakeBackend):
    kind = "opentype"

    def __init__(self, name="Fake Math OTF"):
        super().__init__(name)

    def docxMathFontdimen(self, family):
        if family == 2:
            return [0.0] * 22
        if family == 3:
            return [0.0] * 13
        return [0.0] * 7

    def glyphInfo(self, char):
        return GlyphInfo(char=char, width=0.5, height=0.7, depth=0.2, italic=0)

    def fallbackGlyphInfo(self, char):
        return self.glyphInfo(char)

    def hasChar(self, char):
        return True



class _FakeFont(txfont.Font):
    def __init__(self, name="Fake Roman", size=10):
        super().__init__(_FakeBackend(name), Dimen(size))



class _FakeHBox:
    node_type = nd.NODE_TYPE.HLIST

    def __init__(self, items, source, width=50, height=7, depth=2, rightmost_value=None):
        self.list = items
        self.source = source
        self.width = Dimen(width)
        self.height = Dimen(height)
        self.depth = Dimen(depth)
        self._rightmost_value = Dimen(width) if rightmost_value is None else Dimen(rightmost_value)

    def rightmost(self):
        return self._rightmost_value


class _FakeVBox:
    node_type = nd.NODE_TYPE.VLIST

    def __init__(self, items, width=200, height=120, depth=0):
        self.list = items
        self.width = Dimen(width)
        self.height = Dimen(height)
        self.depth = Dimen(depth)



def _line_box(parser, text, source, font=None):
    font = _FakeFont() if font is None else font
    nodes = []
    for i, word in enumerate(text.split(" ")):
        if i:
            nodes.append(nd.Glue(Glue(Dimen(3)), None))
        for ch in word:
            nodes.append(nd.CharNode(ch, font))
    return _FakeHBox(nodes, source)



def _page_box(parser, items):
    return _FakeVBox(items)



def _docx_bytes(parser, backend):
    backend.close()
    return parser.resolver.in_memory_files["texput.docx"].content


def _paragraph_texts(document):
    return [p.text.replace("\u00A0", " ") for p in document.paragraphs]


def _math_symbol(ch, atom_type=mmode.ATOM_TYPE.ORD, fam=0):
    return mmode.MathSymbol((atom_type.value << 12) | (fam << 8) | ord(ch), -1)


def _display_math_owner(*fields):
    owner = mmode.DisplayMathNode()
    owner.list.extend(fields)
    return owner


def _inline_math_owner(*fields):
    owner = mmode.InlineMathNode(nodes=list(fields))
    return owner


def _alignment_cell(parser, text, width=20, font=None):
    font = _FakeFont() if font is None else font
    box = _FakeHBox([nd.CharNode(ch, font) for ch in text], None, width=width, height=7, depth=2, rightmost_value=width)
    box.span = 1
    return box


def test_docx_module_installs_math_font_array_wrappers(parser):
    assert isinstance(parser.textfont, docx._DocxMathFontArray)
    assert isinstance(parser.scriptfont, docx._DocxMathFontArray)
    assert isinstance(parser.scriptscriptfont, docx._DocxMathFontArray)
    assert parser.builtin["\\textfont"].domain is parser.textfont
    assert parser.builtin["\\scriptfont"].domain is parser.scriptfont
    assert parser.builtin["\\scriptscriptfont"].domain is parser.scriptscriptfont


def test_docx_math_font_wrapper_translates_tex_slot_to_unicode_char(parser, monkeypatch):
    monkeypatch.setattr(docx, "_resolve_parser_docx_math_backend", lambda _parser: _FakeMathBackend())
    original = _FakeFont(name="cmsy10", size=10)
    original.fontchar["skewchar"] = 60
    parser.textfont[2] = original

    wrapped = parser.textfont[2]
    assert isinstance(wrapped, docx._DocxMathFont)
    assert len(wrapped.param) == 22
    assert wrapped.fontchar["skewchar"] == 60

    node = wrapped[chr(0x73)]
    assert node.char == "∫"
    assert node.char_info.char == "∫"


def test_docx_extension_math_font_wrapper_uses_extension_params(parser, monkeypatch):
    monkeypatch.setattr(docx, "_resolve_parser_docx_math_backend", lambda _parser: _FakeMathBackend())
    parser.textfont[3] = _FakeFont(name="cmex10", size=10)
    wrapped = parser.textfont[3]
    assert isinstance(wrapped, docx._DocxMathFont)
    assert len(wrapped.param) == 13



def test_docx_backend_preserves_tex_line_breaks(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para1 = pg.Paragraph(parser, indent=False)
    para2 = pg.Paragraph(parser, indent=False)

    line1 = _line_box(parser, "Hello world", para1)
    line2 = _line_box(parser, "Again soon", para1)
    line3 = _line_box(parser, "Second paragraph", para2)

    page = _page_box(
        parser,
        [
            nd.Glue(Glue(Dimen(10)), "\\topskip"),
            line1,
            nd.Penalty(0),
            nd.Glue(Glue(Dimen(3)), "\\baselineskip"),
            line2,
            nd.Glue(Glue(Dimen(8)), "\\parskip"),
            line3,
        ],
    )
    backend.shipout(page)

    document = Document(io.BytesIO(_docx_bytes(parser, backend)))
    assert _paragraph_texts(document) == [
        "Hello world\nAgain soon",
        "Second paragraph",
    ]


def test_docx_renders_halign_as_table(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    owner = align.HAlignment()
    owner.tabskips = [Glue(Dimen(0)), Glue(Dimen(0)), Glue(Dimen(0))]
    row1 = align.Row()
    row2 = align.Row()
    row1.cells = [_alignment_cell(parser, "a", width=15), _alignment_cell(parser, "b", width=18)]
    row2.cells = [_alignment_cell(parser, "c", width=15), _alignment_cell(parser, "d", width=18)]
    owner.rows = [row1, row2]

    rowbox1 = _FakeHBox([], owner, width=33, height=8, depth=2, rightmost_value=33)
    rowbox2 = _FakeHBox([], owner, width=33, height=8, depth=2, rightmost_value=33)
    page = _page_box(parser, [rowbox1, rowbox2])
    backend.shipout(page)

    document = Document(io.BytesIO(_docx_bytes(parser, backend)))
    assert len(document.tables) == 1
    table = document.tables[0]
    assert table.cell(0, 1).text == "a"
    assert table.cell(0, 3).text == "b"
    assert table.cell(1, 1).text == "c"
    assert table.cell(1, 3).text == "d"


def test_docx_promotes_wrapped_alignment_line_to_table(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    owner = align.HAlignment()
    owner.tabskips = [Glue(Dimen(0)), Glue(Dimen(0))]
    row = align.Row()
    row.cells = [_alignment_cell(parser, "1", width=15), _alignment_cell(parser, "2", width=18)]
    owner.rows = [row]

    rowbox = _FakeHBox([], owner, width=33, height=8, depth=2, rightmost_value=33)
    wrapper = _FakeHBox([rowbox], None, width=33, height=8, depth=2, rightmost_value=33)
    para = pg.Paragraph(parser, indent=False)
    line = _FakeHBox([wrapper], para, width=80, height=8, depth=2, rightmost_value=33)
    page = _page_box(parser, [line])
    backend.shipout(page)

    document = Document(io.BytesIO(_docx_bytes(parser, backend)))
    assert len(document.tables) == 1
    assert document.tables[0].cell(0, 1).text == "1"
    assert document.tables[0].cell(0, 3).text == "2"


def test_docx_promotes_wrapped_alignment_line_with_leading_indent_box_to_table(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    owner = align.HAlignment()
    owner.tabskips = [Glue(Dimen(0)), Glue(Dimen(0))]
    row = align.Row()
    row.cells = [_alignment_cell(parser, "1", width=15), _alignment_cell(parser, "2", width=18)]
    owner.rows = [row]

    rowbox = _FakeHBox([], owner, width=33, height=8, depth=2, rightmost_value=33)
    wrapper = _FakeHBox([rowbox], None, width=33, height=8, depth=2, rightmost_value=33)
    indent = bx.IndentBox(parser, width=Dimen(12))
    para = pg.Paragraph(parser, indent=True)
    line = _FakeHBox([indent, wrapper], para, width=90, height=8, depth=2, rightmost_value=43)
    page = _page_box(parser, [line])
    backend.shipout(page)

    document = Document(io.BytesIO(_docx_bytes(parser, backend)))
    assert len(document.tables) == 1
    assert document.tables[0].cell(0, 1).text == "1"
    assert document.tables[0].cell(0, 3).text == "2"
    tbl_ind = document.tables[0]._tbl.tblPr.find(qn("w:tblInd"))
    assert tbl_ind is not None
    assert int(tbl_ind.get(qn("w:w"))) == docx.DocxBackend._fit_text_twips(Dimen(12))


def test_docx_renders_display_alignment_as_table(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    owner = align.HAlignment()
    owner.tabskips = [Glue(Dimen(0)), Glue(Dimen(0))]
    row = align.Row()
    row.cells = [_alignment_cell(parser, "x", width=15)]
    owner.rows = [row]
    display = align.MAlignment(owner, list=[])

    page = _page_box(parser, [display])
    backend.shipout(page)

    document = Document(io.BytesIO(_docx_bytes(parser, backend)))
    assert len(document.tables) == 1
    assert document.tables[0].cell(0, 1).text == "x"


def test_docx_deduplicates_repeated_wrapped_alignment_owner(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    owner = align.HAlignment()
    owner.tabskips = [Glue(Dimen(0)), Glue(Dimen(0)), Glue(Dimen(0))]
    row1 = align.Row()
    row1.cells = [_alignment_cell(parser, "a", width=15), _alignment_cell(parser, "b", width=18)]
    row2 = align.Row()
    row2.cells = [_alignment_cell(parser, "c", width=15), _alignment_cell(parser, "d", width=18)]
    owner.rows = [row1, row2]

    rowbox1 = _FakeHBox([], owner, width=33, height=8, depth=2, rightmost_value=33)
    rowbox2 = _FakeHBox([], owner, width=33, height=8, depth=2, rightmost_value=33)
    wrap1 = _FakeHBox([rowbox1], None, width=33, height=8, depth=2, rightmost_value=33)
    wrap2 = _FakeHBox([rowbox2], None, width=33, height=8, depth=2, rightmost_value=33)
    para = pg.Paragraph(parser, indent=False)
    line1 = _FakeHBox([wrap1], para, width=80, height=8, depth=2, rightmost_value=33)
    line2 = _FakeHBox([wrap2], para, width=80, height=8, depth=2, rightmost_value=33)
    page = _page_box(parser, [line1, line2])
    backend.shipout(page)

    document = Document(io.BytesIO(_docx_bytes(parser, backend)))
    assert len(document.tables) == 1


def test_docx_display_alignment_emits_omml_fraction_and_tag(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    owner = align.HAlignment()
    owner.tabskips = [Glue(Dimen(0)), Glue(Dimen(0)), Glue(Dimen(0)), Glue(Dimen(0))]
    row = align.Row()

    num = mmode.MathListHolder([_math_symbol("d"), _math_symbol("x")])
    den = mmode.MathListHolder([_math_symbol("d"), _math_symbol("t")])
    frac = mmode.Over(num, den, True, None)
    frac_atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    frac_atom.nucleus = mmode.Subformula()
    frac_atom.nucleus.list = [frac]

    lhs_math = _FakeHBox([], frac_atom, width=16, height=12, depth=4, rightmost_value=16)
    lhs_cell = _FakeHBox([lhs_math], None, width=16, height=12, depth=4, rightmost_value=16)
    lhs_cell.raw = [lhs_math]
    lhs_cell.span = 1

    rhs_atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    rhs_atom.nucleus = mmode.Subformula()
    rhs_atom.nucleus.list = [_math_symbol("x")]
    rhs_math = _FakeHBox([], rhs_atom, width=8, height=8, depth=2, rightmost_value=8)
    rhs_cell = _FakeHBox([rhs_math], None, width=8, height=8, depth=2, rightmost_value=8)
    rhs_cell.raw = [rhs_math]
    rhs_cell.span = 1

    font = _FakeFont()
    tag_box = _FakeHBox([nd.CharNode("(", font), nd.CharNode("2", font), nd.CharNode(")", font)], None, width=6, height=7, depth=2, rightmost_value=6)
    tag_cell = _FakeHBox([tag_box], None, width=6, height=7, depth=2, rightmost_value=6)
    tag_cell.raw = [nd.Kern(1), nd.Kern(1), tag_box]
    tag_cell.span = 1

    row.cells = [lhs_cell, rhs_cell, tag_cell]
    owner.rows = [row]

    document = Document()
    backend._emit_alignment(document, docx._AlignmentSpec(owner=owner, display=True))
    out = io.BytesIO()
    document.save(out)
    out.seek(0)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    assert "<m:f>" in xml
    assert "(2)" in xml
    cells = re.findall(r"<w:tc>.*?</w:tc>", xml, flags=re.DOTALL)
    tag_cell_xml = next((cell for cell in cells if "(2)" in cell), None)
    assert tag_cell_xml is not None
    width_match = re.search(r"<w:tcW[^>]*w:w=\"(\d+)\"[^>]*/>", tag_cell_xml)
    assert width_match is not None
    assert int(width_match.group(1)) > 0
    assert "<w:jc w:val=\"right\"/>" in xml


def test_docx_display_alignment_applies_box_shifted_to_table_indent(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    owner = align.HAlignment()
    owner.tabskips = [Glue(Dimen(0)), Glue(Dimen(0))]
    row = align.Row()
    row.cells = [_alignment_cell(parser, "x", width=15)]
    owner.rows = [row]

    shifted_box = _FakeHBox([], owner, width=15, height=8, depth=2, rightmost_value=15)
    shifted_box.shifted = Dimen(9)
    spec = docx._AlignmentSpec(owner=owner, box=shifted_box, display=True, leading_indent=Dimen(7))

    document = Document()
    backend._emit_alignment(document, spec)
    out = io.BytesIO()
    document.save(out)
    out.seek(0)
    with zipfile.ZipFile(out) as z:
        xml = z.read("word/document.xml").decode("utf-8")

    tbl_ind = re.search(r"<w:tblInd w:type=\"dxa\" w:w=\"(\d+)\"/>", xml)
    assert tbl_ind is not None
    expected = docx.DocxBackend._fit_text_twips(Dimen(16))
    assert int(tbl_ind.group(1)) == expected



def test_docx_backend_uses_tex_glue_as_spacing_hints(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    line1 = _line_box(parser, "Alpha beta", para)
    line2 = _line_box(parser, "Gamma delta", para)
    page = _page_box(
        parser,
        [
            line1,
            nd.Glue(Glue(Dimen(3)), "\\baselineskip"),
            line2,
            nd.Glue(Glue(Dimen(8)), "\\parskip"),
        ],
    )
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert 'w:lineRule="exact"' in xml
    assert 'w:line="239"' in xml
    assert 'w:after="0"' in xml
    assert 'w:jc w:val="both"' in xml
    assert "<w:fitText" not in xml
    assert "<w:br/>" in xml
    assert "<w:kern" not in xml
    document = Document(io.BytesIO(data))
    assert _paragraph_texts(document) == ["Alpha beta\nGamma delta"]


def test_docx_text_spaces_use_preserved_spaces(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    font = _FakeFont()
    line = _FakeHBox(
        [
            nd.CharNode("1", font),
            nd.Glue(Glue(Dimen(12)), None),
            nd.CharNode("F", font),
            nd.CharNode("i", font),
            nd.CharNode("g", font),
            nd.CharNode("u", font),
            nd.CharNode("r", font),
            nd.CharNode("e", font),
        ],
        para,
        width=50,
        rightmost_value=50,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert 'xml:space="preserve"> </w:t>' in xml
    assert 'w:spacing w:val="139"' in xml


def test_docx_nested_hbox_uses_inline_textbox(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    font = _FakeFont(name="cmbx12", size=17.28)
    section_box = _FakeHBox(
        [nd.CharNode("1", font)],
        para,
        width=40,
        depth=0,
        rightmost_value=10,
    )
    line = _FakeHBox(
        [
            section_box,
            nd.CharNode("F", font),
            nd.CharNode("i", font),
            nd.CharNode("g", font),
            nd.CharNode("u", font),
            nd.CharNode("r", font),
            nd.CharNode("e", font),
        ],
        para,
        width=200,
        rightmost_value=40,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<w:fitText" not in xml
    m = re.search(r'style="width:39\.8506pt;height:([0-9.]+)pt"', xml)
    assert m is not None
    assert float(m.group(1)) > 6.9738
    assert "v-text-anchor:top" in xml
    assert "<w:noProof/>" in xml
    assert "<w:pict>" in xml
    assert re.search(r'<w:spacing w:before="0" w:after="0" w:lineRule="exact" w:line="34\d"/>', xml)
    assert '<w:textAlignment w:val="baseline"/>' in xml
    assert 'w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"' in xml
    assert "<w:b/>" in xml
    assert re.search(r"<v:textbox[^>]*>.*?<w:t>1</w:t>.*?</v:textbox>", xml, re.S)
    assert "<w:t>Figure</w:t>" in xml


def test_docx_does_not_double_apply_first_line_indent_when_line_starts_with_indent_box(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=True)
    font = _FakeFont()
    indent_width = docx.DocxBackend._paragraph_first_indent(para)
    shipped_indent = _FakeHBox([], None, width=indent_width, height=0, depth=0)
    line = _FakeHBox(
        [
            shipped_indent,
            nd.CharNode("T", font),
            nd.CharNode("e", font),
            nd.CharNode("x", font),
            nd.CharNode("t", font),
        ],
        para,
        width=120,
        rightmost_value=40,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<w:ind" not in xml
    assert "<w:t>Text</w:t>" in xml


def test_docx_inline_math_uses_inline_textbox(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    font = _FakeFont()
    parser.layout["mathsurround"] = Dimen(3)

    atom_x = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_x.nucleus = _math_symbol("x")
    atom_plus = mmode.Atom(mmode.ATOM_TYPE.BIN)
    atom_plus.nucleus = _math_symbol("+", mmode.ATOM_TYPE.BIN)
    atom_y = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_y.nucleus = _math_symbol("y")
    inline = _inline_math_owner(atom_x, atom_plus, atom_y)

    on = nd.MathShift(True)
    on.source = inline
    on.kern = Dimen(3)
    off = nd.MathShift(False)
    off.source = inline
    off.kern = Dimen(3)

    math_x = _FakeHBox([], atom_x, width=8, height=6, depth=1)
    math_plus = _FakeHBox([], atom_plus, width=6, height=6, depth=1)
    math_y = _FakeHBox([], atom_y, width=8, height=6, depth=1)
    line = _FakeHBox(
        [
            nd.CharNode("A", font),
            on,
            math_x,
            math_plus,
            math_y,
            off,
            nd.CharNode("B", font),
        ],
        para,
        width=80,
        height=7,
        depth=2,
        rightmost_value=40,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<w:fitText" not in xml
    assert 'style="width:21.9178pt;height:7.7210pt"' in xml
    assert "<m:oMath>" in xml
    assert "<m:t>x</m:t>" in xml
    assert "<m:t>+</m:t>" in xml
    assert "<m:t>y</m:t>" in xml
    assert xml.count('w:spacing w:val="-40"') >= 2
    assert "<w:fitText" not in xml


def test_docx_inline_integral_stays_non_nary_without_display_style(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    inline = _inline_math_owner()

    integral = mmode.Op()
    integral.nucleus = mmode.MathSymbol((mmode.ATOM_TYPE.OP.value << 12) | (3 << 8) | 0x73, -1)
    integral.sub = _inline_math_owner(mmode.Atom(mmode.ATOM_TYPE.ORD))
    integral.sub.list[0].nucleus = _math_symbol("0")
    integral.sup = _inline_math_owner(mmode.Atom(mmode.ATOM_TYPE.ORD))
    integral.sup.list[0].nucleus = _math_symbol("1")
    integral.typeset_style = mmode.Style(mmode.MATH_STYLE.T)
    atom_x = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_x.nucleus = _math_symbol("x")

    on = nd.MathShift(True)
    on.source = inline
    on.kern = Dimen()
    off = nd.MathShift(False)
    off.source = inline
    off.kern = Dimen()

    line = _FakeHBox(
        [
            on,
            _FakeHBox([], integral, width=14, height=8, depth=2),
            _FakeHBox([], atom_x, width=8, height=6, depth=1),
            off,
        ],
        para,
        width=40,
        height=8,
        depth=2,
        rightmost_value=22,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<m:oMath>" in xml
    assert "<m:nary>" not in xml
    assert "<m:sSubSup>" in xml


def test_docx_inline_math_ignores_internal_tex_spacing_in_omml(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    font = _FakeFont()

    atom_x = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_x.nucleus = _math_symbol("x")
    atom_y = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_y.nucleus = _math_symbol("y")
    inline = _inline_math_owner(atom_x, atom_y)

    on = nd.MathShift(True)
    on.source = inline
    on.kern = Dimen()
    off = nd.MathShift(False)
    off.source = inline
    off.kern = Dimen()

    math_x = _FakeHBox([], atom_x, width=8, height=6, depth=1)
    space = nd.Kern(Dimen(2))
    math_y = _FakeHBox([], atom_y, width=8, height=6, depth=1)
    line = _FakeHBox(
        [
            on,
            math_x,
            space,
            math_y,
            off,
        ],
        para,
        width=40,
        height=7,
        depth=2,
        rightmost_value=18,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<m:t>x</m:t>" in xml
    assert "<m:t>y</m:t>" in xml
    assert not any(space_char in xml for space_char in ("\u2009", "\u205F", "\u200A", "\u2005", "\u2004"))


def test_docx_inline_math_uses_realized_glue_width_from_line_box(parser):
    backend = docx.DocxBackend(parser)

    atom_x = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_x.nucleus = _math_symbol("x")
    atom_y = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_y.nucleus = _math_symbol("y")

    glue = nd.Glue(Glue(Dimen(2), Stretchness(Dimen(2), 0), Stretchness(Dimen(), 0)), None)
    line = _FakeHBox([_FakeHBox([], atom_x, width=8, height=6, depth=1), glue, _FakeHBox([], atom_y, width=8, height=6, depth=1)], None)
    line.glue_ratio = (1, 1, 1)
    line.natural = SimpleNamespace(
        stretch=Stretchness(Dimen(2), 0),
        shrink=Stretchness(Dimen(), 0),
    )

    fields = backend._fragment_math_fields(line.list, line)
    assert fields == [atom_x, atom_y]

    box = backend._inline_math_box(line.list, line_box=line)
    assert box.width == Dimen(20)


def test_docx_inline_math_emits_char_fragments_without_char_sources(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    font = _FakeFont()
    atom_x = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_x.nucleus = _math_symbol("x")
    atom_plus = mmode.Atom(mmode.ATOM_TYPE.BIN)
    atom_plus.nucleus = _math_symbol("+", mmode.ATOM_TYPE.BIN)
    atom_y = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_y.nucleus = _math_symbol("y")
    inline = _inline_math_owner(atom_x, atom_plus, atom_y)
    on = nd.MathShift(True)
    on.source = inline
    on.kern = Dimen(0)
    off = nd.MathShift(False)
    off.source = inline
    off.kern = Dimen(0)

    line = _FakeHBox(
        [
            nd.CharNode("A", font),
            on,
            nd.CharNode("x", font),
            nd.CharNode("+", font),
            nd.CharNode("y", font),
            off,
            nd.CharNode("B", font),
        ],
        para,
        width=80,
        height=7,
        depth=2,
        rightmost_value=40,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<m:oMath>" in xml
    assert "<m:t>x</m:t>" in xml
    assert "<m:t>+</m:t>" in xml
    assert "<m:t>y</m:t>" in xml


def test_docx_inline_math_keeps_line_fragments_separate(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    parser.layout["mathsurround"] = Dimen(3)

    atom_x = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_x.nucleus = _math_symbol("x")
    atom_plus = mmode.Atom(mmode.ATOM_TYPE.BIN)
    atom_plus.nucleus = _math_symbol("+", mmode.ATOM_TYPE.BIN)
    atom_y = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_y.nucleus = _math_symbol("y")
    inline = _inline_math_owner(atom_x, atom_plus, atom_y)

    on = nd.MathShift(True)
    on.source = inline
    on.kern = Dimen(3)
    off = nd.MathShift(False)
    off.source = inline
    off.kern = Dimen(3)

    line1 = _FakeHBox(
        [on, _FakeHBox([], atom_x, width=8, height=6, depth=1), _FakeHBox([], atom_plus, width=6, height=6, depth=1)],
        para,
        width=60,
        height=7,
        depth=2,
        rightmost_value=20,
    )
    line2 = _FakeHBox(
        [_FakeHBox([], atom_y, width=8, height=6, depth=1), off],
        para,
        width=60,
        height=7,
        depth=2,
        rightmost_value=10,
    )
    page = _page_box(parser, [line1, nd.Glue(Glue(Dimen(12)), "\\baselineskip"), line2])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert 'style="width:13.9477pt;height:7.7210pt"' in xml
    assert 'style="width:7.9701pt;height:7.7210pt"' in xml
    assert xml.count("<m:oMath>") == 2
    assert "<m:t>x</m:t>" in xml
    assert "<m:t>+</m:t>" in xml
    assert "<m:t>y</m:t>" in xml
    assert xml.count('xml:space="preserve"> </w:t>') >= 2


def test_docx_inline_math_ignores_penalty_owned_atom_duplicates(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    font = _FakeFont()

    atom_eq = mmode.Atom(mmode.ATOM_TYPE.REL)
    atom_eq.nucleus = _math_symbol("=", mmode.ATOM_TYPE.REL)
    inline = _inline_math_owner(atom_eq)

    on = nd.MathShift(True)
    on.source = inline
    on.kern = Dimen(0)
    off = nd.MathShift(False)
    off.source = inline
    off.kern = Dimen(0)

    penalty = nd.Penalty(0)
    penalty.source = atom_eq
    line = _FakeHBox(
        [
            nd.CharNode("A", font),
            on,
            nd.CharNode("=", font),
            penalty,
            off,
            nd.CharNode("B", font),
        ],
        para,
        width=60,
        height=7,
        depth=2,
        rightmost_value=20,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert xml.count("<m:t>=</m:t>") == 1


def test_docx_sets_default_math_font_in_settings(parser, monkeypatch):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    monkeypatch.setattr(backend, "_resolve_docx_math_font", lambda: "STIX Two Math")

    para = pg.Paragraph(parser, indent=False)
    line = _line_box(parser, "Hello", para)
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/settings.xml").decode("utf-8")
    assert '<m:mathFont m:val="STIX Two Math"/>' in xml


def test_docx_math_operator_text_uses_normal_style(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    atom = mmode.Op()
    body = mmode.Subformula()
    body.list.extend([_math_symbol("s"), _math_symbol("i"), _math_symbol("n")])
    atom.nucleus = body
    inline = _inline_math_owner(atom)

    on = nd.MathShift(True)
    on.source = inline
    on.kern = Dimen(0)
    off = nd.MathShift(False)
    off.source = inline
    off.kern = Dimen(0)
    math_box = _FakeHBox([], atom, width=10, height=6, depth=1)
    line = _FakeHBox([on, math_box, off], pg.Paragraph(parser, indent=False), width=30, height=7, depth=2, rightmost_value=10)
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<m:nor/>" in xml
    assert "<m:t>s</m:t>" in xml
    assert "<m:t>i</m:t>" in xml
    assert "<m:t>n</m:t>" in xml


def test_docx_backend_emits_text_kerns_as_spacing_hints(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    font = _FakeFont()
    line = _FakeHBox(
        [
            nd.CharNode("A", font),
            nd.Kern(Dimen(-1), automatic=True),
            nd.CharNode("V", font),
        ],
        para,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert 'w:jc w:val="both"' in xml
    assert "<w:fitText" not in xml
    assert 'w:spacing w:val="-20"' in xml
    assert "<w:kern" not in xml
    document = Document(io.BytesIO(data))
    assert [p.text for p in document.paragraphs] == ["AV"]


def test_docx_backend_skips_fit_text_for_short_lines(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    line = _FakeHBox(
        [
            nd.CharNode("b", _FakeFont()),
            nd.CharNode("o", _FakeFont()),
            nd.CharNode("x", _FakeFont()),
            nd.CharNode("e", _FakeFont()),
            nd.CharNode("s", _FakeFont()),
        ],
        para,
        width=100,
        rightmost_value=40,
    )
    page = _page_box(parser, [line])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<w:fitText" not in xml
    document = Document(io.BytesIO(data))
    assert [p.text for p in document.paragraphs] == ["boxes"]


def test_docx_backend_handles_horizontally_shifted_nested_vlists(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    line = _line_box(parser, "Shifted text", para)
    inner = _FakeVBox([line], width=80, height=20, depth=0)
    inner.shifted = Dimen(25)
    page = _page_box(parser, [inner])
    backend.shipout(page)

    document = Document(io.BytesIO(_docx_bytes(parser, backend)))
    assert _paragraph_texts(document) == ["Shifted text"]


def test_docx_backend_emits_display_math_textbox(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    atom_a = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_a.nucleus = _math_symbol("a")
    atom_plus = mmode.Atom(mmode.ATOM_TYPE.BIN)
    atom_plus.nucleus = _math_symbol("+", mmode.ATOM_TYPE.BIN)
    atom_b = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_b.nucleus = _math_symbol("b")
    display = _display_math_owner(atom_a, atom_plus, atom_b)

    box = _FakeHBox([_FakeVBox([nd.Kern(Dimen(1))], width=0, height=0, depth=0)], display, width=40, height=9, depth=3)
    box.display = True
    box.shifted = Dimen(15)
    page = _page_box(
        parser,
        [
            nd.Glue(Glue(Dimen(6)), "\\abovedisplayskip"),
            box,
            nd.Glue(Glue(Dimen(8)), "\\belowdisplayskip"),
        ],
    )
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "m:oMathPara" in xml
    assert "mso-fit-text-to-shape:f" in xml
    assert "v:textbox" in xml
    assert "v-text-anchor:top" in xml
    assert 'style="width:39.8506pt;height:11.9552pt"' in xml
    assert 'style="width:14.9440pt;height:1.0000pt"' in xml
    assert '<w:spacing w:before="0" w:after="0"/>' in xml
    assert 'w:lineRule="exact" w:line="239"' in xml
    assert '<w:position w:val="-6"/>' in xml
    assert "<m:t>a</m:t>" in xml
    assert "<m:t>+</m:t>" in xml
    assert "<m:t>b</m:t>" in xml
    assert 'w:left="300"' not in xml


def test_docx_display_integral_uses_nary_operator_markup(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    integral = mmode.Op()
    integral.nucleus = mmode.MathSymbol((mmode.ATOM_TYPE.OP.value << 12) | (3 << 8) | 0x73, -1)
    integral.sub = _display_math_owner(mmode.Atom(mmode.ATOM_TYPE.ORD))
    integral.sub.list[0].nucleus = _math_symbol("0")
    integral.sup = _display_math_owner(mmode.Atom(mmode.ATOM_TYPE.ORD))
    integral.sup.list[0].nucleus = _math_symbol("1")
    integral.typeset_style = mmode.Style(mmode.MATH_STYLE.D)
    atom_x = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_x.nucleus = _math_symbol("x")
    display = _display_math_owner(integral, atom_x)

    box = _FakeHBox([], display, width=40, height=9, depth=3)
    box.display = True
    page = _page_box(parser, [box])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<m:nary>" in xml
    assert "<m:chr" in xml
    assert '<m:limLoc m:val="undOvr"/>' in xml
    assert "<m:t>x</m:t>" in xml
    assert "&#160;" in xml or "\u00a0" in xml
    assert "<m:sSubSup>" not in xml


def test_docx_section_uses_pdf_page_size_and_tex_origin(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    parser.layout["hsize"] = Dimen(200)
    parser.layout["vsize"] = Dimen(300)
    parser.parameters["pdfpagewidth"] = Dimen(500)
    parser.parameters["pdfpageheight"] = Dimen(700)

    para = pg.Paragraph(parser, indent=False)
    line = _FakeHBox([nd.CharNode("A", _FakeFont())], para, width=240, height=360, depth=0, rightmost_value=200)
    page = _FakeVBox([line], width=240, height=360, depth=0)
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert '<w:pgSz w:w="9963" w:h="13948"/>' in xml
    assert '<w:pgMar w:top="2636" w:right="3741" w:bottom="5335" w:left="2237"' in xml


def test_docx_flow_regions_split_header_body_footer(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    parser.layout["vsize"] = Dimen(60)
    font = _FakeFont()
    header_owner = pg.Paragraph(parser, indent=False)
    body_owner = pg.Paragraph(parser, indent=False)
    footer_owner = pg.Paragraph(parser, indent=False)

    header_line = _FakeHBox([nd.CharNode("H", font)], header_owner, width=40, height=7, depth=2)
    body_line = _FakeHBox([nd.CharNode("B", font)], body_owner, width=40, height=7, depth=2)
    footer_line = _FakeHBox([nd.CharNode("F", font)], footer_owner, width=40, height=7, depth=2)

    page = _FakeVBox(
        [
            header_line,
            nd.Glue(Glue(Dimen(70)), None),
            body_line,
            nd.Glue(Glue(Dimen(60)), None),
            footer_line,
        ],
        width=200,
        height=120,
        depth=0,
    )

    specs = list(backend._page_flow_specs(page, []))
    assert [getattr(spec, "region", None) for spec in specs] == ["header", "body", "footer"]


def test_docx_region_classifier_keeps_first_body_line_out_of_header(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    parser.layout["vsize"] = Dimen(100)
    parser.layout["topskip"] = Glue(Dimen(10))
    owner = pg.Paragraph(parser, indent=False)
    first_line = _FakeHBox([nd.CharNode("A", _FakeFont())], owner, width=40, height=7, depth=2)
    page = _FakeVBox([first_line], width=200, height=110, depth=0)

    specs = list(backend._page_flow_specs(page, []))
    assert len(specs) == 1
    assert isinstance(specs[0], docx._ParagraphSpec)
    assert specs[0].region == "body"


def test_docx_display_math_does_not_use_token_stringification(parser, monkeypatch):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    def fail(_tokens):
        raise AssertionError("display-math DOCX export should not stringify token lists")

    monkeypatch.setattr(parser, "expandedToksToString", fail)

    atom_a = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_a.nucleus = _math_symbol("a")
    atom_plus = mmode.Atom(mmode.ATOM_TYPE.BIN)
    atom_plus.nucleus = _math_symbol("+", mmode.ATOM_TYPE.BIN)
    atom_b = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_b.nucleus = _math_symbol("b")
    display = _display_math_owner(atom_a, atom_plus, atom_b)

    box = _FakeHBox([], display, width=40, height=9, depth=3)
    box.display = True
    page = _page_box(parser, [box])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "m:oMathPara" in xml


def test_docx_display_math_ignores_generic_payload_fields(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    class _TokenishPayload:
        def __init__(self):
            self.list = ["from-list"]
            self.raw = "from-raw"
            self.text = "from-text"

    atom_a = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_a.nucleus = _math_symbol("a")
    display = _display_math_owner(_TokenishPayload(), atom_a)

    box = _FakeHBox([], display, width=40, height=9, depth=3)
    box.display = True
    page = _page_box(parser, [box])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "m:oMathPara" in xml
    assert "<m:t>a</m:t>" in xml
    assert "from-list" not in xml
    assert "from-raw" not in xml
    assert "from-text" not in xml


def test_docx_display_math_emits_eqno_as_separate_box(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    atom_a = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_a.nucleus = _math_symbol("a")
    atom_plus = mmode.Atom(mmode.ATOM_TYPE.BIN)
    atom_plus.nucleus = _math_symbol("+", mmode.ATOM_TYPE.BIN)
    atom_b = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_b.nucleus = _math_symbol("b")
    display = _display_math_owner(atom_a, atom_plus, atom_b)
    eqno = mmode.Subformula()
    atom_1 = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom_1.nucleus = _math_symbol("1")
    eqno.list.append(atom_1)
    display.eqno = (eqno, False)

    formula_box = _FakeHBox([], None, width=40, height=11, depth=3)
    eqno_box = _FakeHBox([], None, width=15, height=9, depth=3)
    box = _FakeHBox([formula_box, nd.Kern(Dimen(60)), eqno_box], display, width=115, height=14, depth=8)
    box.display = True
    page = _page_box(parser, [box])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert 'style="width:39.8506pt;height:21.9178pt"' in xml
    assert 'style="width:14.9440pt;height:16.9365pt"' in xml
    assert xml.count("<m:oMathPara>") == 2
    assert '<w:tab/>' in xml
    assert 'w:val="right"' in xml
    assert 'w:pos="2291"' in xml
    assert "<m:t>1</m:t>" in xml


def test_docx_display_math_uses_top_level_display_box_height(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = _math_symbol("x")
    display = _display_math_owner(atom)

    formula_box = _FakeHBox([], None, width=40, height=11, depth=3)
    box = _FakeHBox([formula_box], display, width=40, height=18, depth=6)
    box.display = True
    page = _page_box(parser, [box])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert 'style="width:39.8506pt;height:23.9103pt"' in xml


def test_docx_maps_math_operator_period_slot_to_period(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    atom = mmode.Atom(mmode.ATOM_TYPE.PUNCT)
    atom.nucleus = mmode.MathSymbol((mmode.ATOM_TYPE.PUNCT.value << 12) | (0 << 8) | 0x3A, -1)
    display = _display_math_owner(atom)

    box = _FakeHBox([], display, width=10, height=9, depth=3)
    box.display = True
    page = _page_box(parser, [box])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<m:t>.</m:t>" in xml
    assert "<m:t>:</m:t>" not in xml


def test_docx_maps_math_letter_period_slot_to_period(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | 0x3A, -1)
    display = _display_math_owner(atom)

    box = _FakeHBox([], display, width=10, height=9, depth=3)
    box.display = True
    page = _page_box(parser, [box])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<m:t>.</m:t>" in xml
    assert "<m:t>:</m:t>" not in xml
