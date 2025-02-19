"""
This module implements macros.
"""


import typing
from pytex.token import CATCODE, Command, Token
from pytex.lexer import TokenListScanner
from pytex.accessor import Prefix, Accessor
from pytex.define import Define
from pytex.module import Module
from pytex.expandable import tokenToString


class MacroScanner(TokenListScanner):
    """
    a scanner for expanding the macro replacement text
    """
    def __init__(self, parser, replacement, args):
        TokenListScanner.__init__(self, replacement)
        self.parser = parser
        self.args = args
        self.arg_scanner = None
        parser.input.push(self)
    
    def next(self):
        # if we are in the middle of reading an argument, we read from the argument scanner
        if self.arg_scanner is not None:
            t = self.arg_scanner.read()
            if t is not None:
                return t
        self.arg_scanner = None
        return super().read()

    def eof(self):
        # if we are not reading an argument, and we have reached
        # the end of the replacement text, then we are done
        return super().eof() and (self.arg_scanner is None or self.arg_scanner.eof())
    
    def checkEOF(self, t):
        # return the token, and perform tail recursion optimization
        if self.eof():
            if t is not None:
                self.parser.input.unread(t)
            return None
        return t

    def read(self):
        """
        read the next token from the replacement text

        handle arguments and ## in the replacement text
        """
        t = self.next()
        # tail recursion optimization
        # has we reached the end?
        if t is None or t.catcode != CATCODE.PARAMETER:
            return self.checkEOF(t)
        # handle the case where the next token is ##
        t = self.next()
        if t is None:
            raise ValueError("invalid macro replacement text, # must be followed by a number or another #", self.input.position())
        if t.catcode == CATCODE.PARAMETER:
            return self.checkEOF(t)
        # if the next token is a number, then we read the argument
        if "1" <= t.name <= "9":
            i = ord(t.name) - ord("1")
            if i >= len(self.args):
                raise ValueError("macro has too few arguments")
            self.arg_scanner = TokenListScanner(self.args[i])
            return self.read()
        raise ValueError("invalid macro replacement text, # must be followed by a number of another #", self.input.position())

    def __repr__(self):
        args = []
        for i in range(len(self.args)):
            args.append(f"#{i+1}<-" + "".join([tokenToString(t, "\\", True) for t in self.args[i]]))
        s = "\n  ".join(args)
        return f"{self.macro.name}: {super().__repr__()}\n  {s})" 


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


def toString(toks):
    """
    convert a list of tokens to a string
    """
    return "".join([ t.name+" " if t.catcode is None else t.name for t in toks ])


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
        long = "\\long " if self.long else ""
        outer = "\\outer " if self.outer else ""
        protected = "\\protected " if self.protected else ""
        return f"{long}{outer}{protected}{toString(self.parameters)}->{toString(self.replacement)}"

    def meaning(self, parser):
        return str(self)

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
            if t.catcode != p.catcode or t.name != p.name:
                if len(matched) == 0:
                    return t, start
                parser.input.unread(t)
                for i in range(len(matched)-1, 0, -1):
                    parser.input.unread(matched[i])
                return matched[0], start
            matched.append(t)
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
            toks = parser.readBalancedText(expand=False, include_braces=False, parpar=True)
            return toks, i
        # otherwise, the argument is delimited. In this case, we match the next delimiter
        # in the parameter list. If the delimiter is not matched, we put the unmatched token
        # in the argument and match again.
        while i < len(self.parameters):
            t, i = self.matchDelimited(parser, i)
            if t is None:
                return result, i
            parser.input.unread(t)
            l = parser.readBalancedText(expand=False, include_braces=True, parpar=True)
            result.extend(l)

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
                raise ValueError(f"macro does not match the definition {self} at {t}", pos)
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
            if parser.tracingmacros:
                s = "".join([tokenToString(t, "\\", True) for t in argv])
                parser.message(f"#{p.name}<-{s}")
            args.append(argv)
        # we now create a MacroScanner and read from it.
        # only if the replacement text is not empty
        if len(self.replacement) > 0:
            scanner = MacroScanner(parser, self.replacement, args)
            # scanner is already pushed onto the stack
    
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
        tail = None
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
                elif n.name == "{":
                    parameters.append(n)
                    parser.input.unread(n)
                    tail = n
                    break
                else:
                    raise ValueError("macro argument must be consecutively numbered from 1", pos)
            elif t.catcode == CATCODE.BEGIN_GROUP:
                parser.input.unread(t)
                break
            else:
                parameters.append(t)
        # read the replacement text
        replacement = parser.readBalancedText(expand=self.expand_body, include_braces=False, parpar=False)
        if tail:
            replacement.append(tail)
        macro = Macro(parameters, replacement)
        macro.name = self.index
        if parser.tracingmacros:
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
