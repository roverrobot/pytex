from pytex import html_reflow
# prevent module side effects
html_reflow.mod.init = None
from pytex import font as txfont
from pytex import mmode
from pytex import reflow
from pytex.dimen import Dimen
import pytest
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

    def typesetHBoxRow(self, para, box, inline=False):
        return "row"


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
    assert rendered == ["row"]


def test_html_reflow_hbox_row_uses_flex_layout_for_springs(parser):
    backend = html_reflow.HTMLReflowBackend(parser)
    para = reflow.Paragraph()
    list.append(para, reflow.Spring(2))
    row = backend.typesetHBoxRow(para, SimpleNamespace(width=Dimen(40)), inline=True)
    style = row.get("style")
    assert "display:flex;" in style
    assert "align-items:baseline;" in style
    assert "white-space:nowrap;" in style
    assert "width:" in style
    assert row[0].get("style") == "flex-grow:2;flex-basis:0;"
