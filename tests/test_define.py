import pytest
from pytex.token import CATCODE
from tests import checkValues

def test_let(collector):
    collector.parse("\\let\\a= 1\\a")
    assert collector.getString() == "1"
    try:
        collector.parse("\\let\\a=1\\count\\a=2")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "integer" in e.args[0]
    try:
        collector.parse("\\let\\a=1\\count0=\\a")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "integer" in e.args[0]

def test_futurelet(collector):
    collector.parse("\\futurelet\\a01\\a")
    assert collector.getString() == "01"

def test_chardef(collector):
    checkValues(collector, "\\chardef\\a=`a \\a\\count0=\\a", [["count", 0, ord("a")]])
    assert collector.getString() == "a"

def test_countdef(parser):
    parser.parse("\\countdef\\a=0")
    checkValues(parser, "\\a=1", [["count", 0, 1]])
    checkValues(parser, "\\count1=-\\a", [["count", 1, -1]])

def test_afterassignment(collector):
    collector.parse("\\afterassignment a{\\count0=1}")
    assert collector.getString() == "a "


def test_macro_definition(parser):
    parser.parse("\\def\\a{1}")
    a = parser.lookup("\\a")
    assert a is not None
    assert len(a.parameters) == 0
    assert len(a.replacement) == 1
    assert a.replacement[0].name == "1"
    parser.parse("\\def\\a#1{#1}")
    a = parser.lookup("\\a")
    assert a is not None
    assert len(a.parameters) == 2
    assert a.parameters[0].catcode == CATCODE.PARAMETER
    assert a.parameters[1].name == "1"
    assert len(a.replacement) == 2
    assert a.replacement[0].catcode == CATCODE.PARAMETER
    assert a.replacement[1].name == "1"
    parser.parse("\\def\\a#1#2{#1#2}")
    a = parser.lookup("\\a")
    assert a is not None
    assert len(a.parameters) == 4
    assert a.parameters[0].catcode == CATCODE.PARAMETER
    assert a.parameters[1].name == "1"
    assert a.parameters[2].catcode == CATCODE.PARAMETER
    assert a.parameters[3].name == "2"
    assert len(a.replacement) == 4
    assert a.replacement[0].catcode == CATCODE.PARAMETER
    assert a.replacement[1].name == "1"
    assert a.replacement[2].catcode == CATCODE.PARAMETER
    assert a.replacement[3].name == "2"
    parser.parse("\\def\\a12 {1}")
    a = parser.lookup("\\a")
    assert a is not None
    assert len(a.parameters) == 3
    assert a.parameters[0].name == "1"
    assert a.parameters[1].name == "2"
    assert a.parameters[2].name == " "
    assert len(a.replacement) == 1
    assert a.replacement[0].name == "1"
    parser.parse("\\def\\a1#12{}")
    a = parser.lookup("\\a")
    assert a is not None
    assert len(a.parameters) == 4
    assert a.parameters[0].name == "1"
    assert a.parameters[1].catcode == CATCODE.PARAMETER
    assert a.parameters[2].name == "1"
    assert a.parameters[3].name == "2"
    assert len(a.replacement) == 0
    parser.parse("\\def\\a1#12#2{}")
    a = parser.lookup("\\a")
    assert a is not None
    assert len(a.parameters) == 6
    assert a.parameters[0].name == "1"
    assert a.parameters[1].catcode == CATCODE.PARAMETER
    assert a.parameters[2].name == "1"
    assert a.parameters[3].name == "2"
    assert a.parameters[4].catcode == CATCODE.PARAMETER
    assert a.parameters[5].name == "2"
    assert len(a.replacement) == 0

def test_macro_definition_errors(parser):
    try:
        parser.parse("\\def\\a1#12#2")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "{" in str(e)
    try:
        parser.parse("\\def\\a1#12#2{")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "unbalanced" in str(e)
    try:
        parser.parse("\\def\\a1#2{}")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "consecutively" in str(e)

def test_macro_expansion(collector):
    collector.parse("\\def\\a{1}\\a")
    assert collector.getString() == "1"
    collector.parse("\\def\\a#1{#1}\\a{2}")
    assert collector.getString() == "2 "
    collector.parse("\\def\\a#1#2{#1#2}\\a{1} 2")
    assert collector.getString() == "12 "
    collector.parse("\\def\\a12 {1}\\a12")
    assert collector.getString() == "1"
    collector.parse("\\def\\a1#12{#1}\\a1{2}2")
    assert collector.getString() == "2 "
    collector.parse("\\def\\a1#12#2{#1#2}\\a1{2}23")
    assert collector.getString() == "23 "

def test_macro_expansion_errors(parser):
    try:
        parser.parse("\\def\\a1#12#2{#1#2}\\a1{2}")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "match" in str(e)
    try:
        parser.parse("\\def\\a1#12#2b{#1#2}\\a1{2}2{3}a")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "match" in str(e)


def test_prefixes(parser):
    parser.parse("\\def\\a{1}\\long\\def\\b{2}{\\global\\def\\c{3}}\\outer\\def\\d{4}")
    a = parser.lookup("\\a")
    assert a is not None
    assert not a.long
    assert not a.outer
    b = parser.lookup("\\b")
    assert b is not None
    assert b.long
    assert not b.outer
    c = parser.lookup("\\c")
    assert c is not None
    assert not c.long
    assert not c.outer
    d = parser.lookup("\\d")
    assert d is not None
    assert not d.long
    assert d.outer
    parser.parse("{\\global\\outer\\def\\e{5}}")
    e = parser.lookup("\\e")
    assert e is not None
    assert not e.long
    assert e.outer

def test_prefix_errors(parser):
    try:
        parser.parse("\\outer\\let\\f6")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "macro" in str(e)
    
def test_edef_gdef(collector):
    collector.parse("\\def\\a{1}\\edef\\b{\\a}\\b")
    assert collector.getString() == "1"
    b = collector.lookup("\\b")
    assert b is not None
    assert len(b.replacement) == 1
    assert b.replacement[0].name == "1"
    collector.parse("{\\gdef\\a{2}}\\a")
    assert collector.getString() == "2"

def test_xdef_errors(parser):
    try:
        parser.parse("\\xdef\\c{\\a}")
        assert False, "Expected ValueError"
    except ValueError as e:
        assert "defined" in str(e)

def test_protected(collector):
    collector.parse("\\toks0={\\a}\edef\\b{\\the\\toks0}\\def\\a{1}\\b")
    assert collector.getString() == "1"
    b = collector.lookup("\\b")
    assert b is not None
    assert len(b.replacement) == 1
    assert b.replacement[0].name == "\\a"
    collector.parse("\\the\\toks0")
    assert collector.getString() == "1"
