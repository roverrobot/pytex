import pytest
from pytex import mmode
from pytex import lists
from pytex import node as nd


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
    assert node.char == ord("a")
    assert node.atom_type == mmode.ATOM_TYPE.ORD
    assert node.fam == 0
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
    assert len(node.list) == 2


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
    assert node.char == ord("a")
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
    assert node.char == 0x34
    assert node.fam == 2
    assert node.atom_type == mmode.ATOM_TYPE.OP
    parser.parse("$")


def test_acive(parser):
    parser.parse("\\def\\a{1}\\mathcode`a=\"8000$\\a")
    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    node = top[0]
    assert isinstance(node, mmode.MathSymbol)
    assert node.char == ord("1")
    parser.parse("$")
