"""
This module defines the token list facilities.
"""

import typing
from pytex import serialization
from pytex.lexer import CATCODE, TokenListScanner
from pytex.token import Command, CommandToken, relax
from pytex.module import Module
from pytex.state import Array
from pytex import accessor


def readBalancedText(parser, expand: bool = False, include_braces: bool=False):
    """
    read a balanced token list
    @param parser: the parser
    @param expand: whether to expand the tokens
    @param include_braces: whether to include the braces
    @return: the token list
    """
    pos = parser.input.position()
    lbrace = parser.token_expand() if expand else parser.token()
    if lbrace is None or lbrace.catcode != CATCODE.BEGIN_GROUP:
        raise ValueError("expecting {", pos)
    toks = []
    if include_braces:
        toks.append(lbrace)
    level = 0
    while True:
        t = parser.token_expand(protected=True) if expand else parser.token()
        if t is None:
            raise ValueError("unbalanced token list", pos)
        elif t.catcode == CATCODE.BEGIN_GROUP:
            level += 1
        elif t.catcode == CATCODE.END_GROUP:
            if level == 0:
                if include_braces:
                    toks.append(t)
                return toks
            else:
                level -= 1
        toks.append(t)


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
        if t.catcode == CATCODE.SPACE or t.definition == relax:
            continue
        parser.input.unread(t)
        break


def readGeneralText(parser, expand: bool = True):
    """
    read general text

    A general text is a filler followed by a balanced token list.
    @param parser: the parser
    @param expand: whether to expand the tokens
    @return: the token list
    """
    skipFiller(parser)
    return readBalancedText(parser, expand)


class ToksCommand:
    """
    access a token list value
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        parser.skipFiller()
        t = parser.token()
        if t.isCommand():
            t.definition = parser.lookup(t.name)
            try:
                return t.definition.toksValue(parser)
            except AttributeError:
                pass
        parser.input.unread(t)
        return readBalancedText(parser, expand=False)
    
    def toksValue(self, parser):
        """
        get the token list value
        @param parser: the parser
        """
        return self.getValue(parser)


class ToksAccessor(ToksCommand, accessor.Accessor):
    """
    aaccessor for a toks parameter
    """
    pass
    

class ToksArrayAccessor(ToksCommand, accessor.ArrayAccessor):
    """
    an accessor for the token list array
    """
    def newItemAccessor(self, index):
        return ToksAccessor(self.domain, index)


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


class Case(Command):
    """
    the \\uppercase and \\lowercase commands
    """
    def __init__(self, upper: bool):
        self.upper = upper

    def saveInfo(self):
        return {"init": {"upper": self.upper}}

    def execute(self, parser):
        """
        execute the command

        The command argument is a general text. The tokens in the general text
        are converted to uppercase or lowercase according to the value of the
        \\lccode and \\uccode arrays.
        @param parser: the parser
        """
        if self.upper:
            code = parser.state.uccode
        else:
            code = parser.state.lccode
        text = readGeneralText(parser, expand=False)
        for t in text:
            if len(t.name) > 1:
                continue
            c = code[ord(t.name)]
            if c != 0:
                t.name = chr(c)
        parser.input.push(TokenListScanner(text))


class IgnoreSpaces(Command):
    """
    the \\ignorespaces command
    """
    def execute(self, parser):
        return parser.skipSpaces()


mod = Module("toks",
    attributes = {
        "readBalancedText": readBalancedText,
        "skipFiller": skipFiller,
        "readGeneralText": readGeneralText,
    },
    commands = {
        "aftergroup": AfterGroup(),
        "uppercase": Case(True),
        "lowercase": Case(False),
        "ignorespaces": IgnoreSpaces(),
    },
    domains = {
        "toks": {"generator": lambda: Array([]), "accessor": ToksArrayAccessor},
    },
    parameters={
        "aftergroup": {"value": [], "accessor": None, "domain": "globals"},
        "output": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
        "everyhbox": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
        "everyvbox": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
        "everyjob": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
        "everycr": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
        "errhelp": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
        "everypar": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
        "everymath": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
        "everydisplay": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
    }
)
