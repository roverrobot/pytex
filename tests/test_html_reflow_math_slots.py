from pytex import html_reflow
# prevent module side effects
html_reflow.mod.init = None
from pytex import align
from pytex import box
from pytex import font as txfont
from pytex import glue
from pytex import mmode
from pytex import node as nd
from pytex import reflow
from pytex.dimen import Dimen
import pytest
from lxml import etree
from types import SimpleNamespace


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
    font = txfont.Font(_FakeTextBackend(kind="tfm", name="cmr10"), 10)
    text = html_reflow.reflow.TextRun(font)
    text.setChar("A")
    with pytest.raises(AssertionError, match="OpenType-backed text fonts"):
        backend.typesetTextRun(text)


def test_html_reflow_accepts_substituted_text_backend(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    font = txfont.Font(
        _FakeTextBackend(kind="tfm", name="cmr10", subst_font_name="Times New Roman"),
        10,
    )
    text = html_reflow.reflow.TextRun(font)
    text.setChar("A")
    rendered = backend.typesetTextRun(text)
    style = rendered.get("style")
    assert style.startswith("font-family:Times New Roman;font-size:")
    assert style.endswith("pt;")
    assert rendered.text == "A"


def test_reflow_hbox_passes_glue_state_into_populate_paragraph(parser):
    backend = _CaptureReflow(parser)
    box = SimpleNamespace(shifted=None, list=[], width=Dimen(40))
    rendered = backend.typesetHBox(box)
    assert backend.captured_glue_state == {"order": 1, "shrink": False}
    assert rendered == []


def test_html_reflow_hbox_uses_flex_layout_for_springs(cmr10):
    backend = html_reflow.HTMLReflowBackend(cmr10)
    currentfont = cmr10.parameters["currentfont"]
    currentfont.backend.subst_font_name = "Times New Roman"
    hfil = glue.Glue(0, glue.Stretchness(2, 1))
    row = box.HBox(cmr10, Dimen(40), None)
    row.list = [nd.CharNode("A", currentfont), nd.Glue(hfil, None)]
    row = row.typeset(cmr10)
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


def test_html_reflow_alignment_outer_tabskip_centers_table(cmr10):
    backend = html_reflow.HTMLReflowBackend(cmr10)
    currentfont = cmr10.parameters["currentfont"]
    currentfont.backend.subst_font_name = "Times New Roman"

    owner = align.HAlignment()
    fil = glue.Glue(0, glue.Stretchness(1, 1))
    owner.tabskips = [fil, glue.Glue(), fil]
    row = align.Row()

    left = box.HBox(cmr10, Dimen(20), 0)
    left.list = [nd.CharNode("a", currentfont)]
    left = left.typeset(cmr10)
    left.span = 1

    right = box.HBox(cmr10, Dimen(20), 0)
    right.list = [nd.CharNode("b", currentfont)]
    right = right.typeset(cmr10)
    right.span = 1

    row.cells = [left, right]
    owner.rows = [row]

    table = backend.typesetHAlignment(owner, collection=[], yspacing=Dimen(12))
    html = etree.tostring(table, method="html", encoding="unicode")
    assert 'class="alignment"' in html
    assert "margin-top:" in html
    assert "margin-left:auto;" in html
    assert "margin-right:auto;" in html


def test_html_reflow_alignment_cell_uses_edge_glue_for_flush(cmr10):
    backend = html_reflow.HTMLReflowBackend(cmr10)
    currentfont = cmr10.parameters["currentfont"]
    currentfont.backend.subst_font_name = "Times New Roman"

    owner = align.HAlignment()
    row = align.Row()
    hfil = glue.Glue(0, glue.Stretchness(1, 1))

    right = box.HBox(cmr10, Dimen(30), None)
    right.list = [nd.Glue(hfil, None), nd.CharNode("r", currentfont)]
    right = right.typeset(cmr10)
    right.span = 1

    center = box.HBox(cmr10, Dimen(30), None)
    center.list = [nd.Glue(hfil, None), nd.CharNode("c", currentfont), nd.Glue(hfil, None)]
    center = center.typeset(cmr10)
    center.span = 1

    row.cells = [right, center]
    owner.rows = [row]

    table = backend.typesetHAlignment(owner, collection=[], yspacing=Dimen())
    html = etree.tostring(table, method="html", encoding="unicode")
    assert "justify-content:flex-end;" in html
    assert "justify-content:center;" in html
