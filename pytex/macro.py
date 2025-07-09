"""
This module implements macros.
"""


from pytex.token import CATCODE, Command, ParameterToken, CharToken
from pytex.accessor import Prefix, GlobalPrefix, ParameterAccessor
from pytex.define import Define
from pytex.module import Module
from pytex.expandable import tokenToString


class MacroScanner:
    """
    a scanner for expanding the macro replacement text
    """
    def __init__(self, parser, replacement, args):
        self.replacement = iter(replacement)
        self.parser = parser
        self.args = args
        parser.input.push(self)
        self.active = self.replacement
        # read the next token. Note that replacement is guaranteed to be unon-empty,
        # so this always succeeds
        self.next_token = next(self.active)

    position = None

    def read(self):
        """
        read the next token from the replacement text

        handle arguments and ## in the replacement text
        """
        while True:
            t = self.next_token
            if t is None:
                return t
            # check if t represent a parameter
            if t.catcode == CATCODE.PARAMETER and t.parameter is not None:
                try:
                    args = self.args[t.parameter]
                except IndexError:
                    raise ValueError(f"invalid parameter number: #{t.parameter+1}", self.parser.input.position())
                if args:
                    self.active = iter(args)
                    self.next_token = next(self.active)
                    continue
                # we got empty an argument. Continue reading the replacement text
                try:
                    self.next_token = next(self.active)
                    continue
                except StopIteration:
                    # we are done with the replacement text
                    return None
            # read next_token. Here t is not None and is not a parameter token
            try:
                self.next_token = next(self.active)
            except StopIteration:
                # the current token list is exhausted. We need to check if we are reading from
                # an argument list. If so, we need to switch to the replacement text
                if self.active is not self.replacement:
                    self.active = self.replacement
                    try:
                        self.next_token = next(self.active)
                    except StopIteration:
                        self.next_token = None
                        self.parser.input.pop()  # pop the scanner
                else:
                    self.next_token = None
                    self.parser.input.pop()  # pop the scanner
            return t

    def __repr__(self):
        args = []
        for i in range(len(self.args)):
            args.append(f"#{i+1}<-" + "".join([tokenToString(t, "\\", True) for t in self.args[i]]))
        s = "\n  ".join(args)
        return f"{self.name}: {super().__repr__()}\n  {s}" 


def toString(toks):
    """
    convert a list of tokens to a string
    """
    return "".join([tokenToString(t, "\\", True) for t in toks ])


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

    @classmethod
    def showmeaning(cls, macro):
        long = "\\long " if macro.long else ""
        outer = "\\outer " if macro.outer else ""
        protected = "\\protected " if macro.protected else ""
        return f"{long}{outer}{protected}macro:{toString(cls.parameters(macro.brackets))}->{toString(macro.replacement)}"
    
    def meaning(self):
        return Macro, self

    def matchDelimited(self, parser, bracket):
        """
        match the next delimiter in the parameter list
        @param parser: the parser
        @param bracket: a token list to match
        @return None for matched, or a token list that has been read but not matched
        """
        matched = []
        for p in bracket:
            t = parser.token()
            if t is None:
                raise ValueError(f"macro does not match the definition {self}", parser.input.position())
            if t.catcode != p.catcode or t.name != p.name:
                if matched:
                    parser.input.unread(t)
                    for m in reversed(matched[1:]):
                        parser.input.unread(m)
                    return matched[0]
                return t
            matched.append(t)
        return None

    def readArgument(self, parser, bracket):
        """
        read the next argument
        @param parser: the parser
        @param start: the start position in the parameters list
        @return: the argument as a list of tokens
        """
        # if the bracket is empty, then the argument is undelimited. In this case, the argument 
        # is the next non-space token,, and if the token is {, then the argument is a balanced text
        if not bracket:
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
        t = self.matchDelimited(parser, bracket)
        if t is None:
            return []
        if t.catcode == CATCODE.BEGIN_GROUP:
            result = parser.readBalancedText([t], expand=False, macro=False)
            t = self.matchDelimited(parser, bracket)
            if t is None:
                # matched the bracket: the argument is enclosed in {}. Drop them
                return result[1:-1]
            result.append(t)
        else:
            result = [t]
        while True:
            t = self.matchDelimited(parser, bracket)
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
                parser.message(f"#{len(args)}<-{toString(arg)}")
        # we now create a MacroScanner and read from it.
        # only if the replacement text is not empty
        if self.replacement:
            scanner = MacroScanner(parser, self.replacement, args)
            scanner.name = self
            # scanner is already pushed onto the stack

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
            parser.message(f"macro {self.entry.name}: {macro}")
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
