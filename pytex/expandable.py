"""
This module implements various expandable commands.
"""


from pytex.token import Command, CATCODE, CommandToken, ActiveToken, relax, SpaceToken, CharToken
from pytex.module import Module
from pytex.lexer import TokenListScanner, Scanner
from pytex.state import NamedEntry
import pathlib


class NoExpandToken(CommandToken):
    def __init__(self, parser, inner):
        super().__init__(inner.name)
        self._entry = inner.entry
        self.saved = parser.state.equitable.entry("noexpand")
        if self.saved.value is None:
            self.saved.value = relax
        # Trigger __getattr__("entry") on first read so the token initially
        # behaves like \relax, then falls back to the wrapped token's entry.
        del self.entry

    def __getattr__(self, name):
        if name == "entry":
            self.entry = self._entry
            return self.saved
        raise AttributeError(name)
        
    def saveInfo(self):
        return {"name": self.name}, None
    
    @classmethod
    def new(cls, parser, **kargs):
        return CommandToken.new(parser, **kargs)


class NoExpand(Command):
    """
    The \\noexpand command.
    """
    def expand(self, parser):
        """
        This command prevents the next token from being expanded.
        @param parser: the parser
        """
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token after \\noexpand", parser.input.position())
        entry = t.entry
        if entry is not None and (entry.value is None or entry.value.expand):
            t = NoExpandToken(parser, t)
        parser.input.unread(t)


noexpand = NoExpand()


class ExpandAfter(Command):
    """
    The \\expandafter command.
    """
    def expand(self, parser):
        """
        Expand the command. The expandafter command expands the next token after the next token.
        @param parser: the parser
        """
        t = parser.token()
        if t is None:
            return
        t1 = parser.token()
        if t1.entry is not None:
            definition = t1.definition
            if definition is None:
                raise ValueError(f"undefined command {t1.name}", parser.input.position())
            if definition.expand is not None:
                if parser.tracingcommands > 0:
                    parser.trace(t1, "expand")
                definition.expand(parser)
                parser.input.unread(t)
                return
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
        raise ValueError("unexpected \\endcsname", parser.input.position())


endcsname = EndCSName()


def readCSName(parser):
    name = "\\"
    while True:
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting \\endcsname", parser.input.position())
        if t.definition == endcsname:
            break
        elif t.catcode is None:
            raise ValueError(f"unexpected {t.name}", parser.input.position())
        name += t.name
    t = CommandToken(name)
    t.entry = parser.state.equitable.entry(name)
    return t

        
class CSName(Command):
    """
    The \\csname command.
    """
    def expand(self, parser):
        """
        Expand the command. 
        @param parser: the parser

        The \\csname command expands the tokens until the endcsname command.
        It then collects the token names into a control sequence name, and makes 
        a new command token with the name. The new comand token is the next token in rhe
        input stack.
        """
        t = readCSName(parser)
        definition = t.entry.value
        if definition is None:
            t.entry.set(relax)
        parser.input.unread(t)


def toToks(s: str) -> list:
    """
    Convert a string to a token list.
    @param s: the string
    @return: the token list
    """
    f = lambda c: SpaceToken() if c == " " else CharToken(c, CATCODE.OTHER)
    return list(map(f, iter(s)))


class Number(Command):
    """
    the \\number command, that converts a number to tokens with catcode OTHER
    """
    def str(self, n):
        return str(n)

    def expand(self, parser):
        """
        reads an integer and converts it to a string of tokens with catcode OTHER
        @param parser: the parser
        """
        n = parser.readInteger()
        s = self.str(n)
        if s:
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
        if n > 0:
            for i in range(len(self.LETTERS)):
                letter = self.LETTERS[i]
                value = self.VALUES[i]
                while n >= value:
                    n -= value
                    s += letter
                if n == 0:
                    break
        return s


def formatName(parser, name: str) -> str:
    """
    format the command name, handle the \\ according to \escapechar
    @param parser: the parser
    @param name: the command name
    @return: the command token
    """
    if parser is None:
        s = "\\" 
    else:
        escape = parser.escapechar.value
        s = chr(escape) if 0 <= escape < 256 else ""
    return s + name[1:]


def tokenToString(parser, token, expanded: bool = False):
    """
    Convert a token to a string.
    @param parser: the parser
    @param token: the token to convert
    @param expanded: whether to use TeX's expanded-text form
    @return: the string representation of the token
    """
    if token.catcode is None:
        return formatName(parser, token.name)
    if token.catcode == CATCODE.PARAMETER:
        if expanded:
            return "#" if token.parameter is None else "#" + str(token.parameter + 1)
        return "##" if token.parameter is None else "#" + str(token.parameter+1)
    return token.name


def expandedTokenToString(parser, token):
    """
    Convert a token as TeX does in expanded-text contexts such as \\string,
    \\write, \\message, \\errmessage, and \\special.
    """
    return parser.tokenToString(token, expanded=True)


def toksToString(parser, tokens, expanded: bool = False):
    """
    Convert a list of tokens to a string
    @param parser: the parser
    @param tokens: the list of tokens
    @param expanded: whether to use TeX's expanded-text form
    @return: the string
    """
    def f(token):
        s = parser.tokenToString(token, expanded=expanded)
        return s + " " if token.catcode is None else s
    return "".join(map(f, tokens))


def expandedToksToString(parser, tokens):
    """
    Convert a token list as TeX does in expanded-text contexts such as \\write.
    """
    return parser.toksToString(tokens, expanded=True)


class String(Command):
    """
    the \\string command.
    @param parser: the parser

    It reads a token from the input stack and converts its name to a list of tokens
    with catcode OTHER. The result is pushed back to the input stack.
    """
    def expand(self, parser):
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token", parser.input.position())
        parser.input.push(TokenListScanner(toToks(parser.expandedTokenToString(t))))


class Input(Command):
    """
    The \\input command.
    """
    def expand(self, parser):
        """
        It reads a file name from the input stack, opens the files, and 
        pushes a new scanner to the input stack.
        """
        pos = parser.input.position()
        name = parser.readFileName()
        f = parser.resolver.openIn(name, "source")
        if f is None:
            raise ValueError(f"file {name} not found", pos)
        parser.input.push(Scanner(parser.state, f, name))


class EndInput(Command):
    """
    The \\endinput command.

    This command ends the active scanner of the input stack.
    """
    def expand(self, parser):
        active = parser.input.active
        if active is not None:
            active.end()


class JobName(Command):
    def expand(self, parser):
        parser.input.push(TokenListScanner(toToks(parser.jobname)))


class Meaning(Command):
    def expand(self, parser):
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token", parser.input.position())
        parser.input.push(TokenListScanner(toToks(t.meaning(parser))))


mod = Module("expandable",
    commands={
        "noexpand": noexpand,
        "donot_expand:": noexpand,
        "expandafter": ExpandAfter(),
        "csname": CSName(),
        "endcsname": endcsname,
        "number": Number(),
        "romannumeral": RomanNumeral(),
        "string": String(),
        "input": Input(),
        "endinput": EndInput(),
        "jobname": JobName(),
        "meaning": Meaning(),
    },
    attributes={
        "toksToString": toksToString,
        "tokenToString": tokenToString,
        "expandedToksToString": expandedToksToString,
        "expandedTokenToString": expandedTokenToString,
        "formatName": formatName,
    }
)
