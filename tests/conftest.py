"""
Module level fixtures
"""


import pytest
import types
from pytex.parser import Parser
from pytex.token import CATCODE
from pytex.resolver import InMemoryTextFile


@pytest.fixture()
def parser():
    p = Parser()
    p.state.catcode[ord("{")] = CATCODE.BEGIN_GROUP
    p.state.catcode[ord("}")] = CATCODE.END_GROUP
    p.state.catcode[ord("$")] = CATCODE.MATH_SHIFT
    p.state.catcode[ord("&")] = CATCODE.ALIGNMENT_TAB
    p.state.catcode[ord("#")] = CATCODE.PARAMETER
    p.state.catcode[ord("^")] = CATCODE.SUPERSCRIPT
    p.state.catcode[ord("_")] = CATCODE.SUBSCRIPT
    return p


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
    parser.parse('\\font\\f=cmr10 \\f')
    parser.state.sfcode[ord(",")] = 1250
    parser.state.sfcode[ord(".")] = 3000
    parser.state.sfcode[ord(")")] = 0
    return parser


@pytest.fixture()
def example_tex(parser):
    parser.resolver.in_memory_files["example.tex"] = InMemoryTextFile("Hello, world!\n")
    return parser
