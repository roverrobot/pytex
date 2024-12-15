import typing
from pytex import token
from pytex import lexer
from pytex import state
from pytex.module import ModuleManager
from pytex import assignment
from pytex import integer
from pytex import keyword


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
        @param c: the token representing character
        """
        self.tokens += c.name
    
    def addSpace(self):
        """
        add a space to the current list
        @param c: the token representing space
        """
        self.tokens += " "

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