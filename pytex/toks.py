"""
This module defines the token list facilities.
"""

from pytex.lexer import CATCODE
from pytex.token import Command, Token, relax, CommandToken
from pytex.module import Module
from pytex.state import Array
from pytex import accessor
from pytex.expandable import toToks
from pytex.define import registerdef


def _parameterToken(parameter):
    t = Token.token("#", CATCODE.PARAMETER)
    t.parameter = parameter
    return t


class ExpandBuilder:
    """
    Wrapper that reproduces the old token-list expansion semantics.
    """
    def __init__(self, parser, toks=None):
        self.parser = parser
        if toks is None:
            toks = []
        object.__setattr__(self, "toks", toks)

    def __getattr__(self, name):
        return getattr(self.toks, name)
    
    def append(self, item):
        # not a command
        if item.entry is None:
            return self.toks.append(item)
        definition = item.definition
        if definition is None:
            raise ValueError(f"command {item.name} is not defined", self.parser.input.position())
        if definition.protected or definition.expand is None:
            return self.toks.append(item)
        if definition.expanded is not None:
            return self.toks.extend(definition.expanded(self.parser))
        if self.parser.tracingcommands > 0:
            self.parser.trace(item, "expand")
        self.parser.current_token = item
        t = definition.expand(self.parser)
        if t is not None:
            self.toks.append(t)


def readTo(parser, stop, toks=None, expand: bool = False):
    """
    Read tokens until a stop catcode is found.

    @param parser: the parser
    @param stop: the catcode that terminates the read
    @param toks: the list to read into
    @param expand: whether to expand tokens while reading
    @return: (tokens, end_token)
    """
    if toks is None:
        toks = []
    builder = ExpandBuilder(parser, toks) if expand else toks
    level = 0
    tok = parser.token
    append = builder.append
    while True:
        try:
            t = tok()
        except EOFError:
            miss = "{" if stop == 1 else "}"
            raise ValueError(f"expecting {miss}", parser.input.position())
        catcode = t.catcode
        if catcode == stop and level == 0:
            return toks, t
        if catcode == 1:
            level += 1
        elif catcode == 2:
            level -= 1
            if level < 0:
                raise ValueError("expecting }", parser.input.position())
        append(t)


def skipFiller(parser):
    """
    read a filler

    A filler is a sequence of space tokens or \\relax commands.
    @param parser: the parser
    """
    while True:
        try:
            t = parser.skipSpaces()
        except EOFError:
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
    try:
        lbrace = parser.token_expand() if expand else parser.token()
    except EOFError:
        raise ValueError("expecting {", parser.input.position())
    is_begin_group = (
        lbrace.isTokenExpand(CATCODE.BEGIN_GROUP)
        if expand else
        lbrace.catcode == CATCODE.BEGIN_GROUP
    )
    if not is_begin_group:
        raise ValueError("expecting {", parser.input.position())
    toks, _end = parser.readTo(CATCODE.END_GROUP, expand=expand)
    return toks


def readToks(parser):
    """
    read a toks value from the input stack
    @param parser: the parser
    """
    skip = parser.skipSpacesNoExpand
    while True:
        try:
            t = skip()
        except EOFError:
            break
        if t.definition == relax:
            continue
        parser.input.unread(t)
        break
    value = parser.readInternalValue(accessor.VALUE_TYPE.TOKS, expand=False)
    if value is not None:
        return value
    return readGeneralText(parser, expand=False)
    

ToksAccessor = lambda domain=None, key=None, builtin=True: accessor.Accessor(
    domain,
    key,
    builtin=builtin,
    value_type=accessor.VALUE_TYPE.TOKS,
    read_key=lambda parser: parser.readInteger(),
)

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
        try:
            t = parser.token()
        except EOFError:
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
        parser.input.pushTokenList(toks)


class IgnoreSpaces(Command):
    """
    the \\ignorespaces command
    """
    def execute(self, parser):
        try:
            t = parser.skipSpaces()
        except EOFError:
            return
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
        value, value_type = parser.readInternalValueInfo(accessor.VALUE_TYPE.UNKNOWN)
        if value_type is not None:
            if value_type == accessor.VALUE_TYPE.MUGLUE:
                return toToks(str(value))
            if value_type == accessor.VALUE_TYPE.GLUE:
                return toToks(str(value))
            if value_type == accessor.VALUE_TYPE.DIMEN:
                return toToks(repr(value) + "pt")
            if value_type == accessor.VALUE_TYPE.INT:
                return toToks(repr(parser.cast(value, accessor.VALUE_TYPE.INT)))
            if value_type == accessor.VALUE_TYPE.TOKS:
                return value
            if value_type == accessor.VALUE_TYPE.FONT:
                f = value
                t = CommandToken(f.name)
                t.entry = parser.equitable.entry(f.name)
                return [t]
            raise ValueError(f"invalid value after \\the", parser.input.position())
        try:
            t = parser.token_expand()
        except EOFError:
            raise ValueError(f"expecting a token after \\the", parser.input.position())
        raise ValueError(f"invalid token after \\the: {t.name}", parser.input.position())
    
    def expand(self, parser):
        """
        \\the command expands the next token.
        @param parser: the parser

        The actual expansion depends on the type of the token. Please see TeXBook pp. 214.
        """
        toks = self.expanded(parser)
        parser.input.pushTokenList(toks)


class PageMark(Command):
    """
    Expand to the current page mark token list.
    """

    def __init__(self, key, domain="parameters"):
        self.key = key
        self.domain = domain

    value_type = accessor.VALUE_TYPE.TOKS

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(self.value_type, requested_type):
            return None, None
        return getattr(parser, self.domain)[self.key], self.value_type

    def expand(self, parser):
        toks = getattr(parser, self.domain)[self.key]
        if toks:
            parser.input.pushTokenList(toks)


mod = Module("toks",
    attributes = {
        "readTo": readTo,
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
        "toksdef": registerdef("toks", ToksAccessor),
    },
    domains = {
        "toks": {"generator": ToksArray, "accessor": ToksAccessor},
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
        "topmark": {"value": [], "accessor": None, "domain": "parameters"},
        "botmark": {"value": [], "accessor": None, "domain": "parameters"},
        "firstmark": {"value": [], "accessor": None, "domain": "parameters"},
        "splitfirstmark": {"value": [], "accessor": None, "domain": "globals"},
        "splitbotmark": {"value": [], "accessor": None, "domain": "globals"},
    }
)
