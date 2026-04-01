"""
Module level fixtures
"""


import pytest
import types
from pytex.parser import Parser
from pytex.typeset.shipout import Shipout
from pytex.token import CATCODE
from pytex.resolver import InMemoryTextFile


@pytest.fixture()
def parser(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = Parser()
    p.resolver.output_in_memory = True
    p.shipout = Shipout(p)
    p.catcode[ord("{")] = CATCODE.BEGIN_GROUP
    p.catcode[ord("}")] = CATCODE.END_GROUP
    p.catcode[ord("$")] = CATCODE.MATH_SHIFT
    p.catcode[ord("&")] = CATCODE.ALIGNMENT_TAB
    p.catcode[ord("#")] = CATCODE.PARAMETER
    p.catcode[ord("^")] = CATCODE.SUPERSCRIPT
    p.catcode[ord("_")] = CATCODE.SUBSCRIPT
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
    parser.sfcode[ord(",")] = 1250
    parser.sfcode[ord(".")] = 3000
    parser.sfcode[ord(")")] = 0
    return parser


@pytest.fixture()
def example_tex(parser):
    parser.resolver.in_memory_files["example.tex"] = InMemoryTextFile("Hello, world!\n")
    return parser
