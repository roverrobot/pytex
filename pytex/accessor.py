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
from pytex import state


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
        raise NotImplementedError("readValue method must be implemented in a subclass")

    def set(self, parser, value):
        """
        set the value in the domain.
        @param parser: the parser
        @param value: the value

        We must pass an index to the setValue method, because the index may be read 
        from the input stack, in this case, it imust be read before the value.
        """
        raise NotImplementedError("setValue method must be implemented in a subclass")
    
    def setGlobal(self, parser, value):
        """
        set the value in the domain globally.
        @param parser: the parser
        @param value: the value

        We must pass an index to the setValue method, because the index may be read 
        from the input stack, in this case, it imust be read before the value.
        """
        raise NotImplementedError("setValue method must be implemented in a subclass")

    def queueAfterassignment(self, parser):
        """
        Queue \\afterassignment before the actual write happens.

        The token is only read after this command returns, so ordinary assignments are
        still complete when it executes. This also lets special cases such as \\setbox
        reuse the same helper while deferring the semantic register update until the
        box group closes.
        """
        t = parser.state.globals["afterassignment"]
        if t is None:
            return
        parser.input.unread(t)
        parser.state.globals["afterassignment"] = None
        if parser.tracingcommands > 0 and parser.checkRange():
            parser.message(f"afterassignment: {parser.tokenToString(t)}")
    
    def assign(self, parser, prefixes):
        """
        assign the value to the index
        @param parser: the parser
        @param prefixes: the prefixes to the assignment
        """
        self.readEq(parser)
        value = self.readValue(parser)
        globally = parser.globaldefs.value != 0
        try:
            for p in prefixes:
                value, globally = p.modify(value, globally)
        except ValueError as e:
            e.args = (e.args[0], parser.input.position())
            raise e
        self.queueAfterassignment(parser)
        if globally:
            self.setGlobal(parser, value)
        else:
            self.set(parser, value)
    
    def execute(self, parser):
        """
        execute the assignment command. The default behavior is to raise an error.
        @param parser: the parser
        """
        self.assign(parser, prefixes=[])


class ArrayItemAccessor(Accessor):
    """
    An array item accessor provides access to an item in an array of registers or parameters.
    It is a command that takes a single argument, the index of the item, and returns the value of
    the item.

    @param domain: the domain of the assignment
    @param index: the index of the item in the array
    """
    def __init__(self, domain, index):
        self.domain = domain
        self.index = index

    def saveInfo(self):
        return {"init": {"domain": self.domain.name, "index": self.index}}

    @classmethod
    def new(cls, parser, **kargs):
        """
        create a new accessor from the dictionary
        @param parser: the parser
        @param kargs: the keyword arguments
        @return: the command
        """
        name = kargs["domain"]
        index = kargs["index"]
        return cls(getattr(parser.state, name), index)

    def set(self, parser, value):
        """
        set the value of the item in the array
        @param parser: the parser (not used, but kept for compatibility)
        @param value: the value to set
        """
        try:
            self.domain[self.index] = value
        except IndexError:
            raise ValueError(f"index {self.index} out of range for domain {self.domain.name}", parser.input.position())

    def setGlobal(self, parser, value):
        """
        set the value of the item in the array globally
        @param parser: the parser (not used, but kept for compatibility)
        @param value: the value to set
        """
        self.domain.setGlobal(self.index, value)
    

class ArrayAccessor(token.Command):
    """
    An array accessor provides that accesses an array of registers or parameters. It is a command
    that takes a single argument, the name of the register or parameter, and returns the value of the
    register or parameter.

    @param domain: the domain of the assignment
    """
    def __init__(self, domain):
        """
        @param domain: the domain of the assignment
        """
        self.domain = domain

    def assign(self, parser, prefixes):
        """
        make an assignment
        
        @param parser: the parser
        @param prefixes: the prefixes to the assignment

        the index is read from the input stack, then an accessor to the 
        item is created, and its assign method is called.
        """
        self.getItemAccessor(parser).assign(parser, prefixes)
    
    def execute(self, parser):
        """
        execute the command
        @param parser: the parser
        """
        self.getItemAccessor(parser).assign(parser, prefixes=[])


class ParameterAccessor(Accessor):
    """
    An accessor for a parameter. 

    @param entry: the state.NamedEntry that stores the parameter
    @return the value of the parameter.
    """
    def __init__(self, entry):
        self.entry = entry

    def set(self, parser, value):
        """
        set the value of the parameter
        @param parser: the parser (not used, but kept for compatibility)
        @param value: the value to set
        """
        self.entry.set(value)

    def setGlobal(self, parser, value):
        """
        set the value of the parameter globally
        @param parser: the parser (not used, but kept for compatibility)
        @param value: the value to set
        """
        self.entry.setGlobal(value)


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
        parser.skipFiller()
        t = parser.token()
        if t is None or not t.is_command or not hasattr(t.definition, "assign"):
            raise ValueError("expecting an assignment", parser.input.position())
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
