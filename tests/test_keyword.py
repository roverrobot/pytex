import pytest
from pytex.token import CATCODE

def test_read_keyword(parser):
    parser.readFrom(" test  ")
    k = parser.readKeyword({"tes"})
    assert k == "tes"
    t = parser.token_expand()
    assert t.name == "t"
    parser.readFrom(" Test  ")
    k = parser.readKeyword({"test", "false"})
    assert k == "test"
    t = parser.token_expand()
    assert t is not None
    assert t.catcode == CATCODE.SPACE
    parser.readFrom(" tes  ")
    k = parser.readKeyword({"test", "false"})
    assert k is None
    t = parser.token_expand()
    assert t is not None
    assert t.name == "t"
