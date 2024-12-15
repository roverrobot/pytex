import typing
from pytex import token
from pytex import lexer
from pytex import state
from pytex.module import ModuleManager


class Parser:
    """
    The parser is the main class that processes the input and executes the commands.
    """
    def __init__(self):
        self.state = state.State()
        self.input = lexer.InputStack()
        # for now, characters and spaces are collected in a string
        self.tokens = ""
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
            # if the token is not expandable, t == t1
            if t1 == t:
                return t
            # if the token is consumed, get the next token
            if t1 is None:
                t = self.token()
            else:
                # if the token is expanded, check the expanded token
                t = t1

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

    def readFrom(self, input, name: typing.Optional[str] = None):
        """
        read from the input
        @param input: the input
        """
        if isinstance(input, str):
            self.input.push(lexer.StringScanner(self.state.catcode, input, name))
        else:
            self.input.push(leser.Scanner(self.state.catcode, input, name))

    def addChar(self, c):
        """
        add a character to the current list
        @param c: the token representing character
        """
        self.tokens += c.name
    
    def addSpace(self, c):
        """
        add a space to the current list
        @param c: the token representing space
        """
        self.tokens += c.name

    def lookup(self, name):
        """
        look up a command
        @param name: the name of the command
        @return: the command
        """
        try:
            return self.state.equitable[name]
        except KeyError:
            raise ValueError("command not defined: ", name)