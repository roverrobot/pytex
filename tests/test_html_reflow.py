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
    def __init__(self, kind="opentype", name="Fake Font", subst_font_name=None):
        self.kind = kind
        self.name = name
        self.subst_font_name = subst_font_name
        self.fontdimen = [0.0, 0.5, 0.0, 0.0, 0.7, 1.0, 0.0]


class _CaptureReflow(reflow.Reflow):
    def __init__(self, parser):
        super().__init__(parser)
        self.captured_glue_state = None

    def _glue_state(self, box):
        return {"order": 1, "shrink": False}

    def _box(self, box, inline, xspacing, yspacing):
        return []

    def populateParagraph(self, para, hlist, glue_state):
        self.captured_glue_state = glue_state

    def typesetParagraph(self, para, container=None):
        return container


def _render(node):
    return etree.tostring(node, method="html", encoding="unicode")


def _fake_font(kind="opentype", name="Fake Font", subst_font_name=None, at=10):
    return txfont.Font(
        _FakeTextBackend(kind=kind, name=name, subst_font_name=subst_font_name),
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


def _ord_atom(char):
    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = mmode.MathSymbol(ord(char), -1)
    return atom


def test_html_reflow_close_writes_document_head(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    parser.jobname = "reflow-head"
    backend.body.append(builder.DIV("x"))
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
    text = reflow.TextRun(font)
    text.setChar("A")

    with pytest.raises(AssertionError, match="OpenType-backed text fonts"):
        backend.typesetTextRun(text)


def test_html_reflow_accepts_substituted_text_backend(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    font = _fake_font(kind="tfm", name="cmr10", subst_font_name="Times New Roman")
    text = reflow.TextRun(font)
    text.setChar("A")

    rendered = backend.typesetTextRun(text)
    style = rendered.get("style")
    assert style.startswith("font-family:Times New Roman;font-size:")
    assert style.endswith("pt;")
    assert rendered.text == "A"


def test_reflow_hbox_passes_glue_state_into_populate_paragraph(parser):
    backend = _CaptureReflow(parser)
    rendered = backend.typesetHBox(SimpleNamespace(shifted=None, list=[], width=Dimen(40)))

    assert backend.captured_glue_state == {"order": 1, "shrink": False}
    assert rendered == []


def test_html_reflow_hbox_uses_flex_layout_for_springs(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    font = _fake_font(subst_font_name="Times New Roman")
    hfil = glue.Glue(0, glue.Stretchness(2, 1))
    row = box.HBox(parser, Dimen(40), None)
    row.list = [_char("A", font), nd.Glue(hfil, None)]
    row = row.typeset(parser)

    rendered = backend.typesetHBox(row)
    style = rendered.get("style")
    assert "display:flex;" in style
    assert "align-items:baseline;" in style
    assert "white-space:nowrap;" in style
    assert "width:" in style
    assert any(
        child.get("style", "").startswith("flex-grow:")
        and child.get("style", "").endswith("flex-basis:0;")
        for child in rendered
        if hasattr(child, "get")
    )


def test_html_reflow_typesets_inline_math_with_offsets(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    node = mmode.InlineMathNode(nodes=[_ord_atom("x")])

    rendered = backend.typesetInlineMath(node, collection=[], left_kern=Dimen(3), right_kern=Dimen(5))
    html = _render(rendered)
    assert 'display="inline"' in html
    assert "left:" in html
    assert "right:" in html
    assert ">x<" in html


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
    backend = html_reflow.HTMLReflowBackend(parser)
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

    table = backend.typesetHAlignment(owner, collection=[], yspacing=Dimen(12))
    html = _render(table)
    assert 'class="alignment"' in html
    assert "margin-top:" in html
    assert "margin-left:auto;" in html
    assert "margin-right:auto;" in html


def test_html_reflow_alignment_cell_uses_edge_glue_for_flush(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    font = _fake_font(subst_font_name="Times New Roman")

    owner = align.HAlignment()
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

    table = backend.typesetHAlignment(owner, collection=[], yspacing=Dimen())
    html = _render(table)
    assert "justify-content:flex-end;" in html
    assert "justify-content:center;" in html
