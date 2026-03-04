import pytest
from pytex import box as bx
from pytex import glue
from pytex import node as nd
from pytex import lists
from pytex.node import NODE_TYPE
from pytex import texlive
from pytex.dimen import Dimen


@pytest.fixture()
def box(cmr10):
    cmr10.parse("\\setbox0=\\hbox{Hello, world!}\\relax")
    return cmr10


def test_box_dimensions(box):
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box0 = box.state.box[0]
    box0 = box0.typeset(box)
    assert Dimen(box0.width) == Dimen(55.58344)
    assert Dimen(box0.height) == 6.94444
    assert Dimen(box0.depth) == 1.94444    


def test_box_command(box):
    box0 = box.state.box[0]
    box.parse("\\box0")
    top = box.lists[-1]
    assert top[-1] == box0
    assert box.state.box[0] is None


def test_copy(box):
    box0 = box.state.box[0]
    box.parse("\\setbox1=\\copy0")
    box1 = box.state.box[1]
    assert box1.list == box0.list
    assert box1 is not box0


def test_ifvoid(box):
    box0 = box.state.box[0]
    box.parse("\\ifvoid0 a\\else b\\fi")
    top = box.lists[-1]
    assert top[-1].char == "b"
    box.parse("\\setbox1=\\box0")
    box.parse("\\ifvoid1 c\\else d\\fi")
    assert top[-1].char == "d"
    box.parse("\\ifvoid0 a\\else b\\fi")
    assert top[-1].char == "a"


def test_hbox(cmr10):
    cmr10.parse("\\hbox{Hello, world!}\\relax")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.HLIST
    typed = box.typeset(cmr10)
    assert typed.width == 55.58344
    assert typed.height == 6.94444
    assert typed.depth == 1.94444
    assert len(typed.list) == 14


def test_hbox_accepts_bgroup_alias(cmr10):
    cmr10.parse("\\let\\bgroup={\\let\\egroup=}\\setbox0=\\hbox\\bgroup A\\egroup")
    box0 = cmr10.state.box[0].typeset(cmr10)
    assert box0.width > 0
    assert len(box0.list) == 1

def test_hbox_to(cmr10):
    cmr10.parse("\\hbox to 100pt{Hello, world!}\\relax")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.HLIST
    assert isinstance(box.to, Dimen)
    typed = box.typeset(cmr10)
    assert typed.width == 100
    assert typed.height == 6.94444
    assert typed.depth == 1.94444


def test_hbox_spread(cmr10):
    cmr10.parse("\\hbox spread 10pt{Hello, world!}\\relax")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.HLIST
    assert isinstance(box.spread, Dimen)
    typed = box.typeset(cmr10)
    assert typed.width == 65.58344
    assert typed.height == 6.94444
    assert typed.depth == 1.94444


def test_hbox_sets_badness_before_next_token(cmr10):
    cmr10.parse("\\setbox0=\\hbox to 100pt{a}\\count0=\\badness")
    assert cmr10.state.count[0] == 10000


def test_setbox_defers_packing_until_badness_is_read(cmr10):
    cmr10.parse("\\setbox0=\\hbox to 100pt{a}")
    box0 = cmr10.state.box[0]
    assert box0._typeset_cache is None
    assert cmr10.lastbox is box0
    cmr10.parse("\\count0=\\badness")
    assert box0._typeset_cache is not None
    assert cmr10.state.count[0] == 10000


def test_hbox_overfull_sets_badness_to_one_million(cmr10):
    cmr10.parse("\\setbox0=\\hbox to 0pt{a}\\count0=\\badness")
    assert cmr10.state.count[0] == 1000000


def test_badness_is_not_grouped(parser):
    parser.parse("{\\badness=123}\\count0=\\badness")
    assert parser.state.count[0] == 123


def test_explicit_badness_assignment_clears_pending_box(cmr10):
    cmr10.parse("\\setbox0=\\hbox to 100pt{a}\\badness=7\\count0=\\badness")
    assert cmr10.state.count[0] == 7
    assert cmr10.state.box[0]._typeset_cache is None


def test_vbox(box):
    box.parse("\\vbox{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    b = top[-1]
    assert b.node_type == NODE_TYPE.VLIST
    typed = b.typeset(box)
    assert typed.width == 55.58344
    assert typed.height == 6.94444 + 6.94444 + 1.94444 + 10.00002
    assert typed.depth == 1.94444
    assert len(typed.list) == 4


def test_vbox_sets_badness_before_next_token(parser):
    parser.parse("\\vbox to 10pt{}\\count0=\\badness")
    assert parser.state.count[0] == 10000


def test_vbox_to(box):
    box.parse("\\vbox to 100pt{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    b = top[-1]
    assert b.node_type == NODE_TYPE.VLIST
    typed = b.typeset(box)
    assert typed.width == 55.58344
    assert typed.height == 100
    assert typed.depth == 1.94444
    assert len(typed.list) == 4


def test_vbox_spread(box):
    box.parse("\\vbox spread 10pt{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    b = top[-1]
    assert b.node_type == NODE_TYPE.VLIST
    typed = b.typeset(box)
    assert typed.width == 55.58344
    assert typed.height == 6.94444 + 6.94444 + 1.94444 + 10.00002 + 10
    assert typed.depth == 1.94444
    assert len(typed.list) == 4


class _LeafHBox(nd.Box):
    node_type = NODE_TYPE.HLIST
    typeset = None

    def __init__(self, height=6, depth=2, width=0):
        super().__init__(width, height, depth)
        self.shifted = 0
        self.list = None


def _synthetic_hbox(parser, height=6, depth=2, width=0):
    return _LeafHBox(height, depth, width)


def test_vbox_trailing_glue_zeroes_depth(parser):
    vbox = bx.VBox(parser, None, 0)
    vbox.list.append(_synthetic_hbox(parser, height=6, depth=3))
    vbox.list.append(nd.Penalty(0))
    vbox.list.append(nd.Glue(glue.Glue(4), None))
    typed = vbox.typeset(parser)
    assert typed.height == 10
    assert typed.depth == 0


def test_vbox_trailing_penalty_keeps_depth(parser):
    vbox = bx.VBox(parser, None, 0)
    vbox.list.append(_synthetic_hbox(parser, height=6, depth=3))
    vbox.list.append(nd.Penalty(0))
    typed = vbox.typeset(parser)
    assert typed.height == 6
    assert typed.depth == 3


def test_vbox_uses_captured_boxmaxdepth(parser):
    parser.state.layout["boxmaxdepth"] = Dimen(1)
    vbox = bx.VBox(parser, None, 0)
    vbox.list.append(_synthetic_hbox(parser, height=6, depth=3))
    parser.state.layout["boxmaxdepth"] = Dimen()
    typed = vbox.typeset(parser)
    assert typed.height == 8
    assert typed.depth == 1


def test_vsplit_void(parser):
    parser.parse("\\setbox0=\\vsplit1 to 10pt")
    assert parser.state.box[0] is None
    assert parser.state.box[1] is None


def test_vsplit_splits_box_and_reinserts_splittopskip(parser):
    parser.state.layout["splittopskip"] = glue.Glue(10)
    source = bx.VBox(parser, None, 0)
    source.list.append(_synthetic_hbox(parser, height=6, depth=2, width=10))
    source.list.append(_synthetic_hbox(parser, height=6, depth=2, width=10))
    parser.state.box[1] = source
    parser.parse("\\setbox2=\\vsplit1 to 10pt")
    split = parser.state.box[2].typeset(parser)
    remainder = parser.state.box[1].typeset(parser)
    assert split.height == 10
    assert split.list[0].node_type == NODE_TYPE.HLIST
    assert remainder.list[0].node_type == NODE_TYPE.GLUE
    assert remainder.list[0].glue.dimen == 4
    assert remainder.list[1].node_type == NODE_TYPE.HLIST


def test_vsplit_takes_whole_box_when_target_is_large(parser):
    source = bx.VBox(parser, None, 0)
    source.list.append(_synthetic_hbox(parser, height=6, depth=2, width=10))
    source.list.append(_synthetic_hbox(parser, height=6, depth=2, width=10))
    parser.state.box[1] = source
    parser.parse("\\setbox2=\\vsplit1 to 50pt")
    assert parser.state.box[1] is None
    split = parser.state.box[2].typeset(parser)
    assert split.height == 50


def test_moveright_dispatches_to_vertical_handler(parser):
    parser.parse("\\moveright1pt\\vbox{}")
    top = parser.lists[-1]
    shifted = top[-1]
    assert shifted.node_type == NODE_TYPE.VLIST
    assert shifted.shifted == -1


def test_vtop(box):
    box.parse("\\vtop{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    b = top[-1]
    assert b.node_type == NODE_TYPE.VLIST
    typed = b.typeset(box)
    assert typed.width == 55.58344
    assert typed.height == 6.94444 
    assert typed.depth == 1.94444 + 10.00002 + 6.94444 + 1.94444
    assert len(typed.list) == 4


def test_vtop_to(box):
    box.parse("\\vtop to 100pt{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    b = top[-1]
    assert b.node_type == NODE_TYPE.VLIST
    typed = b.typeset(box)
    assert typed.width == 55.58344
    assert typed.height == 6.94444
    assert typed.depth == 100 - 6.94444 + 1.94444
    assert len(typed.list) == 4

def test_vtop_spread(box):
    box.parse("\\vtop spread 10pt{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    b = top[-1]
    assert b.node_type == NODE_TYPE.VLIST
    typed = b.typeset(box)
    assert typed.width == 55.58344
    assert typed.height == 6.94444
    assert typed.depth == 1.94444 + 10.00002 + 6.94444 + 1.94444 + 10
    assert len(typed.list) == 4


@pytest.mark.parametrize("cmd, attr", [
    ["\\ht", "height"],
    ["\\dp", "depth"],
    ["\\wd", "width"]
])
def test_wd(box, cmd, attr):
    box.parse(f"\\setbox0=\\hbox{{A}}\\dimen0={cmd}0")
    assert box.state.dimen[0] == getattr(box.state.box[0], attr)
    box.parse(f"{cmd}0=100pt")
    assert getattr(box.state.box[0], attr) == 100


def test_box_void(box):
    box.parse("\\box1")
    top = box.lists[-1]
    assert len(top) == 0


def test_unhbox(box):
    box.parse("1\\unhbox0")
    top = box.lists[-1]
    assert len(top) == 15
    assert box.state.box[0] is None


def test_unhbox_wrongmode(box):
    try:
        box.parse("\\unhbox0")
        assert False
    except ValueError as e:
        assert "wrong mode" in str(e)


def test_unvbox_wrongbox(box):
    try:
        box.parse("\\unvbox0")
        assert False
    except ValueError as e:
        assert "vbox" in str(e)


def test_unhcopy(box):
    box.parse("1\\unhcopy0")
    top = box.lists[-1]
    assert len(top) == 15
    box0 = box.state.box[0]
    assert len(box0.list) == 13


def test_unvbox(box):
    box.parse("\\setbox1=\\vbox{\\box0}\\unvbox1")
    top = box.lists[-1]
    assert len(top) == 1
    assert top[0].node_type == NODE_TYPE.HLIST
    assert box.state.box[1] is None


def test_accent_nochar(cmr10):
    cmr10.parse("\\accent65 \\uppercase{1}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 4
    accent = top[1]
    assert accent.node_type == NODE_TYPE.ACCENT
    assert accent.base is None
    assert accent.accent.char == "A"
    assert top[2].char == "1"


def test_accent(cmr10):
    cmr10.parse("\\noindent\\accent65 1\\relax")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 1
    assert top[0].node_type == NODE_TYPE.ACCENT
    hbox = bx.HBox(cmr10, None, Dimen())
    hbox.list = top
    packed = hbox.typeset(cmr10).list
    kern = packed[0]
    assert kern.node_type == NODE_TYPE.KERN
    assert kern.kern == -1.25000
    accent = packed[1]
    assert accent.node_type == NODE_TYPE.HLIST
    assert len(accent.list) == 1
    assert accent.list[0].char == "A"
    kern = packed[2]
    assert kern.node_type == NODE_TYPE.KERN
    assert kern.kern == -6.25002
    char = packed[3]
    assert char.node_type == NODE_TYPE.CHAR
    assert char.char == "1"


def test_accent_italic_alignment_uses_slant(cmr10):
    # Reference from pdfTeX:
    # \hbox(9.58334+1.94444)x3.06665
    # .\kern -0.36249 (for accent)
    # .\hbox(6.94444+0.0)x5.11108, shifted -2.6389
    # ..\tenit ^^S
    # .\kern -4.7486 (for accent)
    # .\tenit f
    cmr10.parse("\\font\\tenit=cmti10 \\tenit\\noindent\\accent19 f\\relax")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 1
    assert top[0].node_type == NODE_TYPE.ACCENT
    hbox = bx.HBox(cmr10, None, Dimen())
    hbox.list = top
    packed = hbox.typeset(cmr10).list
    assert packed[0].node_type == NODE_TYPE.KERN
    assert float(packed[0].kern) == pytest.approx(-0.36249, abs=1e-4)
    assert packed[1].node_type == NODE_TYPE.HLIST
    assert float(packed[1].shifted) == pytest.approx(-2.63890, abs=1e-4)
    assert packed[2].node_type == NODE_TYPE.KERN
    assert float(packed[2].kern) == pytest.approx(-4.74860, abs=1e-4)
    assert packed[3].node_type == NODE_TYPE.CHAR
    assert packed[3].char == "f"


def test_lastbox(cmr10):
    cmr10.parse("1\\hbox{Hello, world!}\\setbox0=\\lastbox")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 2
    box = cmr10.state.box[0]
    assert len(box.list) == 13


def test_lastbox_empty(cmr10):
    cmr10.parse("1\\setbox0=\\lastbox")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 2
    box = cmr10.state.box[0]
    assert box is None


def test_lastbox_vmode(cmr10):
    cmr10.parse("\\vbox{\\setbox0=\\lastbox}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    vbox = top[0]
    assert len(vbox.list) == 0
    box = cmr10.state.box[0]
    assert box is None
    try:
        cmr10.parse("\\hbox{Hello, world!}\\setbox0=\\lastbox")
        assert False
    except ValueError as e:
        assert "\\lastbox" in str(e)


def test_lastbox_main_vmode_after_unvbox(cmr10):
    cmr10.parse("\\setbox1=\\vbox{\\hbox{A}\\hbox{B}}\\unvbox1\\setbox0=\\lastbox\\setbox2=\\lastbox")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 0
    box0 = cmr10.state.box[0]
    box2 = cmr10.state.box[2]
    assert box0 is not None and box0.node_type == NODE_TYPE.HLIST
    assert box2 is not None and box2.node_type == NODE_TYPE.HLIST


def test_afterassignment(cmr10):
    cmr10.parse("\\afterassignment a\\setbox1=\\hbox{}")
    box1 = cmr10.state.box[1]
    assert len(box1.list) == 1
    assert box1.list[0].char == "a"
    assert cmr10.state.globals["afterassignment"] is None
