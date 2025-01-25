import pytest
from pytex import node as nd
from pytex import glue
from pytex import lists
from pytex import texlive
from pytex import hmode
import math


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


def test_controlled_space(cmr10):
    cmr10.parse("\\ ")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL    
    assert len(top) == 3
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.GLUE
    assert node.glue == cmr10.state.parameters["currentfont"].spaceglue


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
    assert node.width is None
    assert node.height == 0.4
    assert node.depth == 0.0
    cmr10.parse("\\hrule width 345pt")
    node = top[-1]
    assert node.width == 345.0
    assert node.height == 0.4
    assert node.depth == 0.0
    cmr10.parse("\\hrule height 1in depth 1in")
    node = top[-1]
    assert node.width is None
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
    assert len(box.content) == 3
    node = box.content[1]
    assert node.node_type == nd.NODE_TYPE.RULE
    assert node.width == 2.0
    assert node.height == box.height
    assert node.depth == box.depth

    