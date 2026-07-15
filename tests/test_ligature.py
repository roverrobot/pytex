import pytest
from pytex import node as nd
from pytex import glyph
from pytex import texlive
from pytex import hmode
from pytex import tfm
from pytex import dimen
from pytex.font import Font
from pytex.font_backend import FontBackend, GlyphInfo


def _raw_nodes(hlist):
    return hlist.rawNodes() if hasattr(hlist, "rawNodes") else getattr(hlist, "raw", hlist)


def _concrete_nodes(hlist):
    return hlist.concreteNodes() if hasattr(hlist, "concreteNodes") else list(hlist)


class _ShapeBackend(FontBackend):
    def __init__(self, programs=None, left_boundary=None, right_boundary=None):
        self.programs = programs or {}
        self._left_boundary = left_boundary
        self._right_boundary = right_boundary

    @property
    def name(self):
        return "shape-test"

    @property
    def design_size(self):
        return 1

    def glyphInfo(self, char):
        return GlyphInfo(
            char,
            1,
            1,
            0,
            glyph_id=ord(char),
            program=self.programs.get(char),
        )

    def glyphInfos(self):
        return ()

    def leftBoundaryProgram(self):
        return self._left_boundary

    def rightBoundaryChar(self):
        return self._right_boundary

    def shape(self, font, source, **kwargs):
        return self._shapeLigKern(font, source, **kwargs)


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
    assert isinstance(lig, glyph.GlyphCluster)
    assert ord(lig.layout.char) == char
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
    assert len(packed) == 3
    assert packed[2].node_type == nd.NODE_TYPE.GLUE
    cluster = packed[1]
    assert isinstance(cluster, glyph.GlyphCluster)
    assert cluster.text == input
    assert cluster.layout.node_type == nd.NODE_TYPE.HLIST
    knode = cluster.layout.list[1]
    assert isinstance(knode, nd.Kern)
    assert not knode.automatic
    font = cmr10.parameters["currentfont"]
    char = font[input[0]]
    next = ord(input[1])
    program = char.char_info.program
    assert next in program
    assert knode.kern == program[next].kern*at


def test_tfm_font_shape_returns_ligature_cluster(cmr10):
    font = cmr10.parameters["currentfont"]
    source = [glyph.TextChar(char, font, True) for char in "ffi"]

    shaped = font.shape(source)

    assert len(shaped) == 1
    assert isinstance(shaped[0], glyph.GlyphCluster)
    assert shaped[0].text == "ffi"
    assert shaped[0].layout.node_type == nd.NODE_TYPE.CHAR
    assert ord(shaped[0].layout.char) == 14


def test_tfm_font_shape_contains_kern_inside_one_cluster(cmr10):
    font = cmr10.parameters["currentfont"]
    source = [glyph.TextChar(char, font, True) for char in "VA"]

    shaped = font.shape(source, parser=cmr10)

    assert len(shaped) == 1
    assert shaped[0].text == "VA"
    assert shaped[0].layout.node_type == nd.NODE_TYPE.HLIST
    assert [node.node_type for node in shaped[0].layout.list] == [
        nd.NODE_TYPE.CHAR,
        nd.NODE_TYPE.KERN,
        nd.NODE_TYPE.CHAR,
    ]
    hidden_kern = shaped[0].layout.list[1]
    assert not hidden_kern.automatic
    assert hidden_kern.kern == font.at * font.glyphInfo("V").program[ord("A")].kern


def test_font_shape_applies_requested_word_boundary_programs(parser):
    left_step = tfm.LigOp(ord("a"), ord("b"), 0)
    left_font = Font(
        _ShapeBackend(left_boundary={ord("a"): left_step}),
        dimen.Dimen(1),
    )

    left = left_font.shape(
        [glyph.TextChar("a", left_font, True)],
        left_boundary=True,
    )

    assert len(left) == 1
    assert left[0].text == "a"
    assert left[0].layout.char == "b"

    right_step = tfm.KernOp(ord("#"), 2)
    right_font = Font(
        _ShapeBackend(programs={"a": {ord("#"): right_step}}, right_boundary="#"),
        dimen.Dimen(1),
    )

    right = right_font.shape(
        [glyph.TextChar("a", right_font, True)],
        parser=parser,
        right_boundary=True,
    )

    assert len(right) == 1
    assert right[0].layout.node_type == nd.NODE_TYPE.HLIST
    assert [node.node_type for node in right[0].layout.list] == [
        nd.NODE_TYPE.CHAR,
        nd.NODE_TYPE.KERN,
    ]
    assert right[0].layout.list[1].kern == dimen.Dimen(2)


def test_font_shape_packs_source_less_insert_with_retained_inputs(parser):
    insert = tfm.LigOp(ord("b"), ord("c"), 3)
    font = Font(
        _ShapeBackend(programs={"a": {ord("b"): insert}}),
        dimen.Dimen(1),
    )
    source = [glyph.TextChar(char, font, True) for char in "ab"]

    shaped = font.shape(source, parser=parser)

    assert len(shaped) == 1
    assert shaped[0].text == "ab"
    assert shaped[0].layout.node_type == nd.NODE_TYPE.HLIST
    assert [item.char for item in shaped[0].layout.list] == ["a", "c", "b"]
    assert shaped[0].width == dimen.Dimen(3)


def test_hlist_delegates_left_boundary_program_to_font_backend(parser):
    parser.lccode[ord("a")] = ord("a")
    left_step = tfm.LigOp(ord("a"), ord("b"), 0)
    font = Font(
        _ShapeBackend(left_boundary={ord("a"): left_step}),
        dimen.Dimen(1),
    )
    hlist = hmode.HList(parser, [], inner=True)
    hlist.open()
    try:
        hlist.append(font["a"])
    finally:
        hlist.close()

    cluster = _concrete_nodes(hlist)[0]
    assert cluster.text == "a"
    assert cluster.layout.char == "b"


def test_hlist_delegates_right_boundary_program_to_font_backend(parser):
    parser.lccode[ord("a")] = ord("a")
    right_step = tfm.KernOp(ord("#"), 2)
    font = Font(
        _ShapeBackend(
            programs={"a": {ord("#"): right_step}},
            right_boundary="#",
        ),
        dimen.Dimen(1),
    )
    hlist = hmode.HList(parser, [], inner=True)
    hlist.open()
    try:
        hlist.append(font["a"])
    finally:
        hlist.close()

    cluster = _concrete_nodes(hlist)[0]
    assert cluster.text == "a"
    assert cluster.layout.node_type == nd.NODE_TYPE.HLIST
    assert cluster.layout.list[1].node_type == nd.NODE_TYPE.KERN
    assert cluster.layout.list[1].kern == dimen.Dimen(2)
