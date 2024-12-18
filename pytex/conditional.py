"""
This module implements conditional commands such as \\\if and \\ifx etc.
"""


import typing
from pytex.token import CATCODE, Command, Token
from pytex.module import Module

def skipBranch(parser):
    """
    skip all tokens in a branch, until an \\else, \\or or \\fi is encountered.
    @param parser: the parser
    @return: the command that was encountered    """
    pos = parser.input.position()
    while True:
        t = parser.token()
        if t is None:
            c, cpos = parser.ifstack[-1]
            raise ValueError("missing a \\fi match matches the {c.name} at {cpos}", pos)
        if t.is_command:
            c = parser.lookup(t.name)
            if c is None:
                continue
            if isinstance(c, Branch):
                return c


class Branch(Command):
    """
    the base class for a branch. Commands such as \else, \or, and \fi are subclasses of this class.
    @param command_name: the name of the command
    """
    def __init__(self, command_name: str):
        self.command_name = command_name
    
    def skipAll(self, parser):
        """
        skip all tokens in a conditional command, until an \\fi is encountered.
        @param parser: the parser
        """
        while True:
            c = skipBranch(parser)
            if isinstance(c, Fi):
                parser.ifstack.pop()
                return

    def expand(self, parser):
        if len(parser.ifstack) == 0:
            raise ValueError("unexpected " + self.command_name)
        self.skipAll(parser)


class Else(Branch):
    """ the \\else command """
    def __init__(self):
        super().__init__("\\else")


class Or(Branch):
    """ the \\or command """
    def __init__(self):
        super().__init__("\\or")

    def expand(self, parser):
        if len(parser.ifstack) == 0 or not parser.ifstack[-1][0].is_case:
            raise ValueError("unexpected \\or")
        self.skipAll(parser)


class Fi(Branch):
    """ the \\fi command """
    def __init__(self):
        super().__init__("\\fi")

    def skipAll(self, parser):
        if len(parser.ifstack) == 0:
            raise ValueError("unexpected \\fi")
        parser.ifstack.pop()


class Conditional(Command):
    """
    The base class for all conditional commands.

    The main method of this class is condition, which should be overridden by subclasses to implement the condition
    of the conditional command.

    @param is_case: whether the command is an \\ifcase command
    """
    def __init__(self, name: str, is_case: bool = False):
        self.name = name
        self.is_case = is_case

    def condition(self, parser):
        """
        The condition of the conditional command.

        This method should be overridden by subclasses to implement the condition of the conditional command.
        It reads the tokens from the parser and returns an integer representing the braanch
        to be taken. The return value should be 0 for true and 1 for false. In the \\ifcase
        command, the return value should be the index of the branch to be taken, starting from 0.

        @param parser: the parser
        @return: the index pf the branch to be taken. 0 for true, 1 for false
        """
        # the default implementation is equivalent to \iftrue
        return 0

    def skipTo(self, parser, condition):
        for i in range(condition):
            c = skipBranch(parser)
            if isinstance(c, Or) and not self.is_case:
                raise ValueError("unexpected \\or")
            if isinstance(c, Else):
                return
            elif isinstance(c, Fi):
                parser.ifstack.pop()
                return

    def expand(self, parser):
        pos = parser.input.position()
        condition = self.condition(parser)
        parser.ifstack.append((self, pos))
        self.skipTo(parser, condition)


class IfCompareToken(Conditional):
    """ 
    the base class for \\if, \\ifx and \\ifcat

    @param name: the name of the command
    @param expand: whether the command should expand the tokens before comparing them
    """
    def __init__(self, name: str, expand_tokens: bool):
        super().__init__(name)
        self.expand_tokens = expand_tokens

    def equal(self, t1, t2):
        raise NotImplementedError()

    def condition(self, parser):
        pos = parser.input.position()
        if self.expand_tokens:
            t1 = parser.token_expand()
            t2 = parser.token_expand()
        else:
            t1 = parser.token()
            t2 = parser.token()
            if t1 is not None and t1.is_command:
                t1 = parser.lookup(t1.name)
            if t2 is not None and t2.is_command:
                t2 = parser.lookup(t2.name)
        if t1 is None or t2 is None:
            raise ValueError("expecting two tokens", pos)
        return 0 if self.equal(t1, t2) else 1


class IfCat(IfCompareToken):
    """ the \\ifcat command """
    def __init__(self):
        super().__init__("\\ifcat", expand_tokens=True)

    def equal(self, t1, t2):
        return t1.catcode == t2.catcode


class If(IfCompareToken):
    """ the \\if command """
    def __init__(self):
        super().__init__("\\if", expand_tokens=True)

    def equal(self, t1, t2):
        return t1.catcode == t2.catcode and (t1.catcode is None or t1.name == t2.name)


class IfX(IfCompareToken):
    """ the \\ifx command """
    def __init__(self):
        super().__init__("\\ifx", expand_tokens=False)
    
    def equal(self, t1, t2):
        # TEX does not expand control sequences when it looks at the two tokens.
        # The condition is true if (a) the two tokens are not macros, and they both 
        # represent the same (character code, category code) pair or the same TEX 
        # primitive or the same \font or \chardef or \countdef, etc.
        # or if (b) the two tokens are macros, and they both have the same status 
        # with respect to \long and \outer, and they both have the same
        # parameters and “top level” expansion.
        if t1 == t2:
            return True
        if t1.catcode != t2.catcode:
            return False
        # now t1 and t2 must have the same catcode
        if t1.catcode != None:
            return t1.name == t2.name
        return False


class IfCase(Conditional):
    """ the \\ifcase command """
    def __init__(self):
        super().__init__("\\ifcase", is_case=True)

    def condition(self, parser):
        return parser.readInteger()


class IfNum(Conditional):
    """ the \\ifnum command """
    def __init__(self, name: str="\\ifnum"):
        super().__init__(name)

    def readValue(self, parser):
        return parser.readInteger()

    def condition(self, parser):
        n1 = self.readValue(parser)
        pos = parser.input.position()
        op = parser.token_expand()
        if op is None or op.catcode != CATCODE.OTHER or op.name not in "<=>":
            raise ValueError("expecting a comparison operator", pos)
        n2 = self.readValue(parser)
        if op.name == "<":
            return 0 if n1 < n2 else 1
        if op.name == "=":
            return 0 if n1 == n2 else 1
        return 0 if n1 > n2 else 1


class IfDim(IfNum):
    """ the \\ifdim command """
    def __init__(self):
        super().__init__("\\ifdim")

    def readValue(self, parser):
        return parser.readDimen()


class IfOdd(Conditional):
    """ the \\ifodd command """
    def __init__(self):
        super().__init__("\\ifodd")

    def condition(self, parser):
        n = parser.readInteger()
        return 0 if n % 2 == 1 else 1


# The default behavior of Conditional is \iftrue

class IfFalse(Conditional):
    """ the \\iffalse command """
    def __init__(self):
        super().__init__("\\iffalse")

    def condition(self, parser):
        return 1


# other conditional commands will be implemented inother modules
# \if[vhm]mode, \ifinner will be implemented with hlists and vlists
# \ifvoid, \ifhbox, \ifvbox will be implemented with boxes
# \ifoef will be implemented with file operations

mod = Module("conditional",
    commands={
        "if": If(),
        "ifx": IfX(),
        "ifcat": IfCat(),
        "ifnum": IfNum(),
        "ifdim": IfDim(),
        "ifcase": IfCase(),
        "ifodd": IfOdd(),
        "iftrue": Conditional("\\iftrue"),
        "iffalse": IfFalse(),
        "else": Else(),
        "or": Or(),
        "fi": Fi(),
    }
)
