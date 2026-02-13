"""
This module implements macros.
"""


from pytex.token import CATCODE, Command, ParameterToken, CharToken
from pytex.accessor import Prefix, GlobalPrefix, ParameterAccessor
from pytex.define import Define
from pytex.module import Module


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
    stop = None

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


class Macro(Command):
    """
    a macro is defined by brackets and the replacement text
    """
    def __init__(self, brackets: list, replacement: list):
        self.brackets = brackets
        self.replacement = replacement
        self.long = False
        self.outer = False
        self.protected = False

    def saveInfo(self):
        brackets = []
        for b in self.brackets:
            brackets.append([t.serialize() for t in b])
        return {
            "init": {
                "brackets": brackets,
                "replacement": [t.serialize() for t in self.replacement],
            },
            "extra": {
                "long": self.long,
                "outer": self.outer,
                "protected": self.protected
            }
        }

    @classmethod
    def new(cls, parser, **kwargs):
        """
        create a new object from the dictionary
        """
        return cls(**kwargs)

    @staticmethod
    def parameters(brackets):
        """
        return the parameters of the macro
        """
        result = brackets[0].copy()
        arg = 0
        for b in brackets[1:]:
            t = ParameterToken("#", CATCODE.PARAMETER)
            t.parameter = arg
            arg += 1
            result.append(t)
            result.extend(b)
        return result

    def meaning(self, parser):
        long = "\\long " if self.long else ""
        outer = "\\outer " if self.outer else ""
        protected = "\\protected " if self.protected else ""
        return f"{long}{outer}{protected}macro:{parser.toksToString(self.parameters(self.brackets))}->{parser.toksToString(self.replacement)}"
    
    def matchDelimited(self, parser, bracket, bracket_len):
        """
        match the next delimiter in the parameter list
        @param parser: the parser
        @param bracket: a token list to match
        @param bracket_len: the length of bracket
        @return None for matched, or a token list that has been read but not matched
        """
        p = bracket[0]
        t = parser.token()
        if t is None:
            raise ValueError(f"macro does not match the definition {self}", parser.input.position())
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
                raise ValueError(f"macro does not match the definition {self}", parser.input.position())
            if t.catcode != p.catcode or t.name != p.name:
                parser.input.unread(t)
                if i > 2:
                    for m in reversed(matched):
                        parser.input.unread(m)
                return first
            matched.append(t)
        return None

    def readArgument(self, parser, bracket):
        """
        read the next argument
        @param parser: the parser
        @param start: the start position in the parameters list
        @return: the argument as a list of tokens
        """
        bracket_len = len(bracket)
        # if the bracket is empty, then the argument is undelimited. In this case, the argument 
        # is the next non-space token,, and if the token is {, then the argument is a balanced text
        if bracket_len == 0:
            # skip spaces
            while True:
                t = parser.token()
                if t is None:
                    return []
                if t.catcode != CATCODE.SPACE:
                    break
            if t.catcode == CATCODE.BEGIN_GROUP:
                result = parser.readBalancedText([], expand=False, macro=False)
                result.pop()
            else:
                result = [t]
            return result
        # otherwise, the argument is delimited. In this case, we match the next delimiter
        # in the parameter list. If the delimiter is not matched, we put the unmatched token
        # in the argument and match again.
        t = self.matchDelimited(parser, bracket, bracket_len)
        if t is None:
            return []
        if t.catcode == CATCODE.BEGIN_GROUP:
            result = parser.readBalancedText([t], expand=False, macro=False)
            t = self.matchDelimited(parser, bracket, bracket_len)
            if t is None:
                # matched the bracket: the argument is enclosed in {}. Drop them
                return result[1:-1]
            result.append(t)
        else:
            result = [t]
        while True:
            t = self.matchDelimited(parser, bracket, bracket_len)
            if t is None:
                return result
            result.append(t)
            if t.catcode == CATCODE.BEGIN_GROUP:
                result = parser.readBalancedText(result, expand=False, macro=False)

    def expand(self, parser):
        """
        expand the macro
        @param parser: the parser
        """
        # we first read the arguments
        args = []
        # the first bracket
        bracket = self.brackets[0]
        for b in bracket:
            t = parser.token()
            if t is None or t.catcode != b.catcode or t.name != b.name:
                raise ValueError(f"macro does not match the definition {self}", parser.input.position())
        for bracket in self.brackets[1:]:
            arg = self.readArgument(parser, bracket)
            args.append(arg)
            if parser.tracingmacros and parser.checkRange():
                parser.message(f"#{len(args)}<-{parser.toksToString(arg)}")
        # we now create a MacroScanner and read from it.
        # only if the replacement text is not empty
        if self.replacement:
            top = parser.input.top
            if isinstance(top, MacroScanner) and not parser.input.saved:
                top.pushExpansion(self.replacement, args)
            else:
                parser.input.push(MacroScanner(self.replacement, args))

    @classmethod
    def compareTokens(cls, l1, l2):
        """
        compare two lists of tokens at the first level
        @param l1: the first list
        @param l2: the second list
        @return: True if the lists are equal, False otherwise
        """
        if len(l1) != len(l2):
            return False
        for t1, t2 in zip(l1, l2):
            if t1.catcode != t2.catcode or t1.name != t2.name:
                return False
        return True

    def __eq__(self, other):
        if not isinstance(other, Macro):
            return False
        if self.long != other.long or self.outer != other.outer or self.protected != other.protected:
            return False
        if len(self.brackets) != len(other.brackets):
            return False
        for b1, b2 in zip(self.brackets, other.brackets):
            if not self.compareTokens(b1, b2):
                return False
        return self.compareTokens(self.replacement, other.replacement)


class MacroAccessor(ParameterAccessor):
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
        arg = 1
        # read the brackets
        tail = None
        brackets = []
        bracket = []
        while True:
            t = parser.token()
            if t is None:
                raise ValueError("expecting {", parser.input.position())
            if t.catcode == CATCODE.PARAMETER:
                n = parser.token()
                if n is None:
                    raise ValueError("macro argument expected", parser.input.position())
                if "1" <= n.name <= "9" and ord(n.name) - ord("0") == arg:
                    arg += 1
                    brackets.append(bracket)
                    bracket = []
                elif n.catcode == CATCODE.BEGIN_GROUP:
                    bracket.append(n)
                    tail = n
                    brackets.append(bracket)
                    break
                else:
                    raise ValueError("macro argument must be consecutively numbered from 1", parser.input.position())
            elif t.catcode == CATCODE.BEGIN_GROUP:
                brackets.append(bracket)
                break
            else:
                bracket.append(t)
        # read the replacement text
        replacement = parser.readBalancedText([], expand=self.expand_body, macro=True)
        # remove the trailing }
        replacement.pop()
        if tail:
            replacement.append(tail)
        macro = Macro(brackets, replacement)
        macro.name = self.entry.name
        if parser.tracingmacros and parser.checkRange():
            parser.message(f"macro {self.entry.name}: {macro.meaning(parser)}")
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


class Def(Define):
    """
    define a macro

    @param globally: whether the definition is global
    @param expand_body: whether the replacement text is expanded
    """
    def __init__(self, globally, expand_body):
        super().__init__(MacroAccessor)
        self.globally = globally
        self.expand_body = expand_body
    
    def getItemAccessor(self, parser):
        p = super().getItemAccessor(parser)
        p.expand_body = self.expand_body
        p.globally = self.globally
        return p


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
