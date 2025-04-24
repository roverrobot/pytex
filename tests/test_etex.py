import pytest
from pytex import etex
from pytex import conditional
from pytex import texlive


def test_numexpr(collector):
    collector.parse("\\the\\numexpr(128-63/2)/64\\relax")
    assert collector.getString() == "2"
    collector.parse("\\the\\numexpr7/4\\relax")
    assert collector.getString() == "2"
    collector.parse("\\the\\numexpr7/5\\relax")
    assert collector.getString() == "1"
    collector.parse("\\number\\numexpr (3+2) / 3 + 2")
    assert collector.getString() == "4"
    collector.parse("\\the\\numexpr-1/2\\relax")
    assert collector.getString() == "-1"

def test_loop(collector):
    collector.parse("""%
        \\def\\foo#1#2{\\number#1
        \\ifnum#1<#2,
        \\expandafter\\foo
        \\expandafter{\\number\\numexpr#1+1\\expandafter}%
        \\expandafter{\\number#2\\expandafter}%
        \\fi}
    """)
    collector.parse("\\foo{1}{5}")
    assert collector.getString() == " 1, 2, 3, 4, 5 "

def test_dimexpr(collector):
    collector.parse("\\dimen0=\\dimexpr 1pt + (2pt - 3pt)/2 \\relax\\the\\dimen0")
    assert collector.getString() == "0.5pt"

def test_glueexpr(collector):
    collector.parse("\\the\\glueexpr (1pt plus 2pt minus 3pt)*2+1pt")
    assert collector.getString() == "3.0pt plus 4.0pt minus 6.0pt"

def test_muexpr(collector):
    collector.parse("\\the\\muexpr 1mu + 2mu/4")
    assert collector.getString() == "1.5mu plus 0.0mu minus 0.0mu"

def test_ifdefined(collector):
    collector.parse("\\ifdefined\\undefined a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\ifdefined\\count a\\else b\\fi")
    assert collector.getString() == "a"

def test_ifcsname(collector):
    collector.parse("\\ifcsname undefined\\endcsname a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\ifcsname count\\endcsname a\\else b\\fi")
    assert collector.getString() == "a"

def test_iffontchar(collector):
    collector.parse("\\font\\f=cmr10 \\f")
    collector.parse("\\iffontchar\\font 65 a\\else b\\fi")
    assert collector.getString() == "a"
    collector.parse("\\iffontchar\\font 366 a\\else b\\fi")
    assert collector.getString() == "b"

def test_unless(collector):
    collector.parse("\\unless\\iftrue a\\else b\\fi")
    assert collector.getString() == "b"
    collector.parse("\\unless\\iffalse a\\else b\\fi")
    assert collector.getString() == "a"

def test_fontchar_dimen(collector):
    collector.parse("\\font\\f=cmr10 \\f")
    collector.parse("\\the\\fontcharwd\\font 65")
    assert collector.getString() == "7.50002pt"
    collector.parse("\\the\\fontcharht\\font 65")
    assert collector.getString() == "6.83331pt"
    collector.parse("\\the\\fontchardp\\font 65")
    assert collector.getString() == "0.0pt"

def test_gluestretchness(collector):
    collector.parse("\\skip0= 0pt plus 1pt minus 2filll")
    collector.parse("\\the\\gluestretchorder\\skip0")
    assert collector.getString() == "0"
    collector.parse("\\the\\gluestretch\\skip0")
    assert collector.getString() == "1.0pt"
    collector.parse("\\the\\glueshrinkorder\\skip0")
    assert collector.getString() == "3"
    collector.parse("\\the\\glueshrink\\skip0")
    assert collector.getString() == "2.0pt"
