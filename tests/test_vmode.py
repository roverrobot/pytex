import pytest
import types
from pytex import node as nd
from pytex import glue
from pytex import lists
from pytex import texlive
from pytex import vmode
from pytex import box as bx
from pytex.dimen import Dimen
from pytex.box import LEADERS_TYPE
from pytex.expandable import toksToString


@pytest.mark.parametrize(
    "input,g", [
        ["\\vskip 10pt", glue.Glue(10)],
        ["\\vfil", glue.Glue(0, glue.Stretchness(1,1))],
        ["\\vfill", glue.Glue(0, glue.Stretchness(1,2))],
        ["\\vss", glue.Glue(0, glue.Stretchness(1,1), glue.Stretchness(1,1))],
        ["\\vnegfil", glue.Glue(0, glue.Stretchness(-1,1))],
    ]
)
def test_glue(parser, input, g):
    parser.parse(input)
    assert len(parser.lists) == 1
    vlist = parser.lists[-1]
    assert len(vlist) == 1
    node = vlist[-1]
    assert node.node_type == nd.NODE_TYPE.GLUE
    assert node.glue == g


def test_space(parser):
    # space should have no effect in vertical mode
    parser.parse(" ")
    assert len(parser.lists) == 1
    vlist = parser.lists[-1]
    assert vlist.type == lists.LISTTYPE.VERTICAL
    assert len(vlist) == 0


def test_par(parser):
    # \par should have no effect in vertical mode
    parser.parse("\n\n\n")
    assert len(parser.lists) == 1
    vlist = parser.lists[-1]
    assert vlist.type == lists.LISTTYPE.VERTICAL
    assert len(vlist) == 0


def test_penalty(cmr10):
    cmr10.parse("\\penalty 10000")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert node.node_type == nd.NODE_TYPE.PENALTY
    assert node.penalty == 10000


def test_insert(cmr10):
    cmr10.parse("\\insert 2{\\vskip 1in}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert node.node_type == nd.NODE_TYPE.INS
    assert node.index == 2
    assert len(node.vlist) == 1
    assert node.vlist[0].node_type == nd.NODE_TYPE.GLUE
    assert node.vlist[0].glue == glue.Glue(72.26999)


def test_mark(cmr10):
    cmr10.parse("\\def\\a{123}\\mark{\\a}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert node.node_type == nd.NODE_TYPE.MARK
    assert toksToString(cmr10, node.tokens) == "123"


def test_special(cmr10):
    cmr10.parse("\\special{abc}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert node.node_type == nd.NODE_TYPE.WHATSIT
    assert toksToString(cmr10, node.text) == "abc"


@pytest.mark.parametrize("cmd, type", [
    ["\\leaders", LEADERS_TYPE.LEADERS],
    ["\\cleaders", LEADERS_TYPE.CLEADERS],
    ["\\xleaders", LEADERS_TYPE.XLEADERS],
])
def test_leaders(cmr10, cmd, type):
    cmr10.parse(cmd + "\\vbox{\\hbox{.}}\\vskip1cm")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert node.node_type == nd.NODE_TYPE.GLUE
    assert node.glue == glue.Glue(7227.0 / 254)
    ltype, box = node.leaders
    assert ltype == type
    assert box.node_type == nd.NODE_TYPE.VLIST
    assert len(box.list) == 1
    assert box.list[0].node_type == nd.NODE_TYPE.HLIST
    try:
        cmr10.parse("\\leaders\\vbox{.}")
        assert False
    except ValueError as e:
        assert "glue" in str(e)
    try:
        cmr10.parse("\\leaders\\vskip 1cm")
        assert False
    except ValueError as e:
        assert "box" in str(e)
    try:
        cmr10.parse("\\leaders\\hbox{.}\\vskip 1cm")
        assert False
    except ValueError as e:
        assert "mode" in str(e)
    try:
        cmr10.parse("\\leaders\\vbox{}\\hskip 1cm")
        assert False
    except ValueError as e:
        assert "mode" in str(e)


@pytest.mark.parametrize("cmd", [
    "\\kern 1cm\\unkern",
    "\\penalty 10000\\unpenalty",
    "\\vfil\\unskip",
])
def test_unkern(cmr10, cmd):
    cmr10.parse(f"{cmd}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 0


def _test_hbox(parser, height=6, depth=2):
    hbox = bx.HBox(parser, None, 0)
    hbox.width = Dimen(0)
    hbox.height = Dimen(height)
    hbox.depth = Dimen(depth)
    hbox.list = []
    return hbox


def test_prevdepth_penalty_does_not_reset(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt")
    vlist = vmode.VList(parser)
    vlist.append(_test_hbox(parser))
    vlist.append(nd.Penalty(0))
    vlist.append(_test_hbox(parser))
    packed = vlist.typesetNodes(parser, [])
    glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert len(glues) == 1
    assert glues[0].glue.dimen == 4


def test_prevdepth_kept_across_glue_kern_penalty(parser):
    vlist = vmode.VList(parser)
    vlist.append(_test_hbox(parser, depth=3))
    vlist.append(nd.Glue(glue.Glue(1), None))
    vlist.append(nd.Kern(1))
    vlist.append(nd.Penalty(0))
    assert vlist.resolvePrevDepth() == 3


def test_rule_resets_prevdepth_and_suppresses_interline_glue(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt")
    vlist = vmode.VList(parser)
    vlist.append(_test_hbox(parser))
    vlist.append(nd.Rule(0, 4, 0))
    vlist.append(_test_hbox(parser))
    packed = vlist.typesetNodes(parser, [])
    glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert len(glues) == 0


def test_rule_resets_resolved_prevdepth(parser):
    vlist = vmode.VList(parser)
    vlist.append(_test_hbox(parser, depth=3))
    vlist.append(nd.Rule(0, 4, 0))
    assert vlist.resolvePrevDepth() == vmode.init_prevdepth


def test_box_context_keeps_interlinepenalty(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt\\interlinepenalty=0")
    vlist = vmode.VList(parser)
    first = _test_hbox(parser)
    second = _test_hbox(parser)
    second.typeset_context = vmode.VNodeContext(parser.state.layout, vmode.init_prevdepth)
    second.typeset_context.interlinepenalty = 123
    vlist.append(first)
    vlist.append(second)
    packed = vlist.typesetNodes(parser, [])
    penalties = [n for n in packed if n.node_type == nd.NODE_TYPE.PENALTY]
    assert len(penalties) == 1
    assert penalties[0].penalty == 123


def test_prevdepth_accessor_is_vlist_local(parser):
    parser.parse("\\prevdepth=5pt\\dimen0=\\prevdepth")
    assert parser.state.dimen[0] == 5


def test_prevdepth_accessor_wrong_mode(cmr10):
    try:
        cmr10.parse("a\\prevdepth=1pt")
        assert False
    except ValueError as e:
        assert "vertical mode" in str(e)
