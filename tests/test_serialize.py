import pytest

from pytex import texlive
from pytex import dimen
from pytex import glue
from pytex import token
from pytex import serialization
from pytex import opentype
from pytex.font_backend import FontSpec


def dimenInfo(d):
    return {"pytex.dimen.Dimen": {"integer": d.value}}

def test_dimen(parser):
    d = dimen.Dimen(10)
    s = d.serialize()
    assert s == dimenInfo(d)
    v = serialization.deserialize(parser, s)
    assert v == d


def test_dimen_array(parser):
    parser.parse("\\dimen0=10pt \\dimen1=\\dimen0")
    d = parser.dumpState()
    assert "dimen" in d
    assert serialization.serialize(d["dimen"][0]) == dimenInfo(dimen.Dimen(10))
    assert serialization.serialize(d["dimen"][1])== dimenInfo(dimen.Dimen(10))
    

def glueInfo(g):
    return {
        "pytex.glue.Glue": {
            "dimen": float(g.dimen), 
            "stretch": g.stretch.serialize(), 
            "shrink": g.shrink.serialize()
        }
    }


def test_glue(parser):
    g = glue.Glue(10)
    s = serialization.serialize(g.serialize())
    assert s == glueInfo(g)
    v = serialization.deserialize(parser, s)
    assert v == g


def test_toks(parser):
    parser.parse("\\toks0={abc\\relax}")
    d = serialization.serialize(parser.toks[0])
    v = serialization.deserialize(parser, d)
    assert len(v) == 4
    assert v[0].name == "a"
    assert v[0].catcode == token.CATCODE.LETTER
    assert v[1].name == "b"
    assert v[1].catcode == token.CATCODE.LETTER
    assert v[2].name == "c"
    assert v[2].catcode == token.CATCODE.LETTER
    assert v[3].name == "\\relax"
    assert v[3].catcode is None


def test_global_builtins_serialize_via_builtin_name(parser):
    equitable = serialization.serialize(parser.dumpState())["equitable"]
    for name in ["\\deadcycles", "\\insertpenalties", "\\prevdepth", "\\prevgraf", "\\badness", "\\nullfont"]:
        assert equitable[name] == {"pytex.serialization.Builtin": {"name": name}}


def test_macro_serialization_preserves_name(parser):
    parser.parse("\\def\\a#1{#1}")
    data = serialization.serialize(parser.lookup("\\a"))
    restored = serialization.deserialize(parser, data)
    assert restored.name == "\\a"
    assert restored.meaning(parser) == "macro:#1->#1"


def test_font_spec_serialization_preserves_lookup_request(parser):
    spec = FontSpec(
        "example.ttc",
        lookup="file",
        display_name="Example",
        font_number=2,
        options="mapping=tex-text",
        features="+liga",
    )

    assert serialization.deserialize(parser, serialization.serialize(spec)) == spec


def test_font_serialization_preserves_mutated_fontdimen_and_fontchar(parser):
    parser.parse(
        "\\font\\f=cmr10 at 10pt "
        "\\fontdimen2\\f=6pt \\fontdimen8\\f=123pt \\hyphenchar\\f=99"
    )
    font = parser.lookup("\\f")
    data = serialization.serialize(font)
    init = data["pytex.font.Font"]
    overrides = data["extra"]["param_overrides"]

    assert init["font_name"] == "cmr10"
    assert "kind" not in init
    assert overrides[0] is None
    assert overrides[1] is not None
    assert all(value is None for value in overrides[2:7])
    assert serialization.deserialize(parser, overrides[7]) == dimen.Dimen(123)
    assert "param" not in data["extra"]
    assert "spaceglue" not in data["extra"]

    restored = serialization.deserialize(parser, data)
    assert len(restored.param) == 8
    assert restored.param[1] == dimen.Dimen(6)
    assert float(restored.param[7]) == 123.0
    assert restored.fontchar["hyphenchar"] == 99
    assert restored.spaceglue == font.spaceglue


def test_font_serialization_preserves_zero_in_extra_fontdimen_slot(parser):
    parser.parse("\\font\\f=cmr10 at 10pt \\fontdimen8\\f=0pt")
    font = parser.lookup("\\f")

    data = serialization.serialize(font)
    overrides = data["extra"]["param_overrides"]
    restored = serialization.deserialize(parser, data)

    assert overrides[7] is not None
    assert len(restored.param) == 8
    assert restored.param[7] == dimen.Dimen()


def test_assigning_space_fontdimen_rebuilds_cached_space_glue(parser):
    parser.parse("\\font\\f=cmr10 at 10pt \\fontdimen2\\f=6pt")
    font = parser.lookup("\\f")

    assert font.param[1] == dimen.Dimen(6)
    assert font.spaceglue.dimen == dimen.Dimen(6)


def test_format_font_rebuilds_metrics_for_reflow_conversion(parser):
    parser.parse("\\font\\f=cmr10 at 10pt \\fontdimen2\\f=6pt \\fontdimen8\\f=123pt")
    source = parser.lookup("\\f")
    if source.backend.pfb_file is None:
        pytest.skip("cmr10 Type 1 font not found")
    data = serialization.serialize(source)
    parser.registerSupportedFontClasses(opentype.TrueTypeBackend)
    parser.font_size_in_bp = True

    restored = serialization.deserialize(parser, data)

    assert isinstance(restored.backend, opentype.Type1TrueTypeBackend)
    assert restored.at == source.at
    assert restored.param[:7] != source.param[:7]
    assert restored.param[1] == dimen.Dimen(6)
    assert restored.param[2] == restored.backend.fontdimen[2] * restored.at
    assert restored.spaceglue.dimen == restored.param[1]
    assert restored.param[7] == source.param[7]


def test_modified_nullfont_uses_sparse_font_serialization(parser):
    nullfont = parser.lookup("\\nullfont")
    original_param = list(nullfont.param)
    original_fontchar = dict(nullfont.fontchar)
    try:
        parser.parse("\\fontdimen8\\nullfont=123pt")
        data = serialization.serialize(nullfont)

        assert "pytex.font.NullFont" in data
        assert all(value is None for value in data["extra"]["param_overrides"][:7])
        assert data["extra"]["param_overrides"][7] is not None

        restored = serialization.deserialize(parser, data)
        assert restored is nullfont
        assert restored.param[7] == dimen.Dimen(123)
    finally:
        nullfont.param[:] = original_param
        nullfont.fontchar = original_fontchar
        nullfont._rebuildSpaceGlue()
