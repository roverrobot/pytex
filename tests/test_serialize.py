import pytest

from pytex import dimen
from pytex import glue
from pytex import token
from pytex import serialization


def dimenInfo(d):
    return {
        "init": {"integer": d.value},
        "__classname__": "pytex.dimen.Dimen",
    }

def test_dimen(parser):
    d = dimen.Dimen(10)
    s = d.serialize()
    assert s == dimenInfo(d)
    v = serialization.deserialize(parser, s)
    assert v == d


def test_dimen_array(parser):
    parser.parse("\\dimen0=10pt \\dimen1=\\dimen0")
    d = parser.state.dump()
    assert "dimen" in d
    assert serialization.serialize(d["dimen"][0]) == dimenInfo(dimen.Dimen(10))
    assert serialization.serialize(d["dimen"][1])== dimenInfo(dimen.Dimen(10))
    

def glueInfo(g):
    return {
        "init": {
            "dimen": dimenInfo(g.dimen), 
            "stretch": g.stretch.serialize(), 
            "shrink": g.shrink.serialize()
        },
        "__classname__": "pytex.glue.Glue",
    }


def test_glue(parser):
    g = glue.Glue(10)
    s = serialization.serialize(g.serialize())
    assert s == glueInfo(g)
    v = serialization.deserialize(parser, s)
    assert v == g


def test_toks(parser):
    parser.parse("\\toks0={abc\\relax}")
    d = serialization.serialize(parser.state.toks[0])
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
