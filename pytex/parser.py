import typing
from pytex import token
from pytex import lexer
from pytex import state
from pytex.module import ModuleManager
from pytex import accessor
from pytex import integer
from pytex import keyword
from pytex import dimen
from pytex import glue
from pytex import arithmatic
from pytex import define
from pytex import toks
from pytex import macro
from pytex import conditional
from pytex import expandable
from pytex import resolver
from pytex import node


class Parser:
    """
    The parser is the main class that processes the input and executes the commands.
    """
    def __init__(self):
        self.state = state.State()
        self.input = lexer.InputStack()
        # the stack of if levels. Each element is a tuple containing the conditional 
        # command and its position in the input.
        self.ifstack = [] 
        # for now, characters and spaces are collected in a string
        for name, mod in ModuleManager.items():
            mod.populate(self)
    
    def token(self):
        """
        get the next token from the input stack
        @return: the next token
        """
        return self.input.read()
    
    def token_expand(self):
        """
        get the next token from the input stack and expand it
        @return: the next token
        """
        t = self.token()
        while True:
            if t is None:
                return None
            t1 = t.expand(self)
            # if the token is consumed, get the next token
            if t1 is None:
                t = self.token()
            else:
                return t1

    def parse(self, input, name: typing.Optional[str] = None):
        """
        parse the input
        @param input: the input
        @param name: the name of the input
        """
        self.readFrom(input, name)
        while True:
            t = self.token_expand()
            if t is None:
                break
            t.execute(self)
        if len(self.ifstack) > 0:
            raise ValueError("missing \\fi")

    def readFrom(self, input, name: typing.Optional[str] = None):
        """
        read from the input
        @param input: the input
        """
        if isinstance(input, str):
            self.input.push(lexer.StringScanner(self.state.catcode, input, name))
        else:
            self.input.push(lexer.Scanner(self.state.catcode, input, name))

    def skipSpaces(self, expand: bool = True, n: int = None):
        """
        skip spaces
        @param expand: whether to expand tokens
        @param n: the number of spaces to skip, None to skip all spaces
        """
        tok = self.token_expand if expand else self.token
        while True:
            if n is not None and n == 0:
                return
            t = tok()
            if t is None or t.catcode != lexer.CATCODE.SPACE:
                self.input.unread(t)
                return
            if n is not None:
                n -= 1

    def addChar(self, c):
        """
        add a character to the current list
        @param c: the character token
        """
        pass
    
    def addSpace(self):
        """
        add a space to the current list
        @param c: the token representing space
        """
        pass

    def lookup(self, name):
        """
        look up a command
        @param name: the name of the command
        @return: the command
        """
        try:
            return self.state.equitable[name]
        except KeyError:
            return None

    def beginGroup(self, position, group_type: state.GROUP_TYPE = state.GROUP_TYPE.SIMPLE):
        """
        begin a group
        @param position: the position of the begin group token
        @param group_type: the type of the group
        """
        self.state.beginGroup(position, group_type)
    
    def endGroup(self, position, group_type: state.GROUP_TYPE = state.GROUP_TYPE.SIMPLE):
        """
        end a group
        @param position: the position of the end group token
        @param group_type: the type of the group
        """
        self.state.endGroup(position, group_type)
        aftergroup = self.state.domains["globals"]["aftergroup"]
        if len(aftergroup) > 0:
            self.input.push(lexer.TokenListScanner(aftergroup))
            self.state.domains["globals"]["aftergroup"] = []
