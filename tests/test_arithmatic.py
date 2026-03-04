import pytest
from tests import checkValues
from pytex.dimen import Dimen


def test_advance(parser):
    checkValues(parser, "\\dimen0 = 10 pt\\advance \\dimen0 by 10 pt", [["dimen", 0, 20]])
    checkValues(parser, "{\\advance \\dimen0 by 10 pt", [["dimen", 0, 30]])
    checkValues(parser, "}", [["dimen", 0, 20]])
    checkValues(parser, "{\\global \\advance \\dimen0 by 10 pt}", [["dimen", 0, 30]])

def test_invalid_unit(parser):
    try:
        parser.parse("\\advance \\dimen0 by 10")
        assert False, " a dimen must have a unit"
    except Exception as e:
        assert "dimension unit expected" in str(e)
        
def test_read_multiply(collector):
    checkValues(collector, "\\dimen0 = 10 pt\\multiply \\dimen0 by 2 pt", [["dimen", 0, 20]])
    assert collector.getString() == "pt "

    
def test_dimen_divide(parser):
    checkValues(parser, "\\dimen0 = 10 pt\\divide \\dimen0 by 2 pt", [["dimen", 0, 5]])


def test_dimen_divide_truncates_like_tex(parser):
    parser.parse("\\dimen0=16.71499pt\\divide\\dimen0 by 65536")
    assert parser.state.dimen[0] == Dimen(integer=16)


def test_int_divide(parser):
    checkValues(parser, "\\count0 = 7 \\divide \\count0 by 5 pt", [["count", 0, 1]])
    checkValues(parser, "\\count0 = 7 \\divide \\count0 by 4 pt", [["count", 0, 1]])
