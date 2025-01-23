import pytest
from pytex import box
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
    assert Dimen(box0.width) == Dimen(55.58344)
    assert Dimen(box0.height) == 6.94444
    assert Dimen(box0.depth) == 1.94444    


def test_box_command(box):
    box0 = box.state.box[0]
    box.parse("\\box0")
    top = box.lists[-1]
    assert top[-1] == box0
    assert box.state.box[0].content is None


def test_copy(box):
    box0 = box.state.box[0]
    box.parse("\\setbox1=\\copy0")
    box1 = box.state.box[1]
    assert box1.content == box0.content
    assert box1.glues == box0.glues
    assert box1.migrate == box0.migrate
    assert box1.width == box0.width
    assert box1.height == box0.height
    assert box1.depth == box0.depth
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
    assert box.width == 55.58344
    assert box.height == 6.94444
    assert box.depth == 1.94444
    assert len(box.content) == 14

def test_hbox_to(cmr10):
    cmr10.parse("\\hbox to 100pt{Hello, world!}\\relax")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.HLIST
    assert box.width == 100
    assert box.height == 6.94444
    assert box.depth == 1.94444


def test_hbox_spread(cmr10):
    cmr10.parse("\\hbox spread 10pt{Hello, world!}\\relax")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.HLIST
    assert box.width == 65.58344
    assert box.height == 6.94444
    assert box.depth == 1.94444


def test_vbox(box):
    box.parse("\\vbox{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.VLIST
    assert box.width == 55.58344
    assert box.height == 6.94444 + 6.94444 + 1.94444 + 10.00002
    assert box.depth == 1.94444
    assert len(box.content) == 3


def test_vbox_to(box):
    box.parse("\\vbox to 100pt{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.VLIST
    assert box.width == 55.58344
    assert box.height == 100
    assert box.depth == 1.94444
    assert len(box.content) == 3


def test_vbox_spread(box):
    box.parse("\\vbox spread 10pt{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.VLIST
    assert box.width == 55.58344
    assert box.height == 6.94444 + 6.94444 + 1.94444 + 10.00002 + 10
    assert box.depth == 1.94444
    assert len(box.content) == 3


def test_vtop(box):
    box.parse("\\vtop{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.VLIST
    assert box.width == 55.58344
    assert box.height == 6.94444 
    assert box.depth == 1.94444 + 10.00002 + 6.94444 + 1.94444
    assert len(box.content) == 3


def test_vtop_to(box):
    box.parse("\\vtop to 100pt{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.VLIST
    assert box.width == 55.58344
    assert box.height == 100
    assert box.depth == 1.94444 + 10.00002 + 6.94444 + 1.94444
    assert len(box.content) == 3

def test_vtop_spread(box):
    box.parse("\\vtop spread 10pt{\\copy0\\vskip1em plus 1em\\box0}\\relax")
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box = top[-1]
    assert box.node_type == NODE_TYPE.VLIST
    assert box.width == 55.58344
    assert box.height == 6.94444 + 10
    assert box.depth == 1.94444 + 10.00002 + 6.94444 + 1.94444
    assert len(box.content) == 3


@pytest.mark.parametrize("cmd, attr", [
    ["\\ht", "height"],
    ["\\dp", "depth"],
    ["\\wd", "width"]
])
def test_wd(box, cmd, attr):
    box.parse(f"\\dimen0={cmd}0")
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
    assert box.state.box[0].content is None


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
    assert box.state.box[0].content is not None


def test_unvbox(box):
    box.parse("\\setbox1=\\vbox{\\box0}\\unvbox1")
    top = box.lists[-1]
    assert len(top) == 1
    assert top[0].node_type == NODE_TYPE.HLIST
    assert box.state.box[1].content is None
