import pytest

from pytex import glyph
from pytex import box as bx
from pytex import node as nd
from pytex import serialization
from pytex.dimen import Dimen
from pytex.font_backend import GlyphInfo
from pytex.glue import Glue, Stretchness


class _GlyphFont:
    at = Dimen(10)

    @staticmethod
    def glyphInfo(char):
        return GlyphInfo(char, 0.5, 0.7, 0.2, glyph_id=ord(char))


def test_text_char_snapshots_interword_glue(parser):
    font = parser.parameters["currentfont"]
    spacing = Glue(3, Stretchness(2), Stretchness(1))

    source = glyph.TextChar(" ", font, False, spacing)
    spacing.dimen = Dimen(9)

    assert source.char == " "
    assert source.font is font
    assert source.word_char is False
    assert source.interword_glue.dimen == Dimen(3)


def test_shaping_records_are_immutable_and_normalized():
    shaped = glyph.ShapedGlyph(
        x_advance=5,
        width=6,
        height=7,
        depth=2,
        glyph_id=42,
        x_offset=-1,
        y_offset=3,
    )
    cluster = glyph.ShapedCluster(1, 3, [shaped])
    kern = glyph.ShapedKern(-0.5, 0, 2)

    assert shaped.x_advance == Dimen(5)
    assert shaped.x_offset == Dimen(-1)
    assert shaped.y_offset == Dimen(3)
    assert cluster.glyphs == (shaped,)
    assert kern.amount == Dimen(-0.5)
    with pytest.raises(AttributeError):
        shaped.x_advance = Dimen(6)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: glyph.ShapedGlyph(1, 1, 1, 0),
        lambda: glyph.ShapedCluster(2, 2, ()),
        lambda: glyph.ShapedKern(1, 0, None),
    ],
)
def test_shaping_records_reject_incomplete_values(factory):
    with pytest.raises((TypeError, ValueError)):
        factory()


def test_one_glyph_cluster_can_represent_multiple_source_characters():
    font = _GlyphFont()
    output = nd.CharNode("A", font)
    source = [
        glyph.TextChar("f", font, True),
        glyph.TextChar("i", font, True),
    ]

    cluster = glyph.GlyphCluster.fromCharNode(
        output,
        source=source,
    )

    assert cluster.node_type == nd.NODE_TYPE.GLYPH_CLUSTER
    assert cluster.text == "fi"
    assert all(item.word_char for item in cluster.source)
    assert cluster.layout.node_type == nd.NODE_TYPE.GLYPH
    assert cluster.layout.char == output.char
    assert cluster.width == output.width
    assert cluster.height == output.height
    assert cluster.depth == output.depth


def test_cluster_measures_boxes_kerns_and_vertical_shifts(parser):
    font = parser.parameters["currentfont"]
    first = glyph.Glyph(font, 5, 7, 1, char="A", glyph_id=1)
    second = glyph.Glyph(font, 4, 6, 2, char="V", glyph_id=2)
    second.shifted = Dimen(-2)
    source = [
        glyph.TextChar("A", font, True),
        glyph.TextChar("V", font, True),
    ]

    layout = bx.HBox(parser, None, None)
    layout.list = [first, nd.Kern(-0.5, True), second]
    layout = layout.typeset(parser)
    cluster = glyph.GlyphCluster(source, layout)

    assert cluster.width == layout.width == first.width - Dimen(0.5) + second.width
    assert cluster.height == layout.height == max(first.height, second.height + Dimen(2))
    assert cluster.depth == layout.depth == max(first.depth, second.depth - Dimen(2))


def test_cluster_requires_one_glyph_or_one_packed_hbox(parser):
    font = parser.parameters["currentfont"]
    source = [glyph.TextChar("A", font, True)]
    output = glyph.Glyph.fromCharNode(font["A"])

    with pytest.raises(TypeError, match="one character/glyph node or one packed HBox"):
        glyph.GlyphCluster(source, [output])

    unpacked = bx.HBox(parser, None, None)
    unpacked.list = [output]
    with pytest.raises(ValueError, match="already be packed"):
        glyph.GlyphCluster(source, unpacked)


def test_text_source_supports_clusters_and_unclustered_char_nodes(parser):
    font = parser.parameters["currentfont"]
    char = font["A"]
    cluster = glyph.GlyphCluster.fromCharNode(char, word_char=True)

    assert [item.char for item in glyph.textSource(char, True)] == ["A"]
    assert glyph.textSource(cluster) == cluster.source
    assert glyph.textSource(nd.Kern(1)) is None
    assert glyph.isTextNode(char)
    assert glyph.isTextNode(cluster)
    assert not glyph.isTextNode(nd.Kern(1))


def test_realized_cluster_serialization_round_trip(parser):
    font = parser.parameters["currentfont"]
    spacing = Glue(3, Stretchness(2), Stretchness(1))
    source = [
        glyph.TextChar("A", font, True),
        glyph.TextChar(" ", font, False, spacing),
    ]
    layout = bx.HBox(parser, None, None)
    layout.list = [glyph.Glyph.fromCharNode(font["A"]), nd.Kern(1, True)]
    layout = layout.typeset(parser)
    cluster = glyph.GlyphCluster(source, layout)

    restored = serialization.deserialize(
        parser,
        serialization.serialize(cluster),
    )

    assert isinstance(restored, glyph.GlyphCluster)
    assert restored.text == "A "
    assert restored.source[0].word_char is True
    assert restored.source[1].interword_glue == spacing
    assert restored.layout.node_type == nd.NODE_TYPE.HLIST
    assert restored.layout.list[0].node_type == nd.NODE_TYPE.GLYPH
    assert restored.layout.list[0].glyph_id == layout.list[0].glyph_id
    assert restored.layout.list[1].automatic is True
    assert restored.width == cluster.width
