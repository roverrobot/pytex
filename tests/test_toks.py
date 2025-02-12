import pytest


def test_read_toks(parser):
    parser.readFrom("{abcd}")
    k = parser.readBalancedText(expand=False)
    # {, a, b, c, d, }, space
    assert len(k) == 7
    assert k[4].name == "d"
    

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
    collector.parse("\\aftergroup a\\aftergroup b{\\count0=1}")
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
