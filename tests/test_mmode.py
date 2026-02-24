import pytest
from pytex import mmode
from pytex import lists
from pytex import node as nd
from pytex import texlive
from pytex import box
from pytex.dimen import Dimen


def isSymbol(node, fam, char):
    return isinstance(node, mmode.MathSymbol) and node.fam == fam and node.char == char


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
    symbol.typeset(math, packed, mmode.MathTypesetContext(math, True), mmode.Style(mmode.MATH_STYLE.T))
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
    assert float(kerns[0].kern) == pytest.approx(mlist.typeset_context.scriptfont[2].param[5], abs=1e-4)


def test_nonscript_removes_immediately_following_glue_or_kern(math):
    math.parse("$\\nonscript\\mkern18mu\\mkern36mu$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 1
    assert float(kerns[0].kern) == pytest.approx(2 * mlist.typeset_context.textfont[2].param[5], abs=1e-4)


def test_nonscript_keeps_following_glue_or_kern_when_style_is_scriptscript(math):
    math.parse("$\\scriptscriptstyle\\nonscript\\mkern18mu\\mkern36mu$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 2
    sigma = mlist.typeset_context.scriptscriptfont[2].param[5]
    assert float(kerns[0].kern) == pytest.approx(sigma, abs=1e-4)
    assert float(kerns[1].kern) == pytest.approx(2 * sigma, abs=1e-4)


def test_mathchoice_uses_current_text_style(math):
    math.parse("$\\mathchoice{\\mkern18mu}{\\mkern36mu}{\\mkern54mu}{\\mkern72mu}$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 1
    sigma = mlist.typeset_context.textfont[2].param[5]
    assert float(kerns[0].kern) == pytest.approx(2 * sigma, abs=1e-4)


def test_mathchoice_uses_current_script_style(math):
    math.parse("$\\scriptstyle\\mathchoice{\\mkern18mu}{\\mkern36mu}{\\mkern54mu}{\\mkern72mu}$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 1
    sigma = mlist.typeset_context.scriptfont[2].param[5]
    assert float(kerns[0].kern) == pytest.approx(3 * sigma, abs=1e-4)


def test_nested_mathchoice_expands_without_mutating_list(math):
    math.parse("$\\mathchoice{\\mkern18mu}{\\mathchoice{\\mkern18mu}{\\mkern36mu}{\\mkern54mu}{\\mkern72mu}}{\\mkern90mu}{\\mkern108mu}$")
    mlist = math.lists[-1][1]
    packed = []
    mlist.typeset(math, packed)
    kerns = [n for n in packed if n.node_type == nd.NODE_TYPE.KERN]
    assert len(kerns) == 1
    sigma = mlist.typeset_context.textfont[2].param[5]
    assert float(kerns[0].kern) == pytest.approx(2 * sigma, abs=1e-4)
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
    ctx = mmode.MathTypesetContext(math, True)
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
    ctx = mmode.MathTypesetContext(math, True)
    mlist.typesetNodes(math, packed, ctx, mmode.Style(mmode.MATH_STYLE.T))

    assert rel.observed_type == mmode.ATOM_TYPE.REL
    assert bin_atom.observed_type == mmode.ATOM_TYPE.ORD


def _mk_atom(atom_type, fam, ch):
    atom = mmode.Atom(atom_type)
    code = (atom_type.value << 12) | (fam << 8) | ord(ch)
    atom.nucleus = mmode.MathSymbol(code, -1)
    return atom


def test_atom_wrapper_proxies_wrapped_atom_fields_and_methods(math):
    atom = _mk_atom(mmode.ATOM_TYPE.ORD, 0, "a")
    wrapped = mmode._AtomWrapper(atom, mmode.ATOM_TYPE.BIN, mmode.Style(mmode.MATH_STYLE.T))
    assert wrapped.nucleus is atom.nucleus
    wrapped.nucleus = None
    assert atom.nucleus is None
    assert callable(wrapped.typeset)


def test_rule14_ord_op_ligature_collapses_pair(math):
    # Put text fonts in family 0 so CMR ligatures/kerns are available.
    math.parse("\\textfont0=\\tenrm \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "f"),
        _mk_atom(mmode.ATOM_TYPE.OP, 0, "i"),
    ])
    ctx = mmode.MathTypesetContext(math, True)
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
    ctx = mmode.MathTypesetContext(math, True)
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
    ctx = mmode.MathTypesetContext(math, True)
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
    ctx = mmode.MathTypesetContext(math, True)
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
    ctx = mmode.MathTypesetContext(math, True)
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
    ctx = mmode.MathTypesetContext(math, True)
    collected = mlist._pass1Collect(math, ctx, mmode.Style(mmode.MATH_STYLE.T))
    mlist._pass1AdjustAtoms(math, ctx, collected)
    wrappers = [x for x in collected if isinstance(x, mmode._AtomWrapper)]
    assert len(wrappers) == 1
    assert wrappers[0].node_type == mmode.ATOM_TYPE.ORD


def test_rule6_bin_to_ord_does_not_trigger_rule14_on_previous_atom(math):
    math.parse("\\textfont0=\\tenrm \\scriptfont0=\\sevenrm \\scriptscriptfont0=\\fiverm")
    mlist = mmode.MList(math)
    mlist.extend([
        _mk_atom(mmode.ATOM_TYPE.ORD, 0, "a"),
        _mk_atom(mmode.ATOM_TYPE.BIN, 0, "f"),
        _mk_atom(mmode.ATOM_TYPE.REL, 0, "i"),
    ])
    ctx = mmode.MathTypesetContext(math, True)
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
    mlist.typesetNodes(math, packed, mmode.MathTypesetContext(math, True), mmode.Style(mmode.MATH_STYLE.T))
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
    ctx = mmode.MathTypesetContext(math, True)
    style = mmode.Style(mmode.MATH_STYLE.T)
    b = d.typeset(math, Dimen(20), ctx, style)
    assert b.node_type == nd.NODE_TYPE.HLIST
    assert b.width == math.state.layout["nulldelimiterspace"]
    axis = Dimen(ctx.sigma(style)[21])
    assert float(b.shifted) == pytest.approx(-float(axis), abs=1e-4)


def test_delim_typeset_order_uses_style_fonts(math):
    code = ((1 << 8) | ord("a")) << 12
    d = mmode.Delim(code, 0)
    ctx = mmode.MathTypesetContext(math, True)

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
    ctx = mmode.MathTypesetContext(math, True)
    b = d.typeset(math, Dimen(), ctx, mmode.Style(mmode.MATH_STYLE.T))
    kerns = [n for n in b.list if n.node_type == nd.NODE_TYPE.KERN and n.automatic]
    assert len(kerns) <= 1
    if kerns:
        assert float(kerns[0].kern) > 0


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
    ctx = mmode.MathTypesetContext(math, True)
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
    ctx = mmode.MathTypesetContext(math, True)
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
    ctx = mmode.MathTypesetContext(math, True)
    sigma = ctx.sigma(style)
    math.parse("\\noindent$a\\over b$\\relax")
    frac = math.lists[-1][-1][0]
    _, _, theta = frac.rule15(ctx, style)
    u, v = frac.rule15b(ctx, style, theta)
    assert float(u) == pytest.approx(sigma[7], abs=1e-4)   # sigma8
    assert float(v) == pytest.approx(sigma[10], abs=1e-4)  # sigma11


def test_fraction_rule15c_atop_construction(math):
    style = mmode.Style(mmode.MATH_STYLE.T)
    ctx = mmode.MathTypesetContext(math, True)
    math.parse("\\noindent$a\\atop b$\\relax")
    frac = math.lists[-1][-1][0]
    packed = []
    frac.typesetNucleus(math, packed, ctx, style)
    assert len(packed) == 3
    left, out, right = packed
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
    ctx = mmode.MathTypesetContext(math, True)
    math.parse("\\noindent$a\\over b$\\relax")
    frac = math.lists[-1][-1][0]
    packed = []
    frac.typesetNucleus(math, packed, ctx, style)
    assert len(packed) == 3
    left, out, right = packed
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
    ctx = mmode.MathTypesetContext(math, True)
    math.parse("\\noindent$a\\over b$\\relax")
    frac = math.lists[-1][-1][0]
    packed = []
    frac.typesetNucleus(math, packed, ctx, style)
    assert len(packed) == 3
    out = packed[1]
    _, k1, _, k2, _ = out.list
    _, _, theta = frac.rule15(ctx, style)
    phi = 3 * theta
    assert float(k1.kern) >= float(phi)
    assert float(k2.kern) >= float(phi)


def test_fraction_rule15e_with_delims_builds_three_boxes(math):
    style = mmode.Style(mmode.MATH_STYLE.T)
    ctx = mmode.MathTypesetContext(math, True)
    math.parse("\\noindent$a\\overwithdelims() b$\\relax")
    frac = math.lists[-1][-1][0]
    packed = []
    frac.typesetNucleus(math, packed, ctx, style)
    assert len(packed) == 3
    left, middle, right = packed
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
    # math_on + (left delim, fraction vbox, right delim) + math_off
    assert len(packed) == 5
    assert packed[0].node_type == nd.NODE_TYPE.MATH
    assert packed[1].node_type == nd.NODE_TYPE.HLIST
    assert packed[2].node_type == nd.NODE_TYPE.VLIST
    assert packed[3].node_type == nd.NODE_TYPE.HLIST
    assert packed[4].node_type == nd.NODE_TYPE.MATH


def test_fraction_rule15e_null_delims_integrated_in_inner_atom_nucleus(math):
    math.parse("\\noindent$a\\over b$\\relax")
    mlist = math.lists[-1][0]
    packed = []
    mlist.typeset(math, packed)
    # math_on + (left null delim, fraction vbox, right null delim) + math_off
    assert len(packed) == 5
    assert packed[0].node_type == nd.NODE_TYPE.MATH
    assert packed[1].node_type == nd.NODE_TYPE.HLIST
    assert packed[2].node_type == nd.NODE_TYPE.VLIST
    assert packed[3].node_type == nd.NODE_TYPE.HLIST
    assert packed[4].node_type == nd.NODE_TYPE.MATH
    assert packed[1].width == math.state.layout["nulldelimiterspace"]
    assert packed[3].width == math.state.layout["nulldelimiterspace"]


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
        math.parse("$\left(a\\eqno1$")
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

        def __init__(self, width, italic=0):
            super().__init__(width, 1, 0)
            self.italic = Dimen(italic)
            self.char = "x"

    b = box.HBox(math, None, None)
    b.list.append(FakeChar(5, italic=2))
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
        math.parse("$\setbox0=\\vcenter{}")
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
