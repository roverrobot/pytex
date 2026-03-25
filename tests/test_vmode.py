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


def _raw_nodes(vlist):
    return getattr(vlist, "raw", vlist)


def _vertical_nodes(vlist):
    contrib = list(getattr(vlist, "contrib", []))
    pending = list(getattr(vlist, "list", vlist))
    return contrib + pending


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
    assert len(top) == 0


def test_penalty(cmr10):
    cmr10.parse("\\penalty 10000")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    nodes = _vertical_nodes(top)
    assert len(nodes) == 1
    node = nodes[0]
    assert node.node_type == nd.NODE_TYPE.PENALTY
    assert node.penalty == 10000


def test_insert(cmr10):
    cmr10.parse("\\insert 2{\\vskip 1in}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    nodes = _vertical_nodes(top)
    assert len(nodes) == 1
    node = nodes[0]
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


def test_mark_preserves_single_hash(cmr10):
    cmr10.parse("\\mark{\\string#}")
    node = cmr10.lists[-1][0]
    assert toksToString(cmr10, node.tokens) == "#"


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


def test_special_outputs_single_hash(parser):
    parser.parse("\\special{\\string#}")
    seen = []
    node = parser.lists[-1][0]
    device = types.SimpleNamespace(special=lambda text: seen.append(text))
    node.output(parser, device)
    assert seen == ["#"]


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
    "\\vfil\\unskip",
    "\\vbox{\\penalty 10000\\unpenalty",
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


def test_lastskip_after_display_math_uses_concrete_vertical_tail(cmr10):
    cmr10.parse("$$a$$\\par\\skip0=\\lastskip\\dimen0=\\lastkern\\count0=\\lastpenalty\\end")
    assert cmr10.state.skip[0] == cmr10.state.layout["belowdisplayshortskip"]
    assert cmr10.state.dimen[0] == 0
    assert cmr10.state.count[0] == 0


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
    pages = list(parser.shipout.pages)
    main._contributePending()
    material = list(main.contrib)
    context = page.PageBuilderContext(parser.state.layout)
    breaker = page.PageBreaker(parser, material, context)
    topmark = list(parser.state.parameters["botmark"])
    page.MainVList._clearInsertScratch(parser)
    start = 0
    while True:
        start, context = breaker.pruneTop(start, context)
        if start >= len(material):
            break
        end, next_start, break_context, break_penalty, _ = breaker.bestBreak(start, context)
        if end <= start:
            end = min(start + 1, len(material))
            next_start = end
            break_context = breaker.advanceContext(start, end, context)
            break_penalty = 0
        box = bx.VBox(parser, break_context.vsize, None)
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


def _concrete_vlist(parser, nodes):
    if isinstance(nodes, page.MainVList):
        return _vertical_nodes(nodes)
    if isinstance(nodes, vmode.VList):
        return list(nodes.list)
    saved_prevdepth = parser.state.globals["prevdepth"]
    try:
        parser.state.globals["prevdepth"] = vmode.init_prevdepth
        vlist = vmode.VList(parser, [])
        for node in nodes:
            vlist.append(node)
        return list(vlist.list)
    finally:
        parser.state.globals["prevdepth"] = saved_prevdepth


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
    packed = _concrete_vlist(parser, vlist)
    glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert len(glues) == 1
    assert glues[0].glue.dimen == 4


def test_vlist_append_inserts_interline_glue_after_discardables(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt")
    vlist = vmode.VList(parser, [])
    first = _test_hbox(parser)
    second = _test_hbox(parser)
    vlist.append(first)
    vlist.append(nd.Glue(glue.Glue(2), None))
    vlist.append(second)
    assert vlist.list[0] is first
    assert vlist.list[1].node_type == nd.NODE_TYPE.GLUE
    assert vlist.list[1].glue.dimen == 2
    assert vlist.list[2].node_type == nd.NODE_TYPE.GLUE
    assert vlist.list[2].name == "\\baselineskip"
    assert vlist.list[3] is second


def test_prevdepth_kept_across_glue_kern_penalty(parser):
    vlist = vmode.VList(parser, [])
    vlist.append(_test_hbox(parser, depth=3))
    vlist.append(nd.Glue(glue.Glue(1), None))
    vlist.append(nd.Kern(1))
    vlist.append(nd.Penalty(0))
    assert parser.state.globals["prevdepth"] == 3


def test_rule_resets_prevdepth_and_suppresses_interline_glue(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt")
    vlist = vmode.VList(parser, [])
    vlist.append(_test_hbox(parser))
    vlist.append(nd.Rule(0, 4, 0))
    vlist.append(_test_hbox(parser))
    packed = _concrete_vlist(parser, vlist)
    glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    penalties = [n for n in packed if n.node_type == nd.NODE_TYPE.PENALTY]
    assert len(glues) == 0
    assert len(penalties) == 0


def test_rule_resets_resolved_prevdepth(parser):
    vlist = vmode.VList(parser, [])
    vlist.append(_test_hbox(parser, depth=3))
    vlist.append(nd.Rule(0, 4, 0))
    assert parser.state.globals["prevdepth"] == vmode.init_prevdepth


def test_box_interline_penalty_override(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt\\interlinepenalty=0")
    vlist = vmode.VList(parser, [])
    first = _test_hbox(parser)
    second = _test_hbox(parser)
    second.interline_penalty = 123
    vlist.append(first)
    vlist.append(second)
    packed = _concrete_vlist(parser, vlist)
    penalties = [n for n in packed if n.node_type == nd.NODE_TYPE.PENALTY]
    assert len(penalties) == 1
    assert penalties[0].penalty == 123


def test_prevdepth_accessor_is_vlist_local(parser):
    parser.parse("\\prevdepth=5pt\\dimen0=\\prevdepth")
    assert parser.state.dimen[0] == 5


def test_prevdepth_assignment_is_not_grouped(parser):
    parser.parse("{\\prevdepth=100pt}\\dimen0=\\prevdepth")
    assert parser.state.dimen[0] == 100


def test_prevdepth_assignment_affects_next_box_context(parser):
    parser.parse("\\baselineskip=12pt\\lineskiplimit=0pt\\lineskip=1pt")
    vlist = vmode.VList(parser, [])
    first = _test_hbox(parser)
    second = _test_hbox(parser)
    vlist.append(first)
    parser.state.globals["prevdepth"] = Dimen(10)
    vlist.append(second)
    packed = _concrete_vlist(parser, vlist)
    glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
    assert len(glues) == 1
    assert glues[0].name == "\\lineskip"
    assert glues[0].glue.dimen == 1


def test_prevdepth_assignment_is_allowed_in_horizontal_mode(cmr10):
    cmr10.parse("a\\prevdepth=1pt\\dimen0=\\prevdepth")
    assert cmr10.state.dimen[0] == 1


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
    main._contributePending()
    material = list(main.contrib)
    context = page.PageBuilderContext(parser.state.layout)
    breaker = page.PageBreaker(parser, material, context)
    start, context = breaker.pruneTop(0, context)
    end, _, _, _, _ = breaker.bestBreak(start, context)
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
    breaker = page.PageBreaker(parser, [], page.PageBuilderContext(parser.state.layout))
    total = glue.Glue(0, glue.Stretchness(1))
    assert breaker.cost(total, Dimen(5), 0) == 100000
    assert breaker.cost(total, Dimen(5), 10000) == float("inf")

    overfull = glue.Glue(10)
    assert breaker.cost(overfull, Dimen(), -10000) == float("inf")
    assert breaker.cost(total, Dimen(1), 0, 10000) == float("inf")


def test_page_badness_underfull_without_stretch_is_finite(parser):
    parser.parse("")
    assert page.VerticalBreaker.badness(glue.Glue(0), Dimen(5)) == 10000


def test_page_topskip_includes_rule(parser):
    parser.parse("\\vsize=20pt\\topskip=10pt")
    main = parser.lists[0]
    rule = nd.Rule(0, 6, 0)
    main.append(rule)
    pages = _break_pages(parser)
    assert pages[0].list[0].node_type == nd.NODE_TYPE.GLUE
    assert pages[0].list[0].name == "\\topskip"
    assert pages[0].list[1] is rule


def test_main_vlist_moves_triggered_nodes_into_contrib(parser):
    parser.parse("")
    main = parser.lists[0]
    parser.state.layout["vsize"] = Dimen(20)
    box = _test_hbox(parser, height=6, depth=0)
    main.append(box)
    assert len(main.list) == 0
    assert len(main.contrib) == 1
    assert main.contrib[0] is box


def test_page_break_uses_current_layout_at_break_time(parser):
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
    assert len(parser.shipout.pages) == 1
    shipped = parser.shipout.pages[0]
    assert shipped.node_type == nd.NODE_TYPE.HLIST


def test_end_default_shipout(cmr10):
    cmr10.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}")
    cmr10.end()
    shipout = cmr10.shipout
    assert len(shipout.pages) == 1
    assert cmr10.state.box[255] is None
    assert cmr10.state.globals["deadcycles"] == 0


def test_end_skips_empty_page_with_only_whatsits(parser):
    seen = []
    parser.parse("")
    parser.lists[0].append(_ProbeWhatsit(seen))
    parser.end()
    shipout = parser.shipout
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
    cmr10.end()
    shipout = cmr10.shipout
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
    cmr10.end()
    assert cmr10.state.count[0] == 123


def test_output_uses_default_when_maxdeadcycles_reached(cmr10):
    cmr10.parse(
        "\\deadcycles=1\\maxdeadcycles=1"
        "\\output={\\global\\count0=1\\shipout\\box255}"
        "\\vsize=20pt\\topskip=0pt\\hbox{A}"
    )
    cmr10.end()
    shipout = cmr10.shipout
    assert len(shipout.pages) == 1
    assert cmr10.state.count[0] == 0
    assert cmr10.state.box[255] is None
    assert cmr10.state.globals["deadcycles"] == 0


def test_end_ships_explicit_shipout_before_page(cmr10):
    cmr10.parse("\\shipout\\hbox{X}\\vsize=20pt\\topskip=0pt\\hbox{A}")
    cmr10.end()
    shipout = cmr10.shipout
    assert len(shipout.pages) == 2
    first = shipout.pages[0]
    second = shipout.pages[1]
    assert first.node_type == nd.NODE_TYPE.HLIST
    assert second.node_type == nd.NODE_TYPE.VLIST


def test_mark(cmr10):
    cmr10.parse("\\def\\a{123}\\hbox{\\mark{\\a}}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    packed = _vertical_nodes(top)
    assert len(packed) == 2
    box = packed[0]
    assert box.node_type == nd.NODE_TYPE.HLIST
    migrate = packed[1]
    assert migrate.node_type == nd.NODE_TYPE.MARK
    assert toksToString(cmr10, migrate.tokens) == "123"


def test_main_vlist_raw_nodes_include_migrated_mark(cmr10):
    cmr10.parse("\\def\\a{123}\\hbox{\\mark{\\a}}")
    raw = cmr10.lists[-1].rawNodes()
    assert len(raw) == 2
    assert raw[0].node_type == nd.NODE_TYPE.HLIST
    assert raw[1].node_type == nd.NODE_TYPE.MARK
    assert toksToString(cmr10, raw[1].tokens) == "123"


def test_insert_migrate(cmr10):
    cmr10.parse("\\hbox{1\\insert 2{\\vskip 1in}}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    packed = _vertical_nodes(top)
    assert len(packed) == 2
    box = packed[0]
    assert box.node_type == nd.NODE_TYPE.HLIST
    node = packed[1]
    assert node.node_type == nd.NODE_TYPE.INS
    assert node.index == 2
    assert len(node.vlist) == 1
    assert node.vlist[0].node_type == nd.NODE_TYPE.GLUE
    assert node.vlist[0].glue == glue.Glue(72.26999)


def test_vadjust_merges_into_vertical_material(cmr10):
    cmr10.parse("\\hsize=100pt\\noindent a\\vadjust{\\hrule height 1pt}b\\par")
    top = cmr10.lists[-1]
    packed = _vertical_nodes(top)
    assert packed[0].node_type == nd.NODE_TYPE.GLUE
    assert packed[1].node_type == nd.NODE_TYPE.HLIST
    assert packed[2].node_type == nd.NODE_TYPE.RULE
    assert packed[2].height == 1


def test_page_break_merges_vadjust_material(cmr10):
    cmr10.parse("\\vsize=100pt\\topskip=0pt\\hsize=100pt\\noindent a\\vadjust{\\hrule height 1pt}b\\par")
    pages = _break_pages(cmr10)
    assert len(pages) == 1
    page0 = pages[0].list
    rule_index = next(i for i, node in enumerate(page0) if node.node_type == nd.NODE_TYPE.RULE)
    assert rule_index > 0
    assert page0[rule_index - 1].node_type == nd.NODE_TYPE.HLIST
    assert page0[rule_index].height == 1
