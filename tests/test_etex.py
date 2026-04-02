import pytest
from pytex.accessor import VALUE_TYPE
from pytex import box as bx
from pytex import conditional
from pytex import glue
from pytex import texlive
from pytex import macro
from pytex import node as nd
from pytex import token
from pytex.module import ModuleManager
from pytex.expandable import toToks, toksToString
from tests.test_vmode import _test_hbox


@pytest.fixture(scope="module", autouse=True)
def _enable_etex_module():
    from pytex import etex
    ModuleManager["etex"] = etex.mod
    try:
        yield
    finally:
        ModuleManager.pop("etex", None)


def _mark(text, index=0):
    node = nd.Mark(toToks(text))
    node.index = index
    return node


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


def test_read_internal_integer_from_dimexpr(parser):
    parser.readFrom("\\dimexpr 1pt\\relax")
    assert parser.readInternalValue(VALUE_TYPE.INT) == 65536

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
    collector.parse("\\ifdefined1a\\else b\\fi")
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


def test_font_meaning_matches_tex_shape(parser):
    parser.parse("\\font\\f=cmr10 at 1pt")
    assert parser.lookup("\\f").meaning(parser) == "select font cmr10 at 1.0pt"


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

def test_readline(example_tex):
    example_tex.parse("\\openin 0=example \\readline 0 to \\a\\closein 0")
    s = "Hello, world!\r"
    a = example_tex.equitable["\\a"]
    assert isinstance(a, macro.Macro)
    assert len(a.replacement) == len(s)
    i = iter(a.replacement)
    for c in s:
        r = next(i)
        assert c == r.name
        cat = token.CATCODE.SPACE if r.name == " " else token.CATCODE.OTHER
        assert r.catcode == cat


def test_scantokens_retokenizes_string_input(collector):
    collector.parse("\\def\\a{A}\\scantokens{\\a}")
    assert collector.getString() == "A "


def test_marks_value_commands_expand(collector):
    collector.globals["topmarks"] = [toToks("A"), toToks("BC")]
    collector.globals["firstmarks"] = [toToks("D")]
    collector.globals["botmarks"] = [toToks("E"), [], toToks("FG")]
    collector.globals["splitfirstmarks"] = [toToks("H"), toToks("I")]
    collector.globals["splitbotmarks"] = [toToks("J")]
    collector.parse("\\topmarks1\\firstmarks0\\botmarks2\\splitfirstmarks1\\splitbotmarks0")
    assert collector.getString() == "BCDFGIJ"


def test_toks_assignment_reads_marks_value_target(parser):
    parser.globals["topmarks"] = [toToks("A"), toToks("BC")]
    parser.parse("\\toks0=\\topmarks1")
    assert toksToString(parser, parser.toks[0]) == "BC"


def test_page_break_updates_marks_registers(parser):
    parser.parse("\\vsize=10pt\\topskip=0pt")
    main = parser.lists[0]
    main.append(_test_hbox(parser, height=6, depth=0))
    main.append(_mark("A", 0))
    main.append(_mark("X", 2))
    main.append(nd.Glue(glue.Glue(4), None))
    main.append(_test_hbox(parser, height=6, depth=0))
    main.append(_mark("B", 0))
    main.append(_mark("Y", 2))
    parser.end()
    pages = parser.shipout.pages
    assert len(pages) == 2
    assert toksToString(parser, parser.globals["topmarks"][0]) == "A"
    assert toksToString(parser, parser.globals["firstmarks"][0]) == "B"
    assert toksToString(parser, parser.globals["botmarks"][0]) == "B"
    assert toksToString(parser, parser.globals["topmarks"][2]) == "X"
    assert toksToString(parser, parser.globals["firstmarks"][2]) == "Y"
    assert toksToString(parser, parser.globals["botmarks"][2]) == "Y"


def test_vsplit_updates_split_marks_registers(parser):
    source = bx.VBox(parser, None, 0)
    source.list.append(_mark("A", 0))
    source.list.append(_mark("X", 3))
    source.list.append(_test_hbox(parser, height=6, depth=2))
    source.list.append(_mark("Y", 3))
    source.list.append(_test_hbox(parser, height=6, depth=2))
    parser.box[1] = source
    parser.parse("\\setbox2=\\vsplit1 to 50pt")
    assert toksToString(parser, parser.globals["splitfirstmarks"][0]) == "A"
    assert toksToString(parser, parser.globals["splitbotmarks"][0]) == "A"
    assert toksToString(parser, parser.globals["splitfirstmarks"][3]) == "X"
    assert toksToString(parser, parser.globals["splitbotmarks"][3]) == "Y"
