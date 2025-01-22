import pytest
from pytex import hbox
from pytex import lists
from pytex import texlive
from pytex.dimen import Dimen


def test_box(cmr10):
    cmr10.parse("\\noindent Hello, world!\\relax")
    top = cmr10.lists[-1]
    f = cmr10.state.parameters["currentfont"]
    assert top.type == lists.LISTTYE.HORIZONTAL
    box = hbox.HBox(top, spread=10)
    assert Dimen(box.width) == Dimen(65.58344)
    assert Dimen(box.height) == 6.94444
    assert Dimen(box.depth) == 1.94444
