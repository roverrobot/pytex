"""
This module implements various expandable commands.
"""


from pytex.token import Command, CATCODE, CommandToken, Token, relax, SpaceToken, CharToken
from pytex.module import Module
from pytex.lexer import TokenListScanner, Scanner
import pathlib

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
        if t.isCommand():
            t = CommandToken(t.name)
            t.noexpand = True
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
        if t1.isCommand():
            definition = parser.lookup(t1.name)
            if definition is None:
                raise ValueError(f"undefined command {t1.name}", parser.input.position())
            if definition.expand is not None:
                if parser.tracingcommands:
                    parser.traceExpansion(t1, definition)
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
    return CommandToken(name)

        
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
        c = parser.lookup(t.name)
        if c is None:
            c = relax
            parser.state.domains["equitable"][t.name] = c
        t.definition = c
        parser.input.unread(t)


def toToks(s: str) -> list:
    """
    Convert a string to a token list.
    @param s: the string
    @return: the token list
    """
    toks = []
    for c in s:
        if c == " ":
            toks.append(SpaceToken())
        else: 
            toks.append(CharToken(c, CATCODE.OTHER))
    return toks


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


def tokenToString(token, escapechar, space_after_command=False):
    """
    Convert a token to a string
    @param token: the token
    @param escapechar: the escape character
    @param space_after_command: add a space after a command
    @return: the string
    """
    if token.catcode is None:
        s = escapechar + token.name[1:]
        if space_after_command:
            s += " "
    elif token.catcode == CATCODE.PARAMETER:
        if token.parameter is None:
            s = "##"
        else:
            s = "#" + str(token.parameter+1)
    else:
        s = token.name
    return s


def toksToString(parser, tokens, space_after_command=False):
    """
    Convert a list of tokens to a string
    @param parser: the parser
    @param tokens: the list of tokens
    @param space_after_command: add a space after a command
    @return: the string
    """
    escape = parser.state.layout["escapechar"]
    escapechar = "" if escape < 0 else chr(escape)
    return "".join(map(lambda x: tokenToString(x, escapechar, space_after_command), tokens))


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
        if t.isCommand():
            escapechar = parser.state.layout["escapechar"]
            escapechar = chr(escapechar) if 0 <= escapechar < 256 else ""
            s = escapechar + t.name[1:]
        else:
            s = t.name
        parser.input.push(TokenListScanner(toToks(s)))


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
        for scanner in parser.input.stack:
            if scanner.position is not None:
                name = scanner.name
                break
        name = "" if scanner is None else scanner.name
        if not name:
            name = "noname"
        stem = pathlib.Path(name).stem
        parser.input.push(TokenListScanner(toToks(stem)))


class Meaning(Command):
    def expand(self, parser):
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token", parser.input.position())
        meaning = t.meaning(parser)
        toks = toToks(meaning)
        parser.input.push(TokenListScanner(toks))


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
    }
)
