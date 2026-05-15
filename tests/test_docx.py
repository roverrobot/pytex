import io
import re
import zipfile

import pytest
from docx import Document as WordDocument
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH

from pytex import align
from pytex import box as bx
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
    def __init__(self, name="Fake Roman", kind="fake", path=None, font_number=0):
        self.name = name
        self.kind = kind
        self.path = path
        self.font_number = font_number
        self.fontdimen = [0.0, 0.5, 0.25, 0.15, 0.7, 1.0, 0.0]

    def glyphInfo(self, char):
        return GlyphInfo(char=char, width=0.5, height=0.7, depth=0.2, italic=0)

    def fallbackGlyphInfo(self, char):
        return self.glyphInfo(char)

    def hasChar(self, char):
        return True

    def _spaceWidth(self):
        return 0.5


class _FakeFont(txfont.Font):
    def __init__(self, name="Fake Roman", size=10, kind="fake", path=None, font_number=0):
        super().__init__(_FakeBackend(name, kind=kind, path=path, font_number=font_number), Dimen(size))


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
    word_section = document._node.sections[0]
    assert int(word_section.page_width) == int(docx._length(Dimen(100)))
    assert int(word_section.page_height) == int(docx._length(Dimen(200)))
    assert int(word_section.left_margin) == int(docx._length(Dimen(10)))
    assert int(word_section.top_margin) == int(docx._length(Dimen(20)))
    assert int(word_section.right_margin) == int(docx._length(Dimen(10)))
    assert int(word_section.bottom_margin) == int(docx._length(Dimen(20)))


def test_docx_shipout_embeds_filesystem_opentype_fonts(parser, tmp_path):
    font_bytes = bytes(range(64))
    font_path = tmp_path / "DemoFont.otf"
    font_path.write_bytes(font_bytes)
    font = _FakeFont("Demo Embedded", kind="opentype", path=str(font_path))
    _install_font(parser, font)
    owner = pg.Paragraph(parser, indent=False)
    backend = docx.DocxBackend(parser)
    parser.shipout = backend

    backend.shipout(_page_box([_line_box("Hi", owner, font)]))
    data = _docx_bytes(parser, backend)

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        assert "word/fonts/font1.odttf" in names
        font_xml = zf.read("word/fontTable.xml").decode("utf-8")
        rels_xml = zf.read("word/_rels/fontTable.xml.rels").decode("utf-8")
        content_types = zf.read("[Content_Types].xml").decode("utf-8")
        settings_xml = zf.read("word/settings.xml").decode("utf-8")
        obfuscated = zf.read("word/fonts/font1.odttf")

    assert 'w:name="Demo Embedded"' in font_xml
    assert "<w:embedRegular" in font_xml
    font_key = re.search(r'w:fontKey="([^"]+)"', font_xml).group(1)
    assert font_key.startswith("{") and font_key.endswith("}")
    assert 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font"' in rels_xml
    assert 'Target="fonts/font1.odttf"' in rels_xml
    assert 'Extension="odttf"' in content_types
    assert "application/vnd.openxmlformats-officedocument.obfuscatedFont" in content_types
    assert "<w:embedTrueTypeFonts" in settings_xml
    key = docx._font_key_bytes(font_key)
    restored = bytearray(obfuscated)
    for index in range(32):
        restored[index] ^= key[index % 16]
    assert bytes(restored) == font_bytes


def test_docx_shipout_writes_one_word_paragraph_per_tex_line(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    para1 = pg.Paragraph(parser, indent=False)
    para2 = pg.Paragraph(parser, indent=False)
    empty_source_glue = nd.Glue(Glue(Dimen()), None)
    empty_source_glue.source = pg.Paragraph(parser, indent=False)

    backend.shipout(
        _page_box(
            [
                _line_box("Hello world", para1, font),
                nd.Penalty(0),
                nd.Glue(Glue(Dimen(3)), "\\baselineskip"),
                empty_source_glue,
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
    assert int(document.paragraphs[1].paragraph_format.space_before) == int(docx._length(Dimen(3)))
    assert int(document.paragraphs[2].paragraph_format.space_before) == int(docx._length(Dimen(8)))


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


def test_docx_inline_vbox_emits_word_textbox_story(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    outer_para = pg.Paragraph(parser, indent=False)
    inner_para = pg.Paragraph(parser, indent=False)
    inner_line = _line_box("X", inner_para, font, width=16)
    vbox = _FakeVBox([inner_line], width=18, height=9, depth=3)
    line = _FakeHBox(
        [nd.CharNode("A", font), vbox, nd.CharNode("B", font)],
        outer_para,
    )

    backend.shipout(_page_box([line]))

    xml = _document_xml(_docx_bytes(parser, backend))
    assert "<w:drawing" in xml
    assert "<wp:inline" in xml
    assert "<w:txbxContent>" in xml
    assert "<w:t>A</w:t>" in xml
    assert "<w:t>X</w:t>" in xml
    assert "<w:t>B</w:t>" in xml
    wp_extent = re.search(r'<wp:extent\b[^>]*\bcx="([^"]+)"[^>]*\bcy="([^"]+)"', xml)
    effect = re.search(r'<wp:effectExtent\b[^>]*\bb="([^"]+)"', xml)
    shape_extent = re.search(r'<a:xfrm><a:off x="0" y="0"/><a:ext cx="([^"]+)" cy="([^"]+)"/>', xml)
    assert wp_extent.groups() == (
        str(docx._emu(vbox.width)),
        str(docx._emu(vbox.height + vbox.depth)),
    )
    assert effect.group(1) == "0"
    assert shape_extent.groups() == (
        str(docx._emu(vbox.width)),
        str(docx._emu(vbox.height + vbox.depth)),
    )
    assert f'<w:position w:val="-{docx.half_pt(vbox.depth)}"/>' in xml


def test_docx_inline_vbox_table_uses_exact_tex_widths(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    outer_para = pg.Paragraph(parser, indent=False)
    owner = align.HAlignment()
    owner.tabskips = [
        Glue(Dimen(2), Stretchness(Dimen(1), 0)),
        Glue(Dimen(3), Stretchness(Dimen(3), 0)),
        Glue(Dimen(5)),
    ]
    row = align.Row()
    row.cells = [_alignment_cell("a", font, width=10), _alignment_cell("b", font, width=20)]
    owner.rows = [row]
    natural = Glue(Dimen(40), Stretchness(Dimen(4), 0))
    row_box = _FakeHBox(
        [],
        source=owner,
        width=48,
        height=8,
        depth=2,
        natural=natural,
        glue_ratio=(1, int(Dimen(8)), int(Dimen(4))),
    )
    vbox = _FakeVBox(
        [row_box],
        width=48,
        height=10,
        depth=0,
    )
    line = _FakeHBox(
        [nd.CharNode("A", font), vbox, nd.CharNode("B", font)],
        outer_para,
    )

    backend.shipout(_page_box([line]))

    xml = _document_xml(_docx_bytes(parser, backend))
    table_width = re.search(r'<w:tblW\b[^>]*\bw:type="([^"]+)"[^>]*\bw:w="([^"]+)"', xml)
    assert table_width.groups() == ("dxa", docx.twips(vbox.width))
    grid_widths = [
        int(value)
        for value in re.findall(r'<w:gridCol\b[^>]*\bw:w="(\d+)"', xml)
    ]
    assert grid_widths == [
        int(docx.twips(Dimen(4))),
        int(docx.twips(Dimen(10))),
        int(docx.twips(Dimen(9))),
        int(docx.twips(Dimen(20))),
        int(docx.twips(Dimen(5))),
    ]
    textbox_xml = re.search(r"<w:txbxContent>(.*)</w:txbxContent>", xml, re.DOTALL).group(1)
    line_heights = re.findall(r'<w:spacing\b[^>]*\bw:line="(\d+)"', textbox_xml)
    assert line_heights == [docx.twips(row_box.height + row_box.depth)] * 2
    extent_width = int(re.search(r"<wp:extent[^>]* cx=\"(\d+)\"", xml).group(1))
    assert extent_width == docx._emu(vbox.width)
    assert 1440 not in grid_widths


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


def test_docx_spacing_uses_scaled_font_space_width(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser, _FakeFont(size=20))
    para = pg.Paragraph(parser, indent=False)
    line = _FakeHBox(
        [
            nd.CharNode("A", font),
            nd.Glue(Glue(Dimen(12)), None),
            nd.CharNode("B", font),
        ],
        para,
    )

    backend.shipout(_page_box([line]))

    xml = _document_xml(_docx_bytes(parser, backend))
    assert f'w:val="{docx.twips(Dimen(2))}"' in xml
    assert f'w:val="{docx.twips(Dimen(7))}"' not in xml


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


def test_docx_inline_math_embeds_svg_picture(parser, monkeypatch):
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
        height=12,
        depth=4,
    )
    captured = {}

    def fake_svg(box):
        captured["box"] = box
        return b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'

    monkeypatch.setattr(backend, "inlineMathSvg", fake_svg)

    backend.shipout(_page_box([line]))

    document = _word_document(parser, backend)
    assert document.paragraphs[0].text == "AB"
    data = _docx_bytes(parser, backend)
    xml = _document_xml(data)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        rels_xml = zf.read("word/_rels/document.xml.rels").decode("utf-8")
        content_types = zf.read("[Content_Types].xml").decode("utf-8")
        svg_payload = zf.read("word/media/pytex-inline-math-1.svg")
    assert captured["box"].list[0].char == "x"
    assert "word/media/pytex-inline-math-1.svg" in names
    assert svg_payload == b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
    assert "<w:drawing" in xml
    assert "<pic:pic>" in xml
    assert "<asvg:svgBlip" in xml
    assert "<a:noFill/>" in xml
    assert "pytexInlineSvg" not in xml
    wp_extent = re.search(r'<wp:extent\b[^>]*\bcx="([^"]+)"[^>]*\bcy="([^"]+)"', xml)
    effect = re.search(r'<wp:effectExtent\b[^>]*\bt="([^"]+)"[^>]*\bb="([^"]+)"', xml)
    transform = re.search(
        r'<a:xfrm><a:off x="0" y="([^"]+)"/><a:ext cx="([^"]+)" cy="([^"]+)"/>',
        xml,
    )
    assert wp_extent.groups() == (
        str(docx._emu(captured["box"].width)),
        str(docx._emu(captured["box"].height + captured["box"].depth)),
    )
    assert effect.groups() == ("0", "0")
    assert transform.groups() == (
        "0",
        str(docx._emu(captured["box"].width)),
        str(docx._emu(captured["box"].height + captured["box"].depth)),
    )
    assert f'<w:position w:val="-{docx.half_pt(captured["box"].depth)}"/>' in xml
    assert 'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"' in rels_xml
    assert 'Target="media/pytex-inline-math-1.svg"' in rels_xml
    assert 'Extension="svg"' in content_types
    assert "image/svg+xml" in content_types


def test_docx_inline_svg_placeholders_do_not_collide_after_ninth_picture(parser, monkeypatch):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    para = pg.Paragraph(parser, indent=False)
    nodes = []
    for _ in range(12):
        owner = mmode.InlineMathNode(nodes=[_math_atom("x")])
        on = nd.MathShift(True)
        on.source = owner
        on.kern = Dimen()
        off = nd.MathShift(False)
        off.source = owner
        off.kern = Dimen()
        nodes.extend([on, nd.CharNode("x", font), off, nd.Glue(Glue(Dimen(2)), None)])
    line = _FakeHBox(nodes, para, width=120, height=12, depth=4)

    def fake_svg(box):
        return b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'

    monkeypatch.setattr(backend, "inlineMathSvg", fake_svg)

    backend.shipout(_page_box([line]))

    data = _docx_bytes(parser, backend)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        document_xml = zf.read("word/document.xml").decode("utf-8")
        rels_xml = zf.read("word/_rels/document.xml.rels").decode("utf-8")
    embed_ids = set(re.findall(r'r:embed="([^"]+)"', document_xml))
    image_rel_ids = set(
        re.findall(
            r'<Relationship Id="([^"]+)" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"',
            rels_xml,
        )
    )
    assert "pytexInlineSvg" not in document_xml
    assert len(embed_ids) == 12
    assert embed_ids <= image_rel_ids
    assert len([name for name in names if name.startswith("word/media/") and name.endswith(".svg")]) == 12


def test_docx_display_math_embeds_shifted_svg_picture(parser, monkeypatch):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    owner = mmode.DisplayMathNode()
    owner.list.append(_math_atom("x"))
    before = nd.Glue(Glue(Dimen(6)), "\\abovedisplayskip")
    before.source = owner
    after = nd.Glue(Glue(Dimen(4)), "\\belowdisplayskip")
    after.source = owner
    display_box = _FakeHBox([nd.CharNode("x", font)], source=owner, width=50, height=12, depth=3)
    display_box.shifted = Dimen(20)
    para = pg.Paragraph(parser, indent=False)
    captured = []

    def fake_svg(box):
        captured.append(box)
        return b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'

    monkeypatch.setattr(backend, "inlineMathSvg", fake_svg)

    backend.shipout(_page_box([before, display_box, after, _line_box("After", para, font)]))

    document = _word_document(parser, backend)
    assert document.paragraphs[0].text == ""
    assert document.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.LEFT
    assert document.paragraphs[1].text == "After"
    assert int(document.paragraphs[1].paragraph_format.space_before) == int(docx._length(Dimen(4)))
    assert len(captured) == 1
    assert captured[0].node_type == nd.NODE_TYPE.VLIST
    assert captured[0].list == [display_box]
    assert captured[0].width == display_box.shifted + display_box.width
    data = _docx_bytes(parser, backend)
    xml = _document_xml(data)
    assert "<w:drawing" in xml
    assert "<asvg:svgBlip" in xml
    assert f'cx="{docx._emu(display_box.shifted + display_box.width)}"' in xml
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.read("word/media/pytex-inline-math-1.svg") == b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'


def test_docx_display_math_uses_page_glue_state_for_display_skip(parser, monkeypatch):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    owner = mmode.DisplayMathNode()
    before = nd.Glue(
        Glue(Dimen(12), shrink=Stretchness(Dimen(12), 0)),
        "\\abovedisplayskip",
    )
    before.source = owner
    display_box = _FakeHBox([nd.CharNode("x", font)], source=owner, width=50, height=12, depth=3)
    page = _FakeVBox([before, display_box], width=200, height=60)
    page.natural = Glue(Dimen(), shrink=Stretchness(Dimen(12), 0))
    page.glue_ratio = bx.GlueRatio(-1, int(Dimen(6)), int(Dimen(12)))

    def fake_svg(box):
        return b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'

    monkeypatch.setattr(backend, "inlineMathSvg", fake_svg)

    backend.shipout(page)

    document = _word_document(parser, backend)
    assert len(document.paragraphs) == 1
    assert int(document.paragraphs[0].paragraph_format.space_before) == int(docx._length(Dimen(6)))


def test_docx_vlist_tail_negative_glue_reduces_last_line_layout(parser, monkeypatch):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    owner = mmode.DisplayMathNode()
    before = nd.Glue(Glue(Dimen(6)), "\\abovedisplayskip")
    before.source = owner
    after = nd.Glue(Glue(Dimen(-4)), None)
    display_box = _FakeHBox([nd.CharNode("x", font)], source=owner, width=50, height=12, depth=6)

    def fake_svg(box):
        return b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'

    monkeypatch.setattr(backend, "inlineMathSvg", fake_svg)

    backend.shipout(_page_box([before, display_box, after]))

    document = _word_document(parser, backend)
    assert len(document.paragraphs) == 1
    assert int(document.paragraphs[0].paragraph_format.line_spacing) == int(docx._length(Dimen(14)))
    xml = _document_xml(_docx_bytes(parser, backend))
    wp_extent = re.search(r'<wp:extent\b[^>]*\bcx="([^"]+)"[^>]*\bcy="([^"]+)"', xml)
    effect = re.search(r'<wp:effectExtent\b[^>]*\bt="([^"]+)"[^>]*\bb="([^"]+)"', xml)
    transform = re.search(
        r'<a:xfrm><a:off x="0" y="([^"]+)"/><a:ext cx="([^"]+)" cy="([^"]+)"/>',
        xml,
    )
    assert wp_extent.groups() == (
        str(docx._emu(display_box.width)),
        str(docx._emu(Dimen(14))),
    )
    assert effect.groups() == ("0", str(docx._emu(Dimen(4))))
    assert transform.groups() == (
        "0",
        str(docx._emu(display_box.width)),
        str(docx._emu(Dimen(18))),
    )


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
    assert document.tables[0].alignment == WD_TABLE_ALIGNMENT.LEFT
    assert document.tables[0].cell(0, 1).text == "a"
    assert document.tables[0].cell(0, 3).text == "b"
    assert document.tables[0].cell(1, 1).text == "c"
    assert document.tables[0].cell(1, 3).text == "d"
    xml = _document_xml(data)
    assert "<w:tblCellMar>" in xml
    assert xml.count('w:w="0" w:type="dxa"') >= 4
    assert xml.count("<w:noWrap/>") >= 4


def test_docx_alignment_zero_width_overhang_cell_gets_visible_width(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    owner = align.HAlignment()
    owner.tabskips = [Glue(Dimen(50)), Glue(Dimen(50))]
    visible = bx.HBox(parser, None, 0)
    visible.list = _char_nodes("1", font)
    visible = visible.typeset(parser)
    cell = bx.HBox(parser, Dimen(), None)
    cell.list = [nd.Kern(-visible.width), visible]
    cell = cell.typeset(parser)
    cell.span = 1
    row = align.Row()
    row.cells = [cell]
    owner.rows = [row]
    row_box = _FakeHBox([], source=owner, width=100, height=10, depth=2)

    backend.shipout(_page_box([row_box]))

    xml = _document_xml(_docx_bytes(parser, backend))
    cell_texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', xml)
    grid_widths = [
        value
        for value in re.findall(r'<w:gridCol\b[^>]*\bw:w="(\d+)"', xml)
    ]
    assert grid_widths == [
        docx.twips(Dimen(50) - visible.width),
        docx.twips(visible.width),
        docx.twips(Dimen(50)),
    ]
    assert '<w:tblLayout w:type="fixed"/>' in xml
    assert ">1<" in xml
    assert "\xa0" not in "".join(cell_texts)


def test_docx_alignment_cell_inline_math_uses_table_row_baseline(parser, monkeypatch):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    owner = align.HAlignment()
    math_owner = mmode.InlineMathNode(nodes=[_math_atom("x")])
    on = nd.MathShift(True)
    on.source = math_owner
    on.kern = Dimen()
    off = nd.MathShift(False)
    off.source = math_owner
    off.kern = Dimen()
    cell = _FakeHBox([on, nd.CharNode("x", font), off], width=10, height=8, depth=3)
    cell.span = 1
    row = align.Row()
    row.cells = [cell]
    owner.rows = [row]
    row_box = _FakeHBox([], source=owner, width=10, height=8, depth=3)

    captured = {}

    def fake_svg(box):
        captured["box"] = box
        return b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'

    monkeypatch.setattr(backend, "inlineMathSvg", fake_svg)

    backend.shipout(_page_box([row_box]))

    xml = _document_xml(_docx_bytes(parser, backend))
    assert "<w:drawing" in xml
    assert f'<w:position w:val="-{docx.half_pt(captured["box"].depth)}"/>' in xml


def test_docx_zero_width_inline_vbox_is_not_emitted(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    para = pg.Paragraph(parser, indent=False)
    vbox = _FakeVBox([], width=0, height=8, depth=3)
    line = _FakeHBox([nd.CharNode("A", font), vbox, nd.CharNode("B", font)], para)

    backend.shipout(_page_box([line]))

    data = _docx_bytes(parser, backend)
    xml = _document_xml(data)
    document = WordDocument(io.BytesIO(data))
    assert "<w:drawing" not in xml
    assert document.paragraphs[0].text == "AB"


def test_docx_inline_vbox_uses_depth_position(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    font = _install_font(parser)
    para = pg.Paragraph(parser, indent=False)
    vbox = _FakeVBox([], width=20, height=8, depth=3)
    line = _FakeHBox([nd.CharNode("A", font), vbox], para, height=8, depth=3)

    backend.shipout(_page_box([line]))

    xml = _document_xml(_docx_bytes(parser, backend))
    assert "<w:drawing" in xml
    assert f'<w:position w:val="-{docx.half_pt(vbox.depth)}"/>' in xml


def test_docx_inline_vtop_is_lowered_by_height(parser):
    backend = docx.DocxBackend(parser)
    parser.shipout = backend
    _install_font(parser)
    para = pg.Paragraph(parser, indent=False)
    vtop = bx.VTop(parser, None, 0)
    vtop.list = []
    vtop.width = Dimen(20)
    vtop.height = Dimen(8)
    vtop.depth = Dimen(30)
    vtop.to = vtop.height
    vtop.spread = Dimen()
    vtop.natural = Glue()
    vtop.glue_ratio = bx.GlueRatio(0, 0, 1)
    vtop.shifted = Dimen()
    line = _FakeHBox([vtop], para, width=20, height=8, depth=30)

    backend.shipout(_page_box([line]))

    xml = _document_xml(_docx_bytes(parser, backend))
    assert "<w:drawing" in xml
    assert f'<w:position w:val="-{docx.half_pt(vtop.height)}"/>' in xml
    assert f'<w:position w:val="-{docx.half_pt(vtop.depth)}"/>' not in xml


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
