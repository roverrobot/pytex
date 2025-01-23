import pytest
from pytex import hbox
from pytex import lists
from pytex.node import NODE_TYPE
from pytex import texlive
from pytex.dimen import Dimen


@pytest.fixture()
def box(cmr10):
    cmr10.parse("\\noindent Hello, world!\\relax")
    top = cmr10.lists.pop()
    box = hbox.HBox(to=None, spread=10)
    box.pack(top)
    cmr10.state.box[0] = box
    return cmr10


def test_box_dimensions(box):
    top = box.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    box0 = box.state.box[0]
    assert Dimen(box0.width) == Dimen(65.58344)
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
