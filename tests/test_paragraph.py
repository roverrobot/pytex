import pytest
import types
from pytex import paragraph
from pytex import lists
from pytex import node as nd
from pytex import texlive
from pytex import vmode
from pytex import mmode
from pytex import page
from pytex import glue
from pytex.dimen import Dimen
from pytex import typeset
from pytex.typeset.paragraph import _LineBreaker

def _raw_nodes(vlist):
    return vlist.rawNodes() if hasattr(vlist, "rawNodes") else getattr(vlist, "raw", vlist)


def _concrete_nodes(vlist):
    return vlist.concreteNodes() if hasattr(vlist, "concreteNodes") else list(vlist)


def _source_nodes(vlist, cls):
    seen = set()
    out = []
    for node in _concrete_nodes(vlist):
        source = getattr(node, "source", None)
        if not isinstance(source, cls):
            continue
        key = id(source)
        if key in seen:
            continue
        seen.add(key)
        out.append(source)
    return out


def simple_context(parshape, hsize, hangindent, hangafter):
    ctx = types.SimpleNamespace(
        volatile={
            "parshape": parshape, 
            "hangindent": hangindent, 
            "hangafter": hangafter
        },
        layout = {"hsize": hsize},
    )
    ctx.lineShape = lambda line_no: paragraph.Paragraph.lineShape(None, ctx, line_no
    )
    return ctx


def test_language(cmr10):
    cmr10.parse("\\language 1 ab\\setlanguage 1 c")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 6
    assert cmr10.parameters["language"] == 1
    assert isinstance(top[3], paragraph.Language)


def test_paragraph_uses_state_when_it_ends(cmr10):
    cmr10.parse("\\hsize=20pt\\parindent=0pt a a a a a\\par")
    vlist = cmr10.lists[-1]
    p = _source_nodes(vlist, paragraph.Paragraph)[0]
    assert isinstance(p, paragraph.Paragraph)
    lines = [
        node for node in _concrete_nodes(vlist)
        if node.node_type == nd.NODE_TYPE.HLIST and getattr(node, "source", None) is p
    ]
    assert len(lines) > 1
    assert all(line.width == 20 for line in lines)
    cmr10.parse("\\hsize=100pt")
    assert all(line.width == 20 for line in lines)


def test_paragraph_is_pretypeset_when_it_ends(cmr10):
    cmr10.parse("\\hsize=100pt a\\par")
    vlist = cmr10.lists[-1]
    p = _source_nodes(vlist, paragraph.Paragraph)[0]
    lines = [
        node for node in _concrete_nodes(vlist)
        if node.node_type == nd.NODE_TYPE.HLIST and getattr(node, "source", None) is p
    ]
    assert len(lines) == 1
    assert lines[0].node_type == nd.NODE_TYPE.HLIST


def test_paragraph_typeset_uses_stored_parfillskip_not_live_state(parser):
    parser.parse("\\parfillskip=0pt a\\par")
    para = _source_nodes(parser.lists[-1], paragraph.Paragraph)[0]
    parser.parameters["parfillskip"] = glue.Glue(0, glue.Stretchness(1, 1))
    out = []
    parser.typeset.paragraph.typeset(para, out)
    assert len(out) == 1
    assert out[0].node_type == nd.NODE_TYPE.HLIST


def test_paragraph_chain_break_on_nonparagraph(parser):
    parser.parse("a\\par\\vskip1pt b\\par")
    vlist = parser.lists[-1]
    ps = _source_nodes(vlist, paragraph.Paragraph)
    p1 = ps[0]
    p2 = ps[1]
    assert isinstance(p1, paragraph.Paragraph)
    assert isinstance(p2, paragraph.Paragraph)
    assert p2.prevgraf == 0


def test_linebreak_uses_explicit_paragraph_argument(parser):
    parser.parse("a\\par")
    para = _source_nodes(parser.lists[-1], paragraph.Paragraph)[0]
    parser.parse("b")
    out = []
    parser.typeset.paragraph.typeset(para, out)
    assert len(out) == 1
    assert out[0].node_type == nd.NODE_TYPE.HLIST


def test_implicit_paragraph_adds_parskip(parser):
    parser.parse("\\parskip=5pt a\\par b\\par")
    top = parser.lists[-1]
    raw = _source_nodes(top, paragraph.Paragraph)
    packed = _concrete_nodes(top)
    assert len(raw) == 2
    assert len(packed) == 4
    assert packed[0].node_type == nd.NODE_TYPE.HLIST
    assert packed[1].node_type == nd.NODE_TYPE.GLUE
    assert packed[1].name == "\\parskip"
    assert packed[1].glue.dimen == 5
    assert packed[2].node_type == nd.NODE_TYPE.GLUE
    assert packed[3].node_type == nd.NODE_TYPE.HLIST


def test_paragraph_boundary_keeps_prevdepth_across_parskip(cmr10):
    cmr10.parse("\\parskip=5pt\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt a\\par b\\par")
    main = cmr10.lists[-1]
    packed = _concrete_nodes(main)
    names = [getattr(n, "name", None) for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert names == ["\\parskip", "\\baselineskip"]
    assert packed[1].glue.dimen == Dimen(5.0)
    assert packed[2].glue.dimen == (
        cmr10.layout["baselineskip"].dimen
        - packed[0].depth
        - packed[3].height
    )


def test_group_in_vmode_does_not_reset_prevdepth(cmr10):
    cmr10.parse("\\parskip=0pt\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt a\\par\\begingroup\\endgroup b\\par")
    main = cmr10.lists[-1]
    packed = _concrete_nodes(main)
    names = [getattr(n, "name", None) for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert names == ["\\parskip", "\\baselineskip"]
    assert packed[2].glue.dimen == (
        cmr10.layout["baselineskip"].dimen
        - packed[0].depth
        - packed[3].height
    )


def test_noindent_after_parskip_change_preserves_outer_parskip(cmr10):
    cmr10.parse("\\hbox{}\\parskip=0pt plus 1pt A\\par\\parskip=0pt\\noindent\\par")
    main = cmr10.lists[-1]
    glues = [n for n in _concrete_nodes(main) if n.node_type == nd.NODE_TYPE.GLUE and n.name == "\\parskip"]
    assert len(glues) >= 2
    assert glues[-2].glue == glue.Glue(0, glue.Stretchness(1, 0), glue.Stretchness(0, 0))
    assert glues[-1].glue == glue.Glue()


def test_linebreak_discards_leading_discardables(cmr10):
    cmr10.parse("\\hsize=100pt\\noindent\\hskip1pt a\\par")
    para = _source_nodes(cmr10.lists[-1], paragraph.Paragraph)[-1]
    out = []
    cmr10.typeset.paragraph.typeset(para, out)
    line = out[0]
    assert line.node_type == nd.NODE_TYPE.HLIST
    assert len(line.list) >= 1
    assert line.list[0].node_type == nd.NODE_TYPE.CHAR
    assert line.list[0].char == "a"


def test_linebreak_typesets_mlist_before_breaking(cmr10):
    cmr10.parse("\\hsize=100pt\\noindent$a$\\par")
    para = _source_nodes(cmr10.lists[-1], paragraph.Paragraph)[0]
    out = []
    cmr10.typeset.paragraph.typeset(para, out)
    line = out[0]
    assert line.node_type == nd.NODE_TYPE.HLIST
    assert not any(isinstance(n, mmode.MList) for n in line.list)
    math_nodes = [n for n in line.list if isinstance(n, nd.MathShift)]
    assert len(math_nodes) == 2
    assert math_nodes[0].kern == cmr10.layout["mathsurround"]
    assert math_nodes[1].kern == cmr10.layout["mathsurround"]


def test_hyphenate_uses_snapshot_words(cmr10):
    cmr10.parse("\\hyphenation{tech-nical}a technical\\par")
    para = _source_nodes(cmr10.lists[-1], paragraph.Paragraph)[-1]
    scan = para._scanBreaks(cmr10, para.list)
    assert len(scan) == 3 # begin, space, end
    _, hyphenate_scan = para._hyphenate(cmr10)
    assert len(hyphenate_scan) == 4
    assert hyphenate_scan[2].disc is not None


def test_lineshape_hangindent_after_positive():
    ctx = simple_context(
        parshape=[],
        hsize=Dimen(20),
        hangindent=Dimen(5),
        hangafter=1,
    )
    assert ctx.lineShape(1) == (0, 20)
    assert ctx.lineShape(2) == (5, 15)


def test_lineshape_hangindent_after_negative():
    ctx = simple_context(
        parshape=[],
        hsize=Dimen(20),
        hangindent=Dimen(-4),
        hangafter=-2,
    )
    assert ctx.lineShape(1) == (0, 16)
    assert ctx.lineShape(2) == (0, 16)
    assert ctx.lineShape(3) == (0, 20)


def test_lineshape_parshape_precedes_hangindent():
    ctx = simple_context(
        parshape=[(Dimen(3), Dimen(9))],
        hsize=Dimen(20),
        hangindent=Dimen(5),
        hangafter=-10,
    )
    assert ctx.lineShape(1) == (3, 9)
    assert ctx.lineShape(3) == (3, 9)


def _lineEndingWord(hbox):
    def append_nodes(text, nodes):
        for sub in nodes:
            if sub.node_type == nd.NODE_TYPE.CHAR:
                text += sub.char
            elif sub.node_type == nd.NODE_TYPE.LIGATURE:
                source = getattr(sub, "source", None)
                if source:
                    text += "".join(char.char for char in source)
                else:
                    text += sub.char
        return text

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
        if node.node_type == nd.NODE_TYPE.DISC:
            current = append_nodes(current, getattr(node, "list", node.replace))
            continue
        if node.node_type == nd.NODE_TYPE.KERN:
            continue
        if current:
            words.append(current)
            current = ""
    if current:
        words.append(current)
    return words[-1] if words else ""


def _lineBoxes(vlist):
    return [node for node in vlist if node.node_type == nd.NODE_TYPE.HLIST]


def _lineText(hbox):
    chars = []
    for node in hbox.list:
        if node.node_type == nd.NODE_TYPE.CHAR:
            chars.append(node.char)
            continue
        if node.node_type == nd.NODE_TYPE.LIGATURE:
            source = getattr(node, "source", None)
            if source:
                chars.extend(c.char for c in source)
            else:
                chars.append(node.char)
    return "".join(chars)


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
    para = _source_nodes(cmr10.lists[-1], paragraph.Paragraph)[-1]
    out = []
    cmr10.typeset.paragraph.typeset(para, out)
    lines = _lineBoxes(out)
    assert len(lines) == 4
    endings = [_lineEndingWord(line) for line in lines]
    assert endings[:3] == ["technique", "than", "less"]


def _reset_outer_vlist(parser):
    if parser.lists is not None:
        parser.lists.clear()
    parser.page_builder.reset()
    parser.lists = lists.ListStack([vmode.VList(parser, [], inner=False)])


def test_linebreak_plain_paragraph_cases(parser):
    parser.parse("\\input plain")

    text = (
        "TEX attempts to choose desirable places to divide your document into individual "
        "pages, and its technique for doing this usually works pretty well. But the problem "
        "of page make-up is considerably more difficult than the problem of line breaking "
        "that we considered in the previous chapter, because pages often have much less "
        "flexibility than lines do."
    )
    parser.parse("\\looseness=-1 ")
    parser.parse(text + "\\par")
    top = parser.lists[-1]
    para = _source_nodes(top, paragraph.Paragraph)[-1]
    lines = [
        node for node in _concrete_nodes(top)
        if node.node_type == nd.NODE_TYPE.HLIST and getattr(node, "source", None) is para
    ]
    assert len(lines) == 4
    endings = [_lineEndingWord(line) for line in lines]
    assert endings[:3] == ["tech-", "difficult", "much"]

    _reset_outer_vlist(parser)
    parser.parse(
        "\\noindent TEX will henceforth insert discretionary hyphens in the specified positions,"
        " whenever it attempts to hyphenate a word that matches an entry in the exception dictionary,"
        " except that plain TEX blocks hyphens after the very first letter or before the last or"
        " second-last letter of a word.\\par"
    )
    para = _source_nodes(parser.lists[-1], paragraph.Paragraph)[-1]
    out = []
    parser.typeset.paragraph.typeset(para, out)
    lines = _lineBoxes(out)
    assert len(lines) == 3
    endings = [_lineEndingWord(line) for line in lines]
    assert endings[0] == "hyphen-"

    _reset_outer_vlist(parser)
    parser.parse(
        "this is a test to double check the line breaking in a math list at the inline math "
        " $from\\;this\\;f(x)=y\\;we\\;test$ this line break thing.\\par"
    )
    para = _source_nodes(parser.lists[-1], paragraph.Paragraph)[-1]
    out = []
    parser.typeset.paragraph.typeset(para, out)
    lines = _lineBoxes(out)
    assert len(lines) == 2
    assert _lineText(lines[0]).endswith("=")
    penalties = [node.penalty for node in lines[0].list if node.node_type == nd.NODE_TYPE.PENALTY]
    assert penalties == [500]


def test_paragraph_typeset_inserts_interline_glue(cmr10):
    cmr10.parse("\\hsize=20pt\\parindent=0pt\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt ")
    cmr10.parse("a a a a a\\par")
    para = _source_nodes(cmr10.lists[-1], paragraph.Paragraph)[-1]
    out = []
    cmr10.typeset.paragraph.typeset(para, out)
    vlist = vmode.VList(cmr10, [])
    vlist.open()
    try:
        for node in out:
            vlist.append(node)
        packed = list(vlist.list)
    finally:
        vlist.close()
    lines = _lineBoxes(packed)
    assert len(lines) > 1
    interline = [node for node in packed if node.node_type == nd.NODE_TYPE.GLUE]
    assert len(interline) >= len(lines) - 1
    assert interline[0].glue.dimen > 0


def test_interline_penalty_uses_brokenpenalty_from_previous_line(parser):
    parser.layout["interlinepenalty"] = 7
    parser.layout["clubpenalty"] = 1000
    parser.layout["widowpenalty"] = 2000
    parser.layout["brokenpenalty"] = 3000
    para = paragraph.Paragraph(parser, False)
    para.line_count = 5
    first = types.SimpleNamespace(line_no=1, hyphenated=True, prev=None)
    second = types.SimpleNamespace(line_no=2, hyphenated=False, prev=first)
    assert parser.typeset.paragraph.interlinePenalty(para, second) == 4007


def test_interline_penalty_applies_widowpenalty_before_last_line(parser):
    parser.layout["interlinepenalty"] = 7
    parser.layout["clubpenalty"] = 1000
    parser.layout["widowpenalty"] = 2000
    parser.layout["brokenpenalty"] = 3000
    para = paragraph.Paragraph(parser, False)
    para.line_count = 5
    prev = types.SimpleNamespace(line_no=4, hyphenated=False, prev=None)
    last = types.SimpleNamespace(line_no=5, hyphenated=False, prev=prev)
    assert parser.typeset.paragraph.interlinePenalty(para, last) == 2007


def test_linebreaker_select_final_positive_looseness():
    finals = [
        types.SimpleNamespace(line_no=4, demerits=10),
        types.SimpleNamespace(line_no=5, demerits=40),
        types.SimpleNamespace(line_no=6, demerits=30),
        types.SimpleNamespace(line_no=6, demerits=20),
    ]
    baseline, chosen = _LineBreaker._selectFinal(finals, 2)
    assert baseline.line_no == 4
    assert chosen.line_no == 6
    assert chosen.demerits == 20


def test_linebreaker_select_final_negative_looseness():
    finals = [
        types.SimpleNamespace(line_no=4, demerits=10),
        types.SimpleNamespace(line_no=3, demerits=30),
        types.SimpleNamespace(line_no=2, demerits=100),
    ]
    baseline, chosen = _LineBreaker._selectFinal(finals, -2)
    assert baseline.line_no == 4
    assert chosen.line_no == 2


def test_paragraph_settings_reset_after_paragraph(parser):
    parser.parse("\\looseness=2 a\\par b\\par")
    assert parser.volatile["looseness"] == 0


def test_parshape_resets_after_paragraph_end(parser):
    parser.parse("\\input plain")
    parser.parse(
        "\\hsize=200pt "
        "\\parshape 1 20pt 100pt "
        "A bit of text.\\par "
        "\\noindent B bit of text.\\par"
    )
    top = parser.lists[-1]
    paras = _source_nodes(top, paragraph.Paragraph)
    assert len(paras) == 2
    first = [
        node for node in _concrete_nodes(top)
        if node.node_type == nd.NODE_TYPE.HLIST and getattr(node, "source", None) is paras[0]
    ]
    second = [
        node for node in _concrete_nodes(top)
        if node.node_type == nd.NODE_TYPE.HLIST and getattr(node, "source", None) is paras[1]
    ]
    assert len(first) == 1
    assert len(second) == 1
    assert first[0].width == 100
    assert first[0].list[0].node_type == nd.NODE_TYPE.GLUE
    assert first[0].list[0].glue.dimen == 20
    assert second[0].width == 200
    assert second[0].list[0].node_type == nd.NODE_TYPE.CHAR
    assert second[0].list[0].char == "B"


def test_internal_paragraph_end_uses_current_par_definition(parser):
    parser.parse("\\input plain")
    parser.parse(
        "\\count0=0 "
        "\\def\\par{\\global\\advance\\count0 by 1 \\endgraf}"
        "a\\vskip0pt"
    )
    assert parser.count[0] == 1


def test_display_math_ends_paragraph_with_primitive_path(parser):
    parser.parse("\\input plain")
    parser.parse(
        "\\count0=0 "
        "\\def\\par{\\global\\advance\\count0 by 1 \\endgraf}"
        "a$$x$$"
    )
    assert parser.count[0] == 0


def test_noindent_with_hanging_label_does_not_add_first_line_indent(parser):
    parser.parse("\\input plain \\hsize=200pt \\hangindent=20pt \\noindent\\hbox{1\\quad}Introduction\\par")
    para = _source_nodes(parser.lists[-1], paragraph.Paragraph)[-1]
    out = []
    parser.typeset.paragraph.typeset(para, out)
    lines = _lineBoxes(out)
    assert len(lines) == 1
    assert lines[0].list[0].node_type == nd.NODE_TYPE.HLIST


def _flatten_text(nodes):
    out = []
    for node in nodes or []:
        if node.node_type == nd.NODE_TYPE.CHAR:
            out.append(node.char)
        elif node.node_type == nd.NODE_TYPE.LIGATURE:
            source = getattr(node, "source", None)
            if source:
                out.extend(char.char for char in source)
            else:
                out.append(node.char)
        elif node.node_type == nd.NODE_TYPE.GLUE:
            out.append(" ")
        elif node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            out.append(_flatten_text(getattr(node, "list", None)))
    return "".join(out)


def _collect_hbox_texts(box):
    texts = []
    for node in getattr(box, "list", None) or []:
        if node.node_type == nd.NODE_TYPE.HLIST:
            texts.append(_flatten_text(node.list).strip())
            texts.extend(_collect_hbox_texts(node))
        elif node.node_type == nd.NODE_TYPE.VLIST:
            texts.extend(_collect_hbox_texts(node))
    return texts
