import pytest
from pytex import paragraph
from pytex import lists
from pytex import node as nd
from pytex import texlive


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
    with pytest.raises(NotImplementedError):
        paragraph.lineBreak(parser, para, parser.lists[0])


def test_linebreak_requires_paragraph(parser):
    with pytest.raises(ValueError):
        paragraph.lineBreak(parser, parser.lists[-1], parser.lists[-1])
