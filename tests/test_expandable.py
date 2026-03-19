import pytest
from pytex.resolver import InMemoryTextFile
from pytex import lexer
from pytex import macro
from pytex.token import ParameterToken, CATCODE


def test_noexpand(parser):
    parser.readFrom("\\noexpand\\test")
    t = parser.token_expand()
    assert t is not None
    assert t.name == "\\test"
    t = parser.token_expand()
    assert t is None
    parser.readFrom("\\noexpand a")
    t = parser.token_expand()
    assert t is not None
    assert t.name == "a"
    parser.parse("\\def\\a{1}\\edef\\b{\\noexpand\\a}")
    b = parser.state.equitable["\\b"]
    assert b.replacement[0].name == "\\a"

def test_noexpand_ifx(collector):
    collector.parse("\\expandafter\\ifx \\noexpand\\a\\a a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\chardef\\a=1 \\expandafter\\ifx \\noexpand\\a\\a a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\def\\a{1}\\expandafter\\ifx \\noexpand\\a\\a a\\else b\\fi")
    assert collector.getString() == "b"

def test_expandafter(collector):
    collector.parse("\\def\\a{a}\\expandafter a\\a")
    assert collector.getString() == "aa"


def test_csname(collector):
    collector.readFrom("\\csname test\\endcsname")
    t = collector.token_expand()
    assert t is not None and t.entry is not None
    t = collector.token_expand()
    assert t is None
    collector.parse("\\test")
    assert collector.getString() == ""
    collector.parse("\\def\\test{a}\\csname test\\endcsname")
    assert collector.getString() == "a"


def test_missing_endcsname(parser):
    try:
        parser.parse("\\csname test")
        assert False, "missing \\endcsname"
    except ValueError as e:
        assert "\\endcsname" in str(e)


def test_unexpected_command(parser):
    try:
        parser.parse("\\csname \\count\\endcsname")
        assert False, "expecting \\endcsname"
    except ValueError as e:
        assert "unexpected \\count" in e.args[0]


def test_misplaced_endcsname(parser):
    try:
        parser.parse("\\endcsname")
        assert False, "unexpected \\endcsname"
    except ValueError as e:
        assert "unexpected \\endcsname" in e.args[0]


def test_number_romannumeral(collector):
    collector.parse("\\count0=123 \\number\\count0")
    assert collector.getString() == "123"
    collector.parse("\\romannumeral\\count0")
    assert collector.getString() == "cxxiii"


def test_string(collector):
    collector.parse("\\escapechar=`! \\string\\test")
    assert collector.getString() == "!test"


def test_string_parameter_token(collector):
    collector.parse("\\string#")
    assert collector.getString() == "# "


def test_toks_to_string_expanded_flag(parser):
    t = ParameterToken("#", CATCODE.PARAMETER)
    assert parser.tokenToString(t) == "##"
    assert parser.tokenToString(t, expanded=True) == "#"
    assert parser.toksToString([t]) == "##"
    assert parser.toksToString([t], expanded=True) == "#"


def test_the(collector):
    collector.parse("\\count0=0 \\the\\count0")
    assert collector.getString() == "0"
    collector.parse("\\dimen0=1pt \\the\\dimen0")
    assert collector.getString() == str(collector.state.dimen[0])+"pt"
    collector.parse("\\skip0=1pt plus 1fil minus 1fil \\relax\\the\\skip0")
    assert collector.getString() == str(collector.state.skip[0])
    collector.parse("\\toks0={\\the\\count0}\\the\\toks0")
    assert collector.getString() == "0"


def test_input(collector):
    collector.resolver.in_memory_files["test.tex"] = InMemoryTextFile("abc")
    collector.parse("123\\input test")
    assert collector.getString() == "123abc "


def test_endinput(collector):
    collector.resolver.in_memory_files["test.tex"] = InMemoryTextFile("abc\\endinput\ndef")
    collector.parse("123\\input test")
    assert collector.getString() == "123abc"


def test_jobname(collector):
    collector.parse("\\jobname", "test")
    assert collector.getString() == "test"


def test_protected_tokens(parser):
    parser.parse("\\def\\a{123}\\toks0={\\a}\\edef\\b{\\the\\toks0}\\edef\\c{\\b}")
    c = parser.state.equitable["\\c"]
    assert isinstance(c, macro.Macro)
    assert len(c.replacement) == 3
