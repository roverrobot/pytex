"""
This module defines the token list facilities.
"""

import typing
from pytex.lexer import CATCODE
from pytex.token import Command
from pytex.module import Module
from pytex.state import Array
from pytex import accessor


def readBalanced(parser, expand: bool = False):
    """
    read a balanced token list
    @param parser: the parser
    @param expand: whether to expand the tokens
    @return: the token list
    """
    tokens = []
    pos = parser.input.position()
    read = lambda: parser.token_expand() if expand else parser.token()
    lbrace = read()
    if lbrace is None or lbrace.catcode != CATCODE.BEGIN_GROUP:
        raise ValueError("expecting {", pos)
    toks = []
    level = 0
    while True:
        t = read()
        if t is None:
            raise ValueError("unbalanced token list", pos)
        elif t.catcode == CATCODE.BEGIN_GROUP:
            level += 1
        elif t.catcode == CATCODE.END_GROUP:
            if level == 0:
                return toks
            else:
                level -= 1
        toks.append(t)


class Relax(Command):
    """
    the \\relax command
    """
    def execute(self, parser):
        """
        execute the command
        @param parser: the parser
        """
        pass


# the \\relax command
relax = Relax()

def skipFiller(parser):
    """
    read a filler

    A filler is a sequence of space tokens or \\relax commands.
    @param parser: the parser
    """
    while True:
        t = parser.token_expand()
        if t is None:
            return
        if t.catcode == CATCODE.SPACE or t == relax:
            continue
        parser.input.unread(t)
        break


def readGeneralText(parser, expand: bool = True):
    """
    read general text

    A general text is a filler followed by a balanced token list.
    @param parser: the parser
    """
    pos = parser.input.position()
    skipFiller(parser)
    return readBalanced(parser, expand)


class ToksValuePointer(accessor.ValuePointer):
    """
    a pointer to the token list
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return readBalanced(parser, expand=False)
    
    def toksValue(self, parser):
        """
        get the token list value
        @param parser: the parser
        """
        return self.getValue(parser)


class ToksArray(Array):
    """
    an array of token lists.

    We need to overwrite the default value handling of Array, because passing
    an empty list to the constructor of Array will create a reference to the
    same list, so that the default value will be shared among all the items.
    """
    def __init__(self):
        super().__init__(ToksValuePointer)
        for i in range(len(self)):
            self[i] = []


class AfterGroup(Command):
    """
    the \\aftergroup command
    """
    def execute(self, parser):
        """
        execute the command
        @param parser: the parser
        """
        t = parser.token()
        if t is None:
            raise ValueError("token expected")
        parser.state.domains["globals"]["aftergroup"].append(t)


mod = Module("toks",
    attributes = {
        "readBalanced": readBalanced,
        "skipFiller": skipFiller,
        "readGeneralText": readGeneralText,
    },
    commands = {
        "relax": relax,
        "aftergroup": AfterGroup()
    },
    domains = {
        "toks": {"generator": ToksArray, "accessor": accessor.ArrayAccessor, "type": ToksValuePointer},
    },
    parameters={
        "aftergroup": {"value": [], "accessor": None, "domain": "globals"},
    }
)
