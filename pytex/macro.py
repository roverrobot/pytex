"""
This module implements macros.
"""


from pytex.token import CATCODE, Command, ParameterToken
from pytex.accessor import Prefix, GlobalPrefix, Accessor
from pytex.define import EquitableAccessor
from pytex.module import Module
from pytex.lexer import TokenListScanner
from pytex.serialization import Serializable


class MacroScanner:
    """
    a scanner for expanding the macro replacement text
    """
    def __init__(self, replacement, args):
        # stack of suspended macro-expansion frames
        self.frames = []
        # Read tokens from replacement text and temporarily switch to argument
        # token lists when encountering #1..#9 placeholders.
        self.active = None
        self.pending = None
        self.resume = None
        self.args = []
        self.pushExpansion(replacement, args)

    position = None
    def pushExpansion(self, replacement, args):
        """
        push a macro expansion frame
        """
        if self.active is not None:
            # Tail-call optimization: if there is no continuation in this scanner,
            # replace the active frame instead of saving it.
            if self.resume is not None:
                self.frames.append((self.active, self.pending, self.resume, self.args))
            else:
                if self.pending is None:
                    self.pending = next(self.active, None)
                if self.pending is not None:
                    self.frames.append((self.active, self.pending, self.resume, self.args))
        self.active = iter(replacement)
        self.pending = None
        self.resume = None
        self.args = args

    def read(self):
        """
        read the next token from the replacement text

        handle arguments and ## in the replacement text
        """
        while True:
            if self.pending is not None:
                t = self.pending
                self.pending = None
            else:
                t = next(self.active, None)
                if t is None:
                    if self.resume is not None:
                        self.active = self.resume
                        self.resume = None
                        self.pending = None
                        continue
                    if self.frames:
                        self.active, self.pending, self.resume, self.args = self.frames.pop()
                        continue
                    return None

            # check if t represent a parameter
            if t.catcode == CATCODE.PARAMETER and t.parameter is not None and self.resume is None:
                try:
                    args = self.args[t.parameter]
                except IndexError:
                    raise ValueError(f"invalid parameter number: #{t.parameter+1}", self.parser.input.position())
                if args:
                    self.resume = self.active
                    self.active = iter(args)
                # if the argument is empty, continue reading the replacement
                continue
            return t


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


def matchStart(parser, macro, bracket, _):
    """
    match the starting bracket raw tokens from the input stack not expanded.
    @param parser: the parser
    @param macro: the macro
    @param bracket: the bracket tokens to match
    @return: the start argument list
    """
    for b in bracket:
        t = parser.token()
        if t is None or t.catcode != b.catcode or t.name != b.name:
            raise ValueError(f"macro does not match the definition {macro}", parser.input.position())
    return []


def readArgUnDelim(parser, macro, bracket, args):
    """
    Read the next undelimited macro argument.
    @param parser: the parser
    @param macro: the macro
    @param bracket: the bracket token to match
    @param args: the argument list read so far
    """
    t = parser.skipSpaces(False)
    if t is None:
        return args.append([])
    if t.catcode != CATCODE.BEGIN_GROUP:
        return args.append([t])
    result, _end = parser.readTo(CATCODE.END_GROUP)
    args.append(result)


def readArgDelim1(parser, macro, bracket, args):
    """
    Read the next macro argument delimited by a single token.
    @param parser: the parser
    @param macro: the macro
    @param bracket: the delimiter token
    @param args: the argument list read so far
    """
    token = parser.token
    result = []
    append = result.append
    while True:
        t = token()
        if t is None:
            raise ValueError(f"macro does not match the definition {macro}", parser.input.position())
        if t.catcode == bracket.catcode and t.name == bracket.name:
            return args.append(result)
        if t.catcode == CATCODE.BEGIN_GROUP:
            # do we keep the { token?
            keep = bool(result)
            append(t)
            result, end = parser.readTo(CATCODE.END_GROUP, result)
            if keep:
                append(end)
                continue
            t = token()
            if t is None:
                raise ValueError(f"macro does not match the definition {macro}", parser.input.position())
            if t.catcode == bracket.catcode and t.name == bracket.name:
                if keep:
                    return args.append(result)
                return args.append(result[1:])
            append(end)
        append(t)


def readArgDelim2(parser, macro, bracket, args):
    """
    Read the next macro argument delimited by two or more tokens.
    @param parser: the parser
    @param macro: the macro
    @param bracket: the delimiter token list
    @param args: the argument list read so far
    """
    bracket_len = len(bracket)
    t = _matchDelimited(parser, macro, bracket, bracket_len)
    if t is None:
        return args.append([])
    if t.catcode == CATCODE.BEGIN_GROUP:
        result, end = parser.readTo(CATCODE.END_GROUP, [t])
        t = _matchDelimited(parser, macro, bracket, bracket_len)
        if t is None:
            return args.append(result[1:])
        result.append(end)
        result.append(t)
    else:
        result = [t]
    while True:
        t = _matchDelimited(parser, macro, bracket, bracket_len)
        if t is None:
            return args.append(result)
        result.append(t)
        if t.catcode == CATCODE.BEGIN_GROUP:
            result, end = parser.readTo(CATCODE.END_GROUP, result)
            result.append(end)


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


class MatchStartCaller(Serializable):
    """
    a caller is a function that reads the arguments of a macro from the input stack
    and appends them to the argument list
    """
    __slot__ = ("func", "bracket")
    def __init__(self, bracket):
        self.func = matchStart
        self.bracket = bracket

    def meaning(self, parser):
        return parser.toksToString(self.bracket)
    
    def __eq__(self, value):
        return isinstance(value, MatchStartCaller) and comapreToks(self.bracket, value.bracket)
    
    def saveInfo(self):
        return {"bracket": self.bracket}, None


class ReadArgUnDelimCaller(Serializable):
    """
    a caller is a function that reads the arguments of a macro from the input stack
    and appends them to the argument list
    """
    __slot__ = ("func", "bracket", "arg")

    def __init__(self, arg):
        self.func = readArgUnDelim
        self.bracket = None
        self.arg = arg

    def meaning(self, parser):
        return f"#{self.arg}"
    
    def __eq__(self, value):
        return isinstance(value, ReadArgUnDelimCaller)
    
    def saveInfo(self):
        return {"arg": self.arg}, None
    

class ReadArgDelim1Caller(Serializable):
    """
    a caller is a function that reads the arguments of a macro from the input stack
    and appends them to the argument list
    """
    __slot__ = ("func", "bracket", "arg")

    def __init__(self, bracket, arg):
        self.func = readArgDelim1
        self.bracket = bracket
        self.arg = arg

    def saveInfo(self):
        return {"bracket": self.bracket, "arg": self.arg}, None

    def meaning(self, parser):
        return f"#{self.arg}{parser.toksToString([self.bracket])}"
    
    def __eq__(self, value):
        return isinstance(value, ReadArgDelim1Caller) and comapreToks(self.bracket, value.bracket)


class ReadArgDelim2Caller(Serializable):
    """
    a caller is a function that reads the arguments of a macro from the input stack
    and appends them to the argument list
    """
    __slot__ = ("func", "bracket", "arg")

    def __init__(self, bracket, arg):
        self.func = readArgDelim2
        self.bracket = bracket
        self.arg = arg

    def saveInfo(self):
        return {"bracket": self.bracket, "arg": self.arg}, None
    
    def meaning(self, parser):
        return f"#{self.arg}{parser.toksToString(self.bracket)}"

    def __eq__(self, value):
        return isinstance(value, ReadArgDelim2Caller) and comapreToks(self.bracket, value.bracket)


def _compileCalls(pattern):
    """
    Compile a macro parameter pattern into runtime call objects.
    @param pattern: the canonical macro pattern token list
    @return: the compiled call list
    """
    calls = []
    p = None
    bracket = []
    patterns = iter(pattern)
    while True:
        p = next(patterns, None)
        if p is None:
            break
        if p.catcode == CATCODE.PARAMETER:
            if p.parameter == 0:
                break
            raise ValueError("macro argument must be consecutively numbered from 1")
        bracket.append(p)
    if bracket:
        calls.append(MatchStartCaller(bracket))
        bracket = []
    if p is not None:
        arg = 1
        while True:
            current_arg = arg
            p = next(patterns, None)
            if p is None or p.catcode == CATCODE.PARAMETER:
                if p is not None:
                    n = p.parameter
                    if n is None:
                        raise ValueError("macro argument expected")
                    if n >= 9:
                        raise ValueError("too many parameters in macro definition")
                    if n != arg:
                        raise ValueError("macro argument must be consecutively numbered from 1")
                    arg += 1
                n = len(bracket)
                if n == 0:
                    calls.append(ReadArgUnDelimCaller(current_arg))
                elif n == 1:
                    calls.append(ReadArgDelim1Caller(bracket[0], current_arg))
                else:
                    calls.append(ReadArgDelim2Caller(bracket, current_arg))
                bracket = []
                if p is None:
                    break
            else:
                bracket.append(p)
    return calls


class Macro(Command):
    """
    a macro is defined by brackets and the replacement text
    """
    def __init__(self, pattern: list, replacement: list):
        self.pattern = pattern
        self.calls = _compileCalls(pattern)
        self.replacement = replacement
        self.long = False
        self.outer = False
        self.protected = False
        self._has_argument = False
        for t in replacement:
            if t.catcode == CATCODE.PARAMETER and t.parameter is not None:
                self._has_argument = True
                break

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
            c.func(parser, self, c.bracket, args)
        # we now create a MacroScanner and read from it.
        # only if the replacement text is not empty
        if self.replacement:
            if not self._has_argument:
                parser.input.push(TokenListScanner(self.replacement))
            else:
                top = parser.input.top
                if isinstance(top, MacroScanner) and not parser.input.saved:
                    top.pushExpansion(self.replacement, args)
                else:
                    parser.input.push(MacroScanner(self.replacement, args))
    
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
        pattern, end = parser.readTo(CATCODE.BEGIN_GROUP, expand=False, macro_body=True)
        if pattern and pattern[-1].catcode == CATCODE.PARAMETER and pattern[-1].parameter is None:
            pattern.pop()
            pattern.append(end)
            tail = end
        # read the replacement text
        replacement, _end = parser.readTo(
            CATCODE.END_GROUP,
            expand=self.expand_body,
            macro_body=True,
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
  attributes={
    "matchStart": matchStart,
    "readArgUnDelim": readArgUnDelim,
    "readArgDelim1": readArgDelim1,
    "readArgDelim2": readArgDelim2,
  },
  commands={
    "def": Def(globally=False, expand_body=False),
    "gdef": Def(globally=True, expand_body=False),
    "edef": Def(globally=False, expand_body=True),
    "xdef": Def(globally=True, expand_body=True),
    "long": Long(),
    "outer": Outer()
  }
)
