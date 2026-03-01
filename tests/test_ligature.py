import pytest
import types
from pytex import node as nd
from pytex import texlive
from pytex import hmode
from pytex import tfm
from pytex import dimen


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
    assert len(top) == len(input) + 2
    packed = []
    top.typesetNodes(cmr10, packed)
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
    at = cmr10.state.parameters["currentfont"].at
    top = cmr10.lists[-1]
    assert len(top) == len(input) + 2
    packed = []
    top.typesetNodes(cmr10, packed)
    assert len(packed) == 5
    assert packed[4].node_type == nd.NODE_TYPE.GLUE
    knode = packed[2]
    assert isinstance(knode, nd.Kern)
    assert knode.automatic
    font = cmr10.state.parameters["currentfont"]
    char = font[input[0]]
    next = ord(input[1])
    program = char.char_info.program
    assert next in program
    assert knode.kern == program[next].kern*at


class _FakeChar:
    node_type = nd.NODE_TYPE.CHAR
    typeset = None

    def __init__(self, char, font, program=None):
        self.char = char
        self.font = font
        self.char_info = types.SimpleNamespace(program=program)


class _FakeFont:
    bc = 0
    ec = 255
    at = dimen.Dimen(1)

    def __init__(self, left_boundary=None, right_boundary=None):
        char_info = [
            types.SimpleNamespace(
                char=chr(i),
                width=dimen.Dimen(),
                height=dimen.Dimen(),
                depth=dimen.Dimen(),
                italic=dimen.Dimen(),
                program=None,
            )
            for i in range(256)
        ]
        self.tfm = types.SimpleNamespace(
            char_info=char_info,
            program=types.SimpleNamespace(
                left_boundary=left_boundary,
                right_boundary=right_boundary,
            )
        )
        self._nodes = {}

    def __getitem__(self, char):
        return self._nodes[char]

    def add(self, char, program=None):
        node = _FakeChar(char, self, program)
        self._nodes[char] = node
        return node


def test_left_boundary_ligature_is_applied(parser):
    parser.state.lccode[ord("a")] = ord("a")
    left = tfm.LigOp(ord("a"), ord("b"), 0)
    font = _FakeFont(left_boundary=left)
    a = font.add("a", {})
    font.add("b", {})
    hlist = hmode.HList(parser, inner=True)
    hlist.append(a)
    packed = []
    hlist.typesetNodes(parser, packed)
    assert len(packed) == 1
    lig = packed[0]
    assert isinstance(lig, hmode.Ligature)
    assert lig.char == "b"
    assert lig.source == [a]


def test_right_boundary_kern_is_applied(parser):
    parser.state.lccode[ord("a")] = ord("a")
    bchar = types.SimpleNamespace(next_char=ord("#"))
    font = _FakeFont(right_boundary=bchar)
    a = font.add("a", {ord("#"): tfm.KernOp(ord("#"), 2)})
    hlist = hmode.HList(parser, inner=True)
    hlist.append(a)
    packed = []
    hlist.typesetNodes(parser, packed)
    assert len(packed) == 2
    assert packed[0] is a
    kern = packed[1]
    assert isinstance(kern, nd.Kern)
    assert kern.kern == 2
    assert kern.automatic
