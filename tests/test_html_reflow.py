from types import SimpleNamespace
from lxml import etree
from lxml.html import builder
import pytest

from pytex import align
from pytex import box
from pytex import font as txfont
from pytex import glue
from pytex import html_reflow
from pytex import mmode
from pytex import node as nd
from pytex import reflow
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


def _ord_atom(char):
    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = mmode.MathSymbol(ord(char), -1)
    return atom


def _open_body(parser, backend=None, jobname="html-reflow-test"):
    parser.jobname = jobname
    backend = backend or html_reflow.HTMLReflowBackend(parser)
    backend.document = backend.open()
    backend.page = backend.document.newPage(Dimen(), Dimen())
    return backend, backend.page.body


def _typeset_hbox(parser, hbox, backend=None):
    backend, body = _open_body(parser, backend=backend)
    with reflow.Builder(backend, body):
        return backend.typesetHBox(hbox)


def _typeset_alignment(parser, owner, yspacing=Dimen(), backend=None):
    backend, body = _open_body(parser, backend=backend)
    table = body.newTable(yspacing=yspacing)
    with reflow.Builder(backend, table):
        backend.typesetHAlignment(owner, collection=[], yspacing=yspacing)
    return table


def test_reflow_generic_interface_builds_parent_created_tree():
    document = html_reflow.Document("tree")
    page = document.newPage(Dimen(100), Dimen(200))
    block = page.body.newBlock(xspacing=Dimen(12), yspacing=Dimen(6))
    paragraph = block.newParagraph(justify="center")
    line = paragraph.newLine()
    font = _fake_font(subst_font_name="Times New Roman")
    run = line.newTextRun(font, reflow.Color.black)
    run.setChar(_char("A", font))

    assert isinstance(document, reflow.Document)
    assert page.body.nodes == [block]
    assert block.nodes == [paragraph]
    assert paragraph.nodes == [line]
    assert line.nodes == [run]
    assert run.node.text == "A"


def test_html_reflow_close_writes_document_head(parser):
    backend, body = _open_body(parser, jobname="reflow-head")
    body.append(reflow.Element(builder.DIV("x")))
    backend.close()

    html = parser.resolver.in_memory_files["reflow-head.html"].content
    assert html.startswith("<!doctype html>")
    assert '<html lang="en">' in html
    assert '<meta charset="utf-8">' in html
    assert "<title>reflow-head</title>" in html
    assert "math{font-family:" in html
    assert "<body>" in html
    assert "<div>x</div>" in html


def test_html_reflow_maps_math_operator_period_slot_to_period(parser):
    atom = mmode.Atom(mmode.ATOM_TYPE.PUNCT)
    atom.nucleus = mmode.MathSymbol((mmode.ATOM_TYPE.PUNCT.value << 12) | (0 << 8) | 0x3A, -1)

    backend = html_reflow.HTMLReflowBackend(parser)
    assert backend.typesetSymbol(atom.nucleus, atom_type=mmode.ATOM_TYPE.PUNCT).text == "."


@pytest.mark.xfail(reason="MathML list lowering still uses the old appendOutput/container API.", strict=True)
def test_html_reflow_maps_ord_period_slot_in_compacted_runs(parser):
    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (0 << 8) | 0x3A, -1)

    backend = html_reflow.HTMLReflowBackend(parser)
    node = backend.typesetMList(
        html_reflow.MROW(),
        [atom],
        atom_type=mmode.ATOM_TYPE.ORD,
        style=mmode.Style(mmode.MATH_STYLE.T),
    )
    assert node.text == "."


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


def test_html_reflow_bundles_local_opentype_font(parser, tmp_path):
    parser.resolver.output_in_memory = False
    backend, _body = _open_body(parser, jobname="font-bundle")
    source = tmp_path / "Custom.otf"
    source.write_bytes(b"not-a-real-font")
    font = _fake_font(kind="opentype", name="Custom Font", path=str(source))

    assert backend.define_font(font) == "pytex-font-1"
    backend.close()

    html = (tmp_path / "font-bundle.html").read_text()
    copied = tmp_path / "font-bundle.assets" / "fonts" / "pytex-font-1.otf"
    assert '@font-face{font-family:"pytex-font-1";' in html
    assert 'url("font-bundle.assets/fonts/pytex-font-1.otf")' in html
    assert copied.read_bytes() == b"not-a-real-font"


def test_html_reflow_reuses_bundled_font_face_for_same_file(parser, tmp_path):
    parser.resolver.output_in_memory = False
    backend, _body = _open_body(parser, jobname="font-reuse")
    source = tmp_path / "Custom.otf"
    source.write_bytes(b"font-data")

    first = _fake_font(kind="opentype", name="Custom Font", at=10, path=str(source))
    second = _fake_font(kind="opentype", name="Custom Font", at=12, path=str(source))
    assert backend.define_font(first) == "pytex-font-1"
    assert backend.define_font(second) == "pytex-font-1"
    backend.close()

    html = (tmp_path / "font-reuse.html").read_text()
    assert html.count("@font-face{") == 1
    assert html.count('font-family:"pytex-font-1"') == 1


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


def test_html_reflow_hbox_renders_inside_builder_context(parser):
    font = _fake_font(subst_font_name="Times New Roman")
    hfil = glue.Glue(0, glue.Stretchness(2, 1))
    row = box.HBox(parser, Dimen(40), None)
    row.list = [_char("A", font), nd.Glue(hfil, None)]
    row = row.typeset(parser)

    rendered = _typeset_hbox(parser, row)
    html = _render(rendered)
    assert "display:block;" in rendered.get("style")
    assert "padding-left:0.0pt;" in rendered.get("style")
    assert ">A " in html


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


@pytest.mark.xfail(reason="Inline math has not been adapted to the new reflow builder interface yet.", strict=True)
def test_html_reflow_typesets_inline_math_with_offsets(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    node = mmode.InlineMathNode(nodes=[_ord_atom("x")])

    rendered = backend.typesetInlineMath(node, collection=[], left_kern=Dimen(3), right_kern=Dimen(5))
    html = _render(rendered)
    assert 'display="inline"' in html
    assert "left:" in html
    assert "right:" in html
    assert ">x<" in html


@pytest.mark.xfail(reason="Display math has not been adapted to the new reflow builder interface yet.", strict=True)
def test_html_reflow_typesets_display_math_with_eqno_table(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    node = mmode.DisplayMathNode()
    node.list = [_ord_atom("x")]
    node.eqno = (SimpleNamespace(list=[_ord_atom("1")]), False)

    rendered = backend.typesetDisplayMath(node, collection=[], yspacing=Dimen(6))
    html = _render(rendered)
    assert 'display="block"' in html
    assert "<mtable" in html
    assert 'columnalign="center right"' in html
    assert ">x<" in html
    assert ">1<" in html


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
