"""
this module implements the tex commands \advance, \multiple and \divide

\\advance <number variable><optional signs><number>
\\multiply <number variable><optional signs><number>
\\divide <number variable><optional signs><number>
"""

from pytex.accessor import Accessor
from pytex.token import Command
from pytex.module import Module
from types import MethodType


class Arithmatics(Command):
    """
    the base class for the arithmatic commands
    """
    def op(self, x, y):
        """
        return the operation
        """
        raise NotImplementedError("the operation mut be implemented in the subclass")
    
    def assign(self, parser, prefixes):
        """
        assign the value to the pointer
        @param parser: the parser
        @param prefixes: the prefixes
        """
        pos = parser.input.position()
        t = parser.token_expand()
        try:
            p = t.getItemAccessor(parser, None)
        except AttributeError:
            raise ValueError("expecting a register or a parameter", pos)
        if hasattr(p, "muglueValue"):
            x = p.muglueValue(parser)
        elif hasattr(p, "glueValue"):
            x = p.glueValue(parser)
        elif hasattr(p, "dimenValue"):
            x = p.dimenValue(parser)
        elif hasattr(p, "intValue"):
            x = p.intValue(parser)
        else:
            raise ValueError("expecting a register or a parameter of integer, dimension, or glue", pos)
        parser.readKeyword(["by"])
        y = self.readByValue(parser, p)
        value = self.op(x, y)
        p.setValue(parser, value, prefixes)

    def readByValue(self, parser, item_accessor):
        """
        read the value of the by keyword
        @param parser: the parser
        @param item_accessor: the item accessor
        """
        return item_accessor.readValue(parser)
    
    def execute(self, parser):
        return self.assign(parser, [])


class Advance(Arithmatics):
    """
    the advance command
    """
    def op(self, x, y):
        return x + y


class Multiply(Arithmatics):
    """
    the multiply command
    """
    def op(self, x, y):
        return x * y
    
    def readByValue(self, parser, item_accessor):
        """
        read the value of the by keyword
        @param parser: the parser
        @param item_accessor: the item accessor
        """
        return parser.readInteger()


class Divide(Multiply):
    def op(self, x, y):
        return x / y


mod = Module(name="arithmatic", 
    commands={
        "advance": Advance(),
        "multiply": Multiply(),
        "divide": Divide()
    }
)
