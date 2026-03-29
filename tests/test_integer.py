import pytest
from pytex.token import Token, CATCODE
from pytex.token import Command
from pytex.accessor import AttrTarget
from pytex.accessor import VALUE_TYPE
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


def test_read_internal_integer_from_chardef_target(parser):
    parser.parse("\\chardef\\a=65")
    parser.readFrom("\\a")
    assert parser.readInternalValue(VALUE_TYPE.INT) == 65


def test_read_internal_integer_from_mathchardef_target(parser):
    parser.parse("\\mathchardef\\a=65")
    parser.readFrom("\\a")
    assert parser.readInternalValue(VALUE_TYPE.INT) == 65


def test_read_internal_integer_from_inputlineno_target(parser):
    parser.readFrom("\\inputlineno")
    assert parser.readInternalValue(VALUE_TYPE.INT) == 1


def test_chardef_target_is_read_only(parser):
    parser.parse("\\chardef\\a=65")
    target = parser.lookup("\\a").getTarget(parser)
    with pytest.raises(ValueError, match="not writable"):
        target.set(66)


def test_mathchardef_target_is_read_only(parser):
    parser.parse("\\mathchardef\\a=65")
    target = parser.lookup("\\a").getTarget(parser)
    with pytest.raises(ValueError, match="not writable"):
        target.set(66)


def test_advance_rejects_read_only_chardef_target(parser):
    with pytest.raises(ValueError, match="not writable"):
        parser.parse("\\chardef\\a=0 \\advance\\a by 1")


def test_advance_rejects_read_only_mathchardef_target(parser):
    with pytest.raises(ValueError, match="not writable"):
        parser.parse("\\mathchardef\\a=0 \\advance\\a by 1")


def test_read_internal_integer_rejects_write_only_target(parser):
    class WriteOnlyInteger(Command):
        def __init__(self, value):
            self.value = value

        def getTarget(self, parser):
            return AttrTarget(self, "value", VALUE_TYPE.INT, readable=False)

    parser.equitable["\\a"] = WriteOnlyInteger(7)
    parser.readFrom("\\a")
    assert parser.readInternalValue(VALUE_TYPE.INT) is None
    t = parser.token_expand()
    assert t is not None
    assert t.name == "\\a"


def test_integer_reader_uses_target_cast_for_dimensions(parser):
    parser.parse("\\dimen0=123pt \\count0=\\dimen0")
    assert parser.count[0] == int(parser.dimen[0])


def test_read_internal_integer_from_count_target(parser):
    parser.parse("\\count0=123")
    parser.readFrom("\\count0")
    assert parser.readInternalValue(VALUE_TYPE.INT) == 123


def test_integer_reader_preserves_outer_target(parser):
    parser.parse("\\count0=1 \\count1=2 \\count0=\\count1")
    assert parser.count[0] == 2


def test_date(collector):
    collector.parse("\\the\\year-\\the\\month-\\the\\day")
    date = datetime.date.today()
    assert collector.getString() == f"{date.year}-{date.month}-{date.day}"
