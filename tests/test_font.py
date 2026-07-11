from pathlib import Path

import pytest
from pytex import font_backend
from pytex import opentype
from pytex import texlive
from pytex.parser import Parser


class _SearchBackend(font_backend.FontBackend):
    kind = "search-test"

    def __init__(self, name):
        self._name = name

    @property
    def name(self):
        return self._name


class _UnsupportedSearchBackend(_SearchBackend):
    @classmethod
    def load(cls, parser, name):
        return cls(name)


class _SupportedSearchBackend(_SearchBackend):
    @classmethod
    def load(cls, parser, name):
        return cls(name)


def test_font_search_prefers_registered_supported_class(parser, monkeypatch):
    monkeypatch.setattr(
        font_backend,
        "_backend_classes",
        [_UnsupportedSearchBackend, _SupportedSearchBackend],
    )
    monkeypatch.setattr(font_backend, "_system_font_backend_cache", {})

    unrestricted = parser.loadFontBackend("demo.font", kind="search-test")
    parser.registerSupportedFontClasses(_SupportedSearchBackend)
    restricted = parser.loadFontBackend("demo.font", kind="search-test")

    assert isinstance(unrestricted, _UnsupportedSearchBackend)
    assert isinstance(restricted, _SupportedSearchBackend)


def test_font_search_converts_only_unsupported_result(parser, monkeypatch):
    monkeypatch.setattr(font_backend, "_backend_classes", [_UnsupportedSearchBackend])
    monkeypatch.setattr(
        font_backend,
        "_font_converters",
        [
            (
                _UnsupportedSearchBackend,
                _SupportedSearchBackend,
                lambda parser, backend: _SupportedSearchBackend(backend.name),
            )
        ],
    )
    monkeypatch.setattr(font_backend, "_system_font_backend_cache", {})
    parser.registerSupportedFontClasses(_SupportedSearchBackend)

    backend = parser.loadFontBackend("demo.font", kind="search-test")

    assert isinstance(backend, _SupportedSearchBackend)


def test_read_font(cmr10):
    assert cmr10.equitable["\\f"].backend.kind == "tfm"
    assert cmr10.equitable["\\f"].backend.name == 'cmr10'
    assert cmr10.equitable["\\f"].at == 10.0
    assert cmr10.parameters["currentfont"].backend.name == 'cmr10'
    assert cmr10.parameters["currentfont"].at == 10.0


def test_read_font_scaled(parser):
    parser.parse('\\font\\f=cmr10 scaled 500')
    assert parser.equitable["\\f"].backend.kind == "tfm"
    assert parser.equitable["\\f"].backend.name == 'cmr10'
    assert parser.equitable["\\f"].at == 5.0


def test_read_font_at(parser):
    parser.parse('\\font\\f=cmr10 at 20pt')
    assert parser.equitable["\\f"].backend.name == 'cmr10'
    assert parser.equitable["\\f"].at == 20.0


def test_read_grouped_tfm_font_name(parser):
    parser.parse('\\font\\f={cmr10} at 20pt')
    assert parser.equitable["\\f"].backend.kind == "tfm"
    assert parser.equitable["\\f"].backend.name == 'cmr10'
    assert parser.equitable["\\f"].at == 20.0


def test_load_font_backend(parser):
    backend = parser.loadFontBackend("cmr10")
    assert backend.kind == "tfm"
    assert backend.name == "cmr10"
    assert backend.design_size == 10.0


def test_font_search_converts_type1_tfm_backend_to_truetype(parser):
    source = parser.loadFontBackend("cmr10")
    if source.pfb_file is None:
        pytest.skip("cmr10 Type 1 font not found")
    source_a = source.glyphInfo("A")
    source_f = source.glyphInfo("f")

    parser.registerSupportedFontClasses(opentype.TrueTypeBackend)
    converted = parser.loadFontBackend("cmr10")

    assert isinstance(converted, opentype.Type1TrueTypeBackend)
    assert converted.source_backend.name == source.name
    assert "glyf" in converted.font
    assert "loca" in converted.font
    assert "CFF " not in converted.font
    assert converted.font.getBestCmap()[ord("A")] == "A"
    assert converted.font.getBestCmap()[ord("<")] == "exclamdown"
    assert converted.design_size == source.design_size
    assert converted.checksum == source.checksum
    assert converted.fontdimen == source.fontdimen
    assert converted.glyphInfo("A").width == source_a.width
    assert converted.glyphInfo("A").height == source_a.height
    assert converted.glyphInfo("A").glyph_name == "A"
    assert converted.glyphInfo("f").program is converted.source_backend.glyphInfo("f").program
    assert converted.glyphInfo("f").program.keys() == source_f.program.keys()


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
    assert backend.dvi_name is None
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
    font = parser.equitable["\\f"]
    assert font.backend.kind == "opentype"
    assert font.backend.name == "lmroman10-regular.otf"
    assert float(font["A"].width) > 7.0


def test_read_system_opentype_font_name(parser, monkeypatch):
    handle = parser.resolver.openIn("lmroman10-regular.otf", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    path = handle.name
    handle.close()

    @classmethod
    def fake_system_path(cls, name):
        return (path, 0) if name == "LM Roman 10 Regular" else None

    monkeypatch.setattr(opentype.OpenTypeBackend, "_systemFontPath", fake_system_path)
    parser.parse("\\font\\f={LM Roman 10 Regular} at 10pt \\f A")
    font = parser.equitable["\\f"]
    assert font.backend.kind == "opentype"
    assert font.backend.name == "LM Roman 10 Regular"
    assert font.backend.path == path
    assert float(font["A"].width) > 7.0


def test_opentype_math_variants_populate_next_larger_and_assembly(parser):
    path = Path(__file__).resolve().parents[1] / ".cache" / "fonts" / "STIXTwoMath-input.ttf"
    if not path.exists():
        pytest.skip("STIXTwoMath input TTF not available")
    try:
        backend = parser.loadFontBackend(str(path))
    except FileNotFoundError:
        pytest.skip("STIXTwoMath input TTF not available")
    info = backend.glyphInfo("∫")
    assert info is not None
    assert info.next_larger is not None
    larger = backend.glyphInfo(info.next_larger)
    assert larger is not None
    assert float(larger.height + larger.depth) > float(info.height + info.depth)
    assert info.assembly is not None
    assert info.assembly.top is not None
    assert info.assembly.repeat is not None
    bracket = backend.glyphInfo("[")
    assert bracket is not None and bracket.assembly is not None
    assert chr(bracket.assembly.top) == "⎡"
    assert chr(bracket.assembly.bottom) == "⎣"
    assert chr(bracket.assembly.repeat) == "⎢"
    assert [part.glyph for part in bracket.assembly.parts[:3]] == ["⎡", "⎢", "⎣"]


def test_missing_character_is_logged_and_omitted(cmr10):
    cmr10.parse('\\setbox0=\\hbox{A\\char"53EF B}')
    chars = [node.char for node in cmr10.box[0].list if hasattr(node, "char")]
    assert chars == ["A", "B"]
    assert "Missing character: There is no 可 (U+53EF) in font cmr10!" in cmr10.logContent()


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
    assert collector.equitable["\\f"].fontchar["hyphenchar"] == 45
    collector.parse('\\the\\hyphenchar\\f')
    assert collector.getString() == '45'
    collector.parse('\\defaulthyphenchar=-1 \\relax\\font\\f=cmr10')
    assert collector.equitable["\\f"].fontchar["hyphenchar"] == -1
    collector.parse('\\the\\hyphenchar\\f')
    assert collector.getString() == '-1'


def test_skewchar(collector):
    collector.parse('\\font\\f=cmr10 \\global\\skewchar\\f=45')
    assert collector.equitable["\\f"].fontchar["skewchar"] == 45
    collector.parse('\\the\\skewchar\\f')
    assert collector.getString() == '45'
    collector.parse('\\defaultskewchar=127 \\relax\\font\\f=cmr10')
    assert collector.equitable["\\f"].fontchar["skewchar"] == 127
    collector.parse('\\the\\skewchar\\f')
    assert collector.getString() == '127'


def test_fontchar_internal_integer_reads_use_target_path(parser):
    parser.parse('\\font\\f=cmr10 \\hyphenchar\\f=45 \\count0=\\hyphenchar\\f \\count1=\\skewchar\\f')
    assert parser.count[0] == 45
    assert parser.count[1] == parser.equitable["\\f"].fontchar["skewchar"]


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


def test_fontdimen_read_past_defined_params_returns_zero(collector):
    collector.parse("\\font\\f=cmr10 \\the\\fontdimen193\\f")
    assert collector.getString() == "0.0pt"


def test_fontdimen_write_past_defined_params_extends_without_format(collector):
    collector.parse("\\font\\f=cmr10 \\fontdimen193\\f=1pt \\the\\fontdimen193\\f")
    assert collector.getString() == "1.0pt"
