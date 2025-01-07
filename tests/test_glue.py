import pytest
from pytex.glue import Glue, Stretchness, MuGlue, MuStretchness
from tests import checkValues


def test_read_glue(parser):
    parser.readFrom("10 pt a")
    result = parser.readGlue()
    assert result == Glue(10)
    t = parser.token_expand()
    assert t is not None
    assert t.name == 'a'
    parser.readFrom("-10in plus 1pt m")
    result = parser.readGlue()
    assert result == Glue(-10*72.27, Stretchness(1, 0))
    t = parser.token_expand()
    assert t is not None
    assert t.name == 'm'
    parser.readFrom("-10in minus 1pt")
    result = parser.readGlue()
    assert result == Glue(-10*72.27, shrink=Stretchness(1, 0))
    parser.readFrom("-10in plus 1pt minus 2fillll")
    result = parser.readGlue()
    assert result == Glue(-10*72.27, Stretchness(1, 0), Stretchness(2, 3))
    t = parser.token_expand()
    assert t is None
        

def test_read_mu(parser):
    parser.readFrom("10 mu")
    result = parser.readGlue(mu=True)
    assert result == MuGlue(10)
    parser.readFrom("-10mu plus 1fil minus 2mu")
    result = parser.readGlue(mu=True)
    assert result == MuGlue(-10, MuStretchness(1, 1), MuStretchness(2, 0))
    parser.readFrom("-10mu plus 1pt")
    try:
        result = parser.readGlue(mu=True)
        assert False, "cannot accept pt as unit when reading a mu glue"
    except Exception as e:
        assert "mu dimension expected" in str(e)


def test_glue_array(parser):
    orig = Glue(10, Stretchness(1, 0), Stretchness(2, 1))
    checkValues(parser, "\\skip0 = 10 pt plus 1pt minus 2fil", [["skip", 0, orig]])
    checkValues(parser, "{\\skip0 = 1 pt", [["skip", 0, Glue(1)]])
    checkValues(parser, "}", [["skip", 0, orig]])


def test_muglue_array(parser):
    orig = MuGlue(10, MuStretchness(1, 0), MuStretchness(2, 1))
    checkValues(parser, "\\muskip0 = 10 mu plus 1mu minus 2fil", [["muskip", 0, orig]])
    try:
        parser.parse("\\muskip0 = 1 pt")
        assert False, "cannot accept pt as unit when reading a mu glue"
    except Exception as e:
        assert "mu dimension expected" in str(e)
