"""
Assignment commands are commands that assign values to registers or parameters

Most assignments also access the value of the register or parameter. For example,
the \\count command assigns a value to a count register and also returns the value
of the count register. Such a commands us called an Accessor. An Accessor points to 
a specific value, could be an item in an array, or a parameter. The latter is also
an item int heequitable. So the Accessor class denote the value that it poitns to by
a domain and an index. 

There are two main methods in the Accessor class: getValue and assign. When the command
is executed, it is an assignment.  On the other hand, the command may be read by other 
commands. In this case, the command is not an assignment, but the getValue() method is called.

An ArrayAccessor command specifies how to access an array, such as the \\catcode array 
or the \\count registers. Its main method is getItemAccessor, which returns an accessor to
an item in the array. The method calles the newItemAccessor method, which must be implemented
in a subclass to provide the accessor to the item.
"""

from pytex import token
from pytex.module import Module
from pytex import token


def skipEq(parser, expand: bool=True):
    """
    read the equal sign from the input stack
    @param parser: the parser
    """
    t = parser.skipSpaces(expand)
    if t is None:
        return
    # read the equal sign
    if t.catcode != token.CATCODE.OTHER or t.name != "=":
        parser.input.unread(t)

class Accessor(token.Command):
    """
    access a value in a domain
    @param domain: the domain of the assignment
    @param index: the index of the assignment
    @param eq: whether there is an equal sign in the assignment
    @param range: the range of valid values
    """
    def __init__(self, domain, index):
        self.domain = domain
        self.index = index

    def readEq(self, parser):
        """
        read the equal sign from the input stack
        @param parser: the parser
        """
        return parser.skipEq(expand=True)

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
        domain = getattr(parser.state, self.domain)
        index = self.getIndex(parser) if self.index is None else self.index
        return domain[index]

    def getIndex(self, parser):
        """
        get the index for teh item
        @param parser: the parser
        """
        return self.index

    def setValue(self, parser, value, globally: bool):
        """
        set the value in the domain.
        @param parser: the parser
        @param value: the value
        @param globally: whether the assignment is global

        We must pass an index to the setValue method, because the index may be read 
        from the input stack, in this case, it imust be read before the value.
        """
        domain = getattr(parser.state, self.domain)
        if globally and hasattr(domain, "setGlobal"):
            domain.setGlobal(self.index, value)
        else:
            domain[self.index] = value
    
    def assign(self, parser, prefixes):
        """
        assign the value to the index
        @param parser: the parser
        @param prefixes: the prefixes to the assignment
        """
        self.readEq(parser)
        value = self.readValue(parser)
        globally = parser.state.parameters["globaldefs"] != 0
        try:
            for p in prefixes:
                value, globally = p.modify(value, globally)
        except ValueError as e:
            e.args = (e.args[0], parser.input.position())
            raise e
        self.setValue(parser, value, globally)
        t = parser.state.globals["afterassignment"]
        if t is not None:
            parser.input.unread(t)
            parser.state.globals["afterassignment"] = None
    
    def execute(self, parser):
        """
        execute the assignment command. The default behavior is to raise an error.
        @param parser: the parser
        """
        self.assign(parser, prefixes=[])

    def getItemAccessor(self, parser, index):
        """
        get the accessor for the item
        @param index: the index
        """
        return self


class ArrayAccessor(token.Command):
    """
    An array accessor provides that accesses an array of registers or parameters. It is a command
    that takes a single argument, the name of the register or parameter, and returns the value of the
    register or parameter.

    @param domain: the domain of the assignment
    """ 
    def __init__(self, domain: str):
        self.domain = domain
    
    def getIndex(self, parser):
        """
        read the index from the input stack
        @param parser: the parser
        """
        try:
            return parser.readInteger()
        except ValueError as e:
            raise ValueError("expectong an integer index", parser.input.position())
    
    def assign(self, parser, prefixes):
        """
        make an assignment
        
        @param parser: the parser
        @param prefixes: the prefixes to the assignment

        the index is read from the input stack, then an accessor to the 
        item is created, and its assign method is called.
        """
        item = self.getItemAccessor(parser, None)
        item.assign(parser, prefixes)

    def getValue(self, parser):
        return self.getItemAccessor(parser, None).getValue(parser)

    def getItemAccessor(self, parser, index):
        """
        get the accessor for an item in the array
        @param index: the index if it is None, it is read from the input stack
        """
        if index is None:
            index = self.getIndex(parser)
        return self.newItemAccessor(index)

    def newItemAccessor(self, index):
        """
        create a new item accessor
        @param index: the index
        """
        raise ValueError("This method should be implemented by a subclass")
    
    def execute(self, parser):
        """
        execute the command
        @param parser: the parser
        """
        self.assign(parser, prefixes=[])


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
    
    def assign(self, parser, prefixes):
        """
        execute the prefix. It reads an assignment from the input stack
        then calls the its assign method.
        @param parser: the parser
        """
        prefixes.append(self)
        pos = parser.input.position()
        parser.skipFiller()
        t = parser.token()
        if t is None or not t.is_command or not hasattr(t.definition, "assign"):
            raise ValueError("expecting an assignment", pos)
        if parser.tracingcommands > 0:
            parser.trace(t, "execute")
        t.definition.assign(parser, prefixes)

    def execute(self, parser):
        """
        execute the prefix
        @param parser: the parser
        """
        self.assign(parser, [])


class GlobalPrefix(Prefix):
    """
    The global prefix
    """
    def modify(self, value, globally: bool):
        return value, True


class AfterAssignment(token.Command):
    """
    the \\afterassignment command

    It reads the next (unexpanded) token and stores it in the afterassignment parameter.
    """
    def execute(self, parser):
        """
        execute the command
        @param parser: the parser
        """
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token")
        parser.state.globals["afterassignment"] = t


module = Module("assignment", 
    commands = {
        "global": GlobalPrefix(),
        "afterassignment": AfterAssignment(),
    },
    parameters= {
        # this token should not have any accessor, because users only interact
        # with it via the afterassignment command.
        "afterassignment": {"value": None, "accessor": None, "domain": "globals"},
    },
    attributes={
        "skipEq": skipEq
    }
)
