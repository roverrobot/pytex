"""
This module defines the token list facilities.
"""

import typing
from pytex.lexer import CATCODE, TokenListScanner
from pytex.token import Command, Token, relax
from pytex.module import Module
from pytex.state import Array
from pytex import accessor
from pytex.expandable import toToks, noexpand


def token_expand(parser):
    """
    expand a token in an expanded token list
    @param parser: the parser
    @param token: the token to expand
    @return: the expanded token, expanded token list of \\the or \\unexpanded
    this is like parser.token_expand(), except that it does not expand protected macros.
    """
    while True:
        t = parser.token()
        if t is None or not t.is_command:
            return t, None
        if t.noexpand:
            t.noexpand = False
            t.definition = relax
            return t, None
        definition = t.definition
        if definition is None:
            raise ValueError(f"undefined command {t.name}", parser.input.position())
        if definition.protected or definition.expand is None:
            return t, None
        if parser.tracingcommands:
            parser.trace(t, "expand")
        if definition.expanded:
            return t, definition.expanded(parser)
        definition.expand(parser)


def readBalancedText(parser, toks: list = [], expand: bool = False, macro: bool = False):
    """
    read until an enclosing }, including balanced { and }.
    @param parser: the parser
    @param toks: the list to read into
    @param expand: whether to expand the tokens
    @param macro: whether reading the body of a macro definition
    @return: toks with the balanced text added (including the enclosing }
    """
    if expand:
        tok = lambda: token_expand(parser)
    else:
        tok = lambda: (parser.token(), None)
    level = 0
    while True:
        t, expanded = tok()
        if t is None:
            raise ValueError("unbalanced token list", parser.input.position())        
        if t.catcode == CATCODE.BEGIN_GROUP:
            # keep reading the tokens until we meet a matching }
            level += 1
        elif t.catcode == CATCODE.END_GROUP:
            if level == 0:
                # we are done
                toks.append(t)
                return toks
            level -= 1
        elif expanded is not None:
            toks.extend(expanded)
            continue
        elif t.catcode == CATCODE.PARAMETER and macro:
            t = Token.token(t.name, CATCODE.PARAMETER)
            t1, expanded = tok()
            if t1.catcode == CATCODE.OTHER and ("1" <= t1.name <= "9"):
                t.parameter = int(t1.name) - 1
            elif t1.catcode != CATCODE.PARAMETER:
                raise ValueError(f"invalid parameter {t1.name}", parser.input.position())
        toks.append(t)

def skipFiller(parser):
    """
    read a filler

    A filler is a sequence of space tokens or \\relax commands.
    @param parser: the parser
    """
    while True:
        t = parser.skipSpaces(expand=True)
        if t is None:
            return
        if t.definition == relax:
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
    lbrace = parser.token_expand() if expand else parser.token()
    if lbrace is None or lbrace.catcode != CATCODE.BEGIN_GROUP:
        raise ValueError("expecting {", parser.input.position())
    toks = readBalancedText(parser, [], expand, macro=False)
    # remove the trailing }
    toks.pop()
    return toks


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
        if t.is_command and hasattr(t.definition, "toksValue"):
            return t.definition.toksValue(parser)
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
        parser.state.groups.aftergroup(t)


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
        # the tokens may have been read from a token list, so we should not change them
        # but instead create new tokens
        toks = []
        for t in text:
            # do not change the name of control sequences
            if t.catcode is None:
                toks.append(t)
                continue
            c = code[ord(t.name)]
            if c == 0:
                toks.append(t)
            else:
                toks.append(Token.token(chr(c), t.catcode))
        parser.input.push(TokenListScanner(toks))


class IgnoreSpaces(Command):
    """
    the \\ignorespaces command
    """
    def execute(self, parser):
        t = parser.skipSpaces()
        if t is not None:
            parser.input.unread(t)


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
        t = parser.token_expand()
        if t is None or t.definition is None:
            raise ValueError(f"invalid token after \\the: {t}", parser.input.position())
        t0 = t
        t = t.definition
        if hasattr(t, "glueValue"):
            value = str(t.glueValue(parser))
        elif hasattr(t, "dimenValue"):
            value = repr(t.dimenValue(parser)) + "pt"
        elif hasattr(t, "intValue"):
            value = repr(t.intValue(parser))
        else:
            value = None
        if value is not None:
            return toToks(value)
        if hasattr(t, "toksValue"):
            return t.toksValue(parser)
        if hasattr(t, "fontValue"):
            return [t]
        raise ValueError(f"invalid token after \\the: {t0}", parser.input.position())
    
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
