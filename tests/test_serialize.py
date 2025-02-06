import pytest

from pytex import dimen
from pytex import glue
from pytex import token
from pytex import toks


def dimenInfo(d):
    return {
        "init": {"integer": d.value},
        "classname": "Dimen",
        "module": "pytex.dimen",
        "serializable": True
    }

def test_dimen(parser):
    d = dimen.Dimen(10)
    s = d.serialize()
    assert s == dimenInfo(d)
    v = dimen.Dimen.deserialize(parser, s)
    assert v == d


def test_dimen_array(parser):
    parser.parse("\\dimen0=10pt \\dimen1=\\dimen0")
    d = parser.state.dump()
    assert "dimen" in d
    assert d["dimen"] == {0: dimenInfo(dimen.Dimen(10)), 1: dimenInfo(dimen.Dimen(10))}
    

def glueInfo(g):
    return {
        "init": {
            "dimen": g.dimen, 
            "stretch": g.stretch.serialize(), 
            "shrink": g.shrink.serialize()
        },
        "classname": "Glue",
        "module": "pytex.glue",
        "serializable": True
    }


def test_glue(parser):
    g = glue.Glue(10)
    s = token.serialize(g.serialize())
    assert s == glueInfo(g)
    v = glue.Glue.deserialize(parser, s)
    assert v == g


def test_toks(parser):
    parser.parse("\\toks0={abc}")
    d = parser.state.toks[0].serialize()
    v = token.deserialize(parser, d)
    assert len(v) == 3
    assert v[0].name == "a"
    assert v[0].catcode == token.CATCODE.LETTER
    assert v[1].name == "b"
    assert v[1].catcode == token.CATCODE.LETTER
    assert v[2].name == "c"
    assert v[2].catcode == token.CATCODE.LETTER
