import pytest
from pytex import align
from pytex import texlive
from pytex import lists
from pytex import vmode
from pytex import glue
from pytex import node as nd
from pytex.dimen import Dimen


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


def _typeset_halign(parser, node):
    packed = vmode.VList(parser, [], inner=True)
    packed.open()
    try:
        parser.alignment_typesetter.typesetHAlignment(node, packed)
        return list(packed.list)
    finally:
        packed.close()


def test_halign(cmr10):
    cmr10.parse("\\halign{1 #& 2 #\\cr a & b\\cr}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    raw = _source_nodes(top, align.HAlignment)
    assert len(raw) == 1
    node = raw[0]
    assert isinstance(node, align.HAlignment)
    assert node.noalign is None
    assert len(node.rows) == 1
    row = node.rows[0]
    assert len(row.cells) == 2

def test_halign_initial_empty_preamble_repeats(cmr10):
    cmr10.parse("\\halign{&#\\cr 1&2&3\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert len(row.cells) == 3

def test_halign_extra_alignment_tab_fails(cmr10):
    with pytest.raises(ValueError):
        cmr10.parse("\\halign{a#b&#\\cr 1&2&3\\cr}")

def test_tabskip(cmr10):
    cmr10.parse("\\tabskip 1pt\\halign{1 #\\tabskip 2pt& 2 #\\cr a & b\\cr}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    raw = _source_nodes(top, align.HAlignment)
    assert len(raw) == 1
    node = raw[0]
    assert len(node.tabskips) == 3
    assert node.tabskips[0] == glue.Glue(1)
    assert node.tabskips[1] == glue.Glue(2)
    assert node.tabskips[2] == glue.Glue(2)


def test_noalign(cmr10):
    cmr10.parse("\\halign{1 #& 2 #\\cr\\noalign{\\vskip1pt} a & b\\cr\\noalign{\\vskip2pt}}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    raw = _source_nodes(top, align.HAlignment)
    assert len(raw) == 1
    node = raw[0]
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


def test_noalign_allows_leading_spaces_after_cr(cmr10):
    cmr10.parse("\\halign{#\\cr   \\noalign{\\vskip1pt} a\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    assert node.noalign is not None
    assert len(node.rows) == 1


def test_consecutive_noalign_bodies_are_preserved(cmr10):
    cmr10.parse(
        "\\everycr{\\noalign{\\penalty10000}}"
        "\\halign{#\\cr a\\cr\\noalign{\\vskip0pt} b\\cr}"
    )
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert row.noalign is not None
    assert [n.node_type for n in row.noalign] == [nd.NODE_TYPE.PENALTY, nd.NODE_TYPE.GLUE]
    assert row.noalign[0].penalty == 10000
    assert row.noalign[1].glue == glue.Glue(0)
    packed = _typeset_halign(cmr10, node)
    row0 = next(i for i, n in enumerate(packed) if n.node_type == nd.NODE_TYPE.HLIST)
    assert packed[row0 + 1].node_type == nd.NODE_TYPE.PENALTY
    assert packed[row0 + 1].penalty == 10000
    assert packed[row0 + 2].node_type == nd.NODE_TYPE.GLUE
    assert packed[row0 + 2].glue == glue.Glue(0)
    assert any(n.node_type == nd.NODE_TYPE.HLIST for n in packed[row0 + 3 :])


def test_trailing_crcr_before_endgroup_after_noalign_does_not_create_empty_row(cmr10):
    cmr10.parse("\\let\\egroup=}\\halign{#\\cr a\\cr\\noalign{\\vskip1pt}\\crcr\\egroup")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    assert len(node.rows) == 1
    assert len(node.rows[0].cells) == 1
    assert node.rows[0].noalign is not None


def test_span(cmr10):
    cmr10.parse("\\halign{1 # & 2 #\\cr a \\span b\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert row.cells[0].span == 2


def test_omit(cmr10):
    cmr10.parse("\\halign{1 # & 2 #\\cr a \\span\\omit b\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert row.cells[0].span == 2
    assert len(row.cells[0].list) == 6 # 1, ,a, , ,b


def test_cell_leading_spaces_are_omitted(cmr10):
    cmr10.parse("\\halign{1#\\cr   a\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert len(row.cells[0].list) == 2


def test_template_leading_spaces_are_omitted(cmr10):
    cmr10.parse("\\halign{   1#\\cr a\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert len(row.cells[0].list) == 2


def test_preamble_balanced_text_hides_cr(cmr10):
    cmr10.parse("\\halign{{\\cr}#\\cr}")
    assert _concrete_nodes(cmr10.lists[-1]) == []


def test_preamble_hash_inside_group_is_valid_placeholder(cmr10):
    cmr10.parse("\\halign{&$1\\over{#}$\\cr 1&2&3\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert len(row.cells) == 3


def test_preamble_multiple_hash_tokens_fail(cmr10):
    with pytest.raises(ValueError):
        cmr10.parse("\\halign{a#b{#}\\cr 1\\cr}")


def test_nested_valign_in_halign_cell(cmr10):
    cmr10.parse("\\halign{#\\cr \\valign{#\\cr a\\cr b\\cr}\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert len(row.cells[0].list) == 2
    assert isinstance(row.cells[0].list[0].source, align.VAlignment)


def test_nested_halign_in_valign_cell(cmr10):
    cmr10.parse("\\setbox1=\\hbox{\\valign{#\\cr \\halign{#\\cr \\hbox{}\\cr}\\cr}}")
    assert cmr10.box[1] is not None


def test_omit_as_first_non_space_token_ignores_template(cmr10):
    cmr10.parse("\\halign{1#2\\cr   \\omit a\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert not hasattr(row.cells[0].list, "omit")
    assert len(row.cells[0].list) == 1


def test_everycr_runs_between_alignment_rows(cmr10):
    cmr10.parse(
        "\\count0=0 "
        "\\everycr{\\noalign{\\global\\advance\\count0 by 1}}"
        "\\setbox0=\\vbox{\\halign{#\\cr a\\cr b\\cr}}"
        "\\message{COUNT=\\the\\count0}"
    )
    assert "COUNT=3" in cmr10.logContent()


def test_halign_typesets_directly_to_rows(cmr10):
    cmr10.parse("\\halign{#&#\\cr a&bc\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    packed = _typeset_halign(cmr10, node)
    assert len(packed) == 1
    assert packed[0].node_type == nd.NODE_TYPE.HLIST


def test_alignment_cells_are_pretypeset_when_closed(cmr10):
    cmr10.parse("\\halign{#&#\\cr a&bc\\cr}")
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    row = node.rows[0]
    assert row.cells[0]._packed is not None
    assert row.cells[1]._packed is not None


def test_halign_span_widths_follow_tex_formula(cmr10):
    cmr10.parse(
        "\\tabskip 0pt"
        "\\halign{#&#&#\\cr"
        "\\kern1pt&\\kern1pt&\\kern1pt\\cr"
        "\\kern1pt\\span\\kern1pt\\span\\kern4pt\\cr"
        "\\kern1pt\\span\\kern3pt\\cr}"
    )
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    packed = _typeset_halign(cmr10, node)
    rows = [item for item in packed if item.node_type == nd.NODE_TYPE.HLIST]
    assert len(rows) == 3
    assert rows[0].width == 6
    assert rows[1].width == 6
    assert rows[2].width == 6


def test_halign_spanned_box_uses_row_glue_setting(cmr10):
    cmr10.parse(
        "\\tabskip 0pt plus 1pt"
        "\\halign to 10pt{#&#\\cr"
        "\\kern1pt&\\kern1pt\\cr"
        "\\kern1pt\\span\\kern1pt\\cr}"
    )
    node = _source_nodes(cmr10.lists[-1], align.HAlignment)[0]
    assert isinstance(node.to, Dimen)
    packed = _typeset_halign(cmr10, node)
    rows = [item for item in packed if item.node_type == nd.NODE_TYPE.HLIST]
    assert len(rows) == 2
    assert rows[0].width == 10
    assert rows[1].width == 10
    assert float(rows[1].glue_ratio) == pytest.approx(8 / 3, abs=1e-4)
    assert float(rows[1].list[1].width) == pytest.approx(1.0, abs=1e-4)
    assert float(rows[1].list[3].width) == pytest.approx(1.0, abs=1e-4)


def test_valign_typesets_to_hbox(cmr10):
    cmr10.parse("\\setbox1=\\hbox{\\valign{#\\cr a\\cr b\\cr}}")
    outer = cmr10.box[1]
    assert outer.typeset(cmr10).list[0].node_type == nd.NODE_TYPE.VLIST


def test_valign_normalizes_cell_box_widths(cmr10):
    cmr10.parse("\\setbox1=\\hbox{\\valign{#&#\\cr \\hbox{a}&\\hbox{bc}\\cr \\hbox{d}&\\hbox{e}\\cr}}")
    outer = cmr10.box[1]
    out = outer.typeset(cmr10)
    left, right = out.list
    left_cells = [node for node in left.list if node.node_type == nd.NODE_TYPE.VLIST]
    right_cells = [node for node in right.list if node.node_type == nd.NODE_TYPE.VLIST]
    assert left_cells[0].width == left.width
    assert left_cells[1].width == left.width
    assert right_cells[0].width == right.width
    assert right_cells[1].width == right.width


def test_halign_in_diplsaymath_shift_displayindent(cmr10):
    cmr10.parse("\\noindent$$\\displayindent=10pt\\halign{&#\\cr1&2\\cr}$$\\par")
    top = cmr10.lists[-1]
    packed = _concrete_nodes(top)
    assert top.type == lists.LISTTYPE.VERTICAL and not top.inner
    display = next(node for node in packed if node.node_type == nd.NODE_TYPE.HLIST and node.shifted == Dimen(10))
    assert display.shifted == Dimen(10)
