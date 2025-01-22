import pytest
from pytex import node as nd
from pytex import texlive
from pytex import hmode


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
    nodes, glues = top.pack()
    assert len(nodes) == 3
    assert len(glues) == 1
    lig = nodes[1]
    assert ord(lig.char) == char
    assert isinstance(lig, hmode.Ligature)
    assert len(lig.characters) == len(input)
    content = "".join([c.char for c in lig.characters])
    assert content == input


@pytest.mark.parametrize("input", [
    "vo", "va", "ve", "VA",  "oe"
])
def test_kern(cmr10, input):
    cmr10.parse(input)
    at = cmr10.state.parameters["currentfont"].at
    top = cmr10.lists[-1]
    nodes, glues = top.pack()
    assert len(nodes) == 5
    assert len(glues) == 1
    knode = nodes[2]
    assert isinstance(knode, nd.Kern)
    assert knode.automatic
    font = cmr10.state.parameters["currentfont"]
    char = font[input[0]]
    next = ord(input[1])
    program = char.char_info.program
    assert next in program
    assert knode.kern == program[next].kern*at
