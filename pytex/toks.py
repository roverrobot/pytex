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
from pytex.expandable import toToks


def token_expand(parser):
    """
    expand a token in an expanded token list
    @param parser: the parser
    @param token: the token to expand
    @return: the expanded token

    this is like parser.token_expand(), except that it does not expand protected macros.
    """
    t = parser.token()
    if t is None or not t.isCommand():
        return t
    if t.noexpand:
        t.noexpand = False
        return t
    definition = parser.lookup(t.name)
    if definition is None:
        raise ValueError(f"undefined command {t.name}", parser.input.position())
    t.definition = definition
    if definition.protected or definition.expand is None:
        return t
    if hasattr(definition, "expanded"):
        return t
    if parser.tracingcommands:
        parser.traceExpansion(t, definition)
    definition.expand(parser)
    return token_expand(parser)


def readBalancedText(parser, expand: bool = False, include_braces: bool = False, parpar=True):
    """
    read a single character or a token list in balanced braces
    @param parser: the parser
    @param expand: whether to expand the tokens
    @param include_braces: whether to include the enclosing braces in the result, if there is a pair
    @param parpar: whether to double the # tokens
    @return: the token list
    """
    level = 0
    t = token_expand(parser) if expand else parser.token()
    if t is None:
        return []
    if t.catcode != CATCODE.BEGIN_GROUP:
        if t.catcode == CATCODE.END_GROUP:
            parser.input.unread(t)
            return []
        definition = t.definition
        if definition is not None and hasattr(definition, "expanded"):
            if parser.tracingcommands:
                parser.traceExpansion(t, definition)
            definition.expanded(parser)
        return [t, t] if t.catcode == CATCODE.PARAMETER and parpar else [t]
    level += 1
    toks = [t] if include_braces else []
    while True:
        t = token_expand(parser) if expand else parser.token()
        if t is None:
            raise ValueError("unbalanced token list", parser.input.position())
        if t.catcode == CATCODE.BEGIN_GROUP:
            level += 1
        elif t.catcode == CATCODE.END_GROUP:
            level -= 1
            if level == 0:
                if include_braces:
                    toks.append(t)
                return toks
        elif t.definition is not None and hasattr(t.definition, "expanded"):
            toks.extend(t.definition.expanded(parser))
            continue
        if parpar and t.catcode == CATCODE.PARAMETER:
            toks.append(t)
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


def readGeneralText(parser, expand: bool = True, parpar=True):
    """
    read general text

    A general text is a filler followed by a balanced token list.
    @param parser: the parser
    @param expand: whether to expand the tokens
    @param parpar: whether to double the # tokens
    @return: the token list
    """
    skipFiller(parser)
    lbrace = parser.token_expand() if expand else parser.token()
    if lbrace is None or lbrace.catcode != CATCODE.BEGIN_GROUP:
        raise ValueError("expecting {", parser.input.position())
    parser.input.unread(lbrace)
    return readBalancedText(parser, expand, include_braces=False, parpar=parpar)


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
        return readGeneralText(parser, expand=False)
    
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
        text = readGeneralText(parser, expand=False, parpar=False)
        for t in text:
            # do not change the name of control sequences
            if t.catcode is None:
                continue
            c = code[ord(t.name)]
            if c != 0:
                t.name = chr(c)
                t.catcode = parser.state.catcode[c]
        parser.input.push(TokenListScanner(text))


class IgnoreSpaces(Command):
    """
    the \\ignorespaces command
    """
    def execute(self, parser):
        return parser.skipSpaces()


class The(Command):
    """
    The \\the command.
    """
    
    def expanded(self, parser):
        """
        expands into a token list
        @param parser: the parser
        @return: the token list
        """
        pos = parser.input.position()
        t = parser.token_expand()
        if t is None or t.definition is None:
            raise ValueError("invalid token after \\the", pos)
        t = t.definition
        if hasattr(t, "glueValue"):
            value = str(t.glueValue(parser))
        elif hasattr(t, "dimenValue"):
            value = str(t.dimenValue(parser)) + "pt"
        elif hasattr(t, "intValue"):
            value = str(t.intValue(parser))
        else:
            value = None
        if value is not None:
            return toToks(value)
        if hasattr(t, "toksValue"):
            return t.toksValue(parser)
        if hasattr(t, "fontValue"):
            return [t]
    
    def expand(self, parser):
        """
        \\the command expands the next token.
        @param parser: the parser

        The actual expansion depends on the type of the token. Please see TeXBook pp. 214.
        """
        toks = self.expanded(parser)
        parser.input.push(TokenListScanner(toks))


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
        "the": The(),
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
