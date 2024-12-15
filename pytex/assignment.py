"""
Assignment commands are commands that assign values to registers or parameters
"""


import typing
from pytex import token
from pytex.module import Module

class Assignment(token.Command):
    """
    This is the base class for assignment commands.  
    @param domain: the domain of the assignment
    @param eq: whether there is an equal sign in the assignment
    """
    def __init__(self, domain: str, eq: bool):
        self.domain = domain
        self.eq = eq

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
        
    def getIndex(self, parser):
        """
        get the index from the input stack
        @param parser: the parser
        """
        raise ValueError("assignment command must have an index")

    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        raise ValueError("assignment command must have a value")

    def assign(self, parser, prefixes: list):
        """
        assign the value to the index
        @param parser: the parser
        @param prefixes: the prefixes to the assignment
        """
        index = self.getIndex(parser)
        if self.eq:
            self.readEq(parser)
        value = self.readValue(parser)
        globally = False
        for p in prefixes:
            value, globally = p.modify(value, globally)
        if globally:
            parser.state[self.domain].setGlobal(index, value)
        else:
            parser.state[self.domain][index] = value


    def execute(self, parser):
        """
        execute the assignment command. The default behavior is to raise an error.
        @param parser: the parser
        """
        self.assign(parser, [])


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
        self.assign(parser, [])

    def assign(self, parser, prefixes: list):
        """
        assign the value to the index
        @param parser: the parser
        @param prefixes: the prefixes to the assignment
        """
        prefixes.append(self)
        pos = parser.input.position()
        assignment = parser.token_expand()
        try:
            assignment.assign(parser, prefixes)
        except:
            raise ValueError("expecting an assignment", pos)


class GlobalPrefix(Prefix):
    """
    The global prefix
    """
    def modify(self, value, globally: bool):
        return value, True


module = Module("assignment", 
    commands = {
        "global": GlobalPrefix()
    }
)
