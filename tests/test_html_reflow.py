from types import SimpleNamespace
from lxml import etree
from lxml.html import builder
import pytest
from PIL import Image
from reportlab.pdfgen import canvas

from pytex import align
from pytex import box
from pytex import font as txfont
from pytex import glue
from pytex import graphics
from pytex import glyph
from pytex import html_reflow
from pytex import hmode
from pytex import mmode
from pytex import node as nd
from pytex import opentype
from pytex import paragraph as pg
from pytex import reflow
from pytex import texlive
from pytex.dimen import Dimen

# prevent module side effects
html_reflow.mod.init = None




class _FakeTextBackend:
    def __init__(self, kind="opentype", name="Fake Font", subst_font_name=None, path=None, font_number=0):
        self.kind = kind
        self.name = name
        self.subst_font_name = subst_font_name
        self.path = path
        self.font_number = font_number
        self.fontdimen = [0.0, 0.5, 0.0, 0.0, 0.7, 1.0, 0.0]


def _render(node):
    if isinstance(node, reflow.Element):
        node = node.node
    return etree.tostring(node, method="html", encoding="unicode")


def _fake_font(kind="opentype", name="Fake Font", subst_font_name=None, at=10, path=None, font_number=0):
    return txfont.Font(
        _FakeTextBackend(
            kind=kind,
            name=name,
            subst_font_name=subst_font_name,
            path=path,
            font_number=font_number,
        ),
        at,
    )


def _char(char, font):
    return nd.CharNode(
        char,
        font,
        char_info=SimpleNamespace(
            char=char,
            width=0.5,
            height=0.7,
            depth=0.0,
            italic=0.0,
        ),
    )


def _text_box(parser, text, font, width=None):
    if width is None:
        hbox = box.HBox(parser, None, 0)
    else:
        hbox = box.HBox(parser, Dimen(width), None)
    hbox.list = [_char(char, font) for char in text]
    return hbox.typeset(parser)


def _node_box(parser, nodes, width=None):
    if width is None:
        hbox = box.HBox(parser, None, 0)
    else:
        hbox = box.HBox(parser, Dimen(width), None)
    hbox.list = list(nodes)
    return hbox.typeset(parser)


def _line_box(parser, nodes, owner=None, width=None):
    hbox = _node_box(parser, nodes, width=width)
    hbox.source = owner
    return hbox


def _ord_atom(char):
    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = mmode.MathSymbol(ord(char), -1)
    return atom


def _open_body(parser, backend=None, jobname="html-reflow-test"):
    parser.jobname = jobname
    backend = backend or html_reflow.HTMLReflowBackend(parser)
    backend.document = backend.open()
    backend.page = backend.document.newPage(_page_spec())
    return backend, backend.page.body


def _page_spec(width=Dimen(), height=Dimen()):
    return reflow.PageSpec(width, height, Dimen(), Dimen(), Dimen(), Dimen())


def _typeset_hbox(parser, hbox, backend=None):
    backend, body = _open_body(parser, backend=backend)
    with reflow.Builder(backend, body):
        return backend.typesetHBox(hbox)


def _typeset_alignment(parser, owner, yspacing=Dimen(), backend=None):
    backend, body = _open_body(parser, backend=backend)
    table = body.newTable(yspacing=yspacing)
    collection = [_alignment_row_box(parser, owner, row) for row in owner.rows]
    with reflow.Builder(backend, table):
        backend.typesetHAlignment(owner, collection=collection, yspacing=yspacing)
    return table


def _alignment_row_box(parser, owner, row):
    nodes = []
    for index, cell in enumerate(row.cells):
        if index < len(owner.tabskips):
            nodes.append(nd.Glue(owner.tabskips[index], None))
        nodes.append(cell)
    if len(owner.tabskips) > len(row.cells):
        nodes.append(nd.Glue(owner.tabskips[len(row.cells)], None))
    box = _node_box(parser, nodes)
    box.source = owner
    return box


def test_reflow_generic_interface_builds_parent_created_tree():
    document = html_reflow.Document("tree")
    page = document.newPage(_page_spec(Dimen(100), Dimen(200)))
    paragraph = page.body.newParagraph(spacing_before=Dimen(6), justify="center")
    line = paragraph.newLine()
    font = _fake_font(subst_font_name="Times New Roman")
    run = line.newTextRun(font, reflow.Color.black)
    run.setChar(_char("A", font))

    assert isinstance(document, reflow.Document)
    assert page.body.nodes == [paragraph]
    assert paragraph.nodes == [line]
    assert line.nodes == [run]
    assert ">A<" in _render(run)


def test_html_reflow_close_writes_document_head(parser):
    backend, body = _open_body(parser, jobname="reflow-head")
    body.append(reflow.Element(builder.DIV("x")))
    backend.close()

    html = parser.resolver.in_memory_files["reflow-head.html"].content
    assert html.startswith("<!doctype html>")
    assert '<html lang="en">' in html
    assert '<meta charset="utf-8">' in html
    assert "<title>reflow-head</title>" in html
    assert "<head style=" not in html
    assert "<style>" in html
    assert "math{font-family:" in html
    assert "<body>" in html
    assert "<div>x</div>" in html


def test_html_reflow_epdf_graphic_special_creates_inline_svg_image(parser, tmp_path, monkeypatch):
    fig = tmp_path / "fig.pdf"
    c = canvas.Canvas(str(fig), pagesize=(200, 100))
    c.drawString(20, 50, "FIG")
    c.save()
    hbox = _node_box(
        parser,
        [nd.Special(f"pdf: epdf bbox 0 0 200 100 width 72pt ({fig})")],
    )

    html = _render(_typeset_hbox(parser, hbox))

    assert "<img" in html
    assert "<object" not in html
    assert "html-reflow-test.assets/graphics/graphic-1.svg" in html
    assert "width:71.731009pt;" in html
    assert "height:35.865504pt;" in html
    assert (tmp_path / "html-reflow-test.assets" / "graphics" / "graphic-1.svg").exists()


@pytest.mark.parametrize(
    ("suffix", "image_format"),
    [
        ("png", "PNG"),
        ("jpg", "JPEG"),
    ],
)
def test_html_reflow_raster_graphic_special_copies_inline_image(
    parser,
    tmp_path,
    suffix,
    image_format,
):
    fig = tmp_path / f"fig.{suffix}"
    Image.new("RGB", (20, 10), "red").save(fig, format=image_format)
    payload = fig.read_bytes()
    hbox = _node_box(
        parser,
        [nd.Special(f"pdf: image width 72pt height 36pt ({fig})")],
    )

    html = _render(_typeset_hbox(parser, hbox))

    target = tmp_path / "html-reflow-test.assets" / "graphics" / f"graphic-1.{suffix}"
    assert "<img" in html
    assert f"html-reflow-test.assets/graphics/graphic-1.{suffix}" in html
    assert "width:71.731009pt;" in html
    assert "height:35.865504pt;" in html
    assert target.read_bytes() == payload


def test_html_reflow_epdf_graphic_uses_xdvipdfmx_scale_transform(parser, tmp_path, monkeypatch):
    fig = tmp_path / "fig.pdf"
    c = canvas.Canvas(str(fig), pagesize=(200, 100))
    c.drawString(20, 50, "FIG")
    c.save()
    hbox = _node_box(
        parser,
        [
            nd.Special("pdf:btrans"),
            nd.Special("x:scale 0.5 0.5"),
            nd.Special(f"pdf: epdf bbox 0 0 200 100 ({fig})"),
            nd.Special("pdf:etrans"),
        ],
    )

    html = _render(_typeset_hbox(parser, hbox))

    assert "<img" in html
    assert "width:100pt;" in html
    assert "height:50pt;" in html
    assert "transform:scale" not in html


def test_html_reflow_graphic_rlap_compensation_uses_emitted_advance(parser, tmp_path):
    fig = tmp_path / "fig.pdf"
    c = canvas.Canvas(str(fig), pagesize=(576, 180))
    c.drawString(20, 90, "FIG")
    c.save()
    natural = _node_box(
        parser,
        [nd.Special(f"pdf: epdf bbox 0 0 576 180 ({fig})")],
        width=576,
    )
    zero_width = _node_box(parser, [natural, nd.Kern(Dimen(-576))], width=0)
    hbox = _node_box(
        parser,
        [
            nd.Special("pdf:btrans"),
            nd.Special("x:scale 0.5625 0.5625"),
            zero_width,
            nd.Special("pdf:etrans"),
            nd.Kern(Dimen(324)),
        ],
        width=324,
    )

    html = _render(_typeset_hbox(parser, hbox))

    assert "<img" in html
    assert "width:323.999981pt;" in html
    assert "margin-left:-576.0pt" not in html
    assert "margin-left:-324.0pt" not in html


def test_html_reflow_maps_math_operator_period_slot_to_period(parser):
    atom = mmode.Atom(mmode.ATOM_TYPE.PUNCT)
    atom.nucleus = mmode.MathSymbol((mmode.ATOM_TYPE.PUNCT.value << 12) | (0 << 8) | 0x3A, -1)

    backend = html_reflow.HTMLReflowBackend(parser)
    assert backend.typesetSymbol(atom.nucleus, atom_type=mmode.ATOM_TYPE.PUNCT).node.text == "."


def test_html_reflow_maps_ord_period_slot_in_compacted_runs(parser):
    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (0 << 8) | 0x3A, -1)

    backend = html_reflow.HTMLReflowBackend(parser)
    row = html_reflow.MRow()
    with reflow.Builder(backend, row):
        backend.typesetMList(
            [atom],
            atom_type=mmode.ATOM_TYPE.ORD,
            style=mmode.Style(mmode.MATH_STYLE.T),
        )

    node = row.node
    assert len(node) == 1
    assert node[0].tag.endswith("mn")
    assert node[0].text == "."


def test_html_reflow_asserts_on_raw_tfm_text_backend(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    font = _fake_font(kind="tfm", name="cmr10")

    with pytest.raises(AssertionError, match="OpenType-backed text fonts"):
        backend._text_font_family(font)


def test_html_reflow_accepts_substituted_text_backend(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    font = _fake_font(kind="tfm", name="cmr10", subst_font_name="Times New Roman")

    assert backend._text_font_family(font) == "Times New Roman"


def test_html_reflow_text_run_collects_characters_and_color():
    font = _fake_font(subst_font_name="Times New Roman")
    text = html_reflow.TextRun(font, reflow.Color.rgb(("0.25", "0.5", "0.75")))
    text.setChar(_char("A", font))
    text.setSpace(Dimen(3))
    text.setChar(_char("B", font))

    rendered = _render(text)
    assert "color:rgb(63,127,191);" in rendered
    assert "font-size:" in rendered
    assert ">A B<" in rendered


def test_html_reflow_text_kern_is_real_inline_node_not_escaped_text():
    font = _fake_font(subst_font_name="Times New Roman")
    text = html_reflow.TextRun(font, reflow.Color.black)
    text.setChar(_char("A", font))
    text.setKern(Dimen(-2))
    text.setChar(_char("B", font))

    rendered = _render(text)
    assert "&lt;" not in rendered
    assert "display:inline-block;" in rendered
    assert "margin-left:" in rendered
    assert rendered.index(">A<") < rendered.index("display:inline-block;") < rendered.index(">B<")


def test_html_reflow_drops_net_negative_spacing_before_first_content(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    leading = box.HBox(parser, Dimen(-12), None)
    leading.list = []
    leading = leading.typeset(parser)
    hbox = _node_box(parser, [leading, nd.Kern(Dimen(-6)), _char("[", font), _char("1", font)])

    html = _render(_typeset_hbox(parser, hbox))

    assert "margin-left:-" not in html
    assert ">[1<" in html


def test_html_reflow_treats_leading_space_as_pre_content_spacing(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    hbox = _node_box(parser, [_char(" ", font), nd.Kern(Dimen(-12)), _char("[", font), _char("1", font)])

    html = _render(_typeset_hbox(parser, hbox))

    assert "margin-left:-" not in html
    assert ">[1<" in html


def test_html_reflow_treats_spacing_only_hbox_as_pre_content_spacing(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    positive = box.HBox(parser, Dimen(6), None)
    positive.list = []
    positive = positive.typeset(parser)
    spacer = _node_box(parser, [positive, nd.Kern(Dimen(-12))])
    hbox = _node_box(parser, [_char(" ", font), spacer, _char("[", font), _char("1", font)])

    html = _render(_typeset_hbox(parser, hbox))

    assert "margin-left:-" not in html
    assert ">[1<" in html


def test_html_reflow_walks_specials_inside_leading_spacing_only_hbox(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    spacer = _node_box(
        parser,
        [
            nd.Special("pdf: dest (cite.one)[@thispage/XYZ @xpos @ypos null]"),
            nd.Kern(Dimen(-12)),
        ],
    )
    hbox = _node_box(parser, [spacer, _char("[", font), _char("1", font)])

    html = _render(_typeset_hbox(parser, hbox))

    assert 'id="cite.one"' in html
    assert "margin-left:-" not in html
    assert ">[1<" in html


def test_html_reflow_clamps_leading_spacing_without_losing_net_indent(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    leading = box.HBox(parser, Dimen(10), None)
    leading.list = []
    leading = leading.typeset(parser)
    hbox = _node_box(parser, [leading, nd.Kern(Dimen(-4)), _char("A", font)])

    html = _render(_typeset_hbox(parser, hbox))

    width = reflow.PT(Dimen(6))
    assert f"display:inline-block;width:{width};" in html
    assert "margin-left:-" not in html
    assert html.index(f"width:{width};") < html.index(">A<")


def test_html_reflow_preserves_interior_negative_line_kern(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    hbox = _node_box(parser, [_char("A", font), nd.Kern(Dimen(-2)), _char("B", font)])

    html = _render(_typeset_hbox(parser, hbox))

    margin = reflow.PT(Dimen(-2))
    assert f"margin-left:{margin};" in html
    assert html.index(">A<") < html.index(f"margin-left:{margin};") < html.index(">B")


def test_html_reflow_bundles_local_opentype_font(parser, tmp_path):
    parser.resolver.output_in_memory = False
    backend, _body = _open_body(parser, jobname="font-bundle")
    source = tmp_path / "Custom.otf"
    source.write_bytes(b"not-a-real-font")
    font = _fake_font(kind="opentype", name="Custom Font", path=str(source))

    assert backend.define_font(font) == "Custom Font"
    backend.close()

    html = (tmp_path / "font-bundle.html").read_text()
    copied = tmp_path / "font-bundle.assets" / "fonts" / "Custom Font.otf"
    assert '@font-face{font-family:"Custom Font";' in html
    assert 'url("font-bundle.assets/fonts/Custom Font.otf")' in html
    assert copied.read_bytes() == b"not-a-real-font"


def test_html_reflow_reuses_bundled_font_face_for_same_file(parser, tmp_path):
    parser.resolver.output_in_memory = False
    backend, _body = _open_body(parser, jobname="font-reuse")
    source = tmp_path / "Custom.otf"
    source.write_bytes(b"font-data")

    first = _fake_font(kind="opentype", name="Custom Font", at=10, path=str(source))
    second = _fake_font(kind="opentype", name="Custom Font", at=12, path=str(source))
    assert backend.define_font(first) == "Custom Font"
    assert backend.define_font(second) == "Custom Font"
    backend.close()

    html = (tmp_path / "font-reuse.html").read_text()
    assert html.count("@font-face{") == 1
    assert html.count('font-family:"Custom Font"') == 1


def test_html_reflow_converts_and_bundles_type1_font(parser, tmp_path):
    parser.resolver.output_in_memory = False
    backend, _body = _open_body(parser, jobname="type1-font-bundle")
    converted = parser.loadFontBackend("cmr10")
    if not isinstance(converted, opentype.Type1TrueTypeBackend):
        pytest.skip("cmr10 Type 1 font not found")
    font = txfont.Font(converted, Dimen(10))

    family = backend.define_font(font)
    backend.close()

    html = (tmp_path / "type1-font-bundle.html").read_text()
    copied = tmp_path / "type1-font-bundle.assets" / "fonts" / f"{family}.ttf"
    assert parser.supported_font_classes == (opentype.TrueTypeBackend,)
    assert f'font-family:"{family}"' in html
    assert copied.read_bytes() == converted.fontData()


def test_html_reflow_emits_cluster_sources_for_opentype_shaping(parser):
    parser.registerSupportedFontClasses(opentype.TrueTypeBackend)
    converted = parser.loadFontBackend("cmr10")
    if not isinstance(converted, opentype.Type1TrueTypeBackend):
        pytest.skip("cmr10 Type 1 font not found")
    font = txfont.Font(converted, Dimen(10))

    hyphens = [glyph.TextChar("-", font, True) for _ in range(3)]
    emdash = glyph.GlyphCluster(hyphens, nd.CharNode(chr(124), font))
    dashes = html_reflow.TextRun(font)
    dashes.setChar(emdash)

    quote_sources = [glyph.TextChar(chr(96), font, False) for _ in range(2)]
    double_quote = glyph.GlyphCluster(
        quote_sources,
        nd.CharNode(chr(92), font),
    )
    quotes = html_reflow.TextRun(font)
    quotes.setChar(double_quote)

    assert ">---<" in _render(dashes)
    assert "font-kerning:normal" in _render(dashes)
    assert "font-variant-ligatures:common-ligatures" in _render(dashes)
    assert ">‘‘<" in _render(quotes)


def test_html_reflow_emits_destination_anchor_for_pdf_dest_special(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    hbox = _node_box(
        parser,
        [
            nd.Special("pdf: dest (target.1)[@thispage/XYZ @xpos @ypos null]"),
            _char("A", font),
        ],
    )

    html = _render(_typeset_hbox(parser, hbox))
    assert 'id="target.1"' in html
    assert ">A<" in html


def test_html_reflow_wraps_internal_goto_annotation_as_link(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    hbox = _node_box(
        parser,
        [
            nd.Special("pdf: beginann <</Type/Annot/Subtype/Link/A<</S/GoTo/D(target.1)>>>>"),
            _char("A", font),
            nd.Special("pdf: endann"),
            _char("B", font),
        ],
    )

    html = _render(_typeset_hbox(parser, hbox))
    assert 'href="#target.1"' in html
    assert html.index('href="#target.1"') < html.index(">B<")


def test_html_reflow_wraps_gotor_annotation_as_external_link(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    hbox = _node_box(
        parser,
        [
            nd.Special("pdf: beginann <</Type/Annot/Subtype/Link/A<</S/GoToR/F(other.pdf)/D(sec.2)>>>>"),
            _char("A", font),
            nd.Special("pdf: endann"),
        ],
    )

    html = _render(_typeset_hbox(parser, hbox))
    assert 'href="other.pdf#sec.2"' in html


def test_html_reflow_reopens_line_spanning_annotation_per_line(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    owner = pg.Paragraph(parser, indent=False)
    line1 = _line_box(
        parser,
        [
            nd.Special("pdf: beginann <</Type/Annot/Subtype/Link/A<</S/GoTo/D(target.1)>>>>"),
            _char("A", font),
        ],
        owner,
    )
    line2 = _line_box(
        parser,
        [
            _char("B", font),
            nd.Special("pdf: endann"),
            _char("C", font),
        ],
        owner,
    )
    backend, body = _open_body(parser)
    with reflow.Builder(backend, body):
        para = body.newParagraph()
        backend.typesetParagraph(para, owner, [line1, line2])

    html = _render(body)
    assert html.count('href="#target.1"') == 2
    assert html.index(">A<") < html.index(">B<") < html.index(">C<")
    assert html.rindex('href="#target.1"') < html.index(">C<")


def test_html_reflow_multiline_inline_math_emits_first_piece_once(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    owner = pg.Paragraph(parser, indent=False)
    inline = mmode.InlineMathNode(nodes=[_ord_atom("x"), _ord_atom("y")])
    on = nd.MathShift(True)
    on.source = inline
    on.kern = Dimen()
    off = nd.MathShift(False)
    off.source = inline
    off.kern = Dimen()

    line1 = _line_box(parser, [_char("A", font), on, _char("x", font)], owner)
    line2 = _line_box(parser, [_char("y", font), off, _char("B", font)], owner)
    backend, body = _open_body(parser)
    with reflow.Builder(backend, body):
        para = body.newParagraph()
        backend.typesetParagraph(para, owner, [line1, line2])

    html = _render(body)
    assert html.count("<math") == 1
    assert ">A<" in html
    assert ">B<" in html
    assert ">xy<" in html
    assert html.index(">A<") < html.index("<math") < html.index(">B<")


def test_html_reflow_hbox_renders_inside_builder_context(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    hfil = glue.Glue(0, glue.Stretchness(2, 1))
    row = box.HBox(parser, Dimen(40), None)
    row.list = [_char("A", font), nd.Glue(hfil, None)]
    row = row.typeset(parser)

    rendered = _typeset_hbox(parser, row)
    html = _render(rendered)
    style = rendered._node.get("style")
    assert isinstance(rendered, html_reflow.Paragraph)
    assert "padding-top:0.0pt;" in style
    assert "width:100%;" in style
    assert ">A<" in html
    assert ">A <" not in html


def test_html_reflow_hbox_strips_edge_glue_used_for_justify(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    hfil = glue.Glue(0, glue.Stretchness(1, 1))
    row = box.HBox(parser, Dimen(40), None)
    row.list = [nd.Glue(hfil, None), _char("A", font), nd.Glue(hfil, None)]
    row = row.typeset(parser)

    rendered = _typeset_hbox(parser, row)
    html = _render(rendered)
    assert "justify:center;" in html
    assert ">A<" in html
    assert "> A<" not in html
    assert ">A <" not in html


def test_html_reflow_hbox_keeps_unset_infinite_edge_glue_out_of_justify(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    hfil = glue.Glue(0, glue.Stretchness(1, 1))
    row = box.HBox(parser, None, 0)
    row.list = [nd.Glue(hfil, None), _char("A", font), nd.Glue(hfil, None)]
    row = row.typeset(parser)

    rendered = _typeset_hbox(parser, row)
    html = _render(rendered)

    assert "justify:justify;" in html
    assert "justify:center;" not in html
    assert ">A<" in html


def test_html_reflow_hbox_keeps_finite_edge_glue(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    row = box.HBox(parser, None, 0)
    row.list = [nd.Glue(glue.Glue(Dimen(9)), None), _char("A", font), nd.Glue(glue.Glue(Dimen(7)), None)]
    row = row.typeset(parser)

    html = _render(_typeset_hbox(parser, row))

    assert "> A <" in html


def test_html_reflow_nested_hbox_flattens_into_inline_flow(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    inner = _node_box(parser, [_char("B", font)])
    outer = _node_box(parser, [_char("A", font), inner, _char("C", font)])

    html = _render(_typeset_hbox(parser, outer))

    assert ">ABC<" in html
    assert "display:inline-block" not in html


def test_html_reflow_nested_hbox_preserves_fixed_glue(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    inner = _node_box(
        parser,
        [_char("A", font), nd.Glue(glue.Glue(Dimen(12)), None), _char("B", font)],
    )
    outer = _node_box(parser, [inner, _char("C", font)])

    html = _render(_typeset_hbox(parser, outer))

    assert ">A<" in html
    assert ">B" in html
    width = reflow.PT(Dimen(12))
    assert f"display:inline-block;width:{width};" in html
    assert html.index(">A<") < html.index(f"width:{width};") < html.index(">B")


def test_html_reflow_nested_indent_box_preserves_width(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    indent = box.IndentBox(parser, width=Dimen(15))
    outer = _node_box(parser, [_char("A", font), indent, _char("B", font)])

    html = _render(_typeset_hbox(parser, outer))

    width = reflow.PT(Dimen(15))
    assert f"display:inline-block;width:{width};" in html
    assert html.index(">A<") < html.index(f"width:{width};") < html.index(">B")


def test_html_reflow_nested_empty_hbox_preserves_width(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    spacer = box.HBox(parser, Dimen(18), None)
    spacer.list = []
    spacer = spacer.typeset(parser)
    outer = _node_box(parser, [_char("A", font), spacer, _char("B", font)])

    html = _render(_typeset_hbox(parser, outer))

    width = reflow.PT(Dimen(18))
    assert f"display:inline-block;width:{width};" in html
    assert html.index(">A<") < html.index(f"width:{width};") < html.index(">B")


def test_html_reflow_paragraph_keeps_tex_line_nodes_separate(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    owner = pg.Paragraph(parser, indent=False)
    line1 = _line_box(parser, [_char("A", font)], owner)
    line2 = _line_box(parser, [_char("B", font)], owner)
    backend, body = _open_body(parser)

    with reflow.Builder(backend, body):
        para = body.newParagraph()
        backend.typesetParagraph(para, owner, [line1, nd.Glue(glue.Glue(Dimen(4)), None), line2])

    lines = [node for node in para.nodes if isinstance(node, html_reflow.Line)]
    assert len(lines) == 2
    assert lines[0].lign_height == line1.height + line1.depth
    assert lines[1].lign_height == line2.height + line2.depth


def test_html_reflow_hbox_requires_current_builder(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    font = _fake_font(subst_font_name="Times New Roman")
    hbox = _text_box(parser, "a", font)

    with pytest.raises(AssertionError, match="typesetHBox requires a current reflow builder"):
        backend.typesetHBox(hbox)


def test_html_reflow_alignment_requires_table_builder(parser):
    backend, body = _open_body(parser)
    owner = align.HAlignment()

    with reflow.Builder(backend, body):
        with pytest.raises(AssertionError, match="typesetHAlignment requires a builder with newRow"):
            backend.typesetHAlignment(owner, collection=[], yspacing=Dimen())


def test_html_reflow_typesets_inline_math_with_offsets(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    node = mmode.InlineMathNode(nodes=[_ord_atom("x")])
    on = nd.MathShift(True)
    on.source = node
    on.kern = Dimen(3)
    off = nd.MathShift(False)
    off.source = node
    off.kern = Dimen(5)

    para = html_reflow.Paragraph()
    line = para.newLine()
    with reflow.ParagraphBuilder(backend, para):
        with reflow.LineBuilder(backend, line):
            backend.typesetLine([on, off])

    html = _render(line)
    assert 'display="inline"' in html
    assert ">x<" in html
    assert "display:inline-block;width:" in html
    assert html.index("<math") < html.index("display:inline-block;width:")


def test_html_reflow_typesets_display_math_with_eqno_table(parser):
    backend, body = _open_body(parser)
    node = mmode.DisplayMathNode()
    node.list = [_ord_atom("x")]
    node.eqno = (SimpleNamespace(list=[_ord_atom("1")]), False)

    with reflow.Builder(backend, body):
        backend.typesetDisplayMath(node, collection=[], yspacing=Dimen(6))

    html = _render(body)
    assert 'display="block"' in html
    assert "<table" in html
    assert ">x<" in html
    assert ">1<" in html


def test_html_reflow_table_cells_use_native_table_layout():
    table = html_reflow.Table()
    row = table.newRow()
    row.newCell(justify="right")

    html = _render(table)
    assert "<td" in html
    assert "display:inline-flex" not in html
    assert "text-align:right;" in html
    assert "vertical-align:baseline;" in html


def test_html_reflow_display_math_eqno_uses_inline_math_cell(parser):
    backend, body = _open_body(parser, jobname="display-math-eqno")
    node = mmode.DisplayMathNode()
    node.list = [_ord_atom("x")]
    node.eqno = (SimpleNamespace(list=[_ord_atom("1")]), False)

    with reflow.Builder(backend, body):
        backend.typesetDisplayMath(node, collection=[], yspacing=Dimen(6))

    html = _render(body)
    assert html.count('display="block"') == 1
    assert 'display="inline"' in html
    assert "white-space:nowrap;" in html
    assert "display:inline-flex" not in html


def test_html_reflow_alignment_outer_tabskip_centers_table(parser):
    font = _fake_font(subst_font_name="Times New Roman")

    owner = align.HAlignment()
    fil = glue.Glue(0, glue.Stretchness(1, 1))
    owner.tabskips = [fil, glue.Glue(), fil]
    row = align.Row()
    left = _text_box(parser, "a", font)
    right = _text_box(parser, "b", font)
    left.span = 1
    right.span = 1
    row.cells = [left, right]
    owner.rows = [row]

    table = _typeset_alignment(parser, owner, yspacing=Dimen(12))
    html = _render(table)
    assert 'class="alignment"' in html
    assert "margin-top:" in html
    assert html.count("<td") == 5
    assert ">a<" in html
    assert ">b<" in html


def test_html_reflow_alignment_cell_uses_edge_glue_for_justify(parser):
    font = _fake_font(subst_font_name="Times New Roman")

    owner = align.HAlignment()
    fil = glue.Glue(0, glue.Stretchness(1, 1))
    owner.tabskips = [fil, glue.Glue(), fil]
    row = align.Row()
    hfil = glue.Glue(0, glue.Stretchness(1, 1))

    right = box.HBox(parser, Dimen(30), None)
    right.list = [nd.Glue(hfil, None), _char("r", font)]
    right = right.typeset(parser)
    right.span = 1

    center = box.HBox(parser, Dimen(30), None)
    center.list = [nd.Glue(hfil, None), _char("c", font), nd.Glue(hfil, None)]
    center = center.typeset(parser)
    center.span = 1

    row.cells = [right, center]
    owner.rows = [row]

    table = _typeset_alignment(parser, owner, yspacing=Dimen())
    html = _render(table)
    assert "justify:right;" in html
    assert "justify:center;" in html
    assert ">r<" in html
    assert ">c<" in html


def test_html_reflow_alignment_cell_inherits_unset_hbox_justification(parser):
    font = _fake_font(subst_font_name="Times New Roman")

    owner = align.HAlignment()
    row = align.Row()
    hfil = glue.Glue(0, glue.Stretchness(1, 1))
    center = box.HBox(parser, None, 0)
    center.list = [nd.Glue(hfil, None), _char("c", font), nd.Glue(hfil, None)]
    center = center.typeset(parser)
    center.span = 1
    row.cells = [center]
    owner.rows = [row]

    table = _typeset_alignment(parser, owner, yspacing=Dimen())
    html = _render(table)

    assert "justify:center;" in html
    assert "flex-grow" not in html
    assert ">c<" in html


def test_html_reflow_alignment_cell_strips_hfil_inside_template_spaces(parser):
    font = _fake_font(subst_font_name="Times New Roman")

    owner = align.HAlignment()
    row = align.Row()
    hfil = glue.Glue(0, glue.Stretchness(1, 1))
    center = box.HBox(parser, None, 0)
    center.list = [
        nd.Glue(glue.Glue(Dimen(3)), None),
        nd.Glue(hfil, None),
        _char("c", font),
        nd.Glue(hfil, None),
        nd.Glue(glue.Glue(Dimen(3)), None),
    ]
    center = center.typeset(parser)
    center.span = 1
    row.cells = [center]
    owner.rows = [row]

    table = _typeset_alignment(parser, owner, yspacing=Dimen())
    html = _render(table)

    assert "justify:center;" in html
    assert "flex-grow" not in html
    assert "> c <" in html
