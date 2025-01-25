import pytest
from pytex import node as nd
from pytex import glue
from pytex import lists
from pytex import texlive


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
    assert str(node.tokens) == "123"
