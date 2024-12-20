"""
This module defines the token list facilities.
"""

import typing
from pytex.lexer import CATCODE, TokenListScanner
from pytex.token import Command
from pytex.module import Module
from pytex.state import Array
from pytex import accessor


class Toks(list):
    """
    a token list
    @param included_braces: whether the enclosing braces are included in the token list
    """
    def __init__(self, *args, included_braces: bool = False):
        super().__init__(*args) 
        self.included_braces = included_braces

    def __repr__(self):
        content = "".join(map(lambda x: x.name, self))
        return content if self.included_braces else  "{" + content + "}"


def token_expand(parser):
    """
    expand a token
    @param parser: the parser
    """
    t = parser.token()
    if t is None or t.protected:
        return t
    t1 = t.expand(parser)
    if t1 is not None:
        return t1
    return token_expand(parser)


def readBalancedText(parser, expand: bool = False, include_braces: bool = False):
    """
    read a balanced token list
    @param parser: the parser
    @param expand: whether to expand the tokens
    @param include_braces: whether to include the braces in the token list
    @return: the token list
    """
    pos = parser.input.position()
    read = lambda: token_expand(parser) if expand else parser.token()
    lbrace = read()
    if lbrace is None or lbrace.catcode != CATCODE.BEGIN_GROUP:
        raise ValueError("expecting {", pos)
    toks = Toks(included_braces=include_braces)
    if include_braces:
        toks.append(lbrace)
    level = 0
    while True:
        t = read()
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


def readGeneralText(parser, expand: bool = True, include_braces: bool = False):
    """
    read general text

    A general text is a filler followed by a balanced token list.
    @param parser: the parser
    @param expand: whether to expand the tokens
    @param include_braces: whether to include the braces in the token list
    @return: the token list
    """
    pos = parser.input.position()
    skipFiller(parser)
    return readBalancedText(parser, expand, include_braces)


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
        "toks": {"generator": ToksArray, "accessor": accessor.ArrayAccessor, "type": ToksValuePointer},
    },
    parameters={
        "aftergroup": {"value": [], "accessor": None, "domain": "globals"},
        "output": {"value": [], "accessor": accessor.ParameterAccessor, "domain": "parameters", "type": ToksValuePointer},
        "everyhbox": {"value": [], "accessor": accessor.ParameterAccessor, "domain": "layout", "type": ToksValuePointer},
        "everyvbox": {"value": [], "accessor": accessor.ParameterAccessor, "domain": "layout", "type": ToksValuePointer},
        "everyjob": {"value": [], "accessor": accessor.ParameterAccessor, "domain": "layout", "type": ToksValuePointer},
        "everycr": {"value": [], "accessor": accessor.ParameterAccessor, "domain": "layout", "type": ToksValuePointer},
        "errhelp": {"value": [], "accessor": accessor.ParameterAccessor, "domain": "layout", "type": ToksValuePointer},
        "everypar": {"value": [], "accessor": accessor.ParameterAccessor, "domain": "layout", "type": ToksValuePointer},
        "everymath": {"value": [], "accessor": accessor.ParameterAccessor, "domain": "layout", "type": ToksValuePointer},
        "everydisplay": {"value": [], "accessor": accessor.ParameterAccessor, "domain": "layout", "type": ToksValuePointer},
    }
)
