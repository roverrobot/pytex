"""
This module defines the token list facilities.
"""

import typing
from pytex.lexer import CATCODE, TokenListScanner
from pytex.token import Command, CommandToken
from pytex.module import Module
from pytex.state import Array
from pytex import accessor


class Toks(list):
    """
    a token list
    """
    def __repr__(self):
        return "".join(map(lambda x: x.name, self))


def token_expand(parser):
    """
    expand a token
    @param parser: the parser
    """
    t = parser.token()
    if t is None or t.protected:
        return t
    t1 = t.expand(parser)
    if t1 is None:
        return token_expand(parser)
    if isinstance(t1, CommandToken) and t1 == t:
        raise ValueError(f"undefined command {t.name}")
    return t1


def readBalancedText(parser, expand: bool = False):
    """
    read a balanced token list
    @param parser: the parser
    @param expand: whether to expand the tokens
    @return: the token list
    """
    pos = parser.input.position()
    read = lambda: token_expand(parser) if expand else parser.token()
    lbrace = read()
    if lbrace is None or lbrace.catcode != CATCODE.BEGIN_GROUP:
        raise ValueError("expecting {", pos)
    toks = Toks()
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


relax = Command()


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
    @param expand: whether to expand the tokens
    @return: the token list
    """
    pos = parser.input.position()
    skipFiller(parser)
    return readBalancedText(parser, expand)


class ToksValuePointer(accessor.ValuePointer):
    """
    a pointer to the token list
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return readBalancedText(parser, expand=False)
    
    def toksValue(self, parser):
        """
        get the token list value
        @param parser: the parser
        """
        return self.getValue(parser)


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


mod = Module("toks",
    attributes = {
        "readBalancedText": readBalancedText,
        "skipFiller": skipFiller,
        "readGeneralText": readGeneralText,
    },
    commands = {
        "relax": relax,
        "aftergroup": AfterGroup(),
        "uppercase": Case(True),
        "lowercase": Case(False),
    },
    domains = {
        "toks": {"generator": lambda: Array([]), "accessor": accessor.ArrayAccessor, "type": ToksValuePointer},
    },
    parameters={
        "aftergroup": {"value": list, "accessor": None, "domain": "globals"},
        "output": {"value": list, "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
        "everyhbox": {"value": list, "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
        "everyvbox": {"value": list, "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
        "everyjob": {"value": list, "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
        "everycr": {"value": list, "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
        "errhelp": {"value": list, "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
        "everypar": {"value": list, "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
        "everymath": {"value": list, "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
        "everydisplay": {"value": list, "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
    }
)
