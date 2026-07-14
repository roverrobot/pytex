from types import SimpleNamespace

from pytex import svg


def test_svg_glyph_cache_accepts_glyph_name_and_id():
    by_name = object()
    by_id = object()
    cache = svg.GlyphCache.__new__(svg.GlyphCache)
    cache.font = SimpleNamespace(getGlyphName=lambda glyph_id: {12: "by-id"}[glyph_id])
    cache.glyph_set = {"by-name": by_name, "by-id": by_id}
    cache.cmap = {}

    named = SimpleNamespace(glyph_name="by-name", glyph_id=None, char=None)
    numbered = SimpleNamespace(glyph_name=None, glyph_id=12, char=None)

    assert cache[named] is by_name
    assert cache[numbered] is by_id
