from pytex.token import CATCODE, Token, CommandToken, SpaceToken, ActiveToken
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

    def __repr__(self):
        file = "" if self.file is None else self.file
        return "%s:%d:%d" % (file, self.line, self.column)


class Tokenizer:
    """
    A tokenizer reads a line of text and returns tokens.
    The main method is read()
    @param line: the line of text to read
    @param state: the parser state
    """
    def __init__(self, line: str, state):
        # catcode is a dictionary that maps characters to their category codes
        self.catcode = state.catcode
        self.equitable = state.equitable
        # skip the leading spaces in line and set self.pos to the first non-space character
        self.line = enumerate(line)
        self.pos = -1
        self.first = -1
        self.saved = []
        last = None
        last_pos = -1
        for self.pos, c in self.line:
            last = c
            last_pos = self.pos
            if self.catcode[ord(c)] != CATCODE.SPACE:
                self.first = self.pos
                self.saved = [c]
                break
        else:
            if last is not None:
                # line has only spaces; keep the last one for current behavior
                self.pos = last_pos
                self.first = last_pos
                self.saved = [last]


    def char(self):
        """
        read a character from the line, and return the character and its category code
        @return: the character and its category code, or (None, None) if the end of the
        line is reached
        """
        if self.saved:
            c = self.saved.pop()
        else:
            try:
                self.pos, c = next(self.line)
            except StopIteration:
                return None, None
        return c, self.catcode[ord(c)]
    
    def unread(self, c):
        """
        save a character for later reading
        @param c: the character to save
        """
        if c is not None:
            self.saved.append(c)

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
            self.unread(c1)
            return c, catcode
        c2, catcode2 = self.char()
        if c2 is None:
            self.unread(c1)
            return c, catcode
        # handle ^^ followed by two hex digits
        if ("0" <= c2 <= "9") or ("a" <= c2 <= "f") or ("A" <= c2 <= "F"):
            c3, catcode3 = self.char()
            if c3 is not None and (("0" <= c3 <= "9") or ("a" <= c3 <= "f") or ("A" <= c3 <= "F")):
                c = int(c2 + c3, 16)
                catcode = self.catcode[c]
                return chr(c), catcode
            self.unread(c3)
        c = ord(c2)
        if c >= 64:
            c -= 64
        else:
            c += 64
        catcode = self.catcode[c]
        return chr(c), catcode

    def skipSpaces(self):
        """
        read a token and if it is a space, skip spaces and return a single space
        """
        catcode = CATCODE.SPACE
        while catcode == CATCODE.SPACE:
            c, catcode = self.charExpand()
        if catcode != CATCODE.END_OF_LINE:
            self.unread(c)

    def read(self) -> typing.Optional[Token]:
        """
        read the next token from the line
        @return: the next token, or None if the end of the line is reached
        """
        c, catcode = self.charExpand()
        if catcode is None:
            return None
        # handle comments
        if catcode == CATCODE.COMMENT:
            return None
        # handle spaces
        if catcode == CATCODE.SPACE:
            self.skipSpaces()
            return SpaceToken()
        if catcode == CATCODE.END_OF_LINE:
            if self.pos == self.first:
                t = CommandToken("\\par")
                t.entry = self.equitable.entry("\\par")
                return t
            return SpaceToken()
        if catcode == CATCODE.ACTIVE:
            t = ActiveToken(c, catcode)
            t.entry = self.equitable.entry(c)
            return t
        if catcode != CATCODE.ESCAPE:
            return self.read() if catcode == CATCODE.IGNORE else Token.token(c, catcode)
        c, catcode = self.charExpand()
        name = "\\" + c
        if catcode == CATCODE.LETTER:
            c, catcode = self.charExpand()
            while catcode == CATCODE.LETTER:
                name += c
                c, catcode = self.charExpand()
            if catcode == CATCODE.SPACE or catcode == CATCODE.END_OF_LINE:
                self.skipSpaces()
            else:
                self.unread(c)
        t = CommandToken(name)
        t.entry = self.equitable.entry(name)
        return t


class Scanner:
    """
    A scanner reads tokens from a stream. The main method is read()
    @param state: the state of the parser
    @param stream: the stream to read from. Must be a file-like object
    @param name: the name of the stream

    We will need the state.catcode and state.parameters["endlinchar"]
    in the lexer.
    """
    def __init__(self, state, stream, name=None):
        if not isinstance(stream, io.IOBase):
            raise TypeError("stream must be a file-like object")
        self.state = state
        self.eol = dict.__getitem__(state.parameters, "endlinechar")
        self.stream = stream
        self.lines = enumerate(stream)
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
            self.line, line = next(self.lines)
            if line[-1] == "\n":
                line = line[:-1]
            eol = self.eol.value
            if 0 <= eol < 256:
                line += chr(eol)
            self.tokenizer = Tokenizer(line, self.state)
        except StopIteration:
            if self.tokenizer is not None:
                self.column = self.tokenizer.pos
            else:
                self.column = 0
            self.tokenizer = None
            if not self.stream.closed:
                self.stream.close()

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
            if t:
                return t
            self.feed()

    def end(self):
        """
        terminate the scanner
        """
        if self.stream is not None:
            self.stream.close()
        self.lines = enumerate([])

    def __repr__(self):
        return f"Scanner({self.position()})"


class StringScanner(Scanner):
    """
    A scanner that reads from a string
    @param state: the state of the parser
    @param s: the string to read from
    @param name: the name of the string
    """
    def __init__(self, state, s: str, name: str=None):
        super().__init__(state, io.StringIO(s), name)


class TokenListScanner:
    """
    A scanner that reads from a list of tokens
    @param toks: the list of tokens
    """
    def __init__(self, toks: typing.List[Token]):
        assert toks is not None
        self.toks = toks
        self.iter = iter(toks)

    def read(self) -> typing.Optional[Token]:
        """
        read the next token from the list
        @return: the next token, or None if the end of the list is reached
        """
        return next(self.iter, None)

    # this scanner does not support token position
    position = None

    def __repr__(self):
        f = lambda t: t.name + " " if isinstance(t, CommandToken) else t.name
        s = "".join(map(f, self.toks))
        return f"TokenListScanner:\n  {s}"


class InputStack:
    """
    A stack of scanners. The goal is to support tex commands such as \\input and \\include

    The main methods are push(), read() and unread()
    """
    def __init__(self):
        self.top = None
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
        if self.saved:
            return self.saved.pop()
        while self.top:
            t = self.top.read()
            if t:
                return t
            if self.stack:
                self.top, self.active = self.stack.pop()
            else:
                self.top = None
                self.active = None

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
        if self.top is not None:
            self.stack.append((self.top, self.active))
        if self.saved:
            # remember that the saved tokens are on a stack. So we need to reverse it
            self.saved.reverse()
            self.stack.append((TokenListScanner(self.saved), self.active))
            self.saved = []
        self.top = lexer
        if lexer.position is not None:
            self.active = lexer
    
    def pop(self):
        """
        pop the top scanner if it is terminated
        @param to: the scanner to pop to (including to)
        """
        try:
            self.top, self.active = self.stack.pop()
        except IndexError:
            self.top = None
            self.active = None

    def clear(self):
        """
        clear the stack of scanners
        """
        self.top = None
        self.saved = []
        self.stack = []
        self.active = None

    def position(self):
        """
        return the position of the last token read
        """
        if self.active is None:
            return Position(None, 0, 0)
        return self.active.position()
    
    def __repr__(self):
        l = ["Input stack:"]
        if len(self.saved) > 0:
            f = lambda t: t.name + " " if isinstance(t, CommandToken) else t.name
            s = "".join(map(f, reversed(self.saved)))
            l.append(f"  saved: {s}")
        for s in repr(self.top).split("\n"):
            l.append(f"  top: {s}")
        for scanner in reversed(self.stack):
            for s in repr(scanner).split("\n"):
                l.append(f"  {s}")
        return "\n".join(l)
