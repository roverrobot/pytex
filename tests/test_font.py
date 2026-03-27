import pytest
from pytex import opentype
from pytex import texlive
from pytex.parser import Parser


def test_read_font(cmr10):
    assert cmr10.state.equitable["\\f"].backend.kind == "tfm"
    assert cmr10.state.equitable["\\f"].backend.name == 'cmr10'
    assert cmr10.state.equitable["\\f"].at == 10.0
    assert cmr10.state.parameters["currentfont"].backend.name == 'cmr10'
    assert cmr10.state.parameters["currentfont"].at == 10.0


def test_read_font_scaled(parser):
    parser.parse('\\font\\f=cmr10 scaled 500')
    assert parser.state.equitable["\\f"].backend.kind == "tfm"
    assert parser.state.equitable["\\f"].backend.name == 'cmr10'
    assert parser.state.equitable["\\f"].at == 5.0


def test_read_font_at(parser):
    parser.parse('\\font\\f=cmr10 at 20pt')
    assert parser.state.equitable["\\f"].backend.name == 'cmr10'
    assert parser.state.equitable["\\f"].at == 20.0


def test_load_font_backend(parser):
    backend = parser.loadFontBackend("cmr10")
    assert backend.kind == "tfm"
    assert backend.name == "cmr10"
    assert backend.design_size == 10.0


def test_system_font_backend_cache_shared_between_parsers():
    p1 = Parser()
    p2 = Parser()
    try:
        b1 = p1.loadFontBackend("cmr10")
        b2 = p2.loadFontBackend("cmr10")
    except FileNotFoundError:
        pytest.skip("cmr10 font not found")
    assert b1 is b2


def test_load_opentype_font_backend(parser):
    try:
        backend = parser.loadFontBackend("lmroman10-regular.otf")
    except FileNotFoundError:
        pytest.skip("lmroman10-regular.otf not found")
    assert backend.kind == "opentype"
    assert backend.name == "lmroman10-regular.otf"
    assert backend.dvi_name == "lmroman10-regular"
    assert backend.design_size == 10.0
    a = backend.glyphInfo("A")
    assert a is not None
    assert float(a.width) > 0.7
    assert float(backend.fontdimen[4]) > 0
    assert float(backend.fontdimen[5]) == 1.0


def test_read_opentype_font(parser):
    try:
        parser.parse("\\font\\f=lmroman10-regular.otf at 10pt \\f A")
    except FileNotFoundError:
        pytest.skip("lmroman10-regular.otf not found")
    font = parser.state.equitable["\\f"]
    assert font.backend.kind == "opentype"
    assert font.backend.name == "lmroman10-regular.otf"
    assert float(font["A"].width) > 7.0


def test_font_optional_keyword_does_not_expand_existing_macro_name(collector):
    try:
        collector.parse("\\def\\a{X}\\font\\a=lmroman10-regular.otf \\a A")
    except FileNotFoundError:
        pytest.skip("lmroman10-regular.otf not found")
    assert collector.getString().strip() == "A"
    assert collector.lookup("\\a").backend.name == "lmroman10-regular.otf"


def test_font_target_is_temporarily_nullfont_while_scanning_size(collector):
    collector.parse("\\def\\b{99pt}\\font\\c=cmr10 at \\b")
    assert collector.lookup("\\c").at == 99.0
    collector.parse("\\font\\a=cmr10 at \\fontdimen6\\a")
    assert collector.lookup("\\a").at == 0.0


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
    collector.parse('\\defaulthyphenchar=-1 \\relax\\font\\f=cmr10')
    assert collector.state.equitable["\\f"].fontchar["hyphenchar"] == -1
    collector.parse('\\the\\hyphenchar\\f')
    assert collector.getString() == '-1'


def test_skewchar(collector):
    collector.parse('\\font\\f=cmr10 \\global\\skewchar\\f=45')
    assert collector.state.equitable["\\f"].fontchar["skewchar"] == 45
    collector.parse('\\the\\skewchar\\f')
    assert collector.getString() == '45'
    collector.parse('\\defaultskewchar=127 \\relax\\font\\f=cmr10')
    assert collector.state.equitable["\\f"].fontchar["skewchar"] == 127
    collector.parse('\\the\\skewchar\\f')
    assert collector.getString() == '127'


def test_fontname(collector):
    collector.parse("\\font\\f=cmr10 \\fontname\\f")
    assert collector.getString() == "nullfont"
    collector.parse("\\font\\f=cmr10 \\relax\\fontname\\f")
    assert collector.getString() == "cmr10"


def test_textfont_assignment_is_local_to_group(collector):
    collector.parse("\\font\\a=cmr10 \\font\\b=cmr12 \\textfont0=\\a")
    collector.parse("{\\textfont0=\\b\\fontname\\textfont0}")
    assert collector.getString().strip() == "cmr12"
    collector.parse("\\fontname\\textfont0")
    assert collector.getString().strip() == "cmr10"


def test_fontdimen(collector):
    collector.parse("\\font\\f=cmr10 \\fontdimen1\\f10pt \\the\\fontdimen1\\f")
    assert collector.getString() == "10.0pt"
