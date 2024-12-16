"""
this module implements the tex commands \advance, \multiple and \divide

\\advance <number variable><optional signs><number>
\\multiply <number variable><optional signs><number>
\\divide <number variable><optional signs><number>
"""

from pytex.accessor import Accessor
from pytex.module import Module
import typing
from types import MethodType


def readBy(self, parser):
    """
    read the optional keyword "by" 
    @param parser: the parser
    """
    return parser.readKeyword({"by"})


class Op:
    """
    the base class for the arithmatic operations

    @param parser: the parser
    @param pointer: the value pointer to operate on
    """
    def __init__(self, parser, pointer):
        self.parser = parser
        self.pointer = pointer

    def op(self, x, y):
        """
        the operation
        @param x: the first value
        @param y: the second value
        @return: the modified value
        """
        return value

    def modify(self, value, globally):
        """
        modify the value
        @param value: the value
        @param globally: whether the assignment is global
        @return: the modified value and whether the assignment is global
        """
        return self.op(self.pointer.getValue(self.parser), value), globally
    

class Arithmatics(Accessor):
    """
    the base class for the arithmatic commands
    """
    def __init__(self):
        super().__init__(None, None, True)

    def op(self, parser, pointer):
        """
        return the operation
        """
        return None
    
    def pointer(self, parser):
        """
        get the value pointer
        @param parser: the parser
        @return: the value pointer and possible prefixes
        """
        t = parser.token_expand()
        try:
            p = t.pointer(parser)
            p.readEq = MethodType(readBy, p)
            p.prefixes.append(self.op(parser, p))
            return p
        except AttributeError:
            raise ValueError("a parameter is expected")


class Add(Op):
    """
    the add operation
    """
    def op(self, x, y):
        return x + y


class Advance(Arithmatics):
    """
    the advance command
    """
    def op(self, parser, pointer):
        return Add(parser, pointer)


class Mul(Op):
    """
    the multiply operation
    """
    def op(self, x, y):
        return x * y


def readFactor(self, parser):
    """
    read the factor is the \\multiply and \\divide commands
    @param parser: the parser
    """
    return parser.readInteger()


class Multiply(Arithmatics):
    """
    the multiply command
    """
    def op(self, parser, pointer):
        return Mul(parser, pointer)
    
    def pointer(self, parser):
        """
        get the value pointer
        @param parser: the parser
        @return: the value pointer and possible prefixes
        """
        p = super().pointer(parser)
        p.readValue = MethodType(readFactor, p)
        return p


class Div(Op):
    """
    the divide operation
    """
    def op(self, x, y):
        return x / y


class Divide(Multiply):
    def op(self, parser, pointer):
        return Div(parser, pointer)


mod = Module(name="arithmatic", 
    commands={
        "advance": Advance(),
        "multiply": Multiply(),
        "divide": Divide()
    }
)
