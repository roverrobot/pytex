import pytest
from pytex.token import CATCODE
from pytex import lexer


class State:
    def __init__(self):
        catcode = []
        for c in range(256):
            catcode.append(CATCODE.OTHER)
        for c in range(ord("A"), ord("Z") + 1):
            catcode[c] = CATCODE.LETTER
            catcode[c + 32] = CATCODE.LETTER
        catcode[ord("\\")] = CATCODE.ESCAPE
        catcode[ord("{")] = CATCODE.BEGIN_GROUP
        catcode[ord("}")] = CATCODE.END_GROUP
        catcode[ord("\r")] = CATCODE.END_OF_LINE
        catcode[ord(" ")] = CATCODE.SPACE
        catcode[ord("\t")] = CATCODE.SPACE
        catcode[ord("^")] = CATCODE.SUPERSCRIPT
        catcode[ord("_")] = CATCODE.SUBSCRIPT
        catcode[ord("$")] = CATCODE.MATH_SHIFT
        catcode[ord("#")] = CATCODE.PARAMETER
        catcode[ord("&")] = CATCODE.ALIGNMENT_TAB
        catcode[ord("%")] = CATCODE.COMMENT
        catcode[ord("@")] = CATCODE.ACTIVE
        catcode[8] = CATCODE.INVALID
        self.catcode = catcode
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
