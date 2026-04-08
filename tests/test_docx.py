import io
import re
import zipfile
from types import SimpleNamespace

from docx import Document
import pytest

from pytex import docx
from pytex import mmode
from pytex import node as nd
from pytex import paragraph as pg
from pytex.dimen import Dimen
from pytex.glue import Glue
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


class _FakeFont:
    def __init__(self, name="Fake Roman", size=10):
        self.backend = _FakeBackend(name)
        self.at = Dimen(size)

    def glyphInfo(self, char):
        return SimpleNamespace(char=char, width=0.5, height=0.7, depth=0.2, italic=0)



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
        "Hello worldAgain soon",
        "Second paragraph",
    ]



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
    assert 'w:line="240"' in xml
    assert 'w:after="0"' in xml
    assert 'w:jc w:val="both"' in xml
    assert 'w:fitText w:id="1" w:val="1000"' in xml
    assert 'w:fitText w:id="2" w:val="1000"' in xml
    assert "<w:kern" not in xml
    document = Document(io.BytesIO(data))
    assert _paragraph_texts(document) == ["Alpha betaGamma delta"]


def test_docx_fit_text_spaces_use_nbsp(parser):
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
    assert 'xml:space="preserve"> ' in xml


def test_docx_nested_hbox_uses_inline_textbox(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    para = pg.Paragraph(parser, indent=False)
    font = _FakeFont()
    section_box = _FakeHBox(
        [nd.CharNode("1", font)],
        para,
        width=40,
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
    assert 'style="width:40.0000pt;height:9.7500pt"' in xml
    assert re.search(r"<w:rPr><w:noProof/><w:position w:val=\"-\d+\"/></w:rPr><w:pict>", xml)
    assert '<w:spacing w:before="0" w:after="0" w:lineRule="exact" w:line="180"/>' in xml
    assert re.search(r"<v:textbox[^>]*>.*?<w:t>1</w:t>.*?</v:textbox>", xml, re.S)
    assert "<w:t>Figure</w:t>" in xml


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
    assert 'w:fitText w:id="1" w:val="1000"' in xml
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
    assert "mso-fit-text-to-shape:t" in xml
    assert "v:textbox" in xml
    assert 'style="width:40.0000pt;height:12.0000pt"' in xml
    assert 'style="width:15.0000pt;height:1.0000pt"' in xml
    assert "<m:t>a</m:t>" in xml
    assert "<m:t>+</m:t>" in xml
    assert "<m:t>b</m:t>" in xml
    assert 'w:left="300"' not in xml


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

    formula_box = _FakeHBox([], None, width=40, height=14, depth=8)
    eqno_box = _FakeHBox([], None, width=15, height=9, depth=3)
    box = _FakeHBox([formula_box, nd.Kern(Dimen(60)), eqno_box], display, width=115, height=14, depth=8)
    box.display = True
    page = _page_box(parser, [box])
    backend.shipout(page)

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert 'style="width:40.0000pt;height:22.0000pt"' in xml
    assert 'style="width:15.0000pt;height:17.0000pt"' in xml
    assert xml.count("<m:oMathPara>") == 2
    assert '<w:tab/>' in xml
    assert 'w:val="right"' in xml
    assert 'w:pos="2300"' in xml
    assert "<m:t>1</m:t>" in xml


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
