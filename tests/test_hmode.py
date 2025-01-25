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


def test_discretionary_invalid_node(cmr10):
    try:
        cmr10.parse("\\discretionary{a}{b }{c}")
        assert False
    except ValueError as e:
        assert "invalid" in str(e)


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


def test_insert_migrate(cmr10):
    cmr10.parse("\hbox{1\\insert 2{\\vskip 1in}}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    assert top[0].node_type == nd.NODE_TYPE.HLIST
    assert len(top[0].content) == 1
    assert len(top[0].migrate) == 1
    node = top[0].migrate[0]
    assert node.node_type == nd.NODE_TYPE.INS
    assert node.index == 2
    assert len(node.vlist) == 1
    assert node.vlist[0].node_type == nd.NODE_TYPE.GLUE
    assert node.vlist[0].glue == glue.Glue(72.26999)


def test_mark(cmr10):
    cmr10.parse("\\def\\a{123}\hbox{\\mark{\\a}}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert node.node_type == nd.NODE_TYPE.HLIST
    assert len(node.content) == 0
    assert len(node.migrate) == 1
    assert str(node.migrate[0].tokens) == "123"


def test_special(cmr10):
    cmr10.parse("1\\special{abc}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 4
    node = top[2]
    assert node.node_type == nd.NODE_TYPE.WHATSIT
    assert str(node.text) == "abc"
