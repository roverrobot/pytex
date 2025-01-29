"""
This module implements various expandable commands.
"""


from pytex.token import Command, CATCODE, CommandToken, Token
from pytex.module import Module
from pytex.toks import Toks
from pytex.lexer import TokenListScanner, Scanner


class NoExpand(Command):
    """
    The \\noexpand command.
    """
    def expand(self, parser):
        """
        Expand the command. The noexpand command prevents the next token from being expanded.
        @param parser: the parser
        @return: the expanded command
        """
        return parser.token()


class ExpandAfter(Command):
    """
    The \\expandafter command.
    """
    def expand(self, parser):
        """
        Expand the command. The expandafter command expands the next token after the next token.
        @param parser: the parser
        @return: the expanded command
        """
        t = parser.token()
        if t is None:
            return None
        t1 = parser.token_expand()
        if t1 is not None:
            parser.input.unread(t1)
        parser.input.unread(t)


class EndCSName(Command):
    """
    The \\endcsname command.
    """
    def execute(self, parser):
        """
        Expand the command. The endcsname command expands the next token as a control sequence name.
        @param parser: the parser
        @return: the expanded command
        """
        raise ValueError("unexpected \\endcsname")


endcsname = EndCSName()


class CSName(Command):
    """
    The \\csname command.
    """
    def expand(self, parser):
        """
        Expand the command. The csname command expands the tokens until the endcsname command.
        and returns the control sequence name.
        @param parser: the parser
        @return: the expanded command
        """
        name = "\\"
        while True:
            t = parser.token_expand()
            if t is None:
                raise ValueError("expecting \\endcsname")
            if t.is_command:
                if t == endcsname:
                    break
                else:
                    raise ValueError("expecting \\endcsname")
            name += t.name
        c = parser.lookup(name)
        if c is not None:
            return c.expand(parser)
        c = Command()
        parser.state.domains["equitable"][name] = c
        return c


def toToks(s: str) -> Toks:
    """
    Convert a string to a token list.
    @param s: the string
    @return: the token list
    """
    toks = Toks()
    for c in s:
        toks.append(Token.token(c, CATCODE.OTHER))
    return toks


class Number(Command):
    """
    the \\number command, that converts a number to tokens with catcode OTHER
    """
    def str(self, n):
        return str(n)

    def expand(self, parser):
        n = parser.readInteger()
        s = self.str(n)
        parser.input.push(TokenListScanner(toToks(s)))


class RomanNumeral(Number):
    """
    the \\romannumeral command, that converts a number to roman numerals
    """
    LETTERS = ["m", "cm", "d", "cd", "c", "xc", "l", "xl", "x", "ix", "v", "iv", "i"]
    VALUES = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]

    def str(self, n):
        i = 1
        s = ""
        for i in range(len(self.LETTERS)):
            letter = self.LETTERS[i]
            value = self.VALUES[i]
            while n >= value:
                n -= value
                s += letter
            if n == 0:
                break
        return s


class String(Command):
    """
    the \\string command, that converts a token to a string
    """
    def expand(self, parser):
        pos = parser.input.position()
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token", pos)
        if t.catcode is None:
            s = chr(parser.state.domains["layout"]["escapechar"]) + t.name[1:]
        else:
            s = t.name
        parser.input.push(TokenListScanner(toToks(s)))


class ProtectedTokenListScanner(TokenListScanner):
    """
    a token list scanner that protects the tokens from expansion
    """
    def read(self):
        t = super().read()
        if t is not None and isinstance(t, CommandToken):
            c = CommandToken(t.name)
            c.catcode = t.catcode
            c.protected = True
            return c
        return t


class The(Command):
    """
    The \\the command.
    """
    def expand(self, parser):
        pos = parser.input.position()
        t = parser.token_expand()
        if t is None or not t.is_command:
            raise ValueError("invalid token after \\the", pos)
        if hasattr(t, "glueValue"):
            value = str(t.glueValue(parser))
        elif hasattr(t, "dimenValue"):
            value = str(t.dimenValue(parser)) + "pt"
        elif hasattr(t, "intValue"):
            value = str(t.intValue(parser))
        else:
            value = None
        if value is not None:
            parser.input.push(TokenListScanner(toToks(value)))
            return
        if hasattr(t, "toksValue"):
            value = t.toksValue(parser)
            parser.input.push(ProtectedTokenListScanner(value))
            return
        if hasattr(t, "fontValue"):
            value = t.fontValue(parser)
            value.execute(parser)


class Input(Command):
    """
    The \\input command.
    """
    def expand(self, parser):
        pos = parser.input.position()
        name = parser.readFileName()
        if name is None:
            raise ValueError("expecting a file name", pos)
        f = parser.resolver.openIn(name, "source")
        if f is None:
            raise ValueError("file not found", pos)
        parser.input.push(Scanner(parser.state.catcode, f, name))


mod = Module("expandable",
    commands={
        "noexpand": NoExpand(),
        "expandafter": ExpandAfter(),
        "csname": CSName(),
        "endcsname": endcsname,
        "number": Number(),
        "romannumeral": RomanNumeral(),
        "string": String(),
        "the": The(),
        "input": Input(),
    }
)