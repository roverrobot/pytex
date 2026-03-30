"""
This module implements macros.
"""


from pytex.token import CATCODE, Command, ParameterToken
from pytex.accessor import Prefix, GlobalPrefix
from pytex.define import EquitableAccessor
from pytex.module import Module
from pytex.lexer import TokenListScanner
from pytex.serialization import Serializable
from pytex import toks


def _matchDelimited(parser, macro, bracket, bracket_len):
    """
    Match the next delimiter in a macro parameter list.
    @param parser: the parser
    @param macro: the macro
    @param bracket: a token list to match
    @param bracket_len: the length of bracket
    @return: None for matched, or the first token that failed to match
    """
    p = bracket[0]
    t = parser.token()
    if t is None:
        raise ValueError(f"macro does not match the definition {macro}", parser.input.position())
    if t.catcode != p.catcode or t.name != p.name:
        return t
    matched = []
    first = t
    i = 1
    while i < bracket_len:
        p = bracket[i]
        i += 1
        t = parser.token()
        if t is None:
            raise ValueError(f"macro does not match the definition {macro}", parser.input.position())
        if t.catcode != p.catcode or t.name != p.name:
            parser.input.unread(t)
            if i > 2:
                for m in reversed(matched):
                    parser.input.unread(m)
            return first
        matched.append(t)
    return None


def comapreToks(x, y):
    if isinstance(x, list):
        if isinstance(y, list):
            if len(x) != len(y):
                return False
            for a, b in zip(x, y):
                if not comapreToks(a, b):
                    return False
            return True
        return False
    if isinstance(y, list):
        return False
    return x.catcode == y.catcode and x.name == y.name


def _parameterToken(parameter):
    t = ParameterToken("#", CATCODE.PARAMETER)
    t.parameter = parameter
    return t


def _readPatternParameter(tokens, i):
    """
    Parse macro parameter syntax in a definition pattern.

    In patterns, an escaped ``#`` coming from an outer macro expansion should
    become a current-layer parameter introducer.
    """
    t = tokens[i]
    if t.parameter is not None:
        if t.parameter >= 0:
            return "arg", t.parameter, i + 1
        if t.parameter == -1:
            return "token", t, i + 1
        return "token", t, i + 1
    i += 1
    if i >= len(tokens):
        return "invalid", None, i
    t1 = tokens[i]
    if t1.catcode == CATCODE.OTHER and ("1" <= t1.name <= "9"):
        return "arg", int(t1.name) - 1, i + 1
    if t1.catcode == CATCODE.PARAMETER:
        return "hash", _parameterToken(None), i + 1
    return "invalid", t1, i + 1


def _readReplacementParameter(tokens, i):
    """
    Parse macro parameter syntax in replacement text.

    The stored replacement tokens preserve what was read. During compilation we
    only assign special meaning to explicit parameter references; escaped hashes
    from outer expansion and plain raw hashes both behave like ordinary ``#``
    tokens at this layer.
    """
    t = tokens[i]
    if t.parameter is not None:
        if t.parameter >= 0:
            return "arg", t.parameter, i + 1
        if t.parameter == -1:
            return "hash", _parameterToken(None), i + 1
        return "token", t, i + 1
    i += 1
    if i >= len(tokens):
        return "invalid", None, i
    t1 = tokens[i]
    if t1.catcode == CATCODE.OTHER and ("1" <= t1.name <= "9"):
        return "arg", int(t1.name) - 1, i + 1
    if t1.catcode == CATCODE.PARAMETER:
        return "hash", _parameterToken(None), i + 1
    return "invalid", t1, i + 1


class MatchStartCaller(Serializable):
    """
    a caller is a function that reads the arguments of a macro from the input stack
    and appends them to the argument list
    """
    __slot__ = ("bracket",)
    def __init__(self, bracket):
        self.bracket = bracket

    def meaning(self, parser):
        return parser.toksToString(self.bracket)
    
    def __eq__(self, value):
        return isinstance(value, MatchStartCaller) and comapreToks(self.bracket, value.bracket)
    
    def saveInfo(self):
        return {"bracket": self.bracket}, None

    def __call__(self, parser, macro, args):
        for b in self.bracket:
            t = parser.token()
            if t is None or t.catcode != b.catcode or t.name != b.name:
                raise ValueError(f"macro does not match the definition {macro}", parser.input.position())
        return args


class ReadArgUnDelimCaller(Serializable):
    """
    a caller is a function that reads the arguments of a macro from the input stack
    and appends them to the argument list
    """
    __slot__ = ("bracket", "arg")

    def __init__(self, arg):
        self.bracket = None
        self.arg = arg

    def meaning(self, parser):
        return f"#{self.arg}"
    
    def __eq__(self, value):
        return isinstance(value, ReadArgUnDelimCaller)
    
    def saveInfo(self):
        return {"arg": self.arg}, None

    def __call__(self, parser, macro, args):
        t = parser.skipSpaces(False)
        if t is None:
            args.append([])
            return args
        if t.catcode != CATCODE.BEGIN_GROUP:
            args.append([t])
            return args
        result, _end = parser.readTo(CATCODE.END_GROUP)
        args.append(result)
        return args
    

class ReadArgDelim1Caller(Serializable):
    """
    a caller is a function that reads the arguments of a macro from the input stack
    and appends them to the argument list
    """
    __slot__ = ("bracket", "arg")

    def __init__(self, bracket, arg):
        self.bracket = bracket
        self.arg = arg

    def saveInfo(self):
        return {"bracket": self.bracket, "arg": self.arg}, None

    def meaning(self, parser):
        return f"#{self.arg}{parser.toksToString([self.bracket])}"
    
    def __eq__(self, value):
        return isinstance(value, ReadArgDelim1Caller) and comapreToks(self.bracket, value.bracket)

    def __call__(self, parser, macro, args):
        token = parser.token
        result = []
        append = result.append
        while True:
            t = token()
            if t is None:
                raise ValueError(f"macro does not match the definition {macro}", parser.input.position())
            if t.catcode == self.bracket.catcode and t.name == self.bracket.name:
                args.append(result)
                return args
            if t.catcode == CATCODE.BEGIN_GROUP:
                keep = bool(result)
                append(t)
                result, end = parser.readTo(CATCODE.END_GROUP, result)
                if keep:
                    append(end)
                    continue
                t = token()
                if t is None:
                    raise ValueError(f"macro does not match the definition {macro}", parser.input.position())
                if t.catcode == self.bracket.catcode and t.name == self.bracket.name:
                    args.append(result if keep else result[1:])
                    return args
                append(end)
            append(t)


class ReadArgDelim2Caller(Serializable):
    """
    a caller is a function that reads the arguments of a macro from the input stack
    and appends them to the argument list
    """
    __slot__ = ("bracket", "arg")

    def __init__(self, bracket, arg):
        self.bracket = bracket
        self.arg = arg

    def saveInfo(self):
        return {"bracket": self.bracket, "arg": self.arg}, None
    
    def meaning(self, parser):
        return f"#{self.arg}{parser.toksToString(self.bracket)}"

    def __eq__(self, value):
        return isinstance(value, ReadArgDelim2Caller) and comapreToks(self.bracket, value.bracket)

    def __call__(self, parser, macro, args):
        bracket_len = len(self.bracket)
        t = _matchDelimited(parser, macro, self.bracket, bracket_len)
        if t is None:
            args.append([])
            return args
        if t.catcode == CATCODE.BEGIN_GROUP:
            result, end = parser.readTo(CATCODE.END_GROUP, [t])
            t = _matchDelimited(parser, macro, self.bracket, bracket_len)
            if t is None:
                args.append(result[1:])
                return args
            result.append(end)
            result.append(t)
        else:
            result = [t]
        while True:
            t = _matchDelimited(parser, macro, self.bracket, bracket_len)
            if t is None:
                args.append(result)
                return args
            result.append(t)
            if t.catcode == CATCODE.BEGIN_GROUP:
                result, end = parser.readTo(CATCODE.END_GROUP, result)
                result.append(end)


def _compileCalls(pattern):
    """
    Compile a macro parameter pattern into runtime call objects.
    @param pattern: the canonical macro pattern token list
    @return: the compiled call list
    """
    calls = []
    arg_count = 0
    bracket = []
    i = 0
    n = len(pattern)
    expected = None

    while i < n:
        p = pattern[i]
        if p.catcode != CATCODE.PARAMETER:
            bracket.append(p)
            i += 1
            continue
        kind, value, i = _readPatternParameter(pattern, i)
        if kind == "hash":
            bracket.append(value)
            continue
        if kind == "token":
            bracket.append(value)
            continue
        if kind == "invalid":
            raise ValueError(
                f"invalid parameter {value.name}" if value is not None else "macro argument expected"
            )
        if value == 0:
            expected = 0
            break
        raise ValueError("macro argument must be consecutively numbered from 1")

    if bracket:
        calls.append(MatchStartCaller(bracket))
        bracket = []
    if expected is None:
        return calls, arg_count

    while True:
        has_next = False
        while i < n:
            p = pattern[i]
            if p.catcode != CATCODE.PARAMETER:
                bracket.append(p)
                i += 1
                continue
            kind, value, i = _readPatternParameter(pattern, i)
            if kind == "hash":
                bracket.append(value)
                continue
            if kind == "token":
                bracket.append(value)
                continue
            if kind == "invalid":
                raise ValueError(
                    f"invalid parameter {value.name}" if value is not None else "macro argument expected"
                )
            if value >= 9:
                raise ValueError("too many parameters in macro definition")
            if value != expected + 1:
                raise ValueError("macro argument must be consecutively numbered from 1")
            has_next = True
            break
        width = len(bracket)
        if width == 0:
            calls.append(ReadArgUnDelimCaller(expected + 1))
        elif width == 1:
            calls.append(ReadArgDelim1Caller(bracket[0], expected + 1))
        else:
            calls.append(ReadArgDelim2Caller(bracket, expected + 1))
        arg_count += 1
        bracket = []
        if not has_next:
            return calls, arg_count
        expected += 1


def _compileReplacementPieces(replacement, arg_count):
    """
    Compile replacement tokens into a leading literal followed by
    ``(arg_index, trailing_literal)`` pairs.
    """
    literal = []
    pieces = [literal]
    i = 0
    n = len(replacement)
    while i < n:
        t = replacement[i]
        if t.catcode != CATCODE.PARAMETER:
            literal.append(t)
            i += 1
            continue
        kind, value, i = _readReplacementParameter(replacement, i)
        if kind == "hash":
            literal.append(value)
            continue
        if kind == "token":
            literal.append(value)
            continue
        if kind == "invalid":
            raise ValueError(
                f"invalid parameter {value.name}" if value is not None else "invalid parameter"
            )
        if value >= arg_count:
            raise ValueError(f"invalid parameter number: #{value+1}")
        literal = []
        pieces.append((value, literal))
    return pieces


class Macro(Command):
    """
    a macro is defined by brackets and the replacement text
    """
    __slot__ = ("pattern", "calls", "replacement", "replacement_pieces", "long", "outer", "protected", "_has_argument")

    def __init__(self, pattern: list, replacement: list):
        self.pattern = pattern
        self.calls, arg_count = _compileCalls(pattern)
        self.replacement = replacement
        self.replacement_pieces = _compileReplacementPieces(replacement, arg_count)
        self.long = False
        self.outer = False
        self.protected = False
        self._has_argument = arg_count > 0

    def className(self):
        return Serializable.className(self)
    
    def saveInfo(self):
        return {
                "pattern": self.pattern,
                "replacement": self.replacement,
            }, {
                "long": self.long,
                "outer": self.outer,
                "protected": self.protected
            }

    @classmethod
    def new(cls, parser, **kwargs):
        """
        create a new object from the dictionary
        """
        return cls(**kwargs)

    def meaning(self, parser):
        long = "\\long " if self.long else ""
        outer = "\\outer " if self.outer else ""
        protected = "\\protected " if self.protected else ""
        args = parser.toksToString(self.pattern)
        s = f"{long}{outer}{protected}{args}->{parser.toksToString(self.replacement)}"
        return s
    
    def expand(self, parser):
        """
        expand the macro
        @param parser: the parser
        """
        # we first read the arguments
        args = []
        for c in self.calls:
            c(parser, self, args)
        # we now create a MacroScanner and read from it.
        # only if the replacement text is not empty
        if self.replacement:
            if not self._has_argument:
                parser.input.push(TokenListScanner(self.replacement_pieces[0]))
            else:
                replacement = list(self.replacement_pieces[0])
                extend = replacement.extend
                for arg, literal in self.replacement_pieces[1:]:
                    extend(args[arg])
                    extend(literal)
                if replacement:
                    parser.input.push(TokenListScanner(replacement))
    
    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, Macro):
            return False
        if self.long != other.long or self.outer != other.outer or self.protected != other.protected:
            return False
        if comapreToks(self.pattern, other.pattern) is False:
            return False
        return comapreToks(self.replacement, other.replacement)


class MacroAccessor(EquitableAccessor):
    """
    an accessor for the \\def command
    @param entry: the entry in the equitable
    @param globally: whether the definition is global
    """
    def readEq(self, parser):
        """
        \\def does not use an equal sign
        """
        pass

    def readValue(self, parser):
        """
        read the macro definition from the input stack

        The macro definition is a parameter text followed by a balanced text.
        @param parser: the parser
        """
        # read the brackets
        tail = None
        pattern, end = parser.readTo(
            CATCODE.BEGIN_GROUP,
            expand=False,
            builder=toks.MacroBodyBuilder(parser),
        )
        if (
            pattern and
            pattern[-1].catcode == CATCODE.PARAMETER and
            getattr(pattern[-1], "parameter", None) is None
        ):
            pattern.pop()
            pattern.append(end)
            tail = end
        # read the replacement text
        replacement, _end = parser.readTo(
            CATCODE.END_GROUP,
            expand=self.expand_body,
            builder=toks.MacroBodyBuilder(parser),
        )
        if tail:
            replacement.append(tail)
        try:
            macro = Macro(pattern, replacement)
        except ValueError as e:
            raise ValueError(e.args[0], parser.input.position())
        macro.name = self.key
        if parser.tracingmacros and parser.checkRange():
            parser.message(f"macro {self.key}: {macro.meaning(parser)}")
        return macro
    
    def assign(self, parser, prefixes):
        """
        assign the macro to the index
        @param parser: the parser
        @param prefixes: the prefixes to the assignment
        """
        if self.globally:
            prefixes.insert(0, GlobalPrefix())
        super().assign(parser, prefixes)


class Def(MacroAccessor):
    """
    define a macro

    @param globally: whether the definition is global
    @param expand_body: whether the replacement text is expanded
    """
    def __init__(self, globally, expand_body):
        super().__init__(None)
        self.globally = globally
        self.expand_body = expand_body


class Long(Prefix):
    """
    the \\long prefix
    """
    def modify(self, value, globally):
        if not isinstance(value, Macro):
            raise ValueError("long can only be applied to a macro")
        value.long = True
        return value, globally


class Outer(Prefix):
    """
    the \\outer prefix
    """
    def modify(self, value, globally):
        if not isinstance(value, Macro):
            raise ValueError("long can only be applied to a macro")
        value.outer = True
        return value, globally


mod = Module("macro",
  commands={
    "def": Def(globally=False, expand_body=False),
    "gdef": Def(globally=True, expand_body=False),
    "edef": Def(globally=False, expand_body=True),
    "xdef": Def(globally=True, expand_body=True),
    "long": Long(),
    "outer": Outer()
  }
)
