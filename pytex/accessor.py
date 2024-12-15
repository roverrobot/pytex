"""
Accessors are commands that access registers or parameters
"""


import typing
from pytex.token import Command
from pytex.assignment import Assignment


class Accessor(Assignment):
    """
    An accessor is a command that accesses a register or a parameter. It is a command that
    takes a single argument, the name of the register or parameter, and returns the value of
    the register or parameter.
    """
    def __init__(self, domain: str):
        super().__init__(domain, eq=True)
    
    def getValue(self, parser):
        """
        get the value from the array. Need to read the index first.
        @param parser: the parser
        """
        index = self.getIndex(parser)
        return parser.state[self.domain][index]


class Array(list):
    SIZE = 65536
    """
    a character code
    """
    def __init__(self, default=None, size: typing.Optional[int]=None):
        if size is None:
            size = self.SIZE
        super().__init__([default] * size)


class ArrayAccessor(Accessor):
    """
    An array accessor is an accessor that accesses an array of registers or parameters. It is a command
    that takes a single argument, the name of the register or parameter, and returns the value of the
    register or parameter.
    """    
    def getIndex(self, parser):
        """
        get the index from the input stack
        @param parser: the parser
        """
        try:
            pos = parser.input.position()
            return parser.readInteger()
        except ValueError as e:
            raise ValueError("expectong an integer", pos)


class ParameterAccessor(Accessor):
    """
    A parameter accessor is an accessor that accesses a parameter. It is a command that takes a single
    argument, the name of the parameter, and returns the value of the parameter.
    """
    def __init__(self, domain: str, name: str):
        super().__init__(domain)
        self.name = name
    
    def getIndex(self, parser):
        """
        get the index from the input stack
        @param parser: the parser
        """
        return self.name
