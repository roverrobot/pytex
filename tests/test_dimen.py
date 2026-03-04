import pytest
from tests import checkValues
from pytex import texlive
from pytex.dimen import Dimen


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
    parser.parse("\\count0=10 \\dimen0=\\count0pt")
    d0 = parser.state.dimen[0]
    assert d0 == 10


def test_read_true_dimen(parser):
    # magnify by a factor of 2.0
    parser.state.parameters["mag"] = 2000
    parser.readFrom("-1Truept")
    result = parser.readDimen()
    assert result == -0.5 # handling true dimension is done by reducing the unit by \mag/1000
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


def test_dimen_division_rounds_to_nearest_scaled_point():
    assert Dimen(integer=1) / 2 == Dimen(integer=1)
    assert Dimen(integer=-1) / 2 == Dimen(integer=-1)


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


def test_negated_internal_dimen_does_not_mutate_source(parser):
    parser.parse("\\dimen0=12pt\\dimen1=-\\dimen0")
    assert parser.state.dimen[0] == 12
    assert parser.state.dimen[1] == -12


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
