r"""
this module implements the tex commands \advance, \multiple and \divide

\\advance <number variable><optional signs><number>
\\multiply <number variable><optional signs><number>
\\divide <number variable><optional signs><number>
"""

from pytex.accessor import Accessor
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
    
    def assign(self, parser, prefixes):
        """
        assign the value to the pointer
        @param parser: the parser
        @param prefixes: the prefixes
        """
        t = parser.token_expand()
        if t.definition is None:
            raise ValueError("expecting a register or a parameter", parser.input.position())
        t = t.definition
        if hasattr(t, "getItemAccessor"):
            p = t.getItemAccessor(parser)
        elif isinstance(t, Accessor):
            p = t
        else:
            raise ValueError("expecting a register or a parameter", parser.input.position())
        domain, key = p.readTarget(parser)
        is_integer = False
        if domain is not None and key is not None:
            x = parser.get(domain, key)
            is_integer = isinstance(x, int)
        else:
            if hasattr(p, "muglueValue"):
                x = p.muglueValue(parser)
            elif hasattr(p, "glueValue"):
                x = p.glueValue(parser)
            elif hasattr(p, "dimenValue"):
                x = p.dimenValue(parser)
            elif hasattr(p, "intValue"):
                x = p.intValue(parser)
                is_integer = True
            else:
                raise ValueError("expecting a register or a parameter of integer, dimension, or glue", parser.input.position())
        parser.readKeyword(["by"])
        y = self.readByValue(parser, p)
        value = self.op(x, y)
        if is_integer:
            value = int(value)
        # set value
        globally = False
        try:
            for prefix in prefixes:
                value, globally = prefix.modify(value, globally)
        except ValueError as e:
            e.args = (e.args[0], parser.input.position())
            raise e
        if domain is not None and key is not None:
            parser.set(domain, key, global_scope=globally, value=value)
        else:
            parser.current_value = value
            if globally:
                p.setGlobal(parser, value)
            else:
                p.set(parser, value)
        parser.afterAssignment()

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
