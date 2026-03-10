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


def test_end_stops_processing(parser):
    parser.parse("\\end\\vskip 1pt")
    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 2
    assert top[0].node_type == nd.NODE_TYPE.GLUE
    assert top[0].name == "\\vfill"
    assert top[1].node_type == nd.NODE_TYPE.PENALTY
    assert top[1].penalty == -0x100000


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


def test_special_outputs_string(parser):
    parser.parse("\\special{abc}")
    seen = []
    node = parser.lists[-1][0]
    device = types.SimpleNamespace(special=lambda text: seen.append(text))
    node.output(parser, device)
    assert seen == ["abc"]


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


def test_last_item_quantities_vmode(cmr10):
    cmr10.parse(
        "\\vskip 5pt plus 1pt minus 1pt"
        "\\skip0=\\lastskip"
        "\\dimen0=\\lastkern"
        "\\count0=\\lastpenalty"
        "\\kern2pt"
        "\\dimen1=\\lastkern"
        "\\count1=\\lastpenalty"
        "\\penalty77"
        "\\count2=\\lastpenalty"
        "\\skip1=\\lastskip"
        "\\count3=\\lastpennalty"
    )
    assert cmr10.state.skip[0] == glue.Glue(5, glue.Stretchness(1), glue.Stretchness(1))
    assert cmr10.state.dimen[0] == 0
    assert cmr10.state.count[0] == 0
    assert cmr10.state.dimen[1] == 2
    assert cmr10.state.count[1] == 0
    assert cmr10.state.count[2] == 77
    assert cmr10.state.skip[1] == glue.Glue()
    assert cmr10.state.count[3] == 77


class _LeafHBox(nd.Box):
    node_type = nd.NODE_TYPE.HLIST
    typeset = None

    def __init__(self, height=6, depth=2):
        super().__init__(0, height, depth)
        self.shifted = 0
        self.list = None


def _test_hbox(parser, height=6, depth=2):
    return _LeafHBox(height, depth)


def _break_pages(parser):
    if parser.lists[-1].type == lists.LISTTYPE.HORIZONTAL:
        parser.endParagraph()
    main = parser.lists[0]
    assert isinstance(main, page.MainVList)
    main._realizeReadyTailEntries()
    material = list(main.contributed)
    breaker = page.MainVListBreaker(parser, material, main.page_initial_context)
    pages = [box.typeset(parser) for box in main.deferred_shipouts]
    context = main.page_initial_context
    topmark = list(parser.state.parameters["botmark"])
    page.MainVList._clearInsertScratch(parser)
    start = 0
    while True:
        start, context = breaker.pruneTop(start, context)
        if start >= len(material):
            break
        end, next_start, break_context, break_penalty = breaker.bestBreak(start, context)
        if end <= start:
            end = min(start + 1, len(material))
            next_start = end
            break_context = breaker.advanceContext(start, end, context)
            break_penalty = 0
        box = bx.VBox(parser, break_context.vsize, Dimen())
        firstmark, botmark = main._pageMarks(material, start, end, topmark)
        main._updatePageMarksByClass(parser, material, start, end, topmark)
        page_nodes = breaker.buildSlice(start, end, context, "\\topskip")
        page.MainVList._clearInsertScratch(parser)
        box.list[:], carry = main._extractPageInserts(parser, page_nodes, breaker)
        pages.append(box.typeset(parser))
        parser.state.layout["outputpenalty"] = break_penalty
        parser.state.globals["insertpenalties"] = breaker.last_insert_penalties
        parser.state.parameters["topmark"] = list(topmark)
        parser.state.parameters["firstmark"] = list(firstmark)
        parser.state.parameters["botmark"] = list(botmark)
        topmark = list(botmark)
        context = breaker.advanceContext(start, next_start, context)
        if carry:
            material[next_start:next_start] = carry
        start = next_start
    return pages


class _ProbeWhatsit(nd.WhatsIt):
    node_type = nd.NODE_TYPE.WHATSIT

    def __init__(self, seen):
        self.seen = seen

    def output(self, parser, device):
        self.seen.append("fired")

    def meaning(self, parser):
        return "ProbeWhatsit"


def test_prevdepth_penalty_does_not_reset(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt")
    vlist = vmode.VList(parser, [])
    vlist.append(_test_hbox(parser))
    vlist.append(nd.Penalty(0))
    vlist.append(_test_hbox(parser))
    packed = vmode.typesetVerticalNodes(parser, vlist, [])
    glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert len(glues) == 1
    assert glues[0].glue.dimen == 4


def test_prevdepth_kept_across_glue_kern_penalty(parser):
    vlist = vmode.VList(parser, [])
    vlist.append(_test_hbox(parser, depth=3))
    vlist.append(nd.Glue(glue.Glue(1), None))
    vlist.append(nd.Kern(1))
    vlist.append(nd.Penalty(0))
    assert vlist.resolvePrevDepth() == 3


def test_rule_resets_prevdepth_and_suppresses_interline_glue(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt")
    vlist = vmode.VList(parser, [])
    vlist.append(_test_hbox(parser))
    vlist.append(nd.Rule(0, 4, 0))
    vlist.append(_test_hbox(parser))
    packed = vmode.typesetVerticalNodes(parser, vlist, [])
    glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert len(glues) == 0


def test_rule_resets_resolved_prevdepth(parser):
    vlist = vmode.VList(parser, [])
    vlist.append(_test_hbox(parser, depth=3))
    vlist.append(nd.Rule(0, 4, 0))
    assert vlist.resolvePrevDepth() == vmode.init_prevdepth


def test_box_context_keeps_interlinepenalty(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt\\interlinepenalty=0")
    vlist = vmode.VList(parser, [])
    first = _test_hbox(parser)
    second = _test_hbox(parser)
    second.typeset_context = vmode.VNodeContext(parser.state.layout, vmode.init_prevdepth)
    second.typeset_context.interlinepenalty = 123
    vlist.append(first)
    vlist.append(second)
    packed = vmode.typesetVerticalNodes(parser, vlist, [])
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
    pages = _break_pages(parser)
    assert len(pages) == 2
    assert pages[0].height == 10
    assert pages[0].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[0].name == "\\topskip"
    assert pages[0].list[1] is first
    assert len(pages[0].list) == 2
    assert pages[1].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[1].list[0].name == "\\topskip"
    assert pages[1].list[1] is second


def test_page_break_uses_topskip_before_first_box(parser):
    parser.parse("\\vsize=20pt\\topskip=10pt")
    main = parser.lists[0]
    assert isinstance(main, page.MainVList)
    main.append(_test_hbox(parser, height=6, depth=0))
    pages = _break_pages(parser)
    assert len(pages) == 1
    assert pages[0].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[0].name == "\\topskip"
    assert pages[0].list[0].glue.dimen == 4


def test_page_break_discards_glue_before_first_box_after_whatsit(parser):
    parser.parse("\\vsize=20pt\\topskip=10pt")
    main = parser.lists[0]
    first = _test_hbox(parser, height=6, depth=0)
    main.append(nd.Special([]))
    main.append(nd.Glue(glue.Glue(2), None))
    main.append(first)
    pages = _break_pages(parser)
    assert len(pages) == 1
    assert pages[0].list[0].node_type == nd.NODE_TYPE.WHATSIT
    assert pages[0].list[1].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[1].name == "\\topskip"
    assert pages[0].list[1].glue.dimen == 4
    assert pages[0].list[2] is first
    assert len(pages[0].list) == 3


def test_page_break_keeps_void_box_and_forced_penalty_before_start(parser):
    parser.parse("\\vsize=20pt\\topskip=10pt")
    main = parser.lists[0]
    first = _test_hbox(parser, height=6, depth=0)
    void = bx.VBox(parser, None, None).typeset(parser)
    main.append(nd.Special([]))
    main.append(void)
    main.append(nd.Penalty(-10001))
    main.append(first)
    pages = _break_pages(parser)
    assert len(pages) == 2
    assert pages[0].list[0].node_type == nd.NODE_TYPE.WHATSIT
    assert pages[0].list[1].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[1].name == "\\topskip"
    assert pages[0].list[1].glue.dimen == 10
    assert pages[0].list[2] is void
    assert pages[1].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[1].list[0].name == "\\topskip"
    assert pages[1].list[0].glue.dimen == 4
    assert pages[1].list[1] is first


def test_page_break_extracts_insert_into_class_box(parser):
    parser.parse("\\vsize=200pt\\topskip=0pt\\count2=1000\\dimen2=200pt")
    main = parser.lists[0]
    main.append(vmode.Insert(2, [nd.Glue(glue.Glue(72.26999), None)]))
    main.append(_test_hbox(parser, height=6, depth=0))
    pages = _break_pages(parser)
    assert len(pages) == 1
    assert all(node.node_type != nd.NODE_TYPE.INS for node in pages[0].list)
    assert parser.state.globals["insertpenalties"] == 0
    ins = parser.state.box[2]
    assert ins is not None
    assert ins.node_type == nd.NODE_TYPE.VLIST
    assert len(ins.list) == 1
    assert ins.list[0].node_type == nd.NODE_TYPE.GLUE
    assert ins.list[0].glue == glue.Glue(72.26999)
    scratch = parser.state.globals["insert"][2]
    assert len(scratch) == 1
    assert scratch[0].node_type == nd.NODE_TYPE.VLIST


def test_insert_step1_skip_reduces_page_goal(parser):
    parser.parse("\\vsize=20pt\\topskip=0pt\\count2=1000\\dimen2=1000pt\\skip2=6pt\\insert2{}")
    main = parser.lists[0]
    main.append(_test_hbox(parser, height=8, depth=0))
    main.append(nd.Glue(glue.Glue(2), None))
    main.append(_test_hbox(parser, height=8, depth=0))
    pages = _break_pages(parser)
    assert len(pages) == 2


def test_insert_split_sets_floatingpenalty_and_carries_remainder(parser):
    parser.parse("\\vsize=100pt\\topskip=0pt\\count2=1000\\dimen2=5pt\\floatingpenalty=123")
    parser.parse(
        "\\insert2{\\hrule height4pt depth0pt\\penalty0\\hrule height4pt depth0pt}"
        "\\insert2{\\hrule height2pt depth0pt}"
    )
    main = parser.lists[0]
    main.append(_test_hbox(parser, height=1, depth=0))
    material = []
    vmode.typesetVerticalNodes(parser, main.list, material)
    breaker = page.MainVListBreaker(parser, material, main.page_initial_context)
    start, context = breaker.pruneTop(0, main.page_initial_context)
    end, _, _, _ = breaker.bestBreak(start, context)
    assert end > start
    ins_nodes = [node for node in material if node.node_type == nd.NODE_TYPE.INS]
    assert len(ins_nodes) == 2
    first = breaker.actionFor(ins_nodes[0])
    second = breaker.actionFor(ins_nodes[1])
    assert first["kind"] == "split"
    assert len(first["tail"]) > 0
    assert second["kind"] == "defer"
    assert breaker.last_insert_penalties == 123
    page_nodes = breaker.buildSlice(start, end, context, "\\topskip")
    page.MainVList._clearInsertScratch(parser)
    kept, carry = page.MainVList._extractPageInserts(parser, page_nodes, breaker)
    assert all(node.node_type != nd.NODE_TYPE.INS for node in kept)
    assert len(carry) == 2
    assert carry[0].node_type == nd.NODE_TYPE.INS
    assert carry[1].node_type == nd.NODE_TYPE.INS
    ins = parser.state.box[2]
    assert ins is not None
    assert ins.node_type == nd.NODE_TYPE.VLIST
    assert len(ins.list) == 1
    assert ins.list[0].node_type == nd.NODE_TYPE.RULE
    assert ins.list[0].height == 4
    assert ins.list[0].depth == 0


def test_page_cost_matches_tex_formula(parser):
    parser.parse("")
    main = parser.lists[0]
    total = glue.Glue(0, glue.Stretchness(1))
    assert main._pageCost(total, Dimen(5), 0) == 100000
    assert main._pageCost(total, Dimen(5), 10000) == float("inf")

    overfull = glue.Glue(10)
    assert main._pageCost(overfull, Dimen(), -10000) == float("inf")
    assert main._pageCost(total, Dimen(1), 0, 10000) == float("inf")


def test_page_badness_underfull_without_stretch_is_finite(parser):
    parser.parse("")
    main = parser.lists[0]
    assert main._pageBadness(glue.Glue(0), Dimen(5)) == 10000


def test_page_break_glue_requires_immediate_non_discardable_predecessor(parser):
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
    end, _, _, _ = main._bestPageBreak(nodes, 0, page.PageBuilderContext(parser.state.layout))
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
    end, _, _, _ = main._bestPageBreak(nodes, 0, page.PageBuilderContext(parser.state.layout))
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
    end, _, _, _ = main._bestPageBreak(nodes, 0, page.PageBuilderContext(parser.state.layout))
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
    pages = _break_pages(parser)
    assert pages[0].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[0].name == "\\topskip"
    assert pages[0].list[1] is rule


def test_main_vlist_inserts_page_state_marker_on_layout_change(parser):
    parser.parse("")
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
    pages = _break_pages(parser)
    assert len(pages) == 1
    assert pages[0].height == 20


def test_shipout_collects_box(parser):
    parser.parse("\\shipout\\hbox{A}")
    assert len(parser.lists[0]) == 0
    assert len(parser.lists[0].deferred_shipouts) == 1
    shipped = parser.lists[0].deferred_shipouts[0]
    assert shipped.node_type == nd.NODE_TYPE.HLIST


def test_output_pages_default_shipout(cmr10):
    cmr10.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}")
    shipout = cmr10.outputPages()
    assert len(shipout.pages) == 1
    assert cmr10.state.box[255] is None
    assert cmr10.state.globals["deadcycles"] == 0
    assert getattr(cmr10, "shipout", None) is None


def test_output_pages_skips_empty_page_with_only_whatsits(parser):
    seen = []
    parser.parse("")
    parser.lists[0].append(_ProbeWhatsit(seen))
    shipout = parser.outputPages()
    assert len(shipout.pages) == 0
    assert seen == ["fired"]


def test_page_break_waits_past_overfull_penalty_if_negative_glue_recovers(parser):
    parser.parse("\\vsize=16pt\\topskip=0pt")
    main = parser.lists[0]
    first = _test_hbox(parser, height=6, depth=2)
    second = _test_hbox(parser, height=6, depth=2)
    main.append(first)
    main.append(nd.Glue(glue.Glue(2), None))
    main.append(second)
    main.append(nd.Penalty(100))
    main.append(nd.Glue(glue.Glue(-2), None))
    pages = _break_pages(parser)
    assert len(pages) == 1
    assert pages[0].list[1] is first
    assert pages[0].list[2].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[2].glue.dimen == 2
    assert pages[0].list[-1].node_type == nd.NODE_TYPE.HLIST


def test_output_routine_can_carry_material_forward(cmr10):
    cmr10.parse(
        "\\output={\\ifnum\\count0=0\\global\\count0=1\\hbox{X}\\fi\\shipout\\box255}"
        "\\vsize=20pt\\topskip=0pt\\hbox{A}"
    )
    shipout = cmr10.outputPages()
    assert len(shipout.pages) == 2
    assert cmr10.state.count[0] == 1
    assert cmr10.state.globals["deadcycles"] == 0
    first = shipout.pages[0].list[1]
    second = shipout.pages[1].list[1]
    assert first.node_type == nd.NODE_TYPE.HLIST
    assert second.node_type == nd.NODE_TYPE.HLIST
    first_chars = [n.char for n in first.list if n.node_type == nd.NODE_TYPE.CHAR]
    second_chars = [n.char for n in second.list if n.node_type == nd.NODE_TYPE.CHAR]
    assert "A" in first_chars
    assert "X" in second_chars

def test_output_routine_sees_outputpenalty(cmr10):
    cmr10.parse(
        "\\output={\\global\\count0=\\outputpenalty\\shipout\\box255}"
        "\\vsize=20pt\\topskip=0pt\\hbox{A}\\penalty123"
    )
    cmr10.outputPages()
    assert cmr10.state.count[0] == 123


def test_output_uses_default_when_maxdeadcycles_reached(cmr10):
    cmr10.parse(
        "\\deadcycles=1\\maxdeadcycles=1"
        "\\output={\\global\\count0=1\\shipout\\box255}"
        "\\vsize=20pt\\topskip=0pt\\hbox{A}"
    )
    shipout = cmr10.outputPages()
    assert len(shipout.pages) == 1
    assert cmr10.state.count[0] == 0
    assert cmr10.state.box[255] is None
    assert cmr10.state.globals["deadcycles"] == 0


def test_output_pages_ships_deferred_shipouts_before_page(cmr10):
    cmr10.parse("\\shipout\\hbox{X}\\vsize=20pt\\topskip=0pt\\hbox{A}")
    shipout = cmr10.outputPages()
    assert len(shipout.pages) == 2
    first = shipout.pages[0]
    second = shipout.pages[1]
    assert first.node_type == nd.NODE_TYPE.HLIST
    assert second.node_type == nd.NODE_TYPE.VLIST


def test_mark(cmr10):
    cmr10.parse("\\def\\a{123}\\hbox{\\mark{\\a}}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    box = top[0]
    assert box.node_type == nd.NODE_TYPE.HLIST
    assert len(box.list) == 1
    packed = []
    vmode.typesetVerticalNodes(cmr10, top.list, packed)
    assert len(packed) == 2
    migrate = packed[1]
    assert migrate.node_type == nd.NODE_TYPE.MARK
    assert toksToString(cmr10, migrate.tokens) == "123"


def test_insert_migrate(cmr10):
    cmr10.parse("\\hbox{1\\insert 2{\\vskip 1in}}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    box = top[0]
    assert box.node_type == nd.NODE_TYPE.HLIST
    assert len(box.list) == 2
    packed = []
    vmode.typesetVerticalNodes(cmr10, top.list, packed)
    assert len(packed) == 2
    node = packed[1]
    assert node.node_type == nd.NODE_TYPE.INS
    assert node.index == 2
    assert len(node.vlist) == 1
    assert node.vlist[0].node_type == nd.NODE_TYPE.GLUE
    assert node.vlist[0].glue == glue.Glue(72.26999)


def test_vadjust_merges_into_vertical_material(cmr10):
    cmr10.parse("\\hsize=100pt\\noindent a\\vadjust{\\hrule height 1pt}b\\par")
    top = cmr10.lists[-1]
    packed = []
    vmode.typesetVerticalNodes(cmr10, top.list, packed)
    assert packed[0].node_type == nd.NODE_TYPE.HLIST
    assert packed[1].node_type == nd.NODE_TYPE.RULE
    assert packed[1].height == 1


def test_page_break_merges_vadjust_material(cmr10):
    cmr10.parse("\\vsize=100pt\\topskip=0pt\\hsize=100pt\\noindent a\\vadjust{\\hrule height 1pt}b\\par")
    pages = _break_pages(cmr10)
    assert len(pages) == 1
    page0 = pages[0].list
    rule_index = next(i for i, node in enumerate(page0) if node.node_type == nd.NODE_TYPE.RULE)
    assert rule_index > 0
    assert page0[rule_index - 1].node_type == nd.NODE_TYPE.HLIST
    assert page0[rule_index].height == 1
