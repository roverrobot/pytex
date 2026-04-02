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
    @param parser: the parser
    """
    def __init__(self, line: str, parser, scanner, name=None, line_number=0):
        # catcode is a dictionary that maps characters to their category codes
        self.catcode = parser.catcode
        self.equitable = parser.equitable
        self.scanner = scanner
        self.name = name
        self.line_number = line_number
        # Skip leading spaces, and also ignored characters that can expose more
        # leading spaces (for example kvsetkeys uses lines that begin with an
        # ignored '&' in e-TeX mode).
        self.chars = enumerate(line)
        self.pos = -1
        self.first = -1
        last = None
        last_pos = -1
        self.peek = None
        for self.pos, c in self.chars:
            last = c
            last_pos = self.pos
            catcode = self.catcode[ord(c)]
            if catcode != CATCODE.SPACE and catcode != CATCODE.IGNORE:
                self.first = self.pos
                self.peek = c
                return
        # line has only spaces; keep the last one for current behavior
        self.pos = last_pos
        self.first = last_pos

    def char(self):
        """
        read a character from the line, and return the character and its category code
        @return: the character and its category code, or (None, None) if the end of the
        line is reached
        """
        item = next(self.chars, None)
        if item is None:
            return None
        self.pos, c = item
        return c
    
    def charExpand(self):
        """
        read a character from the line, and expand ^^. 
        @return: the character and its category code
        """
        if self.peek is None:
            return None, None
        c = self.peek
        self.peek = self.char()
        catcode = self.catcode[ord(c)]
        if catcode != CATCODE.SUPERSCRIPT:
            return c, catcode
        # handle ^^
        c1 = self.peek
        if c1 is None:
            return c, catcode
        catcode1 = self.catcode[ord(c1)]
        if catcode1 != CATCODE.SUPERSCRIPT:
            self.peek = c1
            return c, catcode
        c2 = self.char()
        if c2 is None:
            self.peek = c1
            return c, catcode
        # handle ^^ followed by two hex digits
        if ("0" <= c2 <= "9") or ("a" <= c2 <= "f") or ("A" <= c2 <= "F"):
            c3 = self.char()
            if c3 is not None and (("0" <= c3 <= "9") or ("a" <= c3 <= "f") or ("A" <= c3 <= "F")):
                c4 = int(c2 + c3, 16)
                catcode4 = self.catcode[c4]
                self.peek = self.char()
                return chr(c4), catcode4
            self.peek = c3
        else:
            self.peek = None
        c3 = ord(c2)
        if c3 >= 64:
            c3 -= 64
        else:
            c3 += 64
        catcode3 = self.catcode[c3]
        if self.peek is None:
            self.peek = self.char()
        return chr(c3), catcode3

    def skipSpaces(self):
        """
        read a token and if it is a space, skip spaces and return a single space
        """
        while True:
            c = self.peek
            if c is None:
                return
            catcode = self.catcode[ord(c)]
            if catcode != CATCODE.SPACE:
                break
            self.charExpand()
        if catcode == CATCODE.END_OF_LINE:
            self.peek = None

    def read(self) -> typing.Optional[Token]:
        """
        read the next token from the line
        @return: the next token, or None if the end of the line is reached
        """
        c, catcode = self.charExpand()
        if catcode is None or catcode == CATCODE.COMMENT:
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
        if catcode is not CATCODE.ESCAPE:
            return self.read() if catcode == CATCODE.IGNORE else Token.token(c, catcode)
        c, catcode = self.charExpand()
        name = "\\" + c
        while catcode == CATCODE.LETTER:
            c = self.peek
            if c is None: 
                break
            catcode = self.catcode[ord(c)]
            if catcode == CATCODE.LETTER:
                name += c
                self.charExpand()
            elif catcode == CATCODE.SPACE or catcode == CATCODE.END_OF_LINE:
                self.skipSpaces()
                break
        t = CommandToken(name)
        t.entry = self.equitable.entry(name)        
        return t

    def position(self):
        return Position(self.name, self.line_number + 1, self.pos + 1)

    def end(self):
        self.scanner.end()

    def __repr__(self):
        return f"Tokenizer({self.position()})"


class Scanner:
    """
    A scanner reads tokens from a stream. The main method is read()
    @param parser: the parser
    @param stream: the stream to read from. Must be a file-like object
    @param name: the name of the stream

    We will need the parser.catcode and parser.parameters["endlinchar"]
    in the lexer.
    """
    def __init__(self, parser, stream, name=None):
        if not isinstance(stream, io.IOBase):
            raise TypeError("stream must be a file-like object")
        self.parser = parser
        self.eol = dict.__getitem__(parser.parameters, "endlinechar")
        self.stream = stream
        self.lines = enumerate(stream)
        self.name = name
        # line number
        self.line = -1
        # column number of the last line after the last token is read
        self.column = 0
    
    def feed(self):
        """
        read the next line from the stream
        """
        self.line, line = next(self.lines, (None, None))
        if line is None:
            if not self.stream.closed:
                self.stream.close()
            return None
        if line.endswith("\n"):
            line = line[:-1]
        eol = self.eol.value
        if 0 <= eol < 256:
            line += chr(eol)
        return Tokenizer(line, self.parser, self, self.name, self.line)

    def position(self):
        """
        return the position of the last token read
        """
        return Position(self.name, self.line + 1, self.column + 1)

    def read(self) -> typing.Optional[Token]:
        """
        read the next token from the stream
        @return: the next token, or None if the end of the stream is reached
        """
        while True:
            tokenizer = self.feed()
            if tokenizer is None:
                return None
            t = tokenizer.read()
            self.column = tokenizer.pos
            if t:
                self.parser.input.push(tokenizer)
                return t

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
    @param parser: the parser
    @param s: the string to read from
    @param name: the name of the string
    """
    def __init__(self, parser, s: str, name: str=None):
        super().__init__(parser, io.StringIO(s), name)


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
            t = self.saved.pop()
            entry = t.entry
            if entry is not None and t.definition is not entry.value:
                t.definition = entry.value
            return t
        while self.top:
            t = self.top.read()
            if t:
                entry = t.entry
                if entry is not None:
                    t.definition = entry.value
                return t
            self.top, self.active, self.saved = self.stack.pop()
            if self.saved:
                t = self.saved.pop()
                entry = t.entry
                if entry is not None:
                    t.definition = entry.value
                return t

    def unread(self, token):
        """
        save a token for later reading
        @param token: the token to save
        """
        self.saved.append(token)

    def pushTokenList(self, toks):
        """
        Push a plain token list in front of the current input without creating
        a separate scanner frame.
        """
        if toks:
            self.saved.extend(reversed(toks))

    def push(self, lexer):
        """
        push a new scanner on the stack
        @param lexer: the scanner to push
        """
        self.stack.append((self.top, self.active, self.saved))
        self.top = lexer
        if lexer.position is not None:
            self.active = lexer
        self.saved = []
    
    def pop(self):
        """
        pop the top scanner if it is terminated
        @param to: the scanner to pop to (including to)
        """
        try:
            self.top, self.active, self.saved = self.stack.pop()
        except IndexError:
            self.top = None
            self.active = None
            self.saved = []

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
