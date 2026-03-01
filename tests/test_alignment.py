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
    assert isinstance(node, align.HAlignment)
    assert node.noalign is None
    assert node.typeset_context is not None
    assert len(node.rows) == 1
    row = node.rows[0]
    assert len(row.cells) == 2


def test_tabskip(cmr10):
    cmr10.parse("\\tabskip 1pt\\halign{1 #\\tabskip 2pt& 2 #\\cr a & b\\cr}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
    node = top[0]
    assert len(node.tabskips) == 3
    assert node.tabskips[0] == glue.Glue(1)
    assert node.tabskips[1] == glue.Glue(2)
    assert node.tabskips[2] == glue.Glue(2)


def test_noalign(cmr10):
    cmr10.parse("\\halign{1 #& 2 #\\cr\\noalign{\\vskip1pt} a & b\\cr\\noalign{\\vskip2pt}}")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    assert len(top) == 1
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
    cmr10.parse("\\halign{1 # & 2 #\\cr a \\span b\\cr}")
    top = cmr10.lists[-1]
    node = top[0]
    row = node.rows[0]
    assert len(row.cells) == 2
    assert row.cells[0].list.span == 1


def test_omit(cmr10):
    cmr10.parse("\\halign{1 # & 2 #\\cr a \\span\\omit b\\cr}")
    top = cmr10.lists[-1]
    node = top[0]
    row = node.rows[0]
    assert len(row.cells) == 2
    assert row.cells[0].list.span == 1
    assert len(row.cells[1].list) == 1


def test_cell_leading_spaces_are_omitted(cmr10):
    cmr10.parse("\\halign{1#\\cr   a\\cr}")
    top = cmr10.lists[-1]
    node = top[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert len(row.cells[0].list) == 2


def test_template_leading_spaces_are_omitted(cmr10):
    cmr10.parse("\\halign{   1#\\cr a\\cr}")
    top = cmr10.lists[-1]
    node = top[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert len(row.cells[0].list) == 2


def test_preamble_balanced_text_hides_cr(cmr10):
    cmr10.parse("\\halign{{\\cr}#\\cr}")
    top = cmr10.lists[-1]
    node = top[0]
    assert len(node.rows) == 0


def test_nested_valign_in_halign_cell(cmr10):
    cmr10.parse("\\halign{#\\cr \\valign{#\\cr a\\cr b\\cr}\\cr}")
    top = cmr10.lists[-1]
    node = top[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert len(row.cells[0].list) == 1
    assert isinstance(row.cells[0].list[0], align.VAlignment)


def test_nested_halign_in_valign_cell(cmr10):
    cmr10.parse("\\setbox1=\\hbox{\\valign{#\\cr \\halign{#\\cr \\hbox{}\\cr}\\cr}}")
    assert cmr10.state.box[1] is not None


def test_omit_as_first_non_space_token_ignores_template(cmr10):
    cmr10.parse("\\halign{1#2\\cr   \\omit a\\cr}")
    top = cmr10.lists[-1]
    node = top[0]
    row = node.rows[0]
    assert len(row.cells) == 1
    assert not hasattr(row.cells[0].list, "omit")
    assert len(row.cells[0].list) == 1


def test_halign_typesets_to_vbox(cmr10):
    cmr10.parse("\\halign{#&#\\cr a&bc\\cr}")
    node = cmr10.lists[-1][0]
    packed = []
    node.typeset(cmr10, packed)
    box = packed[0]
    assert box.node_type == nd.NODE_TYPE.VLIST
    assert box.typeset_context is node.typeset_context
    assert len(box.list) == 1
    assert box.list[0].node_type == nd.NODE_TYPE.HLIST


def test_halign_span_widths_follow_tex_formula(cmr10):
    cmr10.parse(
        "\\tabskip 0pt"
        "\\halign{#&#&#\\cr"
        "\\kern1pt&\\kern1pt&\\kern1pt\\cr"
        "\\kern1pt\\span\\kern1pt\\span\\kern4pt\\cr"
        "\\kern1pt\\span\\kern3pt\\cr}"
    )
    node = cmr10.lists[-1][0]
    packed = []
    node.typeset(cmr10, packed)
    box = packed[0]
    rows = [item for item in box.list if item.node_type == nd.NODE_TYPE.HLIST]
    assert box.width == 6
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
    node = cmr10.lists[-1][0]
    packed = []
    node.typeset(cmr10, packed)
    box = packed[0]
    rows = [item for item in box.list if item.node_type == nd.NODE_TYPE.HLIST]
    assert len(rows) == 2
    assert rows[0].width == 10
    assert rows[1].width == 10
    assert float(rows[1].list[1].width) == pytest.approx(4.6666667, abs=1e-4)


def test_valign_typesets_to_hbox(cmr10):
    cmr10.parse("\\setbox1=\\hbox{\\valign{#\\cr a\\cr b\\cr}}")
    outer = cmr10.state.box[1]
    outer.typeset(cmr10, [])
    assert outer.list[0].node_type == nd.NODE_TYPE.HLIST
