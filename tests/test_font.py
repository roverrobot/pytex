import pytest
from pytex import texlive


def test_read_font(cmr10):
    assert cmr10.state.equitable["\\f"].tfm.name == 'cmr10'
    assert cmr10.state.equitable["\\f"].at == 10.0
    assert cmr10.state.parameters["currentfont"].tfm.name == 'cmr10'
    assert cmr10.state.parameters["currentfont"].at == 10.0


def test_read_font_scaled(parser):
    parser.parse('\\font\\f=cmr10 scaled 500')
    assert parser.state.equitable["\\f"].tfm.name == 'cmr10'
    assert parser.state.equitable["\\f"].at == 5.0


def test_read_font_at(parser):
    parser.parse('\\font\\f=cmr10 at 20pt')
    assert parser.state.equitable["\\f"].tfm.name == 'cmr10'
    assert parser.state.equitable["\\f"].at == 20.0


def test_read_font_error(parser):
    try:
        parser.parse('\\font\\test=no_such_font!')
        assert False, "Expected ValueError"
    except FileNotFoundError as e:
        pass


def test_hyphenchar(collector):
    collector.parse('\\font\\f=cmr10 \\global\\hyphenchar\\f=45')
    assert collector.state.equitable["\\f"].fontchar["hyphenchar"] == 45
    collector.parse('\\the\\hyphenchar\\f')
    assert collector.getString() == '45'


def test_skewchar(collector):
    collector.parse('\\font\\f=cmr10 \\global\\skewchar\\f=45')
    assert collector.state.equitable["\\f"].fontchar["skewchar"] == 45
    collector.parse('\\the\\skewchar\\f')
    assert collector.getString() == '45'


def test_fontname(collector):
    collector.parse("\\font\\f=cmr10 \\fontname\\f")
    assert collector.getString() == "nullfont"
    collector.parse("\\font\\f=cmr10 \\relax\\fontname\\f")
    assert collector.getString() == "cmr10"
