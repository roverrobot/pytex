"""
Assignment commands are commands that assign values to registers or parameters
"""


import typing
from pytex import token
from pytex.module import Module
from pytex import token


class ValuePointer(token.Command):
    """
    access a value in a domain
    @param domain: the domain of the assignment
    @param index: the index of the assignment
    @param eq: whether there is an equal sign in the assignment
    """
    def __init__(self, domain, index, eq: bool):
        self.domain = domain
        self.index = index
        self.eq = eq
        self.prefixes = []

    # by default, the assignment is may be global
    allow_global = True

    def readEq(self, parser):
        """
        read the equal sign from the input stack
        @param parser: the parser
        """
        t = parser.token_expand()
        if t is None:
            return
        if t.catcode != token.CATCODE.OTHER or t.name != "=":
            parser.input.unread(t)
            return
        t = parser.token_expand()
        if t.catcode != token.CATCODE.SPACE:
            parser.input.unread(t)

    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        raise ValueError("assignment command must have a value")

    def getValue(self, parser):
        """
        get the value from the domain.
        @param parser: the parser
        """
        return self.domain[self.index]

    def setValue(self, parser, value, globally: bool):
        """
        set the value in the domain.
        @param parser: the parser
        @param value: the value
        @param globally: whether the assignment is global
        """
        if globally and self.allow_global:
            self.domain.setGlobal(self.index, value)
        else:
            self.domain[self.index] = value
    
    def assign(self, parser):
        """
        assign the value to the index
        @param parser: the parser
        @param prefixes: the prefixes to the assignment
        """
        if self.eq:
            self.readEq(parser)
        value = self.readValue(parser)
        globally = parser.state.parameters["globaldefs"] != 0
        for p in self.prefixes:
            value, globally = p.modify(value, globally)
        self.setValue(parser, value, globally)
        self.finalize(parser)

    def finalize(self, parser):
        """
        finalize the assignment
        @param parser: the parser

        This method is mainly needed for box assignment. This is because, for the 
        box assignment, the \\afterassignment token is inserted after the { token,
        i.e., a new group has already started. But if the box assignment happens after
        the { token, the } token finishing the box will undo the assignment. So
        the assignmennt shoudld happen before the group starts. So the group should
        start in this method.
        """
        pass
    
    def execute(self, parser):
        """
        execute the assignment command. The default behavior is to raise an error.
        @param parser: the parser
        """
        self.assign(parser)


class Accessor(token.Command):
    """
    This is the base class to access a value in domain via a value pointer.

    @param domain: the domain of the assignment
    @param pointer_generator: the pointer generator
    @param eq: whether there is an equal sign in the assignment
    """
    def __init__(self, domain: str, pointer_generator, eq: bool):
        self.domain = domain
        self.eq = eq
        self.pointer_generator = pointer_generator

    def getIndex(self, parser):
        """
        get the index from the input stack
        @param parser: the parser
        """
        raise ValueError("assignment command must have an index")

    def pointer(self, parser):
        """
        get the value pointer
        @param parser: the parser
        @return: the value pointer and possible prefixes
        """
        domain = parser.state.domains[self.domain]
        return self.pointer_generator(domain, self.getIndex(parser), self.eq)

    def execute(self, parser):
        """
        execute the assignment command. The default behavior is to raise an error.
        @param parser: the parser
        """
        p = self.pointer(parser)
        p.assign(parser)


class ArrayAccessor(Accessor):
    """
    An array accessor is an accessor that accesses an array of registers or parameters. It is a command
    that takes a single argument, the name of the register or parameter, and returns the value of the
    register or parameter.

    @param domain: the domain of the assignment
    @param pointer_generator: the pointer generator
    @param eq: whether there is an equal sign in the assignment
    """ 
    def __init__(self, domain: str, pointer_generator, eq=True):
        super().__init__(domain, pointer_generator, eq)

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
    def __init__(self, domain: str, name: str, pointer_generator):
        super().__init__(domain, pointer_generator, eq=True)
        self.name = name
    
    def getIndex(self, parser):
        """
        get the index from the input stack
        @param parser: the parser
        """
        return self.name


class Prefix(token.Command):
    """
    A prefix to an assignment
    """    
    def modify(self, value, globally: bool):
        """
        modify the value
        @param value: the value
        @param globally: whether the assignment is global
        @return: the modified value and whether the assignment is global
        """
        raise ValueError("prefix not defined")
    
    def execute(self, parser):
        """
        execute the prefix. It reads an assignment from the input stack
        then calls the its assign method.
        @param parser: the parser
        """
        p = self.pointer(parser)
        p.assign(parser)

    def pointer(self, parser):
        """
        assign the value to the index
        @param parser: the parser
        @param prefixes: the prefixes to the assignment
        """
        pos = parser.input.position()
        assignment = parser.token_expand()
        try:
            p = assignment.pointer(parser)
            p.prefixes.append(self)
            return p
        except KeyError:
            raise ValueError("expecting an assignment", pos)


class GlobalPrefix(Prefix):
    """
    The global prefix
    """
    def modify(self, value, globally: bool):
        return value, True


class Afterassignment(token.Command):
    """
    the \\afterassignment command

    It reads the next (unexpanded) token and stores it in the afterassignment parameter.
    """
    def exec(self, parser):
        """
        execute the command
        @param parser: the parser
        """
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token")
        parser.state.domains.globals.afterassignment = t


module = Module("assignment", 
    commands = {
        "global": GlobalPrefix(),
        "afterassignment": Afterassignment(),
    },
    parameters= {
        # this token should not have any accessor, because users only interact
        # with it via the afterassignment command.
        "afterassignment": {"value": None, "accessor": None, "domain": "globals"},
    },
)
