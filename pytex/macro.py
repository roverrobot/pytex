"""
This module implements macros.
"""


import typing
from pytex.token import CATCODE, Command, Token
from pytex.lexer import TokenListScanner
from pytex.accessor import Prefix, Accessor
from pytex.define import Define
from pytex.module import Module


class MacroScanner(TokenListScanner):
    """
    a scanner for expanding the macro replacement text
    """
    def __init__(self, replacement, args):
        TokenListScanner.__init__(self, replacement)
        self.args = args
        self.arg_scanner = None
    
    def read(self):
        """
        read the next token from the replacement text

        handle arguments and ## in the replacement text
        """
        # if we are in the middle of reading an argument, we read from the argument scanner
        if self.arg_scanner is not None:
            t = self.arg_scanner.read()
            if t is None:
                self.arg_scanner = None
                return self.read()
            return t
        # otherwise, we read from the replacement
        t = super().read()
        # if we have reached the end of the replacement text, we return None
        if t is None:
            return None
        if t.catcode != CATCODE.PARAMETER:
            return t
        # handle the case where the next token is ##
        t = super().read()
        if t is None:
            raise ValueError("invalid macro replacement text, # must be followed by a number of another #", self.input.position())
        if t.catcode == CATCODE.PARAMETER:
            return t
        if "1" <= t.name <= "9":
            i = ord(t.name) - ord("1")
            if i >= len(self.args):
                raise ValueError("macro has too few arguments", self.input.position())
            self.arg_scanner = TokenListScanner(self.args[i])
            return self.read()
        raise ValueError("invalid macro replacement text, # must be followed by a number of another #", self.input.position())


def compareToks(toks1, toks2):
    """
    compare two token lists
    """
    if len(toks1) != len(toks2):
        return False
    for i in range(len(toks1)):
        x = toks1[i]
        y = toks2[i]
        if x.catcode != y.catcode or x.name != y.name:
            return False
    return True


class Macro(Command):
    """
    a macro is defined by brackets and the replacement text
    """
    def __init__(self, parameters: typing.List[Token], replacement: typing.List[Token]):
        self.parameters = parameters
        self.replacement = replacement
        self.long = False
        self.outer = False
        self.protected = False

    def saveInfo(self):
        return {
            "init": {
                "parameters": [t.serialize() for t in self.parameters],
                "replacement": [t.serialize() for t in self.replacement],
            },
            "extra": {
                "long": self.long,
                "outer": self.outer,
                "protected": self.protected
            }
        }

    def __repr__(self):
        return f"Macro({self.parameters},{self.replacement})"
    
    def matchDelimited(self, parser, start):
        """
        match the next delimiter in the parameter list
        @param parser: the parser
        @param start: the start position in the parameters list
        @return: a tuple. If matched, (None, next position in the parameters list)
        if not matched, (the unmatched token, start)
        """
        matched = []
        for i in range(start, len(self.parameters)): 
            p = self.parameters[i]
            if p.catcode == CATCODE.PARAMETER:
                return None, i
            t = parser.token()
            if t is None:
                raise ValueError(f"macro does not match the definition {self}", parser.input.position())
            matched.append(t)
            if t.catcode != p.catcode or t.name != p.name:
                t = matched.pop(0)
                for u in reversed(matched):
                    parser.input.unread(u)
                return t, start
        return None, len(self.parameters)

    def readArgument(self, parser, start):
        """
        read the next argument
        @param parser: the parser
        @param start: the start position in the parameters list
        @return: the argument and the next position in the parameters list
        """
        result = []
        i = start
        # if the next token to match is # or we have reached the end of the parameter list
        # then the argument is undelimited. In this case, the argument is the next non-space
        # token,, and if the token is {, then the argument is a balanced text
        if i >= len(self.parameters) or self.parameters[i].catcode == CATCODE.PARAMETER:
            parser.skipSpaces(expand=False)
            t = parser.token()
            if t is None:
                raise ValueError(f"macro does not match the definition {self}", parser.input.position())
            if t.catcode == CATCODE.BEGIN_GROUP:
                parser.input.unread(t)
                return parser.readBalancedText(expand=False), i
            return [t], i
        # otherwise, the argument is delimited. In this case, we match the next delimiter
        # in the parameter list. If the delimiter is not matched, we put the unmatched token
        # in the argument and match again.
        while i < len(self.parameters):
            t, i = self.matchDelimited(parser, i)
            if t is None:
                return result, i
            if t.catcode == CATCODE.BEGIN_GROUP:
                parser.input.unread(t)
                l = parser.readBalancedText(expand=False, include_braces=True)
                result.extend(l)
            else:
                result.append(t)

    def expand(self, parser):
        """
        expand the macro
        @param parser: the parser
        """
        # we first read the arguments
        i = 0
        argi = 1
        args = []
        while i < len(self.parameters):
            pos = parser.input.position()
            t, i = self.matchDelimited(parser, i)
            # if not matched, the macro does not match the definition
            if t is not None:
                raise ValueError("macro does not match the definition {self}", pos)
            # if matched and we have reached the end of the parameter list, that means 
            # we have matched all parameter texts, and so we break the loop
            if i >= len(self.parameters):
                break
            # the next token in parameters must be # followed by the argument number. 
            p = self.parameters[i]
            i += 1
            assert(p.catcode == CATCODE.PARAMETER and i < len(self.parameters))
            # we check the argument number which is the next token in the parameters list
            # we should not have reached the end of the parameters list
            p = self.parameters[i]
            assert("1" <= p.name <= "9" and ord(p.name) - ord("0") == argi)
            i += 1
            argi += 1
            # We read the argument and append it to thelist of arguments.
            argv, i = self.readArgument(parser, i)
            args.append(argv)
        # we now create a MacroScanner and read from it.
        scanner = MacroScanner(self.replacement, args)
        parser.input.push(scanner)
    
    def __eq__(self, other):
        # this is used by the \\ifx command to compare two macros
        try:
            return compareToks(self.parameters, other.parameters) and compareToks(self.replacement, other.replacement)
        except AttributeError:
            return False


class MacroAccessor(Accessor):
    """
    an accessor for the \\def command
    """
    def readEq(self, parser):
        """
        \def does not use an equal sign
        """
        pass

    def readValue(self, parser):
        """
        read the macro definition from the input stack

        The macro definition is a parameter text followed by a balanced text.
        @param parser: the parser
        """
        parameters = []
        arg = 1
        last = False
        # read the brackets
        while not last:
            t = parser.token()
            if t is None:
                raise ValueError("expecting {", parser.input.position())
            if t.catcode == CATCODE.PARAMETER:
                pos = parser.input.position()
                n = parser.token()
                if n is None:
                    raise ValueError("macro argument expected", pos)
                if "1" <= n.name <= "9" and ord(n.name) - ord("0") == arg:
                    parameters.append(t)
                    parameters.append(n)
                    arg += 1
                else:
                    raise ValueError("macro argument must be consecutively numbered from 1", pos)
            elif t.catcode == CATCODE.BEGIN_GROUP:
                parser.input.unread(t)
                break
            else:
                parameters.append(t)
        # read the replacement text
        replacement = parser.readBalancedText(expand=self.expanded)
        return Macro(parameters, replacement)
    
    def setValue(self, parser, value, globally):
        return super().setValue(parser, value, self.globally or globally)


class Def(Define):
    """
    define a macro

    @param globally: whether the definition is global
    @param expanded: whether the replacement text is expanded
    """
    def __init__(self, globally, expanded):
        Define.__init__(self)
        self.globally = globally
        self.expanded = expanded
    
    def saveInfo(self):
        return {
            "init": {
                "globally": self.globally,
                "expanded": self.expanded
            }
        }
    
    def getItemAccessor(self, parser, index):
        p = MacroAccessor(self.domain, self.getIndex(parser))
        p.expanded = self.expanded
        p.globally = self.globally
        return p


class MacroPrefix(Prefix):
    """
    the base class for prefixes for macro definition
    """
    def validate(self, command):
        if not isinstance(command, Def):
            raise ValueError("expecting a macro definition", command)


class Long(MacroPrefix):
    """
    the \\long prefix
    """
    def modify(self, value, globally):
        value.long = True
        return value, globally


class Outer(MacroPrefix):
    """
    the \\outer prefix
    """
    def modify(self, value, globally):
        value.outer = True
        return value, globally


mod = Module("macro",
  commands={
    "def": Def(globally=False, expanded=False),
    "gdef": Def(globally=True, expanded=False),
    "edef": Def(globally=False, expanded=True),
    "xdef": Def(globally=True, expanded=True),
    "long": Long(),
    "outer": Outer()
  }
)
