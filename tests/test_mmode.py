import pytest
from pytex import mmode
from pytex import lists
from pytex import node as nd
from pytex import texlive
from pytex.dimen import Dimen


@pytest.fixture()
def math(parser):
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
    \\textfont2=\\tensy \\scriptfont2=\\sevensy \\scriptscriptfont2=\\fivesy
    \\delcode`(=\"028300 \\delcode`)=\"029301 \\delcode`.=0
    """
    parser.parse(fonts)
    return parser

@pytest.mark.parametrize("inner", [True, False])
def test_mlist(parser, inner):
    open = close = "$" if inner else "$$"
    parser.parse(f"{open}a")
    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert top.inner == inner
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert node.sub is None
    assert node.sup is None
    assert node.nucleus == (1, "a")
    assert node.atom_type == mmode.ATOM_TYPE.ORD
    parser.parse(f"{close}")
    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 3
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.MATH


def test_mlist_mismatch(parser):
    try:
        parser.parse("$$a$x")
        assert False
    except ValueError as e:
        assert "missing" in str(e)
    

def test_subformula(parser):
    parser.parse("${ab}")
    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Subformula)
    assert node.sub is None
    assert node.sup is None
    assert len(node.nucleus) == 2


@pytest.mark.parametrize("field, value, type", [
    ["sub", "b", mmode.MathSymbol],
    ["sup", "b", mmode.MathSymbol],
    ["sub", "{ab}", mmode.Subformula],
    ["sup", "{ab}", mmode.Subformula],
])
def test_scripts(parser, field, value, type):
    if field == "sub":
        cmd = "_"
        other = "sup"
    else:
        cmd = "^"
        other = "sub"
    parser.parse(f"$a{cmd}{value}")
    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Atom)
    assert node.nucleus == (1, "a")
    script = getattr(node, field)
    other = getattr(node, other)
    assert script is not None
    assert other is None
    assert isinstance(script, type)
    assert script.sub is None
    assert script.sup is None
    parser.parse("$")


@pytest.mark.parametrize("cmd", [
    "\\mathchar\"1234", 
    "\\mathchardef\\a=\"1234\\a",
])
def test_mathchar(parser, cmd):
    parser.parse(f"${cmd}")
    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.MathSymbol)
    assert node.nucleus == (2, chr(0x34))
    assert node.atom_type == mmode.ATOM_TYPE.OP
    parser.parse("$")


def test_active(parser):
    parser.parse("\\def\\a{1}\\mathcode`a=\"8000$\\a")
    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.MathSymbol)
    assert node.nucleus == (0, "1")
    parser.parse("$")


def test_mkern(math):
    math.parse("$a\\mkern 10mu b")
    top = math.lists[-1]
    assert len(top) == 3
    node = top[1]
    assert node.node_type == nd.NODE_TYPE.KERN
    assert node.kern == 10
    assert node.mu
    math.parse("$")


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
    assert node.style == style
    math.parse("$")


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
    delim, oprand = node.nucleus
    assert delim.small.nucleus == (2, chr(0x70))
    assert delim.large.nucleus == (3, chr(0x70))
    assert oprand.nucleus == (1, "a")
    math.parse("$")


def test_mathaccent(math):
    math.parse("$\\mathaccent\"362 a")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Accent)
    accent, base = node.nucleus
    assert base.nucleus == (1, "a")
    assert accent.nucleus == (3, chr(0x62))
    math.parse("$")


def test_delimiter(math):
    math.parse("$\\delimiter\"1270370")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.MathSymbol)
    assert node.nucleus == (2, chr(0x70))
    assert node.atom_type == mmode.ATOM_TYPE.OP
    math.parse("$ $\\left(a+b\\right)")
    top = math.lists[-1]
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Subformula)
    assert len(node.nucleus) == 3
    assert node.left.small.nucleus == (0, chr(0x28))
    assert node.right.small.nucleus == (0, chr(0x29))
    math.parse("$")


@pytest.mark.parametrize("cmd, bar, thickness, left, right", [
    ["\\over", True, None, None, None],
    ["\\overwithdelims()", True, None, (0, chr(0x28)), (0, chr(0x29))],
    ["\\atop", False, None, None, None],
    ["\\atopwithdelims()", False, None, (0, chr(0x28)), (0, chr(0x29))],
    ["\\above10pt", True, 10, None, None],
    ["\\abovewithdelims()10pt", True, 10, (0, chr(0x28)), (0, chr(0x29))],
])
def test_fractions(math, cmd, bar, thickness, left, right):
    math.parse(f"$\\left(a{cmd} b\\right)")
    top = math.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.Subformula)
    assert node.left.small.nucleus == (0, chr(0x28))
    assert node.right.small.nucleus == (0, chr(0x29))
    assert len(node.nucleus) == 1
    frac = node.nucleus[0]
    assert isinstance(frac, mmode.Over)
    if left is None:
        assert frac.left is None
    else:
        assert frac.left.small.nucleus == left
    if right is None:
        assert frac.right is None
    else:
        assert frac.right.small.nucleus == right 
    num, den, bar, thickness = frac.nucleus
    assert len(num.nucleus) == 1
    assert num.nucleus[0].nucleus == (1, "a")
    assert len(den.nucleus) == 1
    assert den.nucleus[0].nucleus == (1, "b")
    assert bar == bar
    assert thickness == thickness
    math.parse("$")