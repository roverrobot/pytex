import pytest
from pytex import paragraph
from pytex import lists
from pytex import node as nd
from pytex import texlive
from pytex import vmode
from pytex import mmode


def test_discretionaary(cmr10):
    cmr10.parse("a-b")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 6
    disc = top[4]
    assert isinstance(disc, nd.Disc)


def test_language(cmr10):
    cmr10.parse("a\\language 1 b")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 5
    lang = top[2]
    assert isinstance(lang, paragraph.Language)
    assert lang.language == 1


def test_paragraph_typeset_context_snapshot(parser):
    parser.parse("\\hsize=10pt a\\par")
    vlist = parser.lists[-1]
    p = vlist[0]
    assert isinstance(p, paragraph.Paragraph)
    assert p.typeset_context is not None
    assert p.typeset_context.paragraph is p
    assert p.typeset_context.hsize == 10
    assert p.typeset_context.prevgraf == 0
    parser.parse("\\hsize=20pt")
    assert p.typeset_context.hsize == 10


def test_paragraph_prevgraf_propagation(parser):
    parser.parse("a\\par b\\par")
    vlist = parser.lists[-1]
    p1 = vlist[0]
    p2 = vlist[1]
    assert isinstance(p1, paragraph.Paragraph)
    assert isinstance(p2, paragraph.Paragraph)
    assert p1.typeset_context.next_context is p2.typeset_context
    assert p2.typeset_context.prev_context is p1.typeset_context
    assert p1.typeset_context.prevgraf == 0
    assert p2.typeset_context.prevgraf == 0
    p1.typeset_context.setLineCount(7)
    assert p2.typeset_context.prevgraf == 7


def test_paragraph_chain_break_on_nonparagraph(parser):
    parser.parse("a\\par\\vskip1pt b\\par")
    vlist = parser.lists[-1]
    p1 = vlist[0]
    p2 = vlist[2]
    assert isinstance(p1, paragraph.Paragraph)
    assert isinstance(p2, paragraph.Paragraph)
    assert p1.typeset_context.next_context is None
    assert p2.typeset_context.prev_context is None
    assert p2.typeset_context.prevgraf == 0


def test_linebreak_uses_explicit_paragraph_argument(parser):
    parser.parse("a\\par")
    para = parser.lists[-1][0]
    parser.parse("b")
    out = vmode.VList(parser)
    assert paragraph.lineBreak(parser, para, out)
    assert len(out) == 1
    assert out[0].node_type == nd.NODE_TYPE.HLIST
    assert para.typeset_context.line_count == 1


def test_linebreak_requires_paragraph(parser):
    with pytest.raises(ValueError):
        paragraph.lineBreak(parser, parser.lists[-1], parser.lists[-1])


def test_linebreak_discards_leading_discardables(cmr10):
    cmr10.parse("\\hsize=100pt\\noindent\\hskip1pt a\\par")
    para = next(n for n in cmr10.lists[-1] if isinstance(n, paragraph.Paragraph))
    out = vmode.VList(cmr10)
    assert paragraph.lineBreak(cmr10, para, out)
    line = out[0]
    assert line.node_type == nd.NODE_TYPE.HLIST
    assert len(line.list) >= 2
    assert line.list[0].node_type == nd.NODE_TYPE.GLUE
    assert line.list[1].node_type == nd.NODE_TYPE.CHAR
    assert line.list[1].char == "a"


def test_linebreak_typesets_mlist_before_breaking(cmr10):
    cmr10.parse("\\hsize=100pt\\noindent$a$\\par")
    para = next(n for n in cmr10.lists[-1] if isinstance(n, paragraph.Paragraph))
    out = vmode.VList(cmr10)
    assert paragraph.lineBreak(cmr10, para, out)
    line = out[0]
    assert line.node_type == nd.NODE_TYPE.HLIST
    assert not any(isinstance(n, mmode.MList) for n in line.list)
    math_nodes = [n for n in line.list if isinstance(n, nd.MathShift)]
    assert len(math_nodes) == 2
    assert math_nodes[0].kern == cmr10.state.layout["mathsurround"]
    assert math_nodes[1].kern == cmr10.state.layout["mathsurround"]
