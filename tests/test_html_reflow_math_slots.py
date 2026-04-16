from pytex import html_reflow
# prevent module side effects
html_reflow.mod.init = None
from pytex import mmode


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
