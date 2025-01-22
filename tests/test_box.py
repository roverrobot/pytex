import pytest
from pytex import hbox
from pytex import lists
from pytex import texlive
from pytex.dimen import Dimen


@pytest.fixture()
def box(cmr10):
    cmr10.parse("\\noindent Hello, world!\\relax")
    top = cmr10.lists.pop()
    box = hbox.HBox(top, spread=10)
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
