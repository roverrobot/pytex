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
    A tokenizer reads text from a file-like backstore and returns tokens.
    The main method is read().
    """
    def __init__(self, source, parser, name=None, line_number=0):
        if isinstance(source, str):
            source = io.StringIO(source)
        elif not isinstance(source, io.IOBase):
            raise TypeError("source must be a string or a file-like object")
        # catcode is a dictionary that maps characters to their category codes
        self.catcode = parser.catcode
        self.equitable = parser.equitable
        self.endlinechar = dict.__getitem__(parser.parameters, "endlinechar")
        self.source = source
        self.name = name if name is not None else getattr(source, "name", None)
        self.lines = enumerate(source, start=line_number)
        self.line_number = line_number
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
        line_number, line = next(self.lines, (None, None))
        if line is None:
            self.chars = iter(())
            self.pos = -1
            self.first = -1
            self.peek = None
            self.lines = enumerate(())
            if not self.source.closed:
                self.source.close()
            self.exhausted = True
            return False
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
        if self.source is not None and not self.source.closed:
            self.source.close()
        self.lines = enumerate(())

    def __repr__(self):
        return f"Tokenizer({self.position()})"


class InputStack:
    """
    A stack of tokenizers. The goal is to support tex commands such as \\input
    and \\include.

    The main methods are push(), read() and unread()
    """
    def __init__(self):
        self.top = None
        # the stack of tokenizers
        self.stack = []
        # the saved tokens that are unread
        self.saved = []

    def read(self) -> typing.Optional[Token]:
        """
        Read the next token from the active tokenizer.
        @return: the next token
        @raise EOFError: if the end of the stack is reached
        """
        try:
            t = self.saved.pop() if self.saved else self.top.read()
            entry = t.entry
            if entry is not None and t.definition is not entry.value:
                t.definition = entry.value
            return t
        except EOFError:
            self.pop()
            return self.read()
        except AttributeError as e:
            if self.top is None:
                raise EOFError
            raise e

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

    def push(self, tokenizer):
        """
        push a new tokenizer on the stack
        @param tokenizer: the tokenizer to push
        """
        if not isinstance(tokenizer, Tokenizer):
            raise TypeError("InputStack only accepts Tokenizer frames")
        self.stack.append((self.top, self.saved))
        self.top = tokenizer
        self.saved = []
    
    def pop(self):
        """
        pop the top tokenizer if it is terminated
        """
        try:
            self.top, self.saved = self.stack.pop()
        except IndexError:
            self.top = None
            self.saved = []
            raise EOFError

    def clear(self):
        """
        clear the stack of tokenizers
        """
        self.top = None
        self.saved = []
        self.stack = []

    def position(self):
        """
        return the position of the last token read
        """
        if self.top is None:
            return Position(None, 0, 0)
        return self.top.position()
    
    def __repr__(self):
        l = ["Input stack:"]
        if len(self.saved) > 0:
            f = lambda t: t.name + " " if isinstance(t, CommandToken) else t.name
            s = "".join(map(f, reversed(self.saved)))
            l.append(f"  saved: {s}")
        for s in repr(self.top).split("\n"):
            l.append(f"  top: {s}")
        for tokenizer, _saved in reversed(self.stack):
            for s in repr(tokenizer).split("\n"):
                l.append(f"  {s}")
        return "\n".join(l)
