import pytest
from tests import checkValues
from pytex import texlive


def test_read_dimen(parser):
    parser.readFrom("10 pt")
    result = parser.readDimen()
    assert result == 10
    parser.readFrom("-10in")
    result = parser.readDimen()
    assert result == -10*72.27
    parser.readFrom("-1Truept")
    result = parser.readDimen()
    assert result == -1
    parser.readFrom("-1 true pt")
    result = parser.readDimen()
    assert result == -1


def test_read_true_dimen(parser):
    # magnify by a factor of 2.0
    parser.state.layout["mag"] = 2000
    parser.readFrom("-1Truept")
    result = parser.readDimen()
    assert result == -2
    parser.readFrom("-1 true em")
    try:
        parser.readDimen()
        assert False, "em cannot follow true"
    except Exception as e:
        assert "unit" in str(e)
    

def test_read_mu(parser):
    parser.readFrom("10 mu")
    result = parser.readDimen(mu=True)
    assert result == 10


def test_read_dimen_with_invalid_unit(parser):
    parser.readFrom("10 pt")
    try:
        parser.readDimen(mu=True)
        assert False, "cannot accept pt as unit when reading in mu dimension"
    except Exception as e:
        assert "mu dimension expected" in str(e)
    parser.readFrom("10 p")
    try:
        parser.readDimen()
        assert False, "cannot accept invalid unit"
    except Exception as e:
        assert "dimension unit expected" in str(e)


def test_dimen_array(parser):
    checkValues(parser, "\\dimen0 1 pt", [["dimen", 0, 1]])
    checkValues(parser, "\\dimen0 = 10 pt", [["dimen", 0, 10]])
    checkValues(parser, "{\\dimen0 = 1 pt", [["dimen", 0, 1]])
    checkValues(parser, "}", [["dimen", 0, 10]])


def test_dimen_parameter(parser):
    checkValues(parser, "\\hsize = 10 pt", [["layout", "hsize", 10]])
    checkValues(parser, "{\\hsize = 1 pt", [["layout", "hsize", 1]])
    checkValues(parser, "}", [["layout", "hsize", 10]])


def test_em_ex(parser):
    parser.parse("\\font\\f=cmr10 \\f")
    parser.readFrom("1 em")
    result = parser.readDimen()
    assert result == 10.00002
    parser.readFrom("1 ex")
    result = parser.readDimen()
    assert result == 4.30554