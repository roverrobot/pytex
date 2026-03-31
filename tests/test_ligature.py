import pytest
import types
from pytex import node as nd
from pytex import texlive
from pytex import hmode
from pytex import tfm
from pytex import dimen


def _raw_nodes(hlist):
    return hlist.rawNodes() if hasattr(hlist, "rawNodes") else getattr(hlist, "raw", hlist)


def _concrete_nodes(hlist):
    return hlist.concreteNodes() if hasattr(hlist, "concreteNodes") else list(hlist)


@pytest.mark.parametrize("input,char", [
    ["ff", 11],
    ["fi", 12],
    ["fl", 13],
    ["ffi", 14],
    ["ffl", 15],
    ["--", 0x7b],
    ["---", 0x7c],
    ["``", 0x5c],
    ["''", 34],
])
def test_ligatures(cmr10, input, char):
    cmr10.parse(input)
    top = cmr10.lists[-1]
    assert len(_raw_nodes(top)) == len(input) + 2
    packed = _concrete_nodes(top)
    assert len(packed) == 3
    assert packed[2].node_type == nd.NODE_TYPE.GLUE
    lig = packed[1]
    assert ord(lig.char) == char
    assert isinstance(lig, hmode.Ligature)
    assert len(lig.source) == len(input)
    content = "".join([c.char for c in lig.source])
    assert content == input


@pytest.mark.parametrize("input", [
    "vo", "va", "ve", "VA",  "oe"
])
def test_kern(cmr10, input):
    cmr10.parse(input)
    at = cmr10.parameters["currentfont"].at
    top = cmr10.lists[-1]
    assert len(_raw_nodes(top)) == len(input) + 2
    packed = _concrete_nodes(top)
    assert len(packed) == 5
    assert packed[4].node_type == nd.NODE_TYPE.GLUE
    knode = packed[2]
    assert isinstance(knode, nd.Kern)
    assert knode.automatic
    font = cmr10.parameters["currentfont"]
    char = font[input[0]]
    next = ord(input[1])
    program = char.char_info.program
    assert next in program
    assert knode.kern == program[next].kern*at


class _FakeChar:
    node_type = nd.NODE_TYPE.CHAR
    typeset = None

    def __init__(self, char, font, char_info):
        self.char = char
        self.font = font
        self.char_info = char_info


class _FakeFont:
    at = dimen.Dimen(1)

    def __init__(self, left_boundary=None, right_boundary=None):
        self._nodes = {}
        self._left_boundary = None
        if left_boundary is not None:
            self._left_boundary = {}
            step = left_boundary
            while step is not None:
                self._left_boundary[step.next_char] = step
                step = step.next_step
        self._right_boundary = None if right_boundary is None else chr(right_boundary.next_char)

    def __getitem__(self, char):
        return self._nodes[char]

    def glyphInfo(self, char):
        node = self._nodes.get(char)
        return None if node is None else node.char_info

    def leftBoundaryProgram(self):
        return self._left_boundary

    def rightBoundaryChar(self):
        return self._right_boundary

    def add(self, char, program=None):
        node = _FakeChar(char, self, types.SimpleNamespace(
            char=char,
            width=dimen.Dimen(),
            height=dimen.Dimen(),
            depth=dimen.Dimen(),
            italic=dimen.Dimen(),
            program=program,
        ))
        self._nodes[char] = node
        return node


def test_left_boundary_ligature_is_applied(parser):
    parser.lccode[ord("a")] = ord("a")
    left = tfm.LigOp(ord("a"), ord("b"), 0)
    font = _FakeFont(left_boundary=left)
    a = font.add("a", {})
    font.add("b", {})
    hlist = hmode.HList(parser, [], inner=True)
    hlist.open()
    try:
        hlist.append(a)
    finally:
        hlist.close()
    packed = _concrete_nodes(hlist)
    assert len(packed) == 1
    lig = packed[0]
    assert isinstance(lig, hmode.Ligature)
    assert lig.char == "b"
    assert lig.source == [a]


def test_right_boundary_kern_is_applied(parser):
    parser.lccode[ord("a")] = ord("a")
    bchar = types.SimpleNamespace(next_char=ord("#"))
    font = _FakeFont(right_boundary=bchar)
    a = font.add("a", {ord("#"): tfm.KernOp(ord("#"), 2)})
    hlist = hmode.HList(parser, [], inner=True)
    hlist.open()
    try:
        hlist.append(a)
    finally:
        hlist.close()
    packed = _concrete_nodes(hlist)
    assert len(packed) == 2
    assert packed[0] is a
    kern = packed[1]
    assert isinstance(kern, nd.Kern)
    assert kern.kern == 2
    assert kern.automatic
