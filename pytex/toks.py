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


def _parameterToken(parameter):
    t = Token.token("#", CATCODE.PARAMETER)
    t.parameter = parameter
    return t


def _builderClose(builder, stop):
    if isinstance(builder, list):
        return builder
    return builder.close(stop)


class ExpandBuilder:
    """
    Wrapper that reproduces the old ``toks.token_expand`` semantics while
    delegating concrete tokens to an inner builder.
    """
    def __init__(self, parser, inner=None):
        self.parser = parser
        self.inner = inner

    def token(self):
        """
        Expand a token in an expanded token list.
        @return: the expanded token, expanded token list of \\the or
        \\unexpanded. This is like ``parser.token_expand()``, except that it
        does not expand protected macros.
        """
        parser = self.parser
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

    def append(self, t):
        self.inner.append(t)

    def extend(self, toks):
        self.inner.extend(toks)

    def close(self, stop):
        return _builderClose(self.inner, stop)

class MacroBodyBuilder:
    """
    Builder that normalizes direct-input ``#`` syntax while preserving hashes
    that arrived via expanded token lists.
    """
    def __init__(self, parser, toks=None):
        self.parser = parser
        self.toks = [] if toks is None else toks
        self.pending_parameter = False

    def _invalid(self, t=None):
        parser = self.parser
        if t is None:
            raise ValueError("invalid parameter", parser.input.position())
        raise ValueError(f"invalid parameter {t.name}", parser.input.position())

    def append(self, t):
        if not self.pending_parameter:
            if t.catcode == CATCODE.PARAMETER and getattr(t, "parameter", None) is None:
                self.pending_parameter = True
                return
            self.toks.append(t)
            return
        if t.catcode == CATCODE.OTHER and ("1" <= t.name <= "9"):
            self.toks.append(_parameterToken(int(t.name) - 1))
            self.pending_parameter = False
            return
        if t.catcode == CATCODE.PARAMETER and getattr(t, "parameter", None) is None:
            self.toks.append(_parameterToken(-1))
            self.pending_parameter = False
            return
        self._invalid(t)

    def extend(self, toks):
        if self.pending_parameter and toks:
            self._invalid(toks[0])
        for t in toks:
            if t.catcode == CATCODE.PARAMETER and getattr(t, "parameter", None) is None:
                self.toks.append(_parameterToken(-1))
            else:
                self.toks.append(t)

    def close(self, stop):
        if self.pending_parameter:
            if stop == CATCODE.BEGIN_GROUP:
                self.toks.append(_parameterToken(None))
            else:
                self._invalid()
            self.pending_parameter = False
        return self.toks


def readTo(parser, stop, toks=None, expand: bool = False, builder=None):
    """
    Read tokens until a stop catcode is found.

    @param parser: the parser
    @param stop: the catcode that terminates the read
    @param toks: the list to read into
    @param expand: whether to expand tokens while reading
    @return: (tokens, end_token)
    """
    if builder is None:
        builder = [] if toks is None else toks
    if expand:
        builder = ExpandBuilder(parser, builder)
    level = 0

    while True:
        if expand:
            t, expanded = builder.token()
        else:
            t = parser.token()
            expanded = None
        if t is None:
            miss = "{" if stop == CATCODE.BEGIN_GROUP else "}"
            raise ValueError(f"expecting {miss}", parser.input.position())
        if expanded is not None:
            builder.extend(expanded)
            continue
        catcode = t.catcode
        if catcode == stop and level == 0:
            return _builderClose(builder, stop), t
        if catcode == CATCODE.BEGIN_GROUP:
            level += 1
            builder.append(t)
            continue
        if catcode == CATCODE.END_GROUP:
            level -= 1
            if level < 0:
                raise ValueError("expecting }", parser.input.position())
            builder.append(t)
            continue
        builder.append(t)


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
    is_begin_group = (
        lbrace is not None and (
            lbrace.isTokenExpand(CATCODE.BEGIN_GROUP)
            if expand else
            lbrace.catcode == CATCODE.BEGIN_GROUP
        )
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
    while True:
        t = parser.skipSpaces(expand=False)
        if t is None:
            break
        if t.definition == relax:
            continue
        parser.input.unread(t)
        break
    value = parser.readInternalValue(accessor.VALUE_TYPE.TOKS, expand=False)
    if value is not None:
        return value
    return readGeneralText(parser, expand=False)
    

ToksAccessor = accessor.typedAccessor(accessor.VALUE_TYPE.TOKS)

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
            raise ValueError(f"expecting a token after \\the", parser.input.position())
        raise ValueError(f"invalid token after \\the: {t.name}", parser.input.position())
    
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

    target_type = accessor.VALUE_TYPE.TOKS

    def getTarget(self, parser):
        return accessor.ReadOnlyTarget(getattr(parser, self.domain)[self.key], self.target_type)

    def expand(self, parser):
        toks = self.getTarget(parser).get()
        if toks:
            parser.input.push(TokenListScanner(toks))


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
