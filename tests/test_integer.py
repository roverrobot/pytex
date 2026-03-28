import pytest
from pytex.token import Token, CATCODE
from tests import checkValues
import datetime


def test_read_integer_dec(parser):
    parser.readFrom("123 a")
    result = parser.readInteger()
    assert result == 123
    t = parser.token_expand()
    assert t is not None
    assert t.catcode == CATCODE.LETTER
    assert t.name == "a"

def test_read_integer_oct(parser):
    parser.readFrom("'10")
    result = parser.readInteger()
    assert result == 8

def test_read_integer_hex(parser):
    parser.readFrom('"10')
    result = parser.readInteger()
    assert result == 16

def test_read_integer_char(parser):
    parser.readFrom("`a")
    result = parser.readInteger()
    assert result == 97
    parser.readFrom("`\\a")
    result = parser.readInteger()
    assert result == 97

    
def test_read_signed_integer(parser):
    parser.readFrom("-123")
    result = parser.readInteger()
    assert result == -123
    parser.readFrom("+123")
    result = parser.readInteger()
    assert result == 123
    parser.readFrom("--123")
    result = parser.readInteger()
    assert result == 123
    parser.readFrom("-+123")
    result = parser.readInteger()
    assert result == -123
    parser.readFrom("++123")
    result = parser.readInteger()
    assert result == 123

def test_read_integer_error(parser):
    try:
        parser.readFrom("abc")
        result = parser.readInteger()
    except ValueError as e:
        assert "integer" in str(e)

def test_integer_array(parser):
    checkValues(parser, "\\count0=1", [["count", 0, 1]])
    checkValues(parser, "\\count0 2", [["count", 0, 2]])
    checkValues(parser, "\\count1=-\\count0", [["count", 1, -2]])
    checkValues(parser, "{\\count1=1", [["count", 1, 1]])
    checkValues(parser, "}", [["count", 1, -2]])
    checkValues(parser, "{\\global\\count1=1}", [["count", 1, 1]])

def test_global_integer(parser):
    checkValues(parser, "{\\prevgraf=7", [["globals", "prevgraf", 7]])
    dump = parser.dumpState()
    assert "globals" not in dump

def test_chardef(collector):
    collector.parse("\\chardef\\a=65 \\a")
    assert collector.getString() == "A"
    collector.parse("\\count0=\\a")
    assert collector.count[0] == 65

def test_mathchardef(parser):
    parser.parse("\\mathchardef\\a=65 \\count0=\\a")
    assert parser.count[0] == 65


def test_date(collector):
    collector.parse("\\the\\year-\\the\\month-\\the\\day")
    date = datetime.date.today()
    assert collector.getString() == f"{date.year}-{date.month}-{date.day}"
