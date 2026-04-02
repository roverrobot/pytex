import pytest
from pytex.token import CATCODE
from pytex import lexer
from pytex import token as tk
from pytex import state as st


class Catcodes(list):
    def __init__(self):
        for c in range(256):
            self.append(CATCODE.OTHER)
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = CATCODE.LETTER
            self[c + 32] = CATCODE.LETTER
        self[ord("\\")] = CATCODE.ESCAPE
        self[ord("{")] = CATCODE.BEGIN_GROUP
        self[ord("}")] = CATCODE.END_GROUP
        self[ord("\r")] = CATCODE.END_OF_LINE
        self[ord(" ")] = CATCODE.SPACE
        self[ord("\t")] = CATCODE.SPACE
        self[ord("^")] = CATCODE.SUPERSCRIPT
        self[ord("_")] = CATCODE.SUBSCRIPT
        self[ord("$")] = CATCODE.MATH_SHIFT
        self[ord("#")] = CATCODE.PARAMETER
        self[ord("&")] = CATCODE.ALIGNMENT_TAB
        self[ord("%")] = CATCODE.COMMENT
        self[ord("@")] = CATCODE.ACTIVE
        self[8] = CATCODE.INVALID

    def __getitem__(self, key):
        if key > len(self):
            return CATCODE.OTHER
        return super().__getitem__(key)


class ScannerParser:
    def __init__(self):
        self.parameters = st.Dict("parameters")
        self.parameters["endlinechar"] = ord("\r")
        self.equitable = st.Dict("equitable")
        self.catcode = Catcodes()
        self.input = lexer.InputStack()


@pytest.fixture
def parser():
    return ScannerParser()


def stack_for(parser, scanner):
    parser.input.push(scanner)
    return parser.input


class Input:
    def __init__(self, name, input, toks):
        self.name = name
        self.input = input
        self.toks = toks


class StringInput(Input):
    def __init__(self, name, input):
        toks = [t for t in input]
        toks.append(" ")
        super().__init__(name, input, toks)


testdata = [
    StringInput("tokens", "A1a{}^_$#&@"),
    Input("commands", "\\alpha 1 \\beta", ["\\alpha", "1", " ", "\\beta"]),
    Input("comment", "A%comment\n  1", ["A", "1", " "]),
    Input("space", "A  \tB", ["A", " ", "B", " "]),
    Input("eol", "A \n \n B", ["A", " ", "\\par", "B", " "]),
    Input("expand",  "^^61^^a", ["a", "!", " "])
]

@pytest.mark.parametrize(
    "input",
    testdata,
    ids = [test.name for test in testdata]
)
def test_token(parser, input):
    cat = []
    for t in input.toks:
        c = None if t[0] == "\\" else parser.catcode[ord(t[0])]
        cat.append(c)
    scanner = lexer.StringScanner(parser, input.input)
    stack = stack_for(parser, scanner)
    for i in range(len(input.toks)):
        t = input.toks[i]
        c = cat[i]
        token = stack.read()
        assert token is not None
        assert token.name == t
        assert token.catcode == c
    token = stack.read()
    assert token is None


def test_input_stack(parser):
    stack = parser.input
    scanner = lexer.StringScanner(parser, "ABC")
    stack.push(scanner)
    token = stack.read()
    assert token is not None
    assert token.name == "A"
    assert token.catcode == CATCODE.LETTER
    B = stack.read()
    C = stack.read()
    stack.unread(C)
    stack.unread(B)
    scanner = lexer.StringScanner(parser, "1")
    stack.push(scanner)
    token = stack.read()
    assert token is not None
    assert token.name == "1"
    assert token.catcode == CATCODE.OTHER
    token = stack.read()
    assert token is not None
    assert token.name == " "
    assert token.catcode == CATCODE.SPACE
    token = stack.read()
    assert token is not None
    assert token.name == "B"
    assert token.catcode == CATCODE.LETTER
    token = stack.read()
    assert token is not None
    assert token.name == "C"
    assert token.catcode == CATCODE.LETTER
    token = stack.read()
    assert token is not None
    assert token.name == " "
    assert token.catcode == CATCODE.SPACE
    token = stack.read()
    assert token is None


def test_push_token_list_splices_tokens_without_new_scanner_frame(parser):
    stack = parser.input
    scanner = lexer.StringScanner(parser, "A")
    stack.push(scanner)
    token = stack.read()
    assert token is not None
    assert token.name == "A"
    B = tk.Token.token("B", CATCODE.LETTER)
    C = tk.Token.token("C", CATCODE.LETTER)
    top = stack.top
    depth = len(stack.stack)
    stack.pushTokenList([B, C])
    assert stack.top is top
    assert len(stack.stack) == depth
    token = stack.read()
    assert token is not None
    assert token.name == "B"
    token = stack.read()
    assert token is not None
    assert token.name == "C"
    token = stack.read()
    assert token is not None
    assert token.isSpace(False)
    token = stack.read()
    assert token is None


def test_unicode(parser):
    s = "1é测"
    scanner = lexer.StringScanner(parser, s)
    stack = stack_for(parser, scanner)
    for i in range(len(s)):
        t = stack.read()
        assert t is not None
        assert t.catcode == CATCODE.OTHER
        assert t.name == s[i]
    t = stack.read()
    assert t.catcode is CATCODE.SPACE


def test_ignore(parser):
    # ignore space 
    parser.catcode[32] = CATCODE.IGNORE
    s = "\\a b"
    scanner = lexer.StringScanner(parser, s)
    stack = stack_for(parser, scanner)
    t = stack.read()
    assert t is not None
    assert t.catcode == None
    assert t.name == "\\a"
    t = stack.read()
    assert t is not None
    assert t.catcode == CATCODE.LETTER
    assert t.name == "b"
    t = stack.read()
    assert t is not None
    assert t.catcode == CATCODE.SPACE
    t = stack.read()
    assert t is None


def test_leading_ignore_does_not_preserve_space(parser):
    parser.catcode[ord("&")] = CATCODE.IGNORE
    scanner = lexer.StringScanner(parser, "& A")
    stack = stack_for(parser, scanner)
    t = stack.read()
    assert t is not None
    assert t.catcode == CATCODE.LETTER
    assert t.name == "A"
    t = stack.read()
    assert t is not None
    assert t.catcode == CATCODE.SPACE
    t = stack.read()
    assert t is None


def test_command(parser):
    scanner = lexer.StringScanner(parser, "\\: ")
    stack = stack_for(parser, scanner)
    t = stack.read()
    assert t is not None
    assert t.catcode is None and t.name == "\\:"
    t = stack.read()
    assert t.isSpace(False)


def test_endlinechar_negative_one_skips_empty_line(parser):
    parser.parameters["endlinechar"] = -1
    scanner = lexer.StringScanner(parser, "\nA")
    stack = stack_for(parser, scanner)
    token = stack.read()
    assert token is not None
    assert token.name == "A"
    assert token.catcode == CATCODE.LETTER
    token = stack.read()
    assert token is None


def test_carets_at_eol_with_no_endlinechar(parser):
    parser.parameters["endlinechar"] = -1
    scanner = lexer.StringScanner(parser, "^^")
    stack = stack_for(parser, scanner)
    tokens = []
    while True:
        token = stack.read()
        if token is None:
            break
        tokens.append(token)
    assert [t.name for t in tokens] == ["^", "^"]
    assert [t.catcode for t in tokens] == [CATCODE.SUPERSCRIPT, CATCODE.SUPERSCRIPT]


def test_carets_at_eol_with_default_endlinechar(parser):
    parser.parameters["endlinechar"] = ord("\r")
    scanner = lexer.StringScanner(parser, "^^")
    stack = stack_for(parser, scanner)
    token = stack.read()
    assert token is not None
    assert token.name == "M"
    assert token.catcode == CATCODE.LETTER
    token = stack.read()
    assert token is None


def test_utf(parser):
    scanner = lexer.StringScanner(parser, "😄")
    stack = stack_for(parser, scanner)
    token = stack.read()
    assert token is not None
    assert token.name == "😄"
    assert token.catcode == CATCODE.OTHER
    token = stack.read()
    assert token.catcode == CATCODE.SPACE
    token = stack.read()
    assert token is None
