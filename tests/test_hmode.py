import pytest
from pytex import node as nd
from pytex import glue
from pytex import lists
from pytex import texlive
from pytex import hmode
from pytex import paragraph
from pytex.box import LEADERS_TYPE
from pytex import texlive
from pytex import dimen
from pytex.expandable import toksToString

def test_new_paragraph(cmr10):
    s = "Hello, world!"
    cmr10.parse(s)
    assert len(cmr10.lists) == 2
    hlist = cmr10.lists[-1]
    assert hlist.type == lists.LISTTYPE.HORIZONTAL
    # The stored list keeps raw characters; ligatures are formed when typeset.
    assert len(hlist) == len(s) + 2
    node = hlist[0]
    assert isinstance(node, hmode.IndentBox)
    node = hlist[1]
    assert node.node_type == nd.NODE_TYPE.CHAR
    assert node.char  == "H"
    node = hlist[7]
    assert node.node_type == nd.NODE_TYPE.GLUE


def test_everypar_runs_before_first_character(cmr10):
    cmr10.parse("\\everypar={\\setbox0=\\lastbox}123")
    hlist = cmr10.lists[-1]
    assert hlist.type == lists.LISTTYPE.HORIZONTAL
    assert "".join(node.char for node in hlist if node.node_type == nd.NODE_TYPE.CHAR) == "123"
    assert not any(isinstance(node, hmode.IndentBox) for node in hlist)
    assert isinstance(cmr10.state.box[0], hmode.IndentBox)


def test_par(cmr10):
    cmr10.parse("hello\n\n")
    assert len(cmr10.lists) == 1
    vlist = cmr10.lists[-1]
    assert vlist.type == lists.LISTTYPE.VERTICAL
    hlist = vlist[0].list
    assert len(hlist) == 8 # indent, h, e, l, l, o, penalty(10000), glue,
    node = hlist[0]
    assert isinstance(node, hmode.IndentBox)
    node = hlist[1]
    assert node.node_type == nd.NODE_TYPE.CHAR
    assert node.char == "h"
    node = hlist[6]
    assert node.node_type == nd.NODE_TYPE.PENALTY
    assert node.penalty == 10000
    node = hlist[7]
    assert node.node_type == nd.NODE_TYPE.GLUE


def test_noindent_par_creates_no_empty_line(cmr10):
    cmr10.parse("\\noindent\\par")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert not top


def test_vskip(cmr10):
    cmr10.parse("hello\\vskip 1in\nworld\n\n")
    assert len(cmr10.lists) == 1
    vlist = cmr10.lists[-1]
    assert vlist.type == lists.LISTTYPE.VERTICAL
    hlists = [node for node in vlist if isinstance(node, paragraph.Paragraph)]
    assert len(hlists) == 2
    assert len(hlists[0].list) == 8
    vs = [node for node in vlist if node.node_type == nd.NODE_TYPE.GLUE and node.glue.dimen == 72.26999]
    assert len(vs) == 1


def test_controlled_space(cmr10):
    cmr10.parse("\\ ")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL    
    # the indent box and the controlled space
    assert len(top) == 3
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.GLUE
    assert node.glue == cmr10.state.parameters["currentfont"].spaceglue


def test_spacefactor_accessor(cmr10):
    cmr10.parse("\\noindent\\spacefactor=1200\\count0=\\spacefactor\\par")
    assert cmr10.state.count[0] == 1200
    # \spacefactor assignment is not grouped; it belongs to the current hlist.
    cmr10.parse("\\noindent{\\spacefactor=900}\\count0=\\spacefactor\\par")
    assert cmr10.state.count[0] == 900


def test_hrule_wrongmode(cmr10):
    try:
        cmr10.parse("1\\hrule width 345pt\n")
        assert False
    except ValueError as e:
        assert "horizontal" in str(e)

def test_hrule(cmr10):
    cmr10.parse("\\hrule")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert node.node_type == nd.NODE_TYPE.RULE
    assert node.width == dimen.NEG_MAX_DIMEN
    assert node.height == 0.4
    assert node.depth == 0.0
    cmr10.parse("\\hrule width 345pt")
    node = top[-1]
    assert node.width == 345.0
    assert node.height == 0.4
    assert node.depth == 0.0
    cmr10.parse("\\hrule height 1in depth 1in")
    node = top[-1]
    assert node.width == dimen.NEG_MAX_DIMEN
    assert node.height == 72.26999
    assert node.depth == 72.26999
    cmr10.parse("\\hrule width 345pt width 1in")
    node = top[-1]
    assert node.width == 72.26999
    assert node.height == 0.4
    assert node.depth == 0.0

def test_vrule(cmr10):
    cmr10.parse("\\hbox{1\\vrule width 2pt p}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[0]
    assert box.node_type == nd.NODE_TYPE.HLIST
    node = box.list[1]
    assert node.node_type == nd.NODE_TYPE.RULE
    assert node.width == 2.0
    assert node.height == dimen.NEG_MAX_DIMEN
    assert node.depth == dimen.NEG_MAX_DIMEN


def test_penalty(cmr10):
    cmr10.parse("1\\penalty 10000")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 3
    node = top[2]
    assert node.node_type == nd.NODE_TYPE.PENALTY
    assert node.penalty == 10000


def test_discretionary(cmr10):
    cmr10.parse("\\discretionary{a-}{b}{c}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 3
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.DISC
    assert len(node.pre) == 2
    assert node.pre[0].node_type == nd.NODE_TYPE.CHAR
    assert node.pre[0].char == "a"
    assert node.pre[1].node_type == nd.NODE_TYPE.CHAR
    assert node.pre[1].char == "-"
    assert len(node.post) == 1
    assert node.post[0].node_type == nd.NODE_TYPE.CHAR
    assert node.post[0].char == "b"
    assert len(node.replace) == 1
    assert node.replace[0].node_type == nd.NODE_TYPE.CHAR
    assert node.replace[0].char == "c"


def test_discretionary_inside_hbox_typesets(cmr10):
    cmr10.parse("\\setbox0=\\hbox{a\\discretionary{\\hbox{-}}{}{}}")
    box0 = cmr10.state.box[0].typeset(cmr10)
    assert len(box0.list) == 2
    assert box0.list[0].node_type == nd.NODE_TYPE.CHAR
    assert box0.list[0].char == "a"
    assert box0.list[1].node_type == nd.NODE_TYPE.DISC


def test_discretionary_invalid_node(cmr10):
    try:
        cmr10.parse("\\discretionary{a}{b }{c}")
        assert False
    except ValueError as e:
        assert "valid" in str(e)


def test_insert(cmr10):
    cmr10.parse("1\\insert 2{\\vskip 1in}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 4
    node = top[2]
    assert node.node_type == nd.NODE_TYPE.INS
    assert node.index == 2
    assert len(node.vlist) == 1
    assert node.vlist[0].node_type == nd.NODE_TYPE.GLUE
    assert node.vlist[0].glue == glue.Glue(72.26999)


def test_insert_invalid(cmr10):
    try:
        cmr10.parse("\\insert 255{\\vskip 1in}")
        assert False
    except ValueError as e:
        assert "invalid" in str(e)
    try:
        cmr10.parse("\\insert 256{\\vskip 1in}")
        assert False
    except ValueError as e:
        assert "invalid" in str(e)


def string(token_list):
    return "".join([t.char for t in token_list])


def test_special(cmr10):
    cmr10.parse("1\\special{abc}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 4
    node = top[2]
    assert node.node_type == nd.NODE_TYPE.WHATSIT
    assert toksToString(cmr10, node.text) == "abc"


@pytest.mark.parametrize("cmd, type", [
    ["\\leaders", LEADERS_TYPE.LEADERS],
    ["\\cleaders", LEADERS_TYPE.CLEADERS],
    ["\\xleaders", LEADERS_TYPE.XLEADERS],
])
def test_leaders(cmr10, cmd, type):
    cmr10.parse(f"\\noindent1{cmd}\\hbox{{.}}\\hskip1cm2\\relax")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 3
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.GLUE
    assert node.glue == glue.Glue(7227.0 / 254)
    ltype, box = node.leaders
    assert ltype == type
    assert box.node_type == nd.NODE_TYPE.HLIST
    assert len(box.list) == 1
    assert box.list[0].char == "."
    try:
        cmr10.parse("1\\leaders\\hbox{.}")
        assert False
    except ValueError as e:
        assert "glue" in str(e)
    try:
        cmr10.parse("1\\leaders\\hskip 1cm")
        assert False
    except ValueError as e:
        assert "box" in str(e)
    try:
        cmr10.parse("1\\leaders\\vbox{}\\hskip 1cm")
        assert False
    except ValueError as e:
        assert "mode" in str(e)
    try:
        cmr10.parse("1\\leaders\\hbox{}\\vskip 1cm")
        assert False
    except ValueError as e:
        assert "mode" in str(e)


@pytest.mark.parametrize("cmd", [
    "\\kern 1cm\\unkern",
    "\\penalty 10000\\unpenalty",
    "\\hfil\\unskip",
])
def test_unkern(cmr10, cmd):
    cmr10.parse(f"1{cmd}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 2
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.CHAR


def test_last_item_quantities_hmode(cmr10):
    cmr10.parse(
        "\\noindent"
        "\\hskip 3pt plus 2pt minus 1pt"
        "\\skip0=\\lastskip"
        "\\count0=\\lastpenalty"
        "\\dimen0=\\lastkern"
        "\\kern4pt"
        "\\dimen1=\\lastkern"
        "\\count1=\\lastpenalty"
        "\\penalty123"
        "\\count2=\\lastpenalty"
        "\\skip1=\\lastskip"
        "\\count3=\\lastpennalty"
    )
    assert cmr10.state.skip[0] == glue.Glue(3, glue.Stretchness(2), glue.Stretchness(1))
    assert cmr10.state.count[0] == 0
    assert cmr10.state.dimen[0] == 0
    assert cmr10.state.dimen[1] == 4
    assert cmr10.state.count[1] == 0
    assert cmr10.state.count[2] == 123
    assert cmr10.state.skip[1] == glue.Glue()
    assert cmr10.state.count[3] == 123


def test_italic_correction(cmr10):
    cmr10.parse(r"\font\it=cmti10 \it l\/")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    # the indent box, the char, and the kern, and a (trailing) white space
    assert len(top) == 4
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.CHAR
    assert node.char == "l"
    node = top[2]
    assert node.node_type == nd.NODE_TYPE.KERN
    assert node.kern == cmr10.state.parameters["currentfont"]["l"].italic
