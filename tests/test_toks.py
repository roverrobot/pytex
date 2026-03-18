import pytest
from pytex.token import CATCODE, CommandToken, Token
from pytex import toks
from pytex import node as nd
from pytex import glue
from pytex.expandable import toToks
from tests.test_vmode import _test_hbox


def test_read_toks(parser):
    parser.readFrom("abcd}")
    k = parser.readBalancedText([])
    # a, b, c, d, }, space
    assert len(k) == 5
    assert k[3].name == "d"
    

def test_read_general_text(parser):
    parser.readFrom(" \\relax  {abcd}")
    k = parser.readGeneralText(expand=False)
    assert len(k) == 4
    assert k[3].name == "d"


def test_toks_register(parser):
    parser.parse("\\toks0={abcd}")
    k = parser.state.toks[0]
    assert len(k) == 4
    assert k[3].name == "d"


def test_aftergroup(collector):
    collector.parse("{\\aftergroup a\\aftergroup b\\count0=1}")
    assert collector.getString() == "ab "

        
def test_case(collector):
    collector.parse("\\uppercase{a!}")
    assert collector.getString() == "A! "
    collector.parse("\\lowercase{!A}")
    assert collector.getString() == "!a "
    collector.parse("\\catcode`z=13\\catcode`Z=13\\let Z=a\\uppercase{azb}")
    assert collector.getString() == "AaB "
    collector.parse("\\uppercase{a\\lowercase{Bc}}")
    assert collector.getString() == "Abc "
    collector.parse("\\uppercase{a\\def\\a{Bc}}\\a")
    assert collector.getString() == "ABC"


def test_parpar(parser):
    parser.parse("\\toks0={#}")
    toks0 = parser.state.toks[0]
    assert len(toks0) == 1
    assert toks0[0].catcode == CATCODE.PARAMETER


def test_toks_token_expand_keeps_token_alias(parser):
    t0 = CommandToken("\\bgroup")
    t0.definition = Token("{", CATCODE.BEGIN_GROUP)

    def next_token():
        if getattr(next_token, "seen", False):
            return None
        next_token.seen = True
        return t0

    parser.token = next_token
    t, expanded = toks.token_expand(parser)
    assert expanded is None
    assert t is t0


def test_page_mark_commands_expand(collector):
    collector.state.parameters["topmark"] = toToks("AB")
    collector.state.parameters["firstmark"] = toToks("CD")
    collector.state.parameters["botmark"] = toToks("EF")
    collector.parse("\\topmark\\firstmark\\botmark")
    assert collector.getString() == "ABCDEF"


def test_page_break_updates_marks(parser):
    parser.parse("\\vsize=10pt\\topskip=0pt")
    main = parser.lists[0]
    main.append(_test_hbox(parser, height=6, depth=0))
    main.append(nd.Mark(toToks("A")))
    main.append(nd.Glue(glue.Glue(4), None))
    main.append(_test_hbox(parser, height=6, depth=0))
    main.append(nd.Mark(toToks("B")))
    parser.end()
    pages = parser.shipout.pages
    assert len(pages) == 2
    assert "".join(t.name for t in parser.state.parameters["topmark"]) == "A"
    assert "".join(t.name for t in parser.state.parameters["firstmark"]) == "B"
    assert "".join(t.name for t in parser.state.parameters["botmark"]) == "B"


def test_page_break_nonzero_marks_require_etex(parser):
    parser.parse("\\vsize=10pt\\topskip=0pt")
    main = parser.lists[0]
    mark = nd.Mark(toToks("X"))
    mark.index = 2
    main.append(_test_hbox(parser, height=6, depth=0))
    main.append(mark)
    with pytest.raises(AssertionError):
        parser.end()
