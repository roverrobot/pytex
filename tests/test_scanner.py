import pytest
from pytex.token import CATCODE
from pytex import lexer


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


class State:
    def __init__(self):
        self.catcode = Catcodes()
        self.parameters = {"endlinechar": ord("\r")}


@pytest.fixture
def state():
    return State()


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
def test_token(state, input):
    cat = []
    for t in input.toks:
        c = None if t[0] == "\\" else state.catcode[ord(t[0])]
        cat.append(c)
    scanner = lexer.StringScanner(state, input.input)
    for i in range(len(input.toks)):
        t = input.toks[i]
        c = cat[i]
        token = scanner.read()
        assert token is not None
        assert token.name == t
        assert token.catcode == c
    token = scanner.read()
    assert token is None


def test_input_stack(state):
    stack = lexer.InputStack()
    scanner = lexer.StringScanner(state, "ABC")
    stack.push(scanner)
    token = stack.read()
    assert token is not None
    assert token.name == "A"
    assert token.catcode == CATCODE.LETTER
    B = stack.read()
    C = stack.read()
    stack.unread(C)
    stack.unread(B)
    scanner = lexer.StringScanner(state, "1")
    stack.push(scanner)
    token = stack.read()
    assert token is not None
    assert token.name == "1"
    assert token.catcode == CATCODE.OTHER
    token = scanner.read()
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
    token = scanner.read()
    assert token is None


def test_unicode(state):
    s = "1é测"
    scanner = lexer.StringScanner(state, s)
    for i in range(len(s)):
        t = scanner.read()
        assert t is not None
        assert t.catcode == CATCODE.OTHER
        assert t.name == s[i]
    t = scanner.read()
    assert t.catcode is CATCODE.SPACE


def test_ignore(state):
    # ignore space 
    state.catcode[32] = CATCODE.IGNORE
    s = "\\a b"
    scanner = lexer.StringScanner(state, s)
    t = scanner.read()
    assert t is not None
    assert t.catcode == None
    assert t.name == "\\a"
    t = scanner.read()
    assert t is not None
    assert t.catcode == CATCODE.LETTER
    assert t.name == "b"
    t = scanner.read()
    assert t is not None
    assert t.catcode == CATCODE.SPACE
    t = scanner.read()
    assert t is None