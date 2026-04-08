import io
import zipfile
from types import SimpleNamespace

from docx import Document
import pytest

from pytex import docx
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

    def __init__(self, items, source, width=50, height=7, depth=2):
        self.list = items
        self.source = source
        self.width = Dimen(width)
        self.height = Dimen(height)
        self.depth = Dimen(depth)


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
    assert [p.text for p in document.paragraphs] == [
        "Hello world\nAgain soon",
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
    assert 'Alpha beta' in xml and 'Gamma delta' in xml


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
    assert [p.text for p in document.paragraphs] == ["Shifted text"]
