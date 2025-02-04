import pytest
from pytex import align
from pytex import texlive
from pytex import lists
from pytex import glue
from pytex import node as nd


def test_halign(cmr10):
    cmr10.parse("\\halign{1 #& 2 #\\cr a & b\\cr}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, align.Alignment)
    assert node.noalign is None
    assert len(node.rows) == 1
    row = node.rows[0]
    assert len(row.cells) == 2


def test_tabskip(cmr10):
    cmr10.parse("\\tabskip 1pt\\halign{1 #\\tabskip 2pt& 2 #\\cr a & b\\cr}")
    top = cmr10.lists[-1]
    node = top[0]
    row = node.rows[0]
    assert len(row.tabskips) == 3
    assert row.tabskips[0] == glue.Glue(1)
    assert row.tabskips[1] == glue.Glue(2)
    assert row.tabskips[2] == glue.Glue(2)


def test_noalign(cmr10):
    cmr10.parse("\\tabskip 1pt\\halign{1 #& 2 #\\cr\\noalign{\\vskip1pt} a & b\\cr\\noalign{\\vskip2pt}}")
    top = cmr10.lists[-1]
    node = top[0]
    assert node.noalign is not None
    assert len(node.noalign) == 1
    assert node.noalign[0].node_type == nd.NODE_TYPE.GLUE
    assert node.noalign[0].glue == glue.Glue(1)
    assert len(node.rows) == 1
    row = node.rows[0]
    assert row.noalign is not None
    assert len(row.noalign) == 1
    assert row.noalign[0].node_type == nd.NODE_TYPE.GLUE
    assert row.noalign[0].glue == glue.Glue(2)


def test_span(cmr10):
    cmr10.parse("\\tabskip 1pt\\halign{1 #\\tabskip 2pt& 2 #\\cr a \\span b\\cr}")
    top = cmr10.lists[-1]
    node = top[0]
    row = node.rows[0]
    len(row.cells) == 2
    assert row.cells[0].span == True
    assert row.cells[1].span == False
