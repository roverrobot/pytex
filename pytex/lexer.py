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
    A tokenizer reads text from a line-oriented source and returns tokens.
    The main method is read().
    """
    def __init__(self, source):
        parser = source.parser
        # catcode is a dictionary that maps characters to their category codes
        self.catcode = parser.catcode
        self.equitable = parser.equitable
        self.endlinechar = dict.__getitem__(parser.parameters, "endlinechar")
        self.source = source
        self.name = getattr(source, "name", None)
        self.line_number = 0
        self.chars = iter(())
        self.pos = -1
        self.first = -1
        self.peek = None
        self.exhausted = not self._loadLine()

    def _setLine(self, line: str, line_number: int):
        self.line_number = line_number
        if line.endswith("\n"):
            line = line[:-1]
        eol = self.endlinechar.value
        if 0 <= eol < 256:
            line += chr(eol)
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

    def _loadLine(self):
        item = self.source.nextLine()
        if item is None:
            self.chars = iter(())
            self.pos = -1
            self.first = -1
            self.peek = None
            self.exhausted = True
            return False
        line_number, line = item
        self._setLine(line, line_number)
        self.exhausted = False
        return True

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
        read the next token from the source
        @return: the next token
        @raise EOFError: if the source is exhausted
        """
        while True:
            c, catcode = self.charExpand()
            if catcode is None or catcode == CATCODE.COMMENT:
                if self._loadLine():
                    continue
                raise EOFError
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
                if catcode == CATCODE.IGNORE:
                    continue
                return Token.token(c, catcode)
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
        self.source.end()

    def __repr__(self):
        return f"Tokenizer({self.position()})"


class Scanner:
    """
    A scanner is a line-text backstore for Tokenizer.
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
        self.stream = stream
        self.lines = enumerate(stream)
        self.name = name
        # line number
        self.line = -1
        # column number of the last line after the last token is read
        self.column = 0
    
    def nextLine(self):
        """
        Read the next physical line from the stream.
        """
        line_number, line = next(self.lines, (None, None))
        if line is None:
            self.lines = enumerate(())
            if not self.stream.closed:
                self.stream.close()
            return None
        self.line = line_number
        return line_number, line

    def position(self):
        """
        return the position of the last token read
        """
        return Position(self.name, self.line + 1, self.column + 1)

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
        # when true, source exhaustion is re-raised after the exhausted frame
        # has been popped instead of being absorbed into ordinary token flow
        self.eof_passthrough = False

    @staticmethod
    def _positioned(scanner):
        return callable(getattr(scanner, "position", None))

    def activeScanner(self):
        """
        Return the nearest scanner frame that can report source position.
        """
        if self._positioned(self.top):
            return self.top
        for scanner, _saved in reversed(self.stack):
            if self._positioned(scanner):
                return scanner
        return None

    def read(self) -> typing.Optional[Token]:
        """
        Read the next token from the active tokenizer. Line sources are
        backstores: they feed tokenizers onto the stack, but do not themselves
        produce tokens.
        @return: the next token, or None if the end of the stack is reached
        """
        if self.saved:
            return self._restore(self.saved.pop())
        while self.top:
            if isinstance(self.top, Tokenizer):
                try:
                    t = self.top.read()
                except EOFError:
                    self.pop()
                    if self.eof_passthrough:
                        raise
                    if self.saved:
                        return self._restore(self.saved.pop())
                    continue
                self.top.source.column = self.top.pos
                return self._restore(t)
            tokenizer = Tokenizer(self.top)
            if tokenizer.exhausted:
                self.pop()
                if self.eof_passthrough:
                    raise EOFError
                if self.saved:
                    return self._restore(self.saved.pop())
                continue
            self.push(tokenizer)

    @staticmethod
    def _restore(t):
        entry = t.entry
        if entry is not None and t.definition is not entry.value:
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
        self.stack.append((self.top, self.saved))
        self.top = lexer
        self.saved = []
    
    def pop(self):
        """
        pop the top scanner if it is terminated
        @param to: the scanner to pop to (including to)
        """
        try:
            self.top, self.saved = self.stack.pop()
        except IndexError:
            self.top = None
            self.saved = []

    def clear(self):
        """
        clear the stack of scanners
        """
        self.top = None
        self.saved = []
        self.stack = []

    def position(self):
        """
        return the position of the last token read
        """
        active = self.activeScanner()
        if active is None:
            return Position(None, 0, 0)
        return active.position()
    
    def __repr__(self):
        l = ["Input stack:"]
        if len(self.saved) > 0:
            f = lambda t: t.name + " " if isinstance(t, CommandToken) else t.name
            s = "".join(map(f, reversed(self.saved)))
            l.append(f"  saved: {s}")
        for s in repr(self.top).split("\n"):
            l.append(f"  top: {s}")
        for scanner, _saved in reversed(self.stack):
            for s in repr(scanner).split("\n"):
                l.append(f"  {s}")
        return "\n".join(l)
