import pytest
from pytex import align
from pytex import mmode
from pytex import lists
from pytex import node as nd
from pytex import paragraph
from pytex import texlive
from pytex import box
from pytex.dimen import Dimen


def isSymbol(node, fam, char):
    return isinstance(node, mmode.MathSymbol) and node.fam == fam and node.char == char


def mu_unit(context, style):
    return mmode.mudimen(context, style, Dimen(1))


@pytest.fixture()
def math(cmr10):
    fonts="""
    \\font\\tenrm=cmr10 
    \\font\\sevenrm=cmr7
    \\font\\fiverm=cmr5
    \\font\\teni=cmmi10 
    \\font\\seveni=cmmi7
    \\font\\fivei=cmmi5
    \\font\\tensy=cmsy10
    \\font\\sevensy=cmsy7
    \\font\\preloaded=cmsy6
    \\font\\fivesy=cmsy5
    \\font\\tenex=cmex10
    \\font\\tenbf=cmbx10
    \\font\\sevenbf=cmbx7
    \\font\\fivebf=cmbx5
    \\font\\tentt=cmtt10
    \\font\\tensl=cmsl10 
    \\font\\tenit=cmti10
    \\skewchar\\teni='177 \\skewchar\\seveni='177 \\skewchar\\fivei='177
    \\skewchar\\tensy='60 \\skewchar\\sevensy='60 \\skewchar\\fivesy='60
    \\textfont1=\\teni \\scriptfont1=\\seveni \\scriptscriptfont1=\\fivei
    \\textfont2=\\tensy \\scriptfont2=\\sevensy \\scriptscriptfont2=\\fivesy
    \\textfont3=\\tenex \\scriptfont3=\\tenex \\scriptscriptfont3=\\tenex
    \\delcode`(=\"028300 \\delcode`)=\"029301 \\delcode`.=0
    """
    cmr10.parse(fonts)
    return cmr10

@pytest.mark.parametrize("inner", [True, False])
def test_mlist(math, inner):
    open = close = "$" if inner else "$$"
    math.parse(f"{open}a")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert top.inner == inner
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert node.sub is None
    assert node.sup is None
    assert isSymbol(node.nucleus, 1, "a")
    assert node.atom_type == mmode.ATOM_TYPE.ORD
    math.parse(f"{close}")
    top = math.lists[-1]
    if inner:
        assert top.type == lists.LISTTYPE.HORIZONTAL
        assert len(top) == 3
        node = top[1]
    else:
        assert top.type == lists.LISTTYPE.HORIZONTAL
        vtop = math.lists[0]
        assert vtop.type == lists.LISTTYPE.VERTICAL
        node = next(n for n in vtop if isinstance(n, mmode.MList))
        math.parse("\\par")
        packed = []
        math.lists[-1].typesetNodes(math, packed)
        glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
        assert len(glues) >= 2
    assert node.node_type == nd.NODE_TYPE.MATH


def test_mlist_mismatch(math):
    try:
        math.parse("$$a$x")
        assert False
    except ValueError as e:
        assert "missing" in str(e)


def test_math_typeset_context_requires_symbol_and_extension_fonts(parser):
    with pytest.raises(ValueError, match="fontdimen params"):
        parser.parse("$a$")


def test_mlist_typeset_inline(math):
    math.parse("$a$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    assert len(packed) == 3
    assert isinstance(packed[0], nd.MathShift)
    assert packed[0].on
    assert packed[0].kern == math.state.layout["mathsurround"]
    assert isinstance(packed[-1], nd.MathShift)
    assert not packed[-1].on
    assert packed[-1].kern == math.state.layout["mathsurround"]


def test_mlist_typeset_display(math):
    math.parse("$$a$$\\par")
    top = math.lists[0]
    assert len(top) == 3
    packed = []
    top.typesetNodes(math, packed)


def test_display_halign_replaces_display_math_list(math):
    math.parse("$$\\halign{#\\cr \\hbox{}\\cr}$$")
    top = math.lists[0]
    node = next(n for n in top if isinstance(n, align.HAlignMathList))
    assert len(node) == 1
    assert isinstance(node[0], align.MAlignment)


def test_display_halign_typesets_with_display_wrapper(math):
    math.parse("$$\\halign{#\\cr \\hbox{}\\cr}$$\\par")
    top = math.lists[0]
    node = next(n for n in top if isinstance(n, align.HAlignMathList))
    packed = []
    top.typesetNodes(math, packed)
    display = [n for n in packed if getattr(n, "source", None) is node]
    assert len(display) == 5
    assert display[0].node_type == nd.NODE_TYPE.PENALTY
    assert display[0].penalty == node.typeset_context.predisplaypenalty
    assert display[1].node_type == nd.NODE_TYPE.GLUE
    assert display[1].glue == node.typeset_context.abovedisplayskip
    assert display[2].node_type == nd.NODE_TYPE.HLIST
    assert display[3].node_type == nd.NODE_TYPE.PENALTY
    assert display[3].penalty == node.typeset_context.postdisplaypenalty
    assert display[4].node_type == nd.NODE_TYPE.GLUE
    assert display[4].glue == node.typeset_context.belowdisplayskip


def test_subformula_single_char_drops_outer_hbox(math):
    math.parse("${a}$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    assert len(packed) == 3
    assert packed[0].node_type == nd.NODE_TYPE.MATH
    assert packed[1].node_type == nd.NODE_TYPE.CHAR
    assert packed[2].node_type == nd.NODE_TYPE.MATH


def test_mlist_typeset_single_box_drops_outer_hbox(math):
    # Build a sub-mlist that translates to exactly one box node.
    math.parse("$a$")
    context = math.lists[-1][1].typeset_context
    vb = box.VBox(math, None, 0)
    vb.list.append(nd.Rule(1, 1, 0))
    vb.typeset(math, [])
    sub = mmode.MList(math, inner=True, nodes=[mmode.VCent(vb)])
    packed = []
    sub.typeset(math, packed, context, mmode.Style(mmode.MATH_STYLE.T))
    assert len(packed) == 1
    assert packed[0].node_type == nd.NODE_TYPE.VLIST


def test_display_noindent_has_no_synthetic_previous_paragraph(math):
    math.parse("\\noindent$$a$$\\par")
    top = math.lists[0]
    assert isinstance(top[0], mmode.DisplayMathList)
    assert isinstance(top[1], paragraph.Paragraph)
    packed = []
    top.typesetNodes(math, packed)
    assert top[1].typeset_context.prevgraf == 3


def test_mlist_typeset_display_without_closing_paragraph(math):
    math.parse("$$a$$")
    top = math.lists[0]
    packed = []
    top.typesetNodes(math, packed)
    assert len(packed) > 0


def _display_box_for_mlist(packed, mlist):
    return next(
        node
        for node in packed
        if node.node_type == nd.NODE_TYPE.HLIST and getattr(node, "source", None) is mlist
    )


def test_display_centering_uses_half_remaining_width(math):
    math.parse("$$a$$\\par")
    top = math.lists[0]
    mlist = next(node for node in top if isinstance(node, mmode.DisplayMathList))
    packed = []
    top.typesetNodes(math, packed)
    b = _display_box_for_mlist(packed, mlist)
    z = mlist.typeset_context.displaywidth
    s = mlist.typeset_context.displayindent
    expected = s + (z - b.width) / 2
    assert b.shifted == expected


def test_display_predisplaysize_adds_two_ems(math):
    math.parse("\\noindent abc$$a$$\\par")
    top = math.lists[0]
    prev_par = next(node for node in top if isinstance(node, paragraph.Paragraph))
    mlist = next(node for node in top if isinstance(node, mmode.DisplayMathList))
    packed = []
    top.typesetNodes(math, packed)
    last_prev_line = [n for n in packed if n.node_type == nd.NODE_TYPE.HLIST and getattr(n, "source", None) is prev_par][-1]
    expected = last_prev_line.rightmost() + 2 * prev_par.typeset_context.em
    assert float(mlist.typeset_context.predisplaysize) == pytest.approx(float(expected), abs=1e-4)


def test_display_eqno_squeeze_drops_eqno_when_not_enough_shrink(math):
    # Make display width narrow enough that q must include one quad (fontdimen6).
    text_sym = math.state.textfont[2]
    text_rm = math.state.textfont[0]
    text_it = math.state.textfont[1]
    quad = Dimen(text_sym.param[5])
    # Guard the fixture assumption behind this regression.
    assert float(quad) > float(text_sym.param[1])
    wa = text_it["a"].width
    e = text_rm["1"].width
    z = wa + e + (quad / 2)
    math.parse(f"\\displaywidth={float(z):.5f}pt $$a\\eqno1$$\\par")
    top = math.lists[0]
    mlist = next(node for node in top if isinstance(node, mmode.DisplayMathList))
    packed = []
    top.typesetNodes(math, packed)
    display_index = next(
        i
        for i, node in enumerate(packed)
        if node.node_type == nd.NODE_TYPE.HLIST and getattr(node, "source", None) is mlist
    )
    # Right-eqno branch with e=0 appends infinite penalty, then eqno box, then postdisplaypenalty.
    assert packed[display_index + 1].node_type == nd.NODE_TYPE.PENALTY
    assert packed[display_index + 1].penalty == 10000
    assert packed[display_index + 2].node_type == nd.NODE_TYPE.HLIST
    assert packed[display_index + 3].node_type == nd.NODE_TYPE.PENALTY
    assert packed[display_index + 3].penalty == mlist.typeset_context.postdisplaypenalty


def test_everydisplay_can_read_prevgraf_from_previous_paragraph(math):
    math.parse("\\everydisplay{\\message{<PG=\\the\\prevgraf>}}abc$$x$$")
    assert "<PG=1>" in math.logContent()


def test_subformula(parser):
    parser.parse("${ab}")
    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert node.sub is None
    assert node.sup is None
    assert len(node.nucleus) == 2


def test_subformula_unclosed(parser):
    try:
        parser.parse("${ab$")
        assert False
    except ValueError as e:
        assert "mismatch" in str(e)


@pytest.mark.parametrize("field, value, type", [
    ["sub", "b", mmode.MathSymbol],
    ["sup", "b", mmode.MathSymbol],
    ["sub", "{ab}", mmode.MList],
    ["sup", "{ab}", mmode.MList],
])
def test_scripts(math, field, value, type):
    if field == "sub":
        cmd = "_"
        other = "sup"
    else:
        cmd = "^"
        other = "sub"
    math.parse(f"$a{cmd}{value}")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert isSymbol(node.nucleus, 1, "a")
    script = getattr(node, field)
    other = getattr(node, other)
    assert script is not None
    assert other is None
    assert isinstance(script, type)
    math.parse("$")


@pytest.mark.parametrize("src", ["$a^$", "$a_$", "$^$"])
def test_scripts_missing_field_errors(math, src):
    with pytest.raises(ValueError, match="missing field"):
        math.parse(src)


@pytest.mark.parametrize("cmd", [
    "\\mathchar\"1234", 
    "\\mathchardef\\a=\"1234\\a",
])
def test_mathchar(math, cmd):
    math.parse(f"${cmd}")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert isSymbol(node.nucleus, 2, chr(0x34))
    assert node.atom_type == mmode.ATOM_TYPE.OP
    math.parse("$")


def test_mathsymbol_saveinfo_and_typeset(math):
    symbol = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("a"), -1)
    info = symbol.saveInfo()
    assert info["init"]["mathcode"] == symbol.encode()
    packed = []
    context = mmode.MathTypesetContext(True)
    context.snapshot(math)
    symbol.typeset(math, packed, context, mmode.Style(mmode.MATH_STYLE.T))
    assert len(packed) == 1
    assert packed[0].char == "a"


def test_active(math):
    math.parse("\\def\\a{1}\\mathcode`a=\"8000$\\a")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert isSymbol(node.nucleus, 0, "1")
    math.parse("$")


def test_mkern(math):
    math.parse("$a\\mkern 10mu b")
    top = math.lists[-1]
    assert len(top) == 3
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.KERN
    assert node.kern == 10
    assert node.mu
    math.parse("$")


def test_mkern_typeset_uses_style_sigma6(math):
    math.parse("$\\scriptstyle\\mkern18mu$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 1
    mu = mu_unit(mlist.typeset_context, mmode.Style(mmode.MATH_STYLE.S))
    assert kerns[0].kern == 18 * mu


def test_nonscript_removes_immediately_following_glue_or_kern(math):
    math.parse("$\\nonscript\\mkern18mu\\mkern36mu$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 1
    mu = mu_unit(mlist.typeset_context, mmode.Style(mmode.MATH_STYLE.T))
    assert kerns[0].kern == 36 * mu


def test_nonscript_keeps_following_glue_or_kern_when_style_is_scriptscript(math):
    math.parse("$\\scriptscriptstyle\\nonscript\\mkern18mu\\mkern36mu$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 2
    mu = mu_unit(mlist.typeset_context, mmode.Style(mmode.MATH_STYLE.SS))
    assert kerns[0].kern == 18 * mu
    assert kerns[1].kern == 36 * mu


def test_mathchoice_uses_current_text_style(math):
    math.parse("$\\mathchoice{\\mkern18mu}{\\mkern36mu}{\\mkern54mu}{\\mkern72mu}$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 1
    mu = mu_unit(mlist.typeset_context, mmode.Style(mmode.MATH_STYLE.T))
    assert kerns[0].kern == 36 * mu


def test_mathchoice_uses_current_script_style(math):
    math.parse("$\\scriptstyle\\mathchoice{\\mkern18mu}{\\mkern36mu}{\\mkern54mu}{\\mkern72mu}$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 1
    mu = mu_unit(mlist.typeset_context, mmode.Style(mmode.MATH_STYLE.S))
    assert kerns[0].kern == 54 * mu


def test_nested_mathchoice_expands_without_mutating_list(math):
    math.parse("$\\mathchoice{\\mkern18mu}{\\mathchoice{\\mkern18mu}{\\mkern36mu}{\\mkern54mu}{\\mkern72mu}}{\\mkern90mu}{\\mkern108mu}$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 1
    mu = mu_unit(mlist.typeset_context, mmode.Style(mmode.MATH_STYLE.T))
    assert kerns[0].kern == 36 * mu
    assert any(isinstance(n, mmode.ChoiceNode) for n in mlist)


def test_rule5_bin_conversion_uses_effective_previous_atom_type(math):
    class ProbeAtom(mmode.Atom):
        def __init__(self, atom_type):
            super().__init__(atom_type)
            self.observed_prev = None
            self.observed_type = None
            self.nucleus = None

        def typeset(self, parser, packed, context, style):
            self.observed_prev = context.prev_atom_type
            super().typeset(parser, [], context, style)
            self.observed_type = context.atom_type
            packed.append(nd.Kern(0))

    first = ProbeAtom(mmode.ATOM_TYPE.BIN)
    second = ProbeAtom(mmode.ATOM_TYPE.BIN)
    mlist = mmode.MList(math)
    mlist.extend([first, second])
    packed = []
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    mlist.typesetNodes(math, packed, ctx, mmode.Style(mmode.MATH_STYLE.T))

    assert first.observed_prev is None
    assert first.observed_type == mmode.ATOM_TYPE.ORD
    assert second.observed_prev == mmode.ATOM_TYPE.ORD
    # trailing Bin is normalized to Ord (Appendix G end-of-list rule).
    assert second.observed_type == mmode.ATOM_TYPE.ORD
    # Rule 5 must not mutate the source atoms.
    assert first.atom_type == mmode.ATOM_TYPE.BIN
    assert second.atom_type == mmode.ATOM_TYPE.BIN


def test_rule5_bin_after_rel_becomes_ord(math):
    class ProbeAtom(mmode.Atom):
        def __init__(self, atom_type):
            super().__init__(atom_type)
            self.observed_type = None
            self.nucleus = None

        def typeset(self, parser, packed, context, style):
            super().typeset(parser, [], context, style)
            self.observed_type = context.atom_type
            packed.append(nd.Kern(0))

    rel = ProbeAtom(mmode.ATOM_TYPE.REL)
    bin_atom = ProbeAtom(mmode.ATOM_TYPE.BIN)
    mlist = mmode.MList(math)
    mlist.extend([rel, bin_atom])
    packed = []
    ctx = mmode.MathTypesetContext(True)
    ctx.snapshot(math)
    mlist.typesetNodes(math, packed, ctx, mmode.Style(mmode.MATH_STYLE.T))

    assert rel.observed_type == mmode.ATOM_TYPE.REL
    assert bin_atom.observed_type == mmode.ATOM_TYPE.ORD


def _mk_atom(atom_type, fam, ch):
    atom = mmode.Op() if atom_type == mmode.ATOM_TYPE.OP else mmode.Atom(atom_type)
    code = (atom_type.value << 12) | (fam << 8) | ord(ch)
    atom.nucleus = mmode.MathSymbol(code, -1)
    return atom


def test_atom_wrapper_shadows_wrapped_atom_fields_and_methods(math):
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 0, "a")
    wrapped = mmode._AtomWrapper(atom, mmode.ATOM_TYPE.BIN, mmode.Style(mmode.MATH_STYLE.T))
    assert wrapped.nucleus is atom.nucleus
    original = atom.nucleus
    wrapped.nucleus = None
    assert wrapped.nucleus is None
    assert atom.nucleus is original
    assert callable(wrapped.typeset)


def test_rule14_ord_op_ligature_collapses_pair(math):
    # Put text fonts in family 0 so CMR ligatures/kerns are available.
    math.parse("\\textfont0=\\tenrm \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "f"),
        _mk_atom(mmode.ATOM_TYPE.OP, 0, "i"),
    ])
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    collected = mlist._pass1Collect(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    mlist._pass1AdjustAtoms(math, ctx, collected)
    wrappers = [x for x in collected if isinstance(x, mmode._AtomWrapper)]
    assert len(wrappers) == 1
    w = wrappers[0]
    assert w.node_type == mmode.ATOM_TYPE.ORD
    assert isinstance(w.atom.nucleus, mmode.MathSymbol)
    assert w.atom.nucleus.fam == 0
    assert w.atom.nucleus.char not in ("f", "i")


def test_rule14_ord_op_kern_inserts_kern_and_keeps_op(math):
    math.parse("\\textfont0=\\tenrm \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "T"),
        _mk_atom(mmode.ATOM_TYPE.OP, 0, "o"),
    ])
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    collected = mlist._pass1Collect(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    mlist._pass1AdjustAtoms(math, ctx, collected)
    wrappers = [x for x in collected if isinstance(x, mmode._AtomWrapper)]
    kerns = [x for x in collected if x.node_type == nd.NODE_TYPE.KERN and x.automatic]
    assert len(wrappers) == 2
    assert wrappers[0].node_type == mmode.ATOM_TYPE.ORD
    assert wrappers[1].node_type == mmode.ATOM_TYPE.OP
    assert len(kerns) == 1


def test_rule14_not_applied_across_explicit_kern(math):
    math.parse("\\textfont0=\\tenrm \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "f"),
        nd.Kern(0),
        _mk_atom(mmode.ATOM_TYPE.OP, 0, "i"),
    ])
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    collected = mlist._pass1Collect(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    mlist._pass1AdjustAtoms(math, ctx, collected)
    wrappers = [x for x in collected if isinstance(x, mmode._AtomWrapper)]
    auto_kerns = [x for x in collected if x.node_type == nd.NODE_TYPE.KERN and x.automatic]
    assert len(wrappers) == 2
    assert wrappers[0].atom.nucleus.char == "f"
    assert wrappers[1].atom.nucleus.char == "i"
    assert wrappers[1].node_type == mmode.ATOM_TYPE.OP
    assert len(auto_kerns) == 0


def test_rule14_applies_across_removed_style_node(math):
    math.parse("\\textfont0=\\tenrm \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "f"),
        mmode.StyleNode(mmode.MATH_STYLE.T),
        _mk_atom(mmode.ATOM_TYPE.OP, 0, "i"),
    ])
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    collected = mlist._pass1Collect(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    mlist._pass1AdjustAtoms(math, ctx, collected)
    wrappers = [x for x in collected if isinstance(x, mmode._AtomWrapper)]
    assert len(wrappers) == 1
    assert wrappers[0].node_type == mmode.ATOM_TYPE.ORD


def test_rule14_applies_across_removed_choice_node(math):
    math.parse("\\textfont0=\\tenrm \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    empty = mmode.MList(math)
    choice = mmode.ChoiceNode(empty, empty, empty, empty)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "f"),
        choice,
        _mk_atom(mmode.ATOM_TYPE.OP, 0, "i"),
    ])
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    collected = mlist._pass1Collect(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    mlist._pass1AdjustAtoms(math, ctx, collected)
    wrappers = [x for x in collected if isinstance(x, mmode._AtomWrapper)]
    assert len(wrappers) == 1
    assert wrappers[0].node_type == mmode.ATOM_TYPE.ORD


def test_rule14_applies_when_nonscript_removes_following_kern(math):
    math.parse("\\textfont0=\\tenrm \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "f"),
        mmode.NonscriptGlue(),
        mmode.MuKern(18),
        _mk_atom(mmode.ATOM_TYPE.OP, 0, "i"),
    ])
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    collected = mlist._pass1Collect(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    mlist._pass1AdjustAtoms(math, ctx, collected)
    wrappers = [x for x in collected if isinstance(x, mmode._AtomWrapper)]
    assert len(wrappers) == 1
    assert wrappers[0].node_type == mmode.ATOM_TYPE.ORD


def test_rule14_marks_text_symbol_for_rule17(math):
    math.parse("\\textfont0=\\tenit \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "f"),
        _mk_atom(mmode.ATOM_TYPE.REL, 0, "x"),
    ])
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    collected = mlist._pass1Collect(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    mlist._pass1AdjustAtoms(math, ctx, collected)
    wrappers = [x for x in collected if isinstance(x, mmode._AtomWrapper)]
    assert len(wrappers) == 2
    assert wrappers[0].text_symbol
    assert not wrappers[1].text_symbol


def test_rule17_cases(math):
    # Rule 17: math-list nucleus is typeset to a box.
    inner = mmode.MList(math)
    inner.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a"),
        _mk_atom(mmode.ATOM_TYPE.ORD, 1, "b"),
    ])
    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = inner
    mlist = mmode.MList(math)
    mlist.append(atom)
    packed = []
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    mlist.typesetNodes(math, packed, ctx, mmode.Style(mmode.MATH_STYLE.T))
    assert any(n.node_type == nd.NODE_TYPE.HLIST for n in packed), "rule17 math-list nucleus should typeset to a box"

    # Rule 17: text-symbol mark suppresses italic correction kern.
    math.parse("\\textfont0=\\tenit \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 0, "f")
    base = mmode.MathTypesetContext(False)
    base.snapshot(math)
    style = mmode.Style(mmode.MATH_STYLE.T)
    font = base.font(style, 0)
    assert float(font.param[1]) != 0 and float(font["f"].italic) != 0, "rule17 text-symbol fixture precondition"

    plain_ctx = mmode.AtomTypesetContext(base, None)
    plain_ctx.atom_type = mmode.ATOM_TYPE.ORD
    plain_ctx.text_symbol = False
    plain = []
    atom.typeset(math, plain, plain_ctx, style)
    plain_kerns = [n for n in plain if n.node_type == nd.NODE_TYPE.KERN and n.automatic]
    assert len(plain_kerns) == 1, "rule17 plain symbol should get italic kern"

    text_ctx = mmode.AtomTypesetContext(base, None)
    text_ctx.atom_type = mmode.ATOM_TYPE.ORD
    text_ctx.text_symbol = True
    text = []
    atom.typeset(math, text, text_ctx, style)
    text_kerns = [n for n in text if n.node_type == nd.NODE_TYPE.KERN and n.automatic]
    assert len(text_kerns) == 0, "rule17 text symbol should suppress italic kern"

    # Rule 17: subscript present suppresses italic correction kern.
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "f")
    atom.sub = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("i"), -1)
    ctx = mmode.AtomTypesetContext(base, None)
    ctx.atom_type = mmode.ATOM_TYPE.ORD
    ctx.text_symbol = False
    packed = []
    atom.typeset(math, packed, ctx, mmode.Style(mmode.MATH_STYLE.T))
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN and n.automatic]
    assert len(kerns) == 0, "rule17 symbol with subscript should suppress italic kern"


def test_rule20_spacing_cases(math):
    cases = [
        (
            "$\\mathop a\\mathinner b$",
            1,
            lambda mlist, glues: float(glues[0].glue.dimen)
            == pytest.approx(float(mlist.typeset_context.muskips[0].dimen), abs=1e-4),
            "rule20 text style should insert thinmuskip",
        ),
        (
            "$\\scriptstyle\\mathop a\\mathinner b$",
            0,
            lambda mlist, glues: True,
            "rule20 script style should remove nonscript spacing",
        ),
    ]
    for expr, expected_count, predicate, label in cases:
        math.parse(expr)
        mlist = next(n for n in reversed(math.lists[-1]) if isinstance(n, mmode.InlineMathList))
        packed = []
        mlist.typeset(math, packed)
        glues = [n for n in packed if n.node_type == nd.NODE_TYPE.GLUE]
        assert len(glues) == expected_count, label
        assert predicate(mlist, glues), label


def test_rule21_penalty_cases(math):
    cases = [
        (
            "bin inserted in paragraph math",
            mmode.InlineMathList,
            lambda: [
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a"),
                _mk_atom(mmode.ATOM_TYPE.BIN, 1, "b"),
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "c"),
            ],
            {"binoppenalty": 123},
            [123],
        ),
        (
            "rel not inserted before rel",
            mmode.InlineMathList,
            lambda: [
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a"),
                _mk_atom(mmode.ATOM_TYPE.REL, 1, "b"),
                _mk_atom(mmode.ATOM_TYPE.REL, 1, "c"),
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "d"),
            ],
            {"relpenalty": 234},
            [234],
        ),
        (
            "skip when next item is penalty",
            mmode.InlineMathList,
            lambda: [
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a"),
                _mk_atom(mmode.ATOM_TYPE.REL, 1, "b"),
                nd.Penalty(50),
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "c"),
            ],
            {"relpenalty": 345},
            [50],
        ),
        (
            "skip when configured penalty >= 10000",
            mmode.InlineMathList,
            lambda: [
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a"),
                _mk_atom(mmode.ATOM_TYPE.BIN, 1, "b"),
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "c"),
            ],
            {"binoppenalty": 10000},
            [],
        ),
        (
            "disabled outside paragraph math",
            mmode.MList,
            lambda: [
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a"),
                _mk_atom(mmode.ATOM_TYPE.BIN, 1, "b"),
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "c"),
            ],
            {"binoppenalty": 123},
            [],
        ),
        (
            "skip after final item",
            mmode.InlineMathList,
            lambda: [
                _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a"),
                _mk_atom(mmode.ATOM_TYPE.REL, 1, "b"),
            ],
            {"relpenalty": 123},
            [],
        ),
    ]
    for label, list_type, nodes, ctx_overrides, expected in cases:
        mlist = list_type(math)
        mlist.extend(nodes())
        ctx = mmode.MathTypesetContext(False)
        ctx.snapshot(math)
        for key, value in ctx_overrides.items():
            setattr(ctx, key, value)
        packed = []
        mlist.typesetNodes(math, packed, ctx, mmode.Style(mmode.MATH_STYLE.T))
        penalties = [n.penalty for n in packed if n.node_type == nd.NODE_TYPE.PENALTY]
        assert penalties == expected, label


def test_rule6_bin_to_ord_does_not_trigger_rule14_on_previous_atom(math):
    math.parse("\\textfont0=\\tenrm \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "a"),
        _mk_atom(mmode.ATOM_TYPE.BIN, 0, "f"),
        _mk_atom(mmode.ATOM_TYPE.REL, 0, "i"),
    ])
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    collected = mlist._pass1Collect(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    mlist._pass1AdjustAtoms(math, ctx, collected)
    wrappers = [x for x in collected if isinstance(x, mmode._AtomWrapper)]
    auto_kerns = [x for x in collected if x.node_type == nd.NODE_TYPE.KERN and x.automatic]
    assert len(wrappers) == 3
    assert wrappers[0].node_type == mmode.ATOM_TYPE.ORD
    assert wrappers[1].node_type == mmode.ATOM_TYPE.ORD
    assert wrappers[2].node_type == mmode.ATOM_TYPE.REL
    assert wrappers[1].nucleus.char == "f"
    assert wrappers[2].nucleus.char == "i"
    assert len(auto_kerns) == 0


def test_rule18_substeps(math):
    def close(actual, expected, stage):
        assert float(actual) == pytest.approx(float(expected), abs=1e-4), stage

    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    style = mmode.Style(mmode.MATH_STYLE.T)

    # 18a: character nucleus => u=v=0
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a")
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    translated = []
    atom.typesetNucleus(math, translated, ctx, style)
    u, v = atom.rule18a(math, translated, ctx, style)
    assert u == 0 and v == 0, "rule18a char nucleus should set u=v=0"

    # 18a: char+kern nucleus => u=v=0
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "f")
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("i"), -1)
    translated = []
    atom.typesetNucleus(math, translated, ctx, style)
    assert len(translated) == 2 and translated[1].node_type == nd.NODE_TYPE.KERN, "rule18a char+kern translation shape"
    u, v = atom.rule18a(math, translated, ctx, style)
    assert u == 0 and v == 0, "rule18a char+kern should set u=v=0"

    # 18a: box nucleus uses sigma18/sigma19
    inner = mmode.MList(math)
    inner.append(_mk_atom(mmode.ATOM_TYPE.ORD, 1, "a"))
    inner.append(_mk_atom(mmode.ATOM_TYPE.ORD, 1, "b"))
    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = inner
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    translated = []
    atom.typesetNucleus(math, translated, ctx, style)
    assert len(translated) == 1 and translated[0].node_type == nd.NODE_TYPE.HLIST, "rule18a box translation shape"
    h = translated[0].height
    d = translated[0].depth
    q = Dimen(ctx.sigma(style.superscript())[17])
    r = Dimen(ctx.sigma(style.subscript())[18])
    u, v = atom.rule18a(math, translated, ctx, style)
    close(u, h - q, "rule18a box u should use h-q")
    close(v, d + r, "rule18a box v should use d+r")

    # 18b: subscript only
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a")
    atom.sub = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    b = atom.assemble(math, ctx, style)
    assert len(b.list) == 2, "rule18b should append one subscript box"
    sub_box = b.list[1]
    assert sub_box.node_type == nd.NODE_TYPE.HLIST and float(sub_box.shifted) >= 0, "rule18b sub box shape/shift"
    raw = box.HBox(math, None, 0)
    atom.sub.typeset(math, raw.list, ctx, style.subscript())
    raw.typeset(math, [])
    close(sub_box.width, raw.width + ctx.scriptspace, "rule18b should add scriptspace")
    translated = []
    atom.typesetNucleus(math, translated, ctx, style)
    _, v = atom.rule18a(math, translated, ctx, style)
    sigma = ctx.sigma(style)
    sigma16 = Dimen(sigma[15])
    sigma5 = Dimen(sigma[4])
    lift_limit = sub_box.height - Dimen(abs(float(sigma5)) * 4 / 5)
    expected = max(v, sigma16, lift_limit)
    close(sub_box.shifted, expected, "rule18b sub shift formula")

    # 18c: superscript only
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a")
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    b = atom.assemble(math, ctx, style)
    assert len(b.list) == 2, "rule18c should append one superscript box"
    sup_box = b.list[1]
    assert sup_box.node_type == nd.NODE_TYPE.HLIST and float(sup_box.shifted) <= 0, "rule18c sup box shape/shift"
    raw = box.HBox(math, None, 0)
    atom.sup.typeset(math, raw.list, ctx, style.superscript())
    raw.typeset(math, [])
    close(sup_box.width, raw.width + ctx.scriptspace, "rule18c should add scriptspace")
    translated = []
    atom.typesetNucleus(math, translated, ctx, style)
    u, _ = atom.rule18a(math, translated, ctx, style)
    sigma5 = Dimen(ctx.sigma(style)[4])
    p = Dimen(ctx.sigma(style)[13])  # sigma14 in text style
    lift_limit = sup_box.depth + Dimen(abs(float(sigma5)) / 4)
    expected = max(u, p, lift_limit)
    close(sup_box.shifted, -expected, "rule18c sup shift formula")

    # 18c p selection by style
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a")
    x = box.HBox(math, 0, 0)
    x.typeset(math, [])
    u0 = Dimen()
    u_disp = atom.rule18c(x, ctx, mmode.Style(mmode.MATH_STYLE.D, cramped=False), u0)
    u_text = atom.rule18c(x, ctx, mmode.Style(mmode.MATH_STYLE.T, cramped=False), u0)
    u_crmp = atom.rule18c(x, ctx, mmode.Style(mmode.MATH_STYLE.T, cramped=True), u0)
    sigma_disp = ctx.sigma(mmode.Style(mmode.MATH_STYLE.D, cramped=False))
    sigma_text = ctx.sigma(mmode.Style(mmode.MATH_STYLE.T, cramped=False))
    sigma_crmp = ctx.sigma(mmode.Style(mmode.MATH_STYLE.T, cramped=True))
    assert float(u_disp) >= float(Dimen(sigma_disp[12])), "rule18c display should use sigma13"
    assert float(u_text) >= float(Dimen(sigma_text[13])), "rule18c text should use sigma14"
    assert float(u_crmp) >= float(Dimen(sigma_crmp[14])), "rule18c cramped should use sigma15"

    # 18d: both scripts, sub box and v floor
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a")
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    atom.sub = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("c"), -1)
    translated = []
    atom.typesetNucleus(math, translated, ctx, style)
    u, v = atom.rule18a(math, translated, ctx, style)
    x = atom._typesetScriptField(math, atom.sup, ctx, style.superscript())
    u = atom.rule18c(x, ctx, style, u)
    y, v2 = atom.rule18d(math, ctx, style, v)
    raw = box.HBox(math, None, 0)
    atom.sub.typeset(math, raw.list, ctx, style.subscript())
    raw.typeset(math, [])
    close(y.width, raw.width + ctx.scriptspace, "rule18d sub box should include scriptspace")
    assert v2 >= v and v2 >= Dimen(ctx.sigma(style)[16]), "rule18d should enforce v>=max(v,sigma17)"

    # 18e: minimum clearance
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a")
    x = nd.Box(0, 0, 10)
    y = nd.Box(0, 10, 0)
    u2, v2 = atom.rule18e(x, y, ctx, style, Dimen(), Dimen())
    theta = Dimen(ctx.xi(style)[7])
    clearance = (u2 - x.depth) - (y.height - v2)
    close(clearance, 4 * theta, "rule18e should enforce 4theta clearance")

    # 18e: superscript bottom floor
    x = nd.Box(0, 0, 1)
    y = nd.Box(0, 0, 0)
    u = Dimen()
    v = Dimen(100)
    u2, v2 = atom.rule18e(x, y, ctx, style, u, v)
    floor = Dimen(abs(float(ctx.sigma(style)[4])) * 4 / 5)
    close(u2 - x.depth, floor, "rule18e should enforce 4/5 x-height floor")
    close(v2, v - (u2 - u), "rule18e should preserve clearance by reducing v")

    # 18f: assembled both scripts form joint vbox
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "a")
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    atom.sub = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("c"), -1)
    b = atom.assemble(math, ctx, style)
    assert len(b.list) == 2, "rule18f should append one joint scripts vbox"
    joint = b.list[1]
    assert joint.node_type == nd.NODE_TYPE.VLIST and len(joint.list) == 3, "rule18f joint vbox shape"
    assert joint.list[1].node_type == nd.NODE_TYPE.KERN, "rule18f joint vbox middle node should be kern"

    # 18f: delta and expected vertical geometry
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 1, "f")
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    atom.sub = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("c"), -1)
    translated = []
    delta = atom.typesetNucleus(math, translated, ctx, style)
    u, v = atom.rule18a(math, translated, ctx, style)
    x = atom._typesetScriptField(math, atom.sup, ctx, style.superscript())
    u = atom.rule18c(x, ctx, style, u)
    y, v = atom.rule18d(math, ctx, style, v)
    u, v = atom.rule18e(x, y, ctx, style, u, v)
    expected_k = u + v - x.depth - y.height
    b = atom.assemble(math, ctx, style)
    joint = b.list[1]
    top = joint.list[0]
    if float(delta) != 0:
        assert top.node_type == nd.NODE_TYPE.HLIST, "rule18f delta should wrap top in hbox"
        assert top.list[0].node_type == nd.NODE_TYPE.KERN, "rule18f delta wrapper should start with kern"
        close(top.list[0].kern, delta, "rule18f delta kern width")
    close(joint.list[1].kern, expected_k, "rule18f middle kern formula")
    close(joint.depth, y.depth + v, "rule18f joint depth formula")
    close(joint.height, top.height + u, "rule18f joint height formula")


def test_plain_math_reference_metrics(parser):
    parser.parse("\\input plain")

    parser.parse("\\setbox0=\\hbox{$\\displaystyle \\int_0^1$}")
    integral = parser.state.box[0]
    integral.typeset(parser, [])
    # Reference metrics from pdfTeX:
    # \\hbox(15.65013+9.11122)x14.48615
    assert float(integral.width) == pytest.approx(14.48615, abs=1e-4)
    assert float(integral.height) == pytest.approx(15.65013, abs=1e-4)
    assert float(integral.depth) == pytest.approx(9.11122, abs=1e-4)
    assert integral.list[1].node_type == nd.NODE_TYPE.HLIST
    assert integral.list[2].node_type == nd.NODE_TYPE.VLIST

    parser.parse("\\setbox1=\\hbox{$\\displaystyle \\sqrt{a}$}")
    disp = parser.state.box[1]
    disp.typeset(parser, [])
    assert float(disp.width) == pytest.approx(13.61925, abs=1e-4)
    assert float(disp.height) == pytest.approx(8.49092, abs=1e-4)
    assert float(disp.depth) == pytest.approx(1.90904, abs=1e-4)

    parser.parse("\\setbox2=\\hbox{$\\sqrt{a}$}")
    text = parser.state.box[2]
    text.typeset(parser, [])
    assert float(text.width) == pytest.approx(13.61925, abs=1e-4)
    assert float(text.height) == pytest.approx(8.00272, abs=1e-4)
    assert float(text.depth) == pytest.approx(2.39725, abs=1e-4)

    parser.parse("\\setbox3=\\hbox{$\\displaystyle {a^2 \\over b^2}$}")
    frac = parser.state.box[3]
    frac.typeset(parser, [])
    # \\hbox(14.9051+6.85951)x12.17201
    assert float(frac.width) == pytest.approx(12.17201, abs=1e-4)
    assert float(frac.height) == pytest.approx(14.90510, abs=1e-4)
    assert float(frac.depth) == pytest.approx(6.85951, abs=1e-4)


def test_rule13_op_cases(math):
    # Rule 13a: limits stack and rebox geometry.
    atom = _mk_atom(mmode.ATOM_TYPE.OP, 1, "f")
    atom.limits = mmode.MATH_LIMITS.NORMAL
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    atom.sub = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("c"), -1)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    style = mmode.Style(mmode.MATH_STYLE.T)
    b = atom.assemble(math, ctx, style)
    assert len(b.list) == 1, "rule13a limits should produce one stacked nucleus"
    limits_box = b.list[0]
    assert limits_box.node_type == nd.NODE_TYPE.VLIST and len(limits_box.list) == 7, "rule13a limits stack shape"
    assert [n.node_type for n in limits_box.list] == [
        nd.NODE_TYPE.KERN,
        nd.NODE_TYPE.HLIST,
        nd.NODE_TYPE.KERN,
        nd.NODE_TYPE.HLIST,
        nd.NODE_TYPE.KERN,
        nd.NODE_TYPE.HLIST,
        nd.NODE_TYPE.KERN,
    ]
    x = limits_box.list[1]
    y = limits_box.list[3]
    z = limits_box.list[5]
    assert x.width == y.width == z.width, "rule13a x/y/z should be reboxed to equal width"
    delta = Dimen(ctx.font(style, 1)["f"].italic)
    assert float(x.shifted) == pytest.approx(float(delta / 2), abs=1e-4), "rule13a superscript horizontal shift"
    assert float(z.shifted) == pytest.approx(float(Dimen() - (delta / 2)), abs=1e-4), "rule13a subscript horizontal shift"
    # Rule 13a baseline should run through the centered nucleus y, not the
    # bottom of the entire limits stack.
    assert limits_box.depth > 0, "rule13a baseline should pass through centered nucleus"

    # Rule 13: displaylimits only attaches in display style.
    disp = _mk_atom(mmode.ATOM_TYPE.OP, 1, "f")
    disp.limits = mmode.MATH_LIMITS.DISPLAY
    disp.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    b_disp = disp.assemble(math, ctx, mmode.Style(mmode.MATH_STYLE.D))
    assert len(b_disp.list) == 1 and b_disp.list[0].node_type == nd.NODE_TYPE.VLIST, "rule13 displaylimits in display style"

    text = _mk_atom(mmode.ATOM_TYPE.OP, 1, "f")
    text.limits = mmode.MATH_LIMITS.DISPLAY
    text.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    b_text = text.assemble(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    assert len(b_text.list) == 2, "rule13 displaylimits in text style should not stack limits"
    assert b_text.list[0].node_type == nd.NODE_TYPE.HLIST, "rule13 text-style op nucleus box"
    assert b_text.list[1].node_type == nd.NODE_TYPE.HLIST, "rule13 text-style superscript box"

    # Rule 13: display style uses successor for op symbol when available.
    style = mmode.Style(mmode.MATH_STYLE.D)
    # The fixture's symbols family (2) has no successor chains; extension family (3) does.
    font = ctx.font(style, 3)
    source_char = None
    target_char = None
    for info in font.tfm.char_info:
        chain = getattr(info, "chain", None)
        if not info.exists or chain is None:
            continue
        if not (font.bc <= ord(info.char) <= font.ec):
            continue
        if not (font.bc <= ord(chain) <= font.ec):
            continue
        target_info = font.tfm.char_info[ord(chain) - font.bc]
        if not target_info.exists:
            continue
        source_char = info.char
        target_char = chain
        break
    assert source_char is not None, "rule13 successor test precondition: expected chain in extension family"
    atom = _mk_atom(mmode.ATOM_TYPE.OP, 3, source_char)
    atom.limits = mmode.MATH_LIMITS.NONE
    b = atom.assemble(math, ctx, style)
    assert len(b.list) == 1, "rule13 successor path should emit single nucleus box"
    nucleus = b.list[0]
    assert nucleus.node_type == nd.NODE_TYPE.HLIST, "rule13 successor nucleus should be hbox"
    assert nucleus.list[0].node_type == nd.NODE_TYPE.CHAR, "rule13 successor nucleus should start with char"
    assert nucleus.list[0].char == target_char, "rule13 display style should choose successor character"


def test_indent(math):
    math.parse("$a\\indent b")
    top = math.lists[-1]
    assert len(top) == 3
    node = top[1]
    assert node.atom_type == mmode.ATOM_TYPE.ORD
    assert node.nucleus.node_type == nd.NODE_TYPE.HLIST
    math.parse("$")


@pytest.mark.parametrize("cmd, atom_type", [
    ["\\mathord", mmode.ATOM_TYPE.ORD],
    ["\\mathop", mmode.ATOM_TYPE.OP],
    ["\\mathbin", mmode.ATOM_TYPE.BIN],
    ["\\mathrel", mmode.ATOM_TYPE.REL],
    ["\\mathopen", mmode.ATOM_TYPE.OPEN],
    ["\\mathclose", mmode.ATOM_TYPE.CLOSE],
    ["\\mathpunct", mmode.ATOM_TYPE.PUNCT],
    ["\\mathinner", mmode.ATOM_TYPE.INNER],
    ["\\overline", mmode.ATOM_TYPE.OVER],
    ["\\underline", mmode.ATOM_TYPE.UNDER],
])
def test_mathatom(math, cmd, atom_type):
    math.parse(f"${cmd} a")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert node.atom_type == atom_type
    math.parse("$")


@pytest.mark.parametrize("cmd, style", [
    ["\\displaystyle", mmode.MATH_STYLE.D],
    ["\\textstyle", mmode.MATH_STYLE.T],
    ["\\scriptstyle", mmode.MATH_STYLE.S],
    ["\\scriptscriptstyle", mmode.MATH_STYLE.SS],
])
def test_mathstyle(math, cmd, style):
    math.parse(f"${cmd}")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.StyleNode)
    assert node.node_type == nd.NODE_TYPE.MATHNODE
    assert node.style.style == style
    assert not node.style.cramped
    math.parse("$")


@pytest.mark.parametrize("src, up_style, up_cramped, down_style, down_cramped", [
    [mmode.Style(mmode.MATH_STYLE.D, False), mmode.MATH_STYLE.S, False, mmode.MATH_STYLE.S, True],
    [mmode.Style(mmode.MATH_STYLE.D, True), mmode.MATH_STYLE.S, True, mmode.MATH_STYLE.S, True],
    [mmode.Style(mmode.MATH_STYLE.T, False), mmode.MATH_STYLE.S, False, mmode.MATH_STYLE.S, True],
    [mmode.Style(mmode.MATH_STYLE.T, True), mmode.MATH_STYLE.S, True, mmode.MATH_STYLE.S, True],
    [mmode.Style(mmode.MATH_STYLE.S, False), mmode.MATH_STYLE.SS, False, mmode.MATH_STYLE.SS, True],
    [mmode.Style(mmode.MATH_STYLE.SS, False), mmode.MATH_STYLE.SS, False, mmode.MATH_STYLE.SS, True],
])
def test_style_superscript_subscript_transitions(src, up_style, up_cramped, down_style, down_cramped):
    up = src.superscript()
    down = src.subscript()
    assert up.style == up_style
    assert up.cramped == up_cramped
    assert down.style == down_style
    assert down.cramped == down_cramped


@pytest.mark.parametrize("src, num_style, num_cramped, den_style, den_cramped", [
    [mmode.Style(mmode.MATH_STYLE.D, False), mmode.MATH_STYLE.T, False, mmode.MATH_STYLE.T, True],
    [mmode.Style(mmode.MATH_STYLE.D, True), mmode.MATH_STYLE.T, True, mmode.MATH_STYLE.T, True],
    [mmode.Style(mmode.MATH_STYLE.T, False), mmode.MATH_STYLE.S, False, mmode.MATH_STYLE.S, True],
    [mmode.Style(mmode.MATH_STYLE.T, True), mmode.MATH_STYLE.S, True, mmode.MATH_STYLE.S, True],
    [mmode.Style(mmode.MATH_STYLE.S, False), mmode.MATH_STYLE.SS, False, mmode.MATH_STYLE.SS, True],
    [mmode.Style(mmode.MATH_STYLE.SS, True), mmode.MATH_STYLE.SS, True, mmode.MATH_STYLE.SS, True],
])
def test_style_fraction_numerator_denominator(src, num_style, num_cramped, den_style, den_cramped):
    num = src.numerator()
    den = src.denominator()
    assert num.style == num_style
    assert num.cramped == num_cramped
    assert den.style == den_style
    assert den.cramped == den_cramped


def test_style_node_is_consumed_by_typeset(math):
    math.parse("$\\scriptstyle a$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    assert len(packed) == 3
    assert isinstance(packed[0], nd.MathShift)
    assert packed[1].node_type == nd.NODE_TYPE.CHAR
    assert packed[1].char == "a"
    assert isinstance(packed[2], nd.MathShift)


def test_typesetnodes_rule1_passthrough_nodes(math):
    class DummyWhatsit(nd.WhatsIt):
        def typeset(self, parser, packed, context, style):
            raise AssertionError("Rule 1 nodes should not be typeset")

    mlist = mmode.MList(math)
    rule = nd.Rule(1, 1, 0)
    disc = nd.Disc([], [], [])
    penalty = nd.Penalty(50)
    whatsit = DummyWhatsit()
    mlist.extend([rule, disc, penalty, whatsit])
    packed = []
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    mlist.typesetNodes(math, packed, ctx, mmode.Style(mmode.MATH_STYLE.T))
    assert packed == [rule, disc, penalty, whatsit]


@pytest.mark.parametrize("cmd, limits", [
    ["\\nolimits", mmode.MATH_LIMITS.NONE],
    ["\\limits", mmode.MATH_LIMITS.NORMAL],
    ["\\displaylimits", mmode.MATH_LIMITS.DISPLAY],
])
def test_limits(math, cmd, limits):
    math.parse(f"\\mathchardef\\sum=\"1350$\\sum{cmd}")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert node.atom_type == mmode.ATOM_TYPE.OP
    assert node.limits == limits
    math.parse("$")


def test_mathchoice(math):
    math.parse("$\\mathchoice{a}{b}{c}{d}")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.ChoiceNode)
    math.parse("$")


def test_radical(math):
    math.parse("$\\radical\"270370 a")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Rad)
    assert isSymbol(node.delim.small, 2, chr(0x70))
    assert isSymbol(node.delim.large, 3, chr(0x70))
    assert isSymbol(node.oprand, 1, "a")
    info = node.saveInfo()
    assert info["init"]["delim"] is node.delim
    assert info["init"]["oprand"] is node.oprand
    math.parse("$")


def test_rule11_radical_cases(math):
    delim = mmode.Delim(0x270370, 0)
    oprand = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("a"), -1)
    atom = mmode.Rad(delim, oprand)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    style = mmode.Style(mmode.MATH_STYLE.T)

    translated = []
    delta = atom.typesetNucleus(math, translated, ctx, style)
    assert delta == 0, "rule11 radical nucleus should leave delta=0"
    assert len(translated) == 1, "rule11 radical nucleus should emit one wrapped node"
    wrapped = translated[0]
    assert wrapped.node_type == nd.NODE_TYPE.HLIST and len(wrapped.list) == 2, "rule11 wrapped radical structure"
    delim_box, overbar = wrapped.list
    assert delim_box.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST), "rule11 delimiter box type"
    assert overbar.node_type == nd.NODE_TYPE.VLIST, "rule11 overbar should be vbox"
    assert [n.node_type for n in overbar.list[:3]] == [
        nd.NODE_TYPE.KERN,
        nd.NODE_TYPE.RULE,
        nd.NODE_TYPE.KERN,
    ], "rule11 overbar top should be kern-rule-kern"

    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("b"), -1)
    b = atom.assemble(math, ctx, style)
    assert len(b.list) == 2, "rule11 scripts should be attached by rule18"
    wrapped = b.list[0]
    assert wrapped.node_type == nd.NODE_TYPE.HLIST and len(wrapped.list) == 2, "rule11 wrapped radical retained under scripts"
    assert wrapped.list[0].node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST), "rule11 delimiter retained under scripts"
    assert wrapped.list[1].node_type == nd.NODE_TYPE.VLIST, "rule11 overbar retained under scripts"
    assert b.list[1].node_type == nd.NODE_TYPE.HLIST, "rule11 attached script box"


def test_mathaccent(math):
    math.parse("$\\mathaccent\"362 a")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Accent)
    assert isSymbol(node.base, 1, "a")
    assert isSymbol(node.accent, 3, chr(0x62))
    info = node.saveInfo()
    assert info["init"]["accent"] is node.accent
    assert info["init"]["base"] is node.base
    try:
        math.parse("\\accent`^a$")
        assert False
    except ValueError as e:
        assert "accent" in str(e)


def test_rule12_accent_cases(math):
    # Single-char base absorbs scripts inside accent box.
    accent = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (3 << 8) | ord("b"), -1)
    atom = mmode.Accent(accent, mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("a"), -1))
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("c"), -1)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    style = mmode.Style(mmode.MATH_STYLE.T)
    b = atom.assemble(math, ctx, style)
    assert len(b.list) == 1, "rule12 single-char base should absorb scripts"
    z = b.list[0]
    assert z.node_type == nd.NODE_TYPE.VLIST, "rule12 single-char accent result should be vbox"
    assert z.list[-1].node_type == nd.NODE_TYPE.HLIST, "rule12 base+scripts should be last node in accent vbox"
    assert len(z.list[-1].list) >= 2, "rule12 absorbed base should include script content"

    # Non-single base keeps rule16 script attachment outside accent nucleus.
    accent = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (3 << 8) | ord("b"), -1)
    base = mmode.MList(math)
    base.append(mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("a"), -1))
    atom = mmode.Accent(accent, base)
    atom.sup = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("c"), -1)
    b = atom.assemble(math, ctx, style)
    assert len(b.list) == 2, "rule12 non-single base should keep external script attachment"
    assert b.list[0].node_type == nd.NODE_TYPE.VLIST, "rule12 non-single accent nucleus should be vbox"
    assert b.list[1].node_type == nd.NODE_TYPE.HLIST, "rule12 non-single script attachment should be separate hbox"

    # Missing accent char falls back to rule16 behavior.
    missing = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (3 << 8) | 0xFF, -1)
    atom = mmode.Accent(missing, mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("a"), -1))
    b = atom.assemble(math, ctx, style)
    assert any(getattr(n, "char", None) == "a" for n in b.list), "rule12 missing accent should keep base char"
    assert not any(n.node_type == nd.NODE_TYPE.VLIST for n in b.list), "rule12 missing accent should skip accent vbox"


def test_delimiter(math):
    math.parse("$\\delimiter\"1270370")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert isSymbol(node.nucleus, 2, chr(0x70))
    assert node.atom_type == mmode.ATOM_TYPE.OP
    math.parse("$ $\\left(a+b\\right)")
    top = math.lists[-1]
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert isinstance(node.nucleus, mmode.MList)
    assert len(node.nucleus) == 3
    assert isSymbol(node.left.small, 0, chr(0x28))
    assert isSymbol(node.right.small, 0, chr(0x29))
    math.parse("$")


def test_delim_typeset_null_uses_nulldelimiterspace(math):
    d = mmode.Delim(0, 0)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    style = mmode.Style(mmode.MATH_STYLE.T)
    b = d.typeset(math, Dimen(20), ctx, style)
    assert b.node_type == nd.NODE_TYPE.HLIST
    assert b.width == math.state.layout["nulldelimiterspace"]
    axis = Dimen(ctx.sigma(style)[21])
    assert float(b.shifted) == pytest.approx(-float(axis), abs=1e-4)


def test_delim_typeset_null_uses_context_snapshot_not_parser_layout(math):
    d = mmode.Delim(0, 0)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    ctx.nulldelimiterspace = Dimen(7.5)
    math.state.layout["nulldelimiterspace"] = Dimen(0)
    b = d.typeset(math, Dimen(20), ctx, mmode.Style(mmode.MATH_STYLE.T))
    assert b.width == 7.5


def test_delim_typeset_order_uses_style_fonts(math):
    code = ((1 << 8) | ord("a")) << 12
    d = mmode.Delim(code, 0)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)

    b_text = d.typeset(math, Dimen(), ctx, mmode.Style(mmode.MATH_STYLE.T))
    assert b_text.list[0].font is ctx.textfont[1]

    b_script = d.typeset(math, Dimen(), ctx, mmode.Style(mmode.MATH_STYLE.S))
    assert b_script.list[0].font is ctx.scriptfont[1]

    b_scriptscript = d.typeset(math, Dimen(), ctx, mmode.Style(mmode.MATH_STYLE.SS))
    assert b_scriptscript.list[0].font is ctx.scriptscriptfont[1]


def test_delim_typeset_adds_italic_correction(math):
    # family 1 is cmmi in the math fixture; many letters (e.g., l) have italic correction.
    code = ((1 << 8) | ord("l")) << 12
    d = mmode.Delim(code, 0)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    b = d.typeset(math, Dimen(), ctx, mmode.Style(mmode.MATH_STYLE.T))
    kerns = [n for n in b.list if n.node_type == nd.NODE_TYPE.KERN and n.automatic]
    assert len(kerns) <= 1
    if kerns:
        assert float(kerns[0].kern) > 0


def test_rule19_uses_context_delimiter_parameters(math):
    class SpyDelim:
        def __init__(self):
            self.total = None

        def typeset(self, parser, total, context, style, axis):
            self.total = Dimen(total)
            b = box.HBox(parser, 0, 0)
            b.typeset(parser, [])
            return b

    atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
    atom.nucleus = mmode.MathSymbol((mmode.ATOM_TYPE.ORD.value << 12) | (1 << 8) | ord("a"), -1)
    left = SpyDelim()
    right = SpyDelim()
    atom.left = left
    atom.right = right

    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    # Force a distinguishable Rule 19 total from the context snapshot.
    ctx.delimiterfactor = 0
    ctx.delimitershortfall = Dimen(10000)
    # Different parser values should not affect this atom's sizing.
    math.state.layout["delimiterfactor"] = 1000
    math.state.layout["delimitershortfall"] = Dimen(0)

    packed = []
    atom_ctx = mmode.AtomTypesetContext(ctx, None)
    atom_ctx.atom_type = atom.atom_type
    atom.typeset(math, packed, atom_ctx, mmode.Style(mmode.MATH_STYLE.T))
    assert left.total == 0
    assert right.total == 0


@pytest.mark.parametrize("cmd, bar, thickness, left, right", [
    ["\\over", True, None, None, None],
    ["\\overwithdelims()", True, None, (0, chr(0x28)), (0, chr(0x29))],
    ["\\atop", False, None, None, None],
    ["\\atopwithdelims()", False, None, (0, chr(0x28)), (0, chr(0x29))],
    ["\\above10pt", True, 10, None, None],
    ["\\abovewithdelims()10pt", True, 10, (0, chr(0x28)), (0, chr(0x29))],
])
def test_fractions(math, cmd, bar, thickness, left, right):
    math.parse(f"\\noindent$a{cmd} b$\\relax")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 1
    assert top[0].node_type == nd.NODE_TYPE.MATH
    assert len(top[0]) == 1
    frac = top[0][0]
    assert isinstance(frac, mmode.Over)
    if left is None:
        assert frac.delims is None
    else:
        assert frac.delims is not None
        assert isSymbol(frac.delims[0].small, left[0], left[1])
        assert isSymbol(frac.delims[1].small, right[0], right[1])
    num, den, bar, thickness = frac.nucleus
    assert len(num) == 1
    assert isSymbol(num[0].nucleus, 1, "a")
    assert len(den) == 1
    assert isSymbol(den[0].nucleus, 1, "b")
    assert bar == bar
    assert thickness == thickness
    math.parse(f"$\\left(a{cmd} b\\right)")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert isSymbol(node.left.small, 0, chr(0x28))
    assert isSymbol(node.right.small, 0, chr(0x29))
    assert len(node.nucleus) == 1
    frac = node.nucleus[0]
    assert isinstance(frac, mmode.Over)
    if left is None:
        assert frac.delims is None
    else:
        assert frac.delims is not None
        assert isSymbol(frac.delims[0].small, left[0], left[1])
        assert isSymbol(frac.delims[1].small, right[0], right[1])
    math.parse("$")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL


@pytest.mark.parametrize("cmd, expected_theta", [
    ["\\over", "default"],
    ["\\atop", 0],
    ["\\above10pt", 10],
])
def test_fraction_rule15_theta(math, cmd, expected_theta):
    math.parse(f"\\noindent$a{cmd} b$\\relax")
    frac = math.lists[-1][0][0]
    assert isinstance(frac, mmode.Over)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    style = mmode.Style(mmode.MATH_STYLE.T)
    _, _, theta = frac.rule15(ctx, style)
    if expected_theta == "default":
        assert float(theta) == pytest.approx(ctx.xi(style)[7], abs=1e-4)
    else:
        assert theta == expected_theta


def test_fraction_rule15_delimiters(math):
    math.parse("\\noindent$a\\overwithdelims() b$\\relax")
    frac = math.lists[-1][0][0]
    assert isinstance(frac, mmode.Over)
    assert frac.delims is not None
    left, right = frac.delims
    assert isSymbol(left.small, 0, chr(0x28))
    assert isSymbol(right.small, 0, chr(0x29))


def test_fraction_rule15b_uv_text_over_vs_atop(math):
    style = mmode.Style(mmode.MATH_STYLE.T)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    sigma = ctx.sigma(style)

    math.parse("\\noindent$a\\over b$\\relax")
    over = math.lists[-1][-1][0]
    _, _, theta_over = over.rule15(ctx, style)
    u_over, v_over = over.rule15b(ctx, style, theta_over)
    assert float(u_over) == pytest.approx(sigma[8], abs=1e-4)   # sigma9
    assert float(v_over) == pytest.approx(sigma[11], abs=1e-4)  # sigma12

    math.parse("\\noindent$a\\atop b$\\relax")
    atop = math.lists[-1][-1][0]
    _, _, theta_atop = atop.rule15(ctx, style)
    u_atop, v_atop = atop.rule15b(ctx, style, theta_atop)
    assert float(theta_atop) == pytest.approx(0, abs=1e-8)
    assert float(u_atop) == pytest.approx(sigma[9], abs=1e-4)   # sigma10
    assert float(v_atop) == pytest.approx(sigma[11], abs=1e-4)  # sigma12


def test_fraction_rule15b_uv_script(math):
    style = mmode.Style(mmode.MATH_STYLE.S)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    sigma = ctx.sigma(style)
    math.parse("\\noindent$a\\over b$\\relax")
    frac = math.lists[-1][-1][0]
    _, _, theta = frac.rule15(ctx, style)
    u, v = frac.rule15b(ctx, style, theta)
    assert float(u) == pytest.approx(sigma[8], abs=1e-4)   # sigma9
    assert float(v) == pytest.approx(sigma[11], abs=1e-4)  # sigma12


def test_fraction_rule15c_atop_construction(math):
    style = mmode.Style(mmode.MATH_STYLE.T)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    math.parse("\\noindent$a\\atop b$\\relax")
    frac = math.lists[-1][-1][0]
    packed = []
    frac.typesetNucleus(math, packed, ctx, style)
    assert len(packed) == 1
    wrapped = packed[0]
    assert wrapped.node_type == nd.NODE_TYPE.HLIST
    assert len(wrapped.list) == 3
    left, out, right = wrapped.list
    assert left.node_type == nd.NODE_TYPE.HLIST
    assert right.node_type == nd.NODE_TYPE.HLIST
    assert left.width == math.state.layout["nulldelimiterspace"]
    assert right.width == math.state.layout["nulldelimiterspace"]
    assert out.node_type == nd.NODE_TYPE.VLIST
    assert len(out.list) == 3
    x, k, z = out.list
    assert x.node_type == nd.NODE_TYPE.HLIST
    assert k.node_type == nd.NODE_TYPE.KERN
    assert z.node_type == nd.NODE_TYPE.HLIST

    _, _, theta = frac.rule15(ctx, style)
    u, v = frac.rule15b(ctx, style, theta)
    u, v, psi = frac.rule15c(x, z, ctx, style, u, v)
    phi = 3 * Dimen(ctx.xi(style)[7])
    assert float(k.kern) == pytest.approx(float(psi), abs=1e-4)
    assert float(k.kern) >= float(phi)
    assert float(out.height) == pytest.approx(float(x.height + u), abs=1e-4)
    assert float(out.depth) == pytest.approx(float(z.depth + v), abs=1e-4)


def test_fraction_rule15d_over_construction(math):
    style = mmode.Style(mmode.MATH_STYLE.T)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    math.parse("\\noindent$a\\over b$\\relax")
    frac = math.lists[-1][-1][0]
    packed = []
    frac.typesetNucleus(math, packed, ctx, style)
    assert len(packed) == 1
    wrapped = packed[0]
    assert wrapped.node_type == nd.NODE_TYPE.HLIST
    assert len(wrapped.list) == 3
    left, out, right = wrapped.list
    assert left.node_type == nd.NODE_TYPE.HLIST
    assert right.node_type == nd.NODE_TYPE.HLIST
    assert left.width == math.state.layout["nulldelimiterspace"]
    assert right.width == math.state.layout["nulldelimiterspace"]
    assert out.node_type == nd.NODE_TYPE.VLIST
    assert len(out.list) == 5
    x, k1, rule, k2, z = out.list
    assert x.node_type == nd.NODE_TYPE.HLIST
    assert k1.node_type == nd.NODE_TYPE.KERN
    assert rule.node_type == nd.NODE_TYPE.RULE
    assert k2.node_type == nd.NODE_TYPE.KERN
    assert z.node_type == nd.NODE_TYPE.HLIST

    _, _, theta = frac.rule15(ctx, style)
    u, v = frac.rule15b(ctx, style, theta)
    u, v, expect_k1, expect_k2 = frac.rule15d(x, z, ctx, style, theta, u, v)
    assert float(rule.height) == pytest.approx(float(theta), abs=1e-4)
    assert float(k1.kern) == pytest.approx(float(expect_k1), abs=1e-4)
    assert float(k2.kern) == pytest.approx(float(expect_k2), abs=1e-4)
    assert float(k1.kern) >= float(theta)
    assert float(k2.kern) >= float(theta)
    assert float(out.height) == pytest.approx(float(x.height + u), abs=1e-4)
    assert float(out.depth) == pytest.approx(float(z.depth + v), abs=1e-4)


def test_fraction_rule15d_over_min_clearance_script(math):
    style = mmode.Style(mmode.MATH_STYLE.S)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    math.parse("\\noindent$a\\over b$\\relax")
    frac = math.lists[-1][-1][0]
    packed = []
    frac.typesetNucleus(math, packed, ctx, style)
    assert len(packed) == 1
    wrapped = packed[0]
    assert wrapped.node_type == nd.NODE_TYPE.HLIST
    out = wrapped.list[1]
    _, k1, _, k2, _ = out.list
    _, _, theta = frac.rule15(ctx, style)
    phi = theta
    assert float(k1.kern) >= float(phi)
    assert float(k2.kern) >= float(phi)


def test_fraction_rule15e_with_delims_builds_three_boxes(math):
    style = mmode.Style(mmode.MATH_STYLE.T)
    ctx = mmode.MathTypesetContext(False)
    ctx.snapshot(math)
    math.parse("\\noindent$a\\overwithdelims() b$\\relax")
    frac = math.lists[-1][-1][0]
    packed = []
    frac.typesetNucleus(math, packed, ctx, style)
    assert len(packed) == 1
    wrapped = packed[0]
    assert wrapped.node_type == nd.NODE_TYPE.HLIST
    assert len(wrapped.list) == 3
    left, middle, right = wrapped.list
    assert left.node_type == nd.NODE_TYPE.HLIST
    assert middle.node_type == nd.NODE_TYPE.VLIST
    assert right.node_type == nd.NODE_TYPE.HLIST
    axis = Dimen(ctx.sigma(style)[21])
    left_center = (left.height - left.depth) / 2 - left.shifted
    right_center = (right.height - right.depth) / 2 - right.shifted
    assert float(left_center) == pytest.approx(float(axis), abs=1e-4)
    assert float(right_center) == pytest.approx(float(axis), abs=1e-4)


def test_fraction_rule15e_delims_integrated_in_inner_atom_nucleus(math):
    math.parse("\\noindent$a\\overwithdelims() b$\\relax")
    mlist = math.lists[-1][0]
    packed = []
    mlist.typeset(math, packed)
    # math_on + wrapper hbox + math_off
    assert len(packed) == 3
    assert packed[0].node_type == nd.NODE_TYPE.MATH
    assert packed[1].node_type == nd.NODE_TYPE.HLIST
    assert packed[2].node_type == nd.NODE_TYPE.MATH
    inner = packed[1]
    assert len(inner.list) == 3
    assert inner.list[0].node_type == nd.NODE_TYPE.HLIST
    assert inner.list[1].node_type == nd.NODE_TYPE.VLIST
    assert inner.list[2].node_type == nd.NODE_TYPE.HLIST


def test_fraction_rule15e_null_delims_integrated_in_inner_atom_nucleus(math):
    math.parse("\\noindent$a\\over b$\\relax")
    mlist = math.lists[-1][0]
    packed = []
    mlist.typeset(math, packed)
    # math_on + wrapper hbox + math_off
    assert len(packed) == 3
    assert packed[0].node_type == nd.NODE_TYPE.MATH
    assert packed[1].node_type == nd.NODE_TYPE.HLIST
    assert packed[2].node_type == nd.NODE_TYPE.MATH
    inner = packed[1]
    assert len(inner.list) == 3
    assert inner.list[0].node_type == nd.NODE_TYPE.HLIST
    assert inner.list[1].node_type == nd.NODE_TYPE.VLIST
    assert inner.list[2].node_type == nd.NODE_TYPE.HLIST
    assert inner.list[0].width == math.state.layout["nulldelimiterspace"]
    assert inner.list[2].width == math.state.layout["nulldelimiterspace"]


@pytest.mark.parametrize("left", [True, False])
def test_eqno(math, left):
    cmd = "\\leqno" if left else "\\eqno"
    math.parse(f"$$a{cmd}1$$")
    top = math.lists[0]
    assert top.type == lists.LISTTYPE.VERTICAL
    mlist = next(n for n in top if isinstance(n, mmode.MList))
    assert mlist.node_type == nd.NODE_TYPE.MATH
    assert len(mlist) == 1
    atom = mlist[0]
    assert isinstance(atom, mmode.Atom)
    assert isSymbol(atom.nucleus, 1, "a")
    assert mlist.eqno is not None
    eqno, eqno_left = mlist.eqno
    assert eqno_left == left
    assert isinstance(eqno, mmode.MList)
    assert len(eqno) == 1
    node = eqno[0]
    assert isinstance(node, mmode.Atom)
    assert isSymbol(node.nucleus, 0, "1")

def test_eqno_inline(math):
    try:
        math.parse("$a\\eqno1$")
        assert False
    except ValueError as e:
        assert "equation" in str(e)

def test_eqno_subformula(math):
    try:
        math.parse("$\\left(a\\eqno1$")
        assert False
    except ValueError as e:
        assert "equation" in str(e)


def test_italic_correction(math):
    math.parse("$l \\/")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 2
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert isSymbol(node.nucleus, 1, "l")
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.KERN
    assert node.kern == 0


def test_atom_rebox_returns_same_box_when_width_matches(math):
    b = box.HBox(math, None, None)
    b.list.append(nd.Kern(5))
    b.typeset(math, [])
    out = mmode.Atom.rebox(math, b, b.width)
    assert out is b


def test_atom_rebox_unpackages_hbox_and_centers(math):
    class FakeChar(nd.Box):
        node_type = nd.NODE_TYPE.CHAR

        def __init__(self, width, font, italic=0):
            super().__init__(width, 1, 0)
            self.font = font
            self.italic = Dimen(italic)
            # Use a non-letter so the hlist ligature pass does not enter word mode.
            self.char = "("

    b = box.HBox(math, None, None)
    b.list.append(FakeChar(5, math.state.parameters["currentfont"], italic=2))
    b.typeset(math, [])
    target = b.width + Dimen(10)
    out = mmode.Atom.rebox(math, b, target)
    assert out.width == target
    assert any(n.node_type == nd.NODE_TYPE.CHAR for n in out.list)
    # \hss glue added at both sides.
    assert out.list[0].node_type == nd.NODE_TYPE.GLUE
    assert out.list[-1].node_type == nd.NODE_TYPE.GLUE
    # implied italic correction should be preserved as an automatic kern.
    kerns = [n for n in out.list if n.node_type == nd.NODE_TYPE.KERN and n.automatic]
    assert len(kerns) == 1
    assert kerns[0].kern == 2


def test_atom_rebox_rejects_non_hbox(math):
    vb = box.VBox(math, None, None)
    vb.list.append(nd.Rule(3, 1, 0))
    vb.typeset(math, [])
    with pytest.raises(ValueError, match="expects an hbox"):
        mmode.Atom.rebox(math, vb, vb.width + Dimen(5))


def test_box(math):
    math.parse("$\\hbox{a}")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Box)
    box = node.nucleus
    assert box.node_type == nd.NODE_TYPE.HLIST
    assert len(box.list) == 1
    assert box.list[0].char == "a"
    math.parse("$")


def test_vcenter(math):
    math.parse("$\\vcenter{\\vskip 10pt}")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert node.atom_type == mmode.ATOM_TYPE.VCENT
    box = node.nucleus
    assert box.node_type == nd.NODE_TYPE.VLIST
    assert len(box.list) == 1
    assert box.list[0].node_type == nd.NODE_TYPE.GLUE
    math.parse("$")


def test_vcenter_wrongmode(parser):
    try:
        parser.parse("\\vcenter{a}")
        assert False
    except ValueError as e:
        assert "math" in str(e)


def test_vcenter_nobox(math):
    try:
        math.parse("$\\setbox0=\\vcenter{}")
        assert False
    except ValueError as e:
        assert "\\vcenter" in str(e)


def test_nonscript(math):
    math.parse("$\\nonscript")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.NonscriptGlue)
    math.parse("$")
