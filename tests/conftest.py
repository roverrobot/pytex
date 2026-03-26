"""
Module level fixtures
"""


import pytest
import types
from pytex.parser import Parser
from pytex import page
from pytex.token import CATCODE
from pytex.resolver import InMemoryTextFile


@pytest.fixture()
def parser(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = Parser()
    p.resolver.output_in_memory = True
    p.shipout = page.Shipout(p)
    p.state.catcode[ord("{")] = CATCODE.BEGIN_GROUP
    p.state.catcode[ord("}")] = CATCODE.END_GROUP
    p.state.catcode[ord("$")] = CATCODE.MATH_SHIFT
    p.state.catcode[ord("&")] = CATCODE.ALIGNMENT_TAB
    p.state.catcode[ord("#")] = CATCODE.PARAMETER
    p.state.catcode[ord("^")] = CATCODE.SUPERSCRIPT
    p.state.catcode[ord("_")] = CATCODE.SUBSCRIPT
    yield p
    p.close()


def addChar(self, c):
    self.tokens += c


def addSpace(self):
    self.tokens += " "


def getString(self):
    s = self.tokens
    self.tokens = ""
    return s

@pytest.fixture()
def collector(parser):
    parser.tokens = ""
    parser.addChar = types.MethodType(addChar, parser)
    parser.addSpace = types.MethodType(addSpace, parser)
    parser.getString = types.MethodType(getString, parser)
    return parser


@pytest.fixture
def cmr10(parser):
    parser.parse(
        '\\font\\f=cmr10 '
        '\\font\\sym=cmsy10 '
        '\\font\\ext=cmex10 '
        '\\f '
        '\\textfont2=\\sym \\scriptfont2=\\sym \\scriptscriptfont2=\\sym '
        '\\textfont3=\\ext \\scriptfont3=\\ext \\scriptscriptfont3=\\ext'
    )
    parser.state.sfcode[ord(",")] = 1250
    parser.state.sfcode[ord(".")] = 3000
    parser.state.sfcode[ord(")")] = 0
    return parser


@pytest.fixture()
def example_tex(parser):
    parser.resolver.in_memory_files["example.tex"] = InMemoryTextFile("Hello, world!\n")
    return parser
