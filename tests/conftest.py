"""
Module level fixtures
"""


import pytest
import types
from pytex.parser import Parser


@pytest.fixture()
def parser():
    return Parser()


def addChar(self, c):
    self.tokens += c


def addSpace(self):
    self.tokens += " "


def getString(self):
    s = self.tokens
    self.tokens = ""
    return s

@pytest.fixture()
def collector():
    parser = Parser()
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
