import pytest
from pytex import tfm
from pytex import texlive
from pytex.parser import Parser


def test_read_tfm():
    resolver = texlive.TexliveResolver()
    tfm_file = resolver.openIn("cmr10.tfm")
    try:
        tfm_data = tfm.TFM("cmr10", tfm_file)
        assert tfm_data.header.size == 10.0
    except FileNotFoundError:
        pytest.skip("cmr10.tfm not found")


def test_nullfont(parser):
    nullfont = parser.tfm["nullfont"]
    assert nullfont.header.checksum == 0
    assert nullfont.header.size == 0.0
    assert nullfont.ec == 0
    assert nullfont.bc == 0
    c = nullfont.char_info[0]
    assert c.width == 0
    assert c.height == 0
    assert c.depth == 0
    assert c.italic == 0
    assert c.program == None
    assert c.chain == None
    assert c.extend == None
    assert nullfont.param == [0] * 7


def test_system_tfm_cache_shared_between_parsers():
    p1 = Parser()
    p2 = Parser()
    try:
        t1 = p1.loadTFM("cmr10")
        t2 = p2.loadTFM("cmr10")
    except FileNotFoundError:
        pytest.skip("cmr10.tfm not found")
    assert t1 is t2
