import pytest

from pytex import texlive
from pytex import dimen
from pytex import glue
from pytex import token
from pytex import serialization


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


def test_font_serialization_preserves_mutated_fontdimen_and_fontchar(parser):
    parser.parse("\\font\\f=cmr10 at 10pt \\fontdimen8\\f=123pt \\hyphenchar\\f=99")
    font = parser.lookup("\\f")
    data = serialization.serialize(font)
    restored = serialization.deserialize(parser, data)
    assert len(restored.param) == 8
    assert float(restored.param[7]) == 123.0
    assert restored.fontchar["hyphenchar"] == 99
    assert restored.spaceglue == font.spaceglue
