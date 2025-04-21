"""
This module implements conditional commands such as \\\if and \\ifx etc.
"""


import typing
from pytex.token import CATCODE, Command, Token, relax
from pytex.module import Module

def skipBranch(parser, level: list):
    """
    skip all tokens in a branch, until an \\else, \\or or \\fi is encountered.
    @param parser: the parser
    @param level: the current level of the ifstack
    @return: the command that was encountered    
    """
    while True:
        t = parser.token()
        if t is None:
            c, cpos, branch = parser.ifstack[-1]
            raise ValueError("missing a \\fi match matches the {c.name} at {cpos}", parser.input.position())
        if t.is_command:
            c = t.definition
            if isinstance(c, Conditional): # another level
                parser.ifstack.append([c, parser.input.position(), -1])
            elif isinstance(c, Branch):
                if level is parser.ifstack[-1]:
                    return c
                if isinstance(c, Fi):
                    parser.ifstack.pop()


def skipAll(parser):
    """
    skip all tokens in a conditional command, until an \\fi is encountered.
    @param parser: the parser
    @param pop: whether to pop the ifstack
    """
    while True:
        c = skipBranch(parser, parser.ifstack[-1])
        if c == fi:
            parser.ifstack.pop()
            return


class Branch(Command):
    """
    the base class for a branch. Commands such as \else, \or, and \fi are subclasses of this class.
    @param command_name: the name of the command
    """
    def expand(self, parser):
        if len(parser.ifstack) == 0:
            raise ValueError("unexpected " + self.name, parser.input.position())
        skipAll(parser)


class Else(Branch):
    """ the \\else command """
    pass


class Or(Branch):
    """ the \\or command """
    def expand(self, parser):
        if len(parser.ifstack) == 0 or not isinstance(parser.ifstack[-1][0], IfCase):
            raise ValueError("unexpected \\or")
        skipAll(parser)


class Fi(Branch):
    def expand(self, parser):
        if len(parser.ifstack) == 0:
            raise ValueError("unexpected " + self.name, parser.input.position())
        parser.ifstack.pop()


class Conditional(Command):
    """
    The base class for all conditional commands.

    The main method of this class is condition, which should be overridden by subclasses to implement the condition
    of the conditional command.
    """
    def condition(self, parser):
        """
        The condition of the conditional command.

        This method should be overridden by subclasses to implement the condition of the conditional command.
        It reads the tokens from the parser and returns an integer representing the braanch
        to be taken. The return value should be 0 for true and 1 for false. In the \\ifcase
        command, the return value should be the index of the branch to be taken, starting from 0.

        @param parser: the parser
        @param condition: the branch to skip to
        @param level: the current level of the ifstack
        @return: the index pf the branch to be taken. 0 for true, 1 for false
        """
        # the default implementation is equivalent to \iftrue
        return 0

    def skipTo(self, parser, condition, level):
        for i in range(condition):
            c = skipBranch(parser, level)
            if isinstance(c, Or) and not isinstance(self, IfCase):
                raise ValueError("unexpected \\or")
            if isinstance(c, Else):
                return
            elif isinstance(c, Fi):
                parser.ifstack.pop()
                return

    def expand(self, parser):
        # We push the ifstack before checking the condition, because there could be other 
        # conditional commands when hanlding condition.
        # the ifstack saved the command, position in input stack, and branch (condition)
        state = [self, parser.input.position()]
        parser.ifstack.append(state)
        condition = self.condition(parser)
        state.append(condition)
        self.skipTo(parser, condition, level = state)


class IfCompareToken(Conditional):
    """ 
    the base class for \\if, \\ifx and \\ifcat

    @param name: the name of the command
    @param expand: whether the command should expand the tokens before comparing them
    """
    def __init__(self, expand_tokens: bool):
        super().__init__()
        self.expand_tokens = expand_tokens

    def equal(self, t1, t2):
        raise NotImplementedError()

    def condition(self, parser):
        if self.expand_tokens:
            t1 = parser.token_expand()
            t2 = parser.token_expand()
        else:
            t1 = parser.token()
            t2 = parser.token()
        if t1 is None or t2 is None:
            raise ValueError("expecting two tokens", parser.input.position())
        if t1.is_command and isinstance(t1.definition, Token):
            t1 = t1.definition
        if t2.is_command and isinstance(t2.definition, Token):
            t2 = t2.definition
        return 0 if self.equal(t1, t2) else 1


class IfCat(IfCompareToken):
    """ the \\ifcat command """
    def __init__(self):
        super().__init__(expand_tokens=True)

    def equal(self, t1, t2):
        return t1.catcode == t2.catcode


class If(IfCompareToken):
    """ the \\if command """
    def __init__(self):
        super().__init__(expand_tokens=True)

    def equal(self, t1, t2):
        # If either token is a control sequence, TEX considers it to have character 
        # code 256 and category code 16
        # The condition is true if the character codes are equal,
        # independent of the category codes
        if t1.catcode is None and t2.catcode is None:
            return True
        return t1.name == t2.name


class IfX(IfCompareToken):
    """ the \\ifx command """
    def __init__(self):
        super().__init__(expand_tokens=False)
    
    def equal(self, t1, t2):
        # TEX does not expand control sequences when it looks at the two tokens.
        # The condition is true if (a) the two tokens are not macros, and they both 
        # represent the same (character code, category code) pair or the same TEX 
        # primitive or the same \font or \chardef or \countdef, etc.
        # or if (b) the two tokens are macros, and they both have the same status 
        # with respect to \long and \outer, and they both have the same
        # parameters and “top level” expansion.
        if t1.catcode is None and t2.catcode is None:
            return t1.definition == t2.definition
        return (t1.catcode == t2.catcode) and (t1.name == t2.name)


class IfCase(Conditional):
    """ the \\ifcase command """
    def condition(self, parser):
        return parser.readInteger()


class IfNum(Conditional):
    """ the \\ifnum command """

    def readValue(self, parser):
        return parser.readInteger()

    def condition(self, parser):
        n1 = self.readValue(parser)
        op = parser.token_expand()
        if op is None or op.catcode != CATCODE.OTHER or op.name not in "<=>":
            raise ValueError("expecting a comparison operator", parser.input.position())
        n2 = self.readValue(parser)
        if op.name == "<":
            return 0 if n1 < n2 else 1
        if op.name == "=":
            return 0 if n1 == n2 else 1
        return 0 if n1 > n2 else 1


class IfDim(IfNum):
    """ the \\ifdim command """
    def readValue(self, parser):
        return parser.readDimen()


class IfOdd(Conditional):
    """ the \\ifodd command """
    def condition(self, parser):
        n = parser.readInteger()
        return 0 if n % 2 == 1 else 1


# The default behavior of Conditional is \iftrue

class IfFalse(Conditional):
    """ the \\iffalse command """
    def condition(self, parser):
        return 1


fi = Fi()

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
        "iftrue": Conditional(),
        "iffalse": IfFalse(),
        "else": Else(),
        "or": Or(),
        "fi": fi,
    }
)
