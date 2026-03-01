import pytest
import types
from pytex import node as nd
from pytex import glue
from pytex import lists
from pytex import texlive
from pytex import vmode
from pytex import page
from pytex import box as bx
from pytex.dimen import Dimen
from pytex.box import LEADERS_TYPE
from pytex.expandable import toksToString


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
    assert toksToString(cmr10, node.tokens) == "123"


def test_special(cmr10):
    cmr10.parse("\\special{abc}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert node.node_type == nd.NODE_TYPE.WHATSIT
    assert toksToString(cmr10, node.text) == "abc"


@pytest.mark.parametrize("cmd, type", [
    ["\\leaders", LEADERS_TYPE.LEADERS],
    ["\\cleaders", LEADERS_TYPE.CLEADERS],
    ["\\xleaders", LEADERS_TYPE.XLEADERS],
])
def test_leaders(cmr10, cmd, type):
    cmr10.parse(cmd + "\\vbox{\\hbox{.}}\\vskip1cm")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert node.node_type == nd.NODE_TYPE.GLUE
    assert node.glue == glue.Glue(7227.0 / 254)
    ltype, box = node.leaders
    assert ltype == type
    assert box.node_type == nd.NODE_TYPE.VLIST
    assert len(box.list) == 1
    assert box.list[0].node_type == nd.NODE_TYPE.HLIST
    try:
        cmr10.parse("\\leaders\\vbox{.}")
        assert False
    except ValueError as e:
        assert "glue" in str(e)
    try:
        cmr10.parse("\\leaders\\vskip 1cm")
        assert False
    except ValueError as e:
        assert "box" in str(e)
    try:
        cmr10.parse("\\leaders\\hbox{.}\\vskip 1cm")
        assert False
    except ValueError as e:
        assert "mode" in str(e)
    try:
        cmr10.parse("\\leaders\\vbox{}\\hskip 1cm")
        assert False
    except ValueError as e:
        assert "mode" in str(e)


@pytest.mark.parametrize("cmd", [
    "\\kern 1cm\\unkern",
    "\\penalty 10000\\unpenalty",
    "\\vfil\\unskip",
])
def test_unkern(cmr10, cmd):
    cmr10.parse(f"{cmd}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 0


def _test_hbox(parser, height=6, depth=2):
    hbox = bx.HBox(parser, None, 0)
    hbox.width = Dimen(0)
    hbox.height = Dimen(height)
    hbox.depth = Dimen(depth)
    hbox.list = []
    return hbox


def test_prevdepth_penalty_does_not_reset(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt")
    vlist = vmode.VList(parser)
    vlist.append(_test_hbox(parser))
    vlist.append(nd.Penalty(0))
    vlist.append(_test_hbox(parser))
    packed = vlist.typesetNodes(parser, [])
    glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert len(glues) == 1
    assert glues[0].glue.dimen == 4


def test_prevdepth_kept_across_glue_kern_penalty(parser):
    vlist = vmode.VList(parser)
    vlist.append(_test_hbox(parser, depth=3))
    vlist.append(nd.Glue(glue.Glue(1), None))
    vlist.append(nd.Kern(1))
    vlist.append(nd.Penalty(0))
    assert vlist.resolvePrevDepth() == 3


def test_rule_resets_prevdepth_and_suppresses_interline_glue(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt")
    vlist = vmode.VList(parser)
    vlist.append(_test_hbox(parser))
    vlist.append(nd.Rule(0, 4, 0))
    vlist.append(_test_hbox(parser))
    packed = vlist.typesetNodes(parser, [])
    glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert len(glues) == 0


def test_rule_resets_resolved_prevdepth(parser):
    vlist = vmode.VList(parser)
    vlist.append(_test_hbox(parser, depth=3))
    vlist.append(nd.Rule(0, 4, 0))
    assert vlist.resolvePrevDepth() == vmode.init_prevdepth


def test_box_context_keeps_interlinepenalty(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt\\interlinepenalty=0")
    vlist = vmode.VList(parser)
    first = _test_hbox(parser)
    second = _test_hbox(parser)
    second.typeset_context = vmode.VNodeContext(parser.state.layout, vmode.init_prevdepth)
    second.typeset_context.interlinepenalty = 123
    vlist.append(first)
    vlist.append(second)
    packed = vlist.typesetNodes(parser, [])
    penalties = [n for n in packed if n.node_type == nd.NODE_TYPE.PENALTY]
    assert len(penalties) == 1
    assert penalties[0].penalty == 123


def test_prevdepth_accessor_is_vlist_local(parser):
    parser.parse("\\prevdepth=5pt\\dimen0=\\prevdepth")
    assert parser.state.dimen[0] == 5


def test_prevdepth_accessor_wrong_mode(cmr10):
    try:
        cmr10.parse("a\\prevdepth=1pt")
        assert False
    except ValueError as e:
        assert "vertical mode" in str(e)


def test_page_break_inserts_topskip_and_splits_pages(parser):
    parser.parse("\\vsize=10pt\\topskip=0pt")
    main = parser.lists[0]
    assert isinstance(main, page.MainVList)
    first = _test_hbox(parser, height=6, depth=0)
    second = _test_hbox(parser, height=6, depth=0)
    main.append(first)
    main.append(nd.Glue(glue.Glue(4), None))
    main.append(second)
    pages = main.pageBreak(parser)
    assert len(pages) == 2
    assert pages[0].height == 10
    assert pages[0].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[0].name == "\\topskip"
    assert pages[0].list[1] is first
    assert pages[0].list[2].node_type == nd.NODE_TYPE.GLUE
    assert pages[1].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[1].list[0].name == "\\topskip"
    assert pages[1].list[1] is second


def test_page_break_uses_topskip_before_first_box(parser):
    parser.parse("\\vsize=20pt\\topskip=10pt")
    main = parser.lists[0]
    assert isinstance(main, page.MainVList)
    main.append(_test_hbox(parser, height=6, depth=0))
    pages = main.pageBreak(parser)
    assert len(pages) == 1
    assert pages[0].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[0].name == "\\topskip"
    assert pages[0].list[0].glue.dimen == 4


def test_page_break_insert_not_implemented(cmr10):
    cmr10.parse("\\insert 2{\\vskip 1in}")
    with pytest.raises(NotImplementedError):
        cmr10.breakPages()


def test_page_cost_matches_tex_formula(parser):
    main = parser.lists[0]
    total = glue.Glue(0, glue.Stretchness(1))
    assert main._pageCost(total, Dimen(5), 0) == 100000
    assert main._pageCost(total, Dimen(5), 10000) == float("inf")

    overfull = glue.Glue(10)
    assert main._pageCost(overfull, Dimen(), -10000) == float("inf")
    assert main._pageCost(total, Dimen(1), 0, 10000) == float("inf")


def test_page_break_glue_requires_non_discardable_predecessor(parser):
    parser.parse("\\vsize=10pt\\topskip=0pt")
    main = parser.lists[0]
    first = _test_hbox(parser, height=6, depth=0)
    second = _test_hbox(parser, height=6, depth=0)
    nodes = [
        first,
        nd.Penalty(0),
        nd.Glue(glue.Glue(4, glue.Stretchness(1)), None),
        second,
    ]
    end, _, _ = main._bestPageBreak(nodes, 0, page.PageBuilderContext(parser.state.layout))
    assert end == 1


def test_page_break_kern_requires_following_glue(parser):
    parser.parse("\\vsize=10pt\\topskip=0pt")
    main = parser.lists[0]
    nodes = [
        _test_hbox(parser, height=6, depth=0),
        nd.Kern(4),
        _test_hbox(parser, height=6, depth=0),
        nd.Glue(glue.Glue(), None),
    ]
    end, _, _ = main._bestPageBreak(nodes, 0, page.PageBuilderContext(parser.state.layout))
    assert end != 2


def test_page_break_prefers_later_equal_cost_breakpoint(parser):
    parser.parse("\\vsize=10pt\\topskip=0pt")
    main = parser.lists[0]
    nodes = [
        _test_hbox(parser, height=6, depth=0),
        nd.Glue(glue.Glue(0, glue.Stretchness(1, 1)), None),
        nd.Penalty(0),
        nd.Penalty(0),
        _test_hbox(parser, height=6, depth=0),
    ]
    end, _, _ = main._bestPageBreak(nodes, 0, page.PageBuilderContext(parser.state.layout))
    assert end == 3


def test_page_break_uses_maxdepth_in_cost_and_page_box(parser):
    parser.parse("\\maxdepth=2pt")
    main = parser.lists[0]
    first = _test_hbox(parser, height=6, depth=3)
    total = glue.Glue(11, glue.Stretchness(2))
    effective = main._effectiveTotal(total, first.depth, parser.state.layout["maxdepth"])
    assert effective.dimen == 10
    page_nodes = main._buildPage(parser, [first], 0, 1, page.PageBuilderContext(parser.state.layout))
    assert page_nodes[0].node_type == nd.NODE_TYPE.GLUE
    assert page_nodes[1] is first
    assert first.depth == 2


def test_page_topskip_includes_rule(parser):
    parser.parse("\\vsize=20pt\\topskip=10pt")
    main = parser.lists[0]
    rule = nd.Rule(0, 6, 0)
    main.append(rule)
    pages = main.pageBreak(parser)
    assert pages[0].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[0].name == "\\topskip"
    assert pages[0].list[1] is rule


def test_main_vlist_inserts_page_state_marker_on_layout_change(parser):
    main = parser.lists[0]
    parser.state.layout["vsize"] = Dimen(20)
    box = _test_hbox(parser, height=6, depth=0)
    main.append(box)
    assert len(main) == 2
    assert isinstance(main[0], page.PageStateNode)
    assert main[1] is box
    assert main[0].context.vsize == 20


def test_page_break_uses_marker_context(parser):
    parser.parse("\\vsize=10pt\\topskip=0pt")
    main = parser.lists[0]
    first = _test_hbox(parser, height=6, depth=0)
    second = _test_hbox(parser, height=6, depth=0)
    main.append(first)
    main.append(nd.Glue(glue.Glue(2, glue.Stretchness(1, 1)), None))
    parser.state.layout["vsize"] = Dimen(20)
    main.append(second)
    main.append(nd.Penalty(-10000))
    pages = main.pageBreak(parser)
    assert len(pages) == 1
    assert pages[0].height == 20


def test_shipout_collects_box(parser):
    parser.parse("\\shipout\\hbox{A}")
    assert len(parser.shipout.pages) == 1
    page = parser.shipout.pages[0]
    assert page.node_type == nd.NODE_TYPE.HLIST


def test_output_pages_default_shipout(cmr10):
    cmr10.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}")
    pages = cmr10.outputPages()
    assert len(pages) == 1
    assert len(cmr10.shipout.pages) == 1
    assert pages[0] is cmr10.shipout.pages[0]
    assert cmr10.state.box[255] is None


def test_output_routine_can_carry_material_forward(cmr10):
    cmr10.parse(
        "\\output={\\ifnum\\count0=0\\global\\count0=1\\hbox{X}\\fi\\shipout\\box255}"
        "\\vsize=20pt\\topskip=0pt\\hbox{A}"
    )
    pages = cmr10.outputPages()
    assert len(pages) == 2
    assert len(cmr10.shipout.pages) == 2
    assert cmr10.state.count[0] == 1
    first = pages[0].list[1]
    second = pages[1].list[1]
    assert first.node_type == nd.NODE_TYPE.HLIST
    assert second.node_type == nd.NODE_TYPE.HLIST
    first_chars = [n.char for n in first.list if n.node_type == nd.NODE_TYPE.CHAR]
    second_chars = [n.char for n in second.list if n.node_type == nd.NODE_TYPE.CHAR]
    assert "A" in first_chars
    assert "X" in second_chars
