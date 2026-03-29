"""
This module defines the token list facilities.
"""

from pytex.lexer import CATCODE, TokenListScanner
from pytex.token import Command, Token, relax, CommandToken
from pytex.module import Module
from pytex.state import Array
from pytex import accessor
from pytex.expandable import toToks
from pytex.define import registerdef


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
        if t is None or t.entry is None:
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
        t = definition.expand(parser)
        if t:
            return t, None


def readBalancedTextExpanded(parser, toks: list = []):
    """
    read until an enclosing }, including balanced { and }.
    @param parser: the parser
    @param toks: the list to read into
    @param expand: whether to expand the tokens
    @param macro: whether reading the body of a macro definition
    @return: toks with the balanced text added (including the enclosing }
    """
    begin_group = CATCODE.BEGIN_GROUP
    end_group = CATCODE.END_GROUP
    parameter = CATCODE.PARAMETER
    other = CATCODE.OTHER
    append = toks.append
    extend = toks.extend
    level = 0

    token_factory = Token.token
    while True:
        t, expanded = token_expand(parser)
        if t is None:
            raise ValueError("unbalanced token list", parser.input.position())
        catcode = t.catcode
        if catcode == begin_group:
            level += 1
        elif catcode == end_group:
            if level == 0:
                append(t)
                return toks
            level -= 1
        elif expanded is not None:
            extend(expanded)
            continue
        append(t)


def readMacroBodyExpanded(parser):
    """
    read until an enclosing }, including balanced { and }.
    @param parser: the parser
    @param toks: the list to read into
    @param expand: whether to expand the tokens
    @param macro: whether reading the body of a macro definition
    @return: toks with the balanced text added (including the enclosing }
    """
    begin_group = CATCODE.BEGIN_GROUP
    end_group = CATCODE.END_GROUP
    parameter = CATCODE.PARAMETER
    other = CATCODE.OTHER
    toks = []
    append = toks.append
    extend = toks.extend
    level = 0

    token_factory = Token.token
    while True:
        t, expanded = token_expand(parser)
        if t is None:
            raise ValueError("unbalanced token list", parser.input.position())
        catcode = t.catcode
        if catcode == begin_group:
            level += 1
        elif catcode == end_group:
            if level == 0:
                append(t)
                return toks
            level -= 1
        elif expanded is not None:
            extend(expanded)
            continue
        elif catcode == parameter:
            t = token_factory(t.name, parameter)
            t1, _expanded = token_expand(parser)
            if t1.catcode == other and ("1" <= t1.name <= "9"):
                t.parameter = int(t1.name) - 1
            elif t1.catcode != parameter:
                raise ValueError(f"invalid parameter {t1.name}", parser.input.position())
        append(t)


def readBalancedText(parser, toks: list = []):
    """
    read until an enclosing }, including balanced { and }.
    @param parser: the parser
    @param toks: the list to read into
    @param expand: whether to expand the tokens
    @param macro: whether reading the body of a macro definition
    @return: toks with the balanced text added (including the enclosing }
    """
    begin_group = CATCODE.BEGIN_GROUP
    end_group = CATCODE.END_GROUP
    parameter = CATCODE.PARAMETER
    other = CATCODE.OTHER
    append = toks.append
    extend = toks.extend
    level = 0
    tok = parser.token
    token_factory = Token.token
    while True:
        t = tok()
        if t is None:
            raise ValueError("unbalanced token list", parser.input.position())
        catcode = t.catcode
        if catcode == begin_group:
            level += 1
        elif catcode == end_group:
            if level == 0:
                append(t)
                return toks
            level -= 1
        append(t)


def reaadMacroBody(parser):
    """
    read until an enclosing }, including balanced { and }.
    @param parser: the parser
    @param toks: the list to read into
    @param expand: whether to expand the tokens
    @param macro: whether reading the body of a macro definition
    @return: toks with the balanced text added (including the enclosing }
    """
    begin_group = CATCODE.BEGIN_GROUP
    end_group = CATCODE.END_GROUP
    parameter = CATCODE.PARAMETER
    other = CATCODE.OTHER
    toks = []
    append = toks.append
    extend = toks.extend
    level = 0
    tok = parser.token
    token_factory = Token.token
    while True:
        t = tok()
        if t is None:
            raise ValueError("unbalanced token list", parser.input.position())
        catcode = t.catcode
        if catcode == begin_group:
            level += 1
        elif catcode == end_group:
            if level == 0:
                append(t)
                return toks
            level -= 1
        elif catcode == parameter:
            t = token_factory(t.name, parameter)
            t1 = tok()
            if t1.catcode == other and ("1" <= t1.name <= "9"):
                t.parameter = int(t1.name) - 1
            elif t1.catcode != parameter:
                raise ValueError(f"invalid parameter {t1.name}", parser.input.position())
        append(t)


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
    balanced = readBalancedTextExpanded if expand else readBalancedText
    toks = balanced(parser, [])
    # remove the trailing }
    toks.pop()
    return toks


def readToks(parser):
        """
        read a toks value from the input stack
        @param parser: the parser
        """
        parser.skipFiller()
        t = parser.token()
        toksValue = getattr(t.definition, "toksValue", None)
        if toksValue:
            return toksValue(parser)
        parser.input.unread(t)
        return readGeneralText(parser, expand=False)
    

class ToksArrayItemAccessor(accessor.Accessor):
    """
    aaccessor for a toks parameter
    """
    target_type = accessor.VALUE_TYPE.TOKS

    def readKey(self, parser):
        return parser.readInteger()

    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        @return: the toks value
        """
        return readToks(parser)

    def toksValue(self, parser):
        """
        get the toks value
        @param parser: the parser
        @return: the toks value
        """
        return self.domain[self.currentKey(parser)]
    

class ToksArray(Array):
    """
    a toks array, that is a list of token lists
    """
    def __init__(self, state):
        """
        @param name: the name of the array
        @param state: the state of the parser
        @param value: the initial value of the array
        """
        super().__init__("toks", state, [])
    

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
        group = parser.current_group
        if group is not None:
            group.aftergroup.append(t)


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
            code = parser.uccode
        else:
            code = parser.lccode
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
                t1 = Token.token(chr(c), t.catcode)
                if t.entry is not None:
                    # if the token is a command, we need to set the entry
                    t1.entry = parser.equitable.entry(t1.name)
                toks.append(t1)
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
        target = parser.readTarget()
        if target is not None:
            value = parser.get(target)
            if target.value_type == accessor.VALUE_TYPE.MUGLUE:
                return toToks(str(value))
            if target.value_type == accessor.VALUE_TYPE.GLUE:
                return toToks(str(value))
            if target.value_type == accessor.VALUE_TYPE.DIMEN:
                return toToks(repr(value) + "pt")
            if target.value_type == accessor.VALUE_TYPE.INT:
                return toToks(repr(parser.cast(value, accessor.VALUE_TYPE.INT)))
            if target.value_type == accessor.VALUE_TYPE.TOKS:
                return value
            if target.value_type == accessor.VALUE_TYPE.FONT:
                f = value
                t = CommandToken(f.name)
                t.entry = parser.equitable.entry(f.name)
                return [t]

        t = parser.token_expand()
        if t is None:
            raise ValueError(f"invalid token after \\the: {t}", parser.input.position())
        t0 = t
        meaning = t.definition

        if hasattr(meaning, "toksValue"):
            return meaning.toksValue(parser)
        if hasattr(meaning, "fontValue"):
            f = meaning.fontValue(parser)
            t = CommandToken(f.name)
            t.entry = parser.equitable.entry(f.name)
            return [t]
        raise ValueError(f"invalid token after \\the: {t0.name}", parser.input.position())
    
    def expand(self, parser):
        """
        \\the command expands the next token.
        @param parser: the parser

        The actual expansion depends on the type of the token. Please see TeXBook pp. 214.
        """
        toks = self.expanded(parser)
        parser.input.push(TokenListScanner(toks))


class PageMark(Command):
    """
    Expand to the current page mark token list.
    """

    def __init__(self, key, domain="parameters"):
        self.key = key
        self.domain = domain

    def toksValue(self, parser):
        return getattr(parser, self.domain)[self.key]

    def expand(self, parser):
        toks = self.toksValue(parser)
        if toks:
            parser.input.push(TokenListScanner(toks))


mod = Module("toks",
    attributes = {
        "readBalancedText": readBalancedText,
        "readBalancedTextExpanded": readBalancedTextExpanded,
        "readMacroBody": reaadMacroBody,
        "readMacroBodyExpanded": readMacroBodyExpanded,
        "skipFiller": skipFiller,
        "readGeneralText": readGeneralText,
    },
    commands = {
        "aftergroup": AfterGroup(),
        "uppercase": Case(True),
        "lowercase": Case(False),
        "ignorespaces": IgnoreSpaces(),
        "the": The(),
        "topmark": PageMark("topmark"),
        "firstmark": PageMark("firstmark"),
        "botmark": PageMark("botmark"),
        "splitfirstmark": PageMark("splitfirstmark", "globals"),
        "splitbotmark": PageMark("splitbotmark", "globals"),
        "toksdef": registerdef("toks", ToksArrayItemAccessor),
    },
    domains = {
        "toks": {"generator": ToksArray, "accessor": ToksArrayItemAccessor},
    },
    parameters={
        "aftergroup": {"value": [], "accessor": None, "domain": "globals"},
        "output": {"value": [], "accessor": ToksArrayItemAccessor, "domain": "parameters"},
        "everyhbox": {"value": [], "accessor": ToksArrayItemAccessor, "domain": "parameters"},
        "everyvbox": {"value": [], "accessor": ToksArrayItemAccessor, "domain": "parameters"},
        "everyjob": {"value": [], "accessor": ToksArrayItemAccessor, "domain": "parameters"},
        "everycr": {"value": [], "accessor": ToksArrayItemAccessor, "domain": "parameters"},
        "errhelp": {"value": [], "accessor": ToksArrayItemAccessor, "domain": "parameters"},
        "everypar": {"value": [], "accessor": ToksArrayItemAccessor, "domain": "parameters"},
        "everymath": {"value": [], "accessor": ToksArrayItemAccessor, "domain": "parameters"},
        "everydisplay": {"value": [], "accessor": ToksArrayItemAccessor, "domain": "parameters"},
        "topmark": {"value": [], "accessor": None, "domain": "parameters"},
        "botmark": {"value": [], "accessor": None, "domain": "parameters"},
        "firstmark": {"value": [], "accessor": None, "domain": "parameters"},
        "splitfirstmark": {"value": [], "accessor": None, "domain": "globals"},
        "splitbotmark": {"value": [], "accessor": None, "domain": "globals"},
    }
)
