from pytex.token import CATCODE, Token, CommandToken, SpaceToken
import enum
import typing
import io


class Position:
    """
    Represents a position of a token in a file
    @param file: the name of the file
    @param line: the line number
    @param column: the column number
    """
    def __init__(self, file: str, line: int, column: int):
        self.file = file
        self.line = line
        self.column = column

    def __str__(self):
        file = "" if self.file is None else self.file
        return "%s:%d:%d" % (file, self.line, self.column)


class Tokenizer:
    """
    A tokenizer reads a line of text and returns tokens.
    The main method is read()
    @param line: the line of text to read
    @param catcode: a list that maps characters to their category codes
    """
    def __init__(self, line: str, catcode):
        # catcode is a dictionary that maps characters to their category codes
        self.catcode = catcode
        # attach a carriage return to the end of the line
        self.line = enumerate(line + "\r")
        # the saved characters that are unread
        self.saved = []
        # whether we are skippign the initial spaces
        self.start = True
        self.pos = 0

    def char(self):
        """
        read a character from the line, and return the character and its category code
        @return: the character and its category code, or (None, None) if the end of the
        line is reached
        """
        if len(self.saved) > 0:
            c = self.saved.pop()
        else:
            try:
                self.pos, c = next(self.line)
            except StopIteration:
                return None, None
        return c, self.catcode[ord(c)]
    
    def charExpand(self):
        """
        read a character from the line, and expand ^^. 
        @return: the character and its category code
        """
        c, catcode = self.char()
        if catcode != CATCODE.SUPERSCRIPT:
            return c, catcode
        # handle ^^
        c1, catcode1 = self.char()
        if catcode1 != CATCODE.SUPERSCRIPT:
            self.saved.append(c1)
            return c, catcode
        c2, catcode2 = self.char()
        # handle ^^ followed by two hex digits
        if ("0" <= c2 <= "9") or ("a" <= c2 <= "f"):
            c3, catcode3 = self.char()
            if ("0" <= c3 <= "9") or ("a" <= c3 <= "f"):
                c = int(c2 + c3, 16)
                catcode = self.catcode[c]
                return chr(c), catcode
            self.saved.append(c3)
        c = ord(c2)
        if c > 64:
            c -= 64
        else:
            c += 64
        catcode = self.catcode[c]
        return chr(c), catcode

    def read(self) -> typing.Optional[Token]:
        """
        read the next token from the line
        @return: the next token, or None if the end of the line is reached
        """
        c, catcode = self.charExpand()
        if catcode is None:
            return None
        if catcode == CATCODE.IGNORE:
            return self.read()
        # handle comments
        if catcode == CATCODE.COMMENT:
            return None
        # handle spaces
        if catcode == CATCODE.SPACE:
            # skip spaces
            while catcode == CATCODE.SPACE:
                c, catcode = self.charExpand()
            # skip the spaces at the beginning of the line
            if self.start:
                self.saved.append(c)
                return self.read()
            if catcode != CATCODE.END_OF_LINE:
                self.saved.append(c)
            return SpaceToken()
        if catcode == CATCODE.END_OF_LINE:
            if self.start:
                return CommandToken("\\par")
            return SpaceToken()
        self.start = False
        if catcode == CATCODE.ACTIVE:
            return CommandToken(c)
        if catcode != CATCODE.ESCAPE:
            return Token.token(c, catcode)
        c, catcode = self.charExpand()
        name = "\\" + c
        while catcode == CATCODE.LETTER:
            c, catcode = self.charExpand()
            if catcode == CATCODE.LETTER:
                name += c
            elif catcode == CATCODE.SPACE or catcode == CATCODE.END_OF_LINE:
                break
            else:
                self.saved.append(c)
                break
        return CommandToken(name)


class Scanner:
    """
    A scanner reads tokens from a stream. The main method is read()
    @param catcode: a list that maps characters to their category codes
    @param stream: the stream to read from. Could be a string or a file-like object
    @param name: the name of the stream
    """
    def __init__(self, catcode, stream, name=None):
        self.catcode = catcode
        if isinstance(stream, str):
            stream = io.StringIO(stream)
        self.stream = enumerate(stream)
        self.tokenizer = None
        self.name = name
        # line number
        self.line = 0
        # column number of the last line after the last token is read
        self.column = 0
        # read the first line
        self.feed()

    def feed(self):
        """
        read the next line from the stream
        """
        try:
            self.line, line = next(self.stream)
            if line[-1] == "\n":
                line = line[:-1]
            self.tokenizer = Tokenizer(line, self.catcode)
        except StopIteration:
            self.column = self.tokenizer.pos
            self.tokenizer = None

    def position(self):
        """
        return the position of the last token read
        """
        col = self.column if self.tokenizer is None else self.tokenizer.pos
        return Position(self.name, self.line+1, col+1)

    def read(self) -> typing.Optional[Token]:
        """
        read the next token from the stream
        @return: the next token, or None if the end of the stream is reached
        """
        while True:
            if self.tokenizer is None:
                return None
            self.column = self.tokenizer.pos
            t = self.tokenizer.read()
            if t is None:
                self.feed()
                if self.tokenizer is None:
                    return None
                return self.read()
            return t


class TokenListScanner:
    """
    A scanner that reads from a list of tokens
    @param toks: the list of tokens
    """
    def __init__(self, toks: typing.List[Token]):
        self.toks = iter(toks)

    def read(self) -> typing.Optional[Token]:
        """
        read the next token from the list
        @return: the next token, or None if the end of the list is reached
        """
        try:
            return next(self.toks)
        except StopIteration:
            return None
    
    # this scanner does not support token position
    position = None


class InputStack:
    """
    A stack of scanners. The goal is to support tex commands such as \input and \include

    The main methods are push(), read() and unread()
    """
    def __init__(self):
        # the stack of scanners
        self.stack = []
        # the saved tokens that are unread
        self.saved = []
        # the last scanner in teh stack that can return a position
        self.active = None

    def read(self) -> typing.Optional[Token]:
        """
        read the next token from the top scanner on the stack. If the top scanner is
        exhausted, pop it and read from the next scanner on the stack.
        @return: the next token, or None if the end of the stack is reached
        """
        if len(self.saved) > 0:
            return self.saved.pop()
        try:
            t = self.stack[-1].read()
            if t is None:
                self.stack.pop()
                for s in reversed(self.stack):
                    if s.position is not None:
                        self.active = s
                        break
                return self.read()
            return t
        except IndexError:
            return None

    def unread(self, token):
        """
        save a token for later reading
        @param token: the token to save
        """
        self.saved.append(token)

    def push(self, lexer):
        """
        push a new scanner on the stack
        @param lexer: the scanner to push
        """
        if len(self.saved) > 0:
            self.stack.append(TokenListScanner(self.saved))
            self.saved = []
        self.stack.append(lexer)
        if lexer.position is not None:
            self.active = lexer

    def position(self):
        """
        return the position of the last token read
        """
        if self.active is None:
            return Position(None, 0, 0)
        return self.active.position()
