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
    d0 = parser.dimen[0]
    assert d0 == 10


def test_read_true_dimen(parser):
    # magnify by a factor of 2.0
    parser.parameters["mag"] = 2000
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


def test_dimen_division_truncates_toward_zero_scaled_point():
    assert Dimen(integer=1) / 2 == Dimen(integer=0)
    assert Dimen(integer=-1) / 2 == Dimen(integer=0)


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
    assert parser.dimen[0] == 12
    assert parser.dimen[1] == -12


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


def test_dimen_repr_matches_tex_print_scaled():
    assert repr(Dimen(integer=65536)) == "1.0"
    assert repr(Dimen(integer=4736286)) == "72.26999"
    assert repr(Dimen(integer=40258437)) == "614.295"
    assert repr(Dimen(integer=30785865)) == "469.75502"


def test_pt_and_in_parsing_match_tex_scaled_points(parser):
    parser.parse("\\dimen0=72.27pt\\dimen1=1in")
    assert int(parser.dimen[0]) == 4736287
    assert int(parser.dimen[1]) == 4736286


def test_inch_decimal_coefficient_uses_tex_integer_path(parser):
    parser.parse("\\dimen0=12.3in")
    assert int(parser.dimen[0]) == 58256341


def test_read_mu_decimal_uses_scaled_rounding(parser):
    parser.readFrom("1.5mu")
    result = parser.readDimen(mu=True)
    assert int(result) == 98304


def test_parsing_print_scaled_pt_round_trips_scaled_value(parser):
    s = repr(Dimen(integer=30785865))
    parser.parse(f"\\dimen0={s}pt")
    assert int(parser.dimen[0]) == 30785865
