"""
This module implements macros.
"""


from pytex.token import CATCODE, Command, ParameterToken, CharToken
from pytex.accessor import Prefix, Accessor
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
        self.arg_scanner = None
        parser.input.push(self)
        # read the next token
        self.next_token = next(self.replacement)

    position = None
    
    def read(self):
        """
        read the next token from the replacement text

        handle arguments and ## in the replacement text
        """
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
                self.arg_scanner = iter(args)
                self.next_token = next(self.arg_scanner)
            else:
                self.arg_scanner = None
                try:
                    self.next_token = next(self.replacement)
                except StopIteration:
                    return None
            return self.read()
        if self.arg_scanner is not None:
            try:
                self.next_token = next(self.arg_scanner)
            except StopIteration:
                self.arg_scanner = None
                try:
                    self.next_token = next(self.replacement)
                except StopIteration:
                    self.next_token = None
        else:
            try:
                self.next_token = next(self.replacement)
            except StopIteration:
                self.next_token = None
        # tail recursion optimization
        if self.next_token is None:
            self.parser.input.unread(t)
            return None
        return t

    def __repr__(self):
        args = []
        for i in range(len(self.args)):
            args.append(f"#{i+1}<-" + "".join([tokenToString(t, "\\", True) for t in self.args[i]]))
        s = "\n  ".join(args)
        return f"{self.name}: {super().__repr__()}\n  {s})" 


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

    def parameters(self):
        """
        return the parameters of the macro
        """
        result = self.brackets[0].copy()
        arg = 0
        for b in self.brackets[1:]:
            t = ParameterToken("#", CATCODE.PARAMETER)
            arg += 1
            result.append(t)
            n = CharToken(str(arg), CATCODE.OTHER)
            result.append(n)
            result.extend(b)
            if b and b[-1].catcode == CATCODE.BEGIN_GROUP:
                brace = b.pop()
                result.append(t)
                result.append(brace)
        return result

    def __repr__(self):
        long = "\\long " if self.long else ""
        outer = "\\outer " if self.outer else ""
        protected = "\\protected " if self.protected else ""
        return f"{long}{outer}{protected}{toString(self.parameters())}->{toString(self.replacement)}"

    def meaning(self, parser):
        return str(self)

    def matchDelimited(self, parser, bracket):
        """
        match the next delimiter in the parameter list
        @param parser: the parser
        @param start: the start position in the parameters list
        @return: None if matched, or the next token
        """
        if bracket:
            matched = []
            for p in bracket:
                t = parser.token()
                if t is None:
                    raise ValueError(f"macro does not match the definition {self}", parser.input.position())
                if t.catcode != p.catcode or t.name != p.name:
                    if matched:
                        parser.input.unread(t)
                        t = matched[0]
                        for t in reversed(matched[1:]):
                            parser.input.unread(t)
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
        result = []
        # if the bracket is empty, then the argument is undelimited. In this case, the argument 
        # is the next non-space token,, and if the token is {, then the argument is a balanced text
        if not bracket:
            t = parser.skipSpaces(expand=False)
            if t is None:
                return []
            parser.input.unread(t)
            return parser.readBalancedText(expand=False, macro=False, include_braces=False)
        # otherwise, the argument is delimited. In this case, we match the next delimiter
        # in the parameter list. If the delimiter is not matched, we put the unmatched token
        # in the argument and match again.
        #
        # n counts the number of balanced text read. If n == 1 and the argument is 
        # enclosed by braces, we drop the braces
        n = 0 
        while True:
            t = self.matchDelimited(parser, bracket)
            if t:
                if t.catcode == CATCODE.BEGIN_GROUP:
                    parser.input.unread(t)
                    l = parser.readBalancedText(expand=False, macro=False, include_braces=True)
                    result.extend(l)
                else:
                    result.append(t)
                n += 1
            else:
                # we have matched the argument
                # if the argument is enclosed by braces, drop the braces
                if n == 1 and result[0].catcode == CATCODE.BEGIN_GROUP:
                    result.pop()
                    result.pop(0)
                return result

    def expand(self, parser):
        """
        expand the macro
        @param parser: the parser
        """
        # we first read the arguments
        args = []
        # the first bracket
        bracket = self.brackets[0]
        t = self.matchDelimited(parser, bracket)
        if t:
            raise ValueError(f"macro does not match the definition {self}", parser.input.position())
        for bracket in self.brackets[1:]:
            args.append(self.readArgument(parser, bracket))
        # we now create a MacroScanner and read from it.
        # only if the replacement text is not empty
        if self.replacement:
            scanner = MacroScanner(parser, self.replacement, args)
            scanner.name = self.name
            # scanner is already pushed onto the stack
    
    def __eq__(self, other):
        # this is used by the \\ifx command to compare two macros
        if isinstance(other, Macro):
            return self.brackets == other.brackets and self.replacement == other.replacement
        return False


class MacroAccessor(Accessor):
    """
    an accessor for the \\def command
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
                    parser.input.unread(n)
                    tail = n
                    brackets.append(bracket)
                    break
                else:
                    raise ValueError("macro argument must be consecutively numbered from 1", parser.input.position())
            elif t.catcode == CATCODE.BEGIN_GROUP:
                brackets.append(bracket)
                parser.input.unread(t)
                break
            else:
                bracket.append(t)
        # read the replacement text
        replacement = parser.readBalancedText(expand=self.expand_body, macro=True, include_braces=False)
        if tail:
            replacement.append(tail)
        macro = Macro(brackets, replacement)
        macro.name = self.index
        if parser.tracingmacros and parser.checkRange():
            parser.message(f"macro {self.index}: {macro}")
        return macro
    
    def setValue(self, parser, value, globally):
        return super().setValue(parser, value, self.globally or globally)


class Def(Define):
    """
    define a macro

    @param globally: whether the definition is global
    @param expand_body: whether the replacement text is expanded
    """
    def __init__(self, globally, expand_body):
        Define.__init__(self)
        self.globally = globally
        self.expand_body = expand_body
    
    def saveInfo(self):
        return {
            "init": {
                "globally": self.globally,
                "expand_body": self.expand_body
            }
        }
    
    def getItemAccessor(self, parser, index):
        p = MacroAccessor(self.domain, self.getIndex(parser))
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
