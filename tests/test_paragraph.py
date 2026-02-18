import pytest
import types
from pytex import paragraph
from pytex import lists
from pytex import node as nd
from pytex import texlive
from pytex import vmode
from pytex import mmode
from pytex.dimen import Dimen


def test_language(cmr10):
    cmr10.parse("\\language 1 ab\\setlanguage 1 c")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 6
    assert cmr10.state.parameters["language"] == 1
    assert isinstance(top[3], paragraph.Language)


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


def test_paragraph_typeset_context_captures_words_and_hyphenation(cmr10):
    cmr10.parse("\\hyphenation{Tech-nique}\\lefthyphenmin=2\\righthyphenmin=3\\hsize=10pt\\parindent=0pt")
    # This is preceeded by the indent box, is and a are too short. So the only word to be hyphenated is technique
    cmr10.parse("This is a technique\\par")
    p = cmr10.lists[-1][0]
    assert isinstance(p, paragraph.Paragraph)
    ctx = p.typeset_context
    assert [word.text for word in ctx.words] == ["technique"]
    assert p[ctx.words[0].begin].char == "t" and p[ctx.words[0].end-1].char == "e"


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
    para.typeset(parser, out)
    assert len(out) == 1
    assert out[0].node_type == nd.NODE_TYPE.HLIST
    assert para.typeset_context.line_count == 1


def test_linebreak_discards_leading_discardables(cmr10):
    cmr10.parse("\\hsize=100pt\\noindent\\hskip1pt a\\par")
    para = cmr10.lists[-1][-1]
    out = vmode.VList(cmr10)
    para.typeset(cmr10, out)
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
    para.typeset(cmr10, out)
    line = out[0]
    assert line.node_type == nd.NODE_TYPE.HLIST
    assert not any(isinstance(n, mmode.MList) for n in line.list)
    math_nodes = [n for n in line.list if isinstance(n, nd.MathShift)]
    assert len(math_nodes) == 2
    assert math_nodes[0].kern == cmr10.state.layout["mathsurround"]
    assert math_nodes[1].kern == cmr10.state.layout["mathsurround"]


def test_hyphenate_uses_snapshot_words(cmr10):
    cmr10.parse("\\hyphenation{tech-nical}a technical\\par")
    para = cmr10.lists[-1][-1]
    scan = paragraph._BreakCandidateScan(para.typeset_context, para)
    assert len(scan.candidates)==3 # begin, space, end
    hyphenate_scan = para._hyphenate(cmr10, para, scan.candidates)
    assert len(hyphenate_scan) == 4
    assert hyphenate_scan[2].disc is not None


def test_lineshape_hangindent_after_positive():
    ctx = types.SimpleNamespace(
        parshape=[],
        hsize=Dimen(20),
        hangindent=Dimen(5),
        hangafter=1,
    )
    assert paragraph._lineShape(ctx, 1) == (0, 20)
    assert paragraph._lineShape(ctx, 2) == (5, 15)


def test_lineshape_hangindent_after_negative():
    ctx = types.SimpleNamespace(
        parshape=[],
        hsize=Dimen(20),
        hangindent=Dimen(-4),
        hangafter=-2,
    )
    assert paragraph._lineShape(ctx, 1) == (0, 16)
    assert paragraph._lineShape(ctx, 2) == (0, 16)
    assert paragraph._lineShape(ctx, 3) == (0, 20)


def test_lineshape_parshape_precedes_hangindent():
    ctx = types.SimpleNamespace(
        parshape=[(Dimen(3), Dimen(9))],
        hsize=Dimen(20),
        hangindent=Dimen(5),
        hangafter=-10,
    )
    assert paragraph._lineShape(ctx, 1) == (3, 9)
    assert paragraph._lineShape(ctx, 3) == (3, 9)


def _lineEndingWord(hbox):
    words = []
    current = ""
    for node in hbox.list:
        if node.node_type == nd.NODE_TYPE.CHAR:
            current += node.char
            continue
        if node.node_type == nd.NODE_TYPE.LIGATURE:
            source = getattr(node, "source", None)
            if source:
                current += "".join(char.char for char in source)
            else:
                current += node.char
            continue
        if node.node_type == nd.NODE_TYPE.KERN:
            continue
        if current:
            words.append(current)
            current = ""
    if current:
        words.append(current)
    return words[-1] if words else ""


def test_linebreak_matches_tex_reference_paragraph(cmr10):
    text = (
        "TEX attempts to choose desirable places to divide your document into individual "
        "pages, and its technique for doing this usually works pretty well. But the problem "
        "of page make-up is considerably more difficult than the problem of line breaking "
        "that we considered in the previous chapter, because pages often have much less "
        "flexibility than lines do."
    )
    cmr10.parse("\\hsize=6.5in\\parindent=0pt\\pretolerance=100\\tolerance=200 ")
    cmr10.parse(text + "\\par")
    para = cmr10.lists[-1][-1]
    out = vmode.VList(cmr10)
    para.typeset(cmr10, out)
    assert len(out) == 4
    endings = [_lineEndingWord(line) for line in out]
    assert endings[:3] == ["technique", "than", "less"]


def test_linebreak_plain_hyphenate_ends_line_one_with_hyphen(parser):
    parser.parse("\\input plain")
    parser.parse(
        "\\noindent TEX will henceforth insert discretionary hyphens in the specified positions,"
        " whenever it attempts to hyphenate a word that matches an entry in the exception dictionary,"
        " except that plain TEX blocks hyphens after the very first letter or before the last or"
        " second-last letter of a word.\\par"
    )
    para = next(n for n in reversed(parser.lists[-1]) if isinstance(n, paragraph.Paragraph))
    out = vmode.VList(parser)
    para.typeset(parser, out)
    assert len(out) == 3
    endings = [_lineEndingWord(line) for line in out]
    assert endings[0] == "hyphen-"


def test_linebreaker_select_final_positive_looseness():
    finals = [
        types.SimpleNamespace(line_no=4, demerits=10),
        types.SimpleNamespace(line_no=5, demerits=40),
        types.SimpleNamespace(line_no=6, demerits=30),
        types.SimpleNamespace(line_no=6, demerits=20),
    ]
    baseline, chosen = paragraph._LineBreaker._selectFinal(finals, 2)
    assert baseline.line_no == 4
    assert chosen.line_no == 6
    assert chosen.demerits == 20


def test_linebreaker_select_final_negative_looseness():
    finals = [
        types.SimpleNamespace(line_no=4, demerits=10),
        types.SimpleNamespace(line_no=3, demerits=30),
        types.SimpleNamespace(line_no=2, demerits=100),
    ]
    baseline, chosen = paragraph._LineBreaker._selectFinal(finals, -2)
    assert baseline.line_no == 4
    assert chosen.line_no == 2


def test_paragraph_looseness_resets_after_paragraph(parser):
    parser.parse("\\looseness=2 a\\par b\\par")
    vlist = parser.lists[-1]
    p1 = vlist[0]
    p2 = vlist[1]
    assert isinstance(p1, paragraph.Paragraph)
    assert isinstance(p2, paragraph.Paragraph)
    assert p1.typeset_context.looseness == 2
    assert p2.typeset_context.looseness == 0
