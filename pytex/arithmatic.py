r"""
this module implements the tex commands \advance, \multiple and \divide

\\advance <number variable><optional signs><number>
\\multiply <number variable><optional signs><number>
\\divide <number variable><optional signs><number>
"""

from pytex import accessor
from pytex.accessor import VALUE_TYPE
from pytex.token import Command
from pytex.module import Module


class Arithmatics(Command):
    """
    the base class for the arithmatic commands
    """
    def op(self, x, y):
        """
        return the operation
        """
        raise NotImplementedError("the operation mut be implemented in the subclass")
    
    def getAssignment(self, parser):
        target = parser.readTarget()
        if target is None:
            raise ValueError("expecting a register or a parameter", parser.input.position())
        x = parser.get(target)
        is_integer = isinstance(x, int)
        parser.readKeyword(["by"])
        y = self.readByValue(parser, target)
        value = self.op(x, y)
        if is_integer:
            value = int(value)
        return accessor.Assignment(target, value)

    def readByValue(self, parser, target):
        """
        read the value of the by keyword
        @param parser: the parser
        @param target: the bound target
        """
        if target.value_type == VALUE_TYPE.INT:
            return parser.readInteger()
        if target.value_type == VALUE_TYPE.DIMEN:
            return parser.readDimen()
        if target.value_type == VALUE_TYPE.GLUE:
            return parser.readGlue()
        if target.value_type == VALUE_TYPE.MUGLUE:
            return parser.readGlue(mu=True)
        raise ValueError("expecting a numeric target", parser.input.position())
    
    def execute(self, parser):
        return self.getAssignment(parser).apply(parser)


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
    
    def readByValue(self, parser, target):
        """
        read the value of the by keyword
        @param parser: the parser
        @param target: the bound target
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
