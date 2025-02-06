import pytest
from pytex import tfm
from pytex import texlive


def test_read_tfm():
    resolver = texlive.TexliveResolver()
    tfm_file = resolver.openIn("cmr10.tfm")
    try:
        tfm_data = tfm.TFM("cmr10", tfm_file)
        assert tfm_data.header.size == 10.0
    except FileNotFoundError:
        pytest.skip("cmr10.tfm not found")


def test_nullfont(parser):
    nullfont = parser.state.globals["tfm"]["nullfont"]
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
