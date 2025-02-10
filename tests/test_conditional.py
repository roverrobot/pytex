import pytest


def test_if(collector):
    collector.parse("\\if00a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\if00\\else b\\fi")
    assert collector.getString() == ""
    collector.parse("\\if01a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\if01a\\fi")
    assert collector.getString() == ""


def test_missing_fi(collector):
    try:
        collector.parse("\\if00a\\else b")
        assert False, "missing \\fi"
    except ValueError as e:
        assert "\\fi" in str(e)


def tesst_misplaced_fi(parser):
    try:
        parser.parse("\\fi")
        assert False, "extra \\fi"
    except ValueError as e:
        assert "\\fi" in str(e)


def test_misplaced_else(parser):
    try:
        parser.parse("\\else")
        assert False, "extra \\else"
    except ValueError as e:
        assert "\\else" in e.args[0] # e has the position as the second argument


def test_misplaced_or(parser):
    try:
        parser.parse("\\if00a\\or b\\fi")
        assert False, "misplaced \\or"
    except ValueError as e:
        assert "\\or" in str(e)
    

def test_ifx(collector):
    collector.parse("\\def\\a{a}\\def\\b{a}\\ifx\\a\\b a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\def\\a{0}\\ifx\\a 0 a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\ifx\\undefined\\nosuchcommand a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\let\\a=1\\ifx\\a1a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\let\\a=1\\ifx\\a2a\\else b\\fi")
    assert collector.getString() == "b"
    


def test_ifcase(collector):
    collector.parse("\\ifcase0 a\\or b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\ifcase1 a\\or b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\ifcase2 a\\or b\\fi")
    assert collector.getString() == ""
    collector.parse("\\ifcase4 a\\or b\\else c\\fi")
    assert collector.getString() == "c"


def test_ifnum(collector):
    collector.parse("\\count0 1\\count 1 2")
    collector.parse("\\ifnum \\count0=\\count1 a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\ifnum 1>\\count1 a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\ifnum 1=\\count0 a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\ifnum 1=2 a\\else b\\fi")
    assert collector.getString() == "b"


def test_ifnum_miss_number(parser):
    try:
        parser.parse("\\ifnum 1\\else\\fi")
        assert False, "missing number"
    except ValueError as e:
        assert "expecting" in str(e)


def test_ifnum_miss_comparison(parser):
    try:
        parser.parse("\\ifnum 1 2\\else\\fi")
        assert False, "missing comparison"
    except ValueError as e:
        assert "comparison" in str(e)


def test_ifnum_not_number(parser):
    try:
        parser.parse("\\ifnum 1=a\\else\\fi")
        assert False, "not a number"
    except ValueError as e:
        assert "integer" in str(e)


def test_ifdim(collector):
    collector.parse("\\dimen0 1pt\\dimen1 2pt")
    collector.parse("\\ifdim\\dimen0<\\dimen1 a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\ifdim 2pt>\\dimen1 a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\ifdim 1pt>\\dimen1 a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\ifdim 1pt=\\dimen0 a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\ifdim 1pt=\\dimen1 a\\else b\\fi")
    assert collector.getString() == "b"


def test_ifdim_miss_unit(parser):
    try:
        parser.parse("\\ifdim 1\\else\\fi")
        assert False, "missing unit"
    except ValueError as e:
        assert "expected" in str(e)


def test_ifdim_miss_value(parser):
    try:
        parser.parse("\\ifdim 1pt\\else\\fi")
        assert False, "missing value"
    except ValueError as e:
        assert "expecting" in str(e)


def test_ifdim_miss_comparison(parser):
    try:
        parser.parse("\\ifdim 1pt 2pt\\else\\fi")
        assert False, "missing comparison"
    except ValueError as e:
        assert "comparison" in str(e)


def test_ifdim_not_number(parser):
    try:
        parser.parse("\\ifdim 1pt=a\\else\\fi")
        assert False, "not a number"
    except ValueError as e:
        assert "number" in str(e)


def test_ifodd(collector):
    collector.parse("\\ifodd1 a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\ifodd2 a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\count0 3 \\ifodd\\count0 a\\else b\\fi")
    assert collector.getString() == "a"


def test_iftrue_iffalse(collector):
    collector.parse("\\iftrue a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\iffalse a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\iftrue a\\fi")
    assert collector.getString() == "a"
    collector.parse("\\iffalse a\\fi")
    assert collector.getString() == ""


def test_multi_levels(collector):
    collector.parse("\\iftrue\\iffalse a\\else b\\fi\\else c\\fi")
    assert collector.getString() == "b"
    assert len(collector.ifstack) == 0
    collector.parse("\\iftrue a\\else\\iffalse a\\else b\\fi\\fi")
    assert collector.getString() == "a"
    assert len(collector.ifstack) == 0


def test_ifvmode(collector):
    collector.parse("\\ifvmode a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\ifvmode a\\fi")
    assert collector.getString() == "a"
