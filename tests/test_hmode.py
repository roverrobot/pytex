import pytest
from pytex import node as nd
from pytex import glue
from pytex import lists
from pytex import texlive
from pytex import hmode


def test_new_paragraph(cmr10):
    s = "Hello, world!"
    cmr10.parse(s)
    assert len(cmr10.lists) == 2
    hlist = cmr10.lists[-1]
    assert hlist.type == lists.LISTTYPE.HORIZONTAL
    assert len(hlist) == len(s)+2
    node = hlist[0]
    assert isinstance(node, hmode.IndentBox)
    node = hlist[1]
    assert node.node_type == nd.NODE_TYPE.CHAR
    assert node.char  == "H"
    node = hlist[7]
    assert node.node_type == nd.NODE_TYPE.GLUE


def test_par(cmr10):
    cmr10.parse("hello\n\n")
    assert len(cmr10.lists) == 1
    vlist = cmr10.lists[-1]
    assert vlist.type == lists.LISTTYPE.VERTICAL
    hlist = vlist[0]
    assert hlist.type == lists.LISTTYPE.HORIZONTAL
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


def test_vskip(cmr10):
    cmr10.parse("hello\\vskip 1in\nworld\n\n")
    assert len(cmr10.lists) == 1
    vlist = cmr10.lists[-1]
    assert vlist.type == lists.LISTTYPE.VERTICAL
    assert len(vlist) == 3
    hlist = vlist[0]
    assert hlist.type == lists.LISTTYPE.HORIZONTAL
    assert len(hlist) == 8
    node = vlist[1]
    assert node.node_type == nd.NODE_TYPE.GLUE
    assert node.glue.dimen == 72.26999
    hlist = vlist[2]
    assert hlist.type == lists.LISTTYPE.HORIZONTAL
