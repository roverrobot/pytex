import io
import zipfile

from pytex.parser import Parser
from pytex.token import CATCODE


def _set_common_catcodes(parser):
    parser.catcode[ord("{")] = CATCODE.BEGIN_GROUP
    parser.catcode[ord("}")] = CATCODE.END_GROUP
    parser.catcode[ord("$")] = CATCODE.MATH_SHIFT
    parser.catcode[ord("&")] = CATCODE.ALIGNMENT_TAB
    parser.catcode[ord("#")] = CATCODE.PARAMETER
    parser.catcode[ord("^")] = CATCODE.SUPERSCRIPT
    parser.catcode[ord("_")] = CATCODE.SUBSCRIPT


def test_hyphenator_dump_load_roundtrip(parser):
    parser.parse("\\hyphenation{tech-ni-cal}")
    parser.parse("\\language 1 \\hyphenation{micro-wave}")
    parser.hyphenator.setLanguage(parser.parameters["language"])
    parser.hyphenator._insertPattern(
        parser.hyphenator.pattern_trie,
        "abc",
        [0, 1, 0, 2],
    )

    data = parser.dump()

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert all(
            entry.compress_type == zipfile.ZIP_DEFLATED
            for entry in archive.infolist()
        )

    loaded = Parser()
    _set_common_catcodes(loaded)
    loaded.load(io.BytesIO(data))

    assert loaded.formatfile is not None
    assert loaded.hyphenator.language == 1
    loaded.hyphenator.setLanguage(0)
    assert loaded.hyphenator.dicts[0]["technical"] == [4, 6]
    loaded.hyphenator.setLanguage(1)
    assert loaded.hyphenator.dicts[1]["microwave"] == [5]
    assert loaded.hyphenator.words is loaded.hyphenator.dicts[1]
    assert loaded.hyphenator._dumpPatternTrie(loaded.hyphenator.pattern_tries[1]) == [
        ["abc", [0, 1, 0, 2]]
    ]


def test_hyphenator_container_dump_load_is_lazy(parser, monkeypatch):
    parser.parse("\\count0=123")
    parser.parse("\\patterns{a1b}")
    parser.parse("\\language 1 \\hyphenation{mi-cro-wave}\\patterns{c3d}")
    data = parser.dump()

    loaded = Parser()
    _set_common_catcodes(loaded)
    calls = []
    original = loaded.hyphenator._insertPattern

    def tracking_insert(root, letters, weights):
        calls.append(letters)
        return original(root, letters, weights)

    monkeypatch.setattr(type(loaded.hyphenator), "_insertPattern", staticmethod(tracking_insert))
    loaded.load(io.BytesIO(data))

    assert loaded.count[0] == 123
    assert loaded.formatfile is not None
    assert loaded.hyphenator.language == 1
    assert calls == []

    loaded.hyphenator.setLanguage(1)
    assert loaded.hyphenator.hyphenate("cd") == [1]
    assert calls == ["cd"]
    assert loaded.hyphenator.words["microwave"] == [2, 5]

    loaded.hyphenator.setLanguage(0)
    assert loaded.hyphenator.hyphenate("ab") == [1]
    assert calls == ["cd", "ab"]

def test_patterns_parsed_into_trie(parser):
    parser.parse("\\patterns{a1bc .T2e}")
    got = sorted(parser.hyphenator._dumpPatternTrie(parser.hyphenator.pattern_tries[0]))
    assert got == sorted(
        [
            ["abc", [0, 1, 0, 0]],
            [".te", [0, 0, 2, 0]],
        ]
    )


def test_patterns_duplicate_merges_weights_silently(parser):
    parser.parse("\\patterns{a3b4c a1bc ab5c}")
    got = parser.hyphenator._dumpPatternTrie(parser.hyphenator.pattern_tries[0])
    assert got == [["abc", [0, 3, 5, 0]]]
    assert "duplicate hyphenation pattern 'abc'" not in parser.logContent()


def test_patterns_are_language_scoped(parser):
    parser.parse("\\patterns{a1b}")
    parser.parse("\\language 5 \\patterns{c2d}")
    root0 = parser.hyphenator._dumpPatternTrie(parser.hyphenator.pattern_tries[0])
    root5 = parser.hyphenator._dumpPatternTrie(parser.hyphenator.pattern_tries[5])
    assert root0 == [["ab", [0, 1, 0]]]
    assert root5 == [["cd", [0, 2, 0]]]


def test_pattern_hyphenation_basic(parser):
    parser.parse("\\patterns{a1b}")
    assert parser.hyphenator.hyphenate("ab") == [1]
    assert parser.hyphenator.hyphenate("zz") == []


def test_pattern_hyphenation_uses_max_weights(parser):
    parser.parse("\\patterns{ab1c b2c}")
    # both patterns hit boundary between b and c, max is 2 (even) -> no break
    assert parser.hyphenator.hyphenate("abc") == []
    parser.parse("\\patterns{b3c}")
    # now max becomes 3 (odd) -> break at position 2
    assert parser.hyphenator.hyphenate("abc") == [2]


def test_pattern_hyphenation_merges_duplicate_letter_patterns(parser):
    parser.parse("\\patterns{a1bc ab3c}")
    assert parser.hyphenator.hyphenate("abc") == [1, 2]


def test_pattern_hyphenation_respects_boundary_dot(parser):
    parser.parse("\\patterns{.a1}")
    # start-of-word-only pattern
    assert parser.hyphenator.hyphenate("ab") == [1]
    assert parser.hyphenator.hyphenate("ba") == []


def test_hyphenation_exceptions_precede_patterns(parser):
    parser.parse("\\patterns{a1b}")
    parser.parse("\\hyphenation{ab-cd}")
    assert parser.hyphenator.hyphenate("abcd") == [2]


def test_hyphenator_cache_invalidated_by_patterns(parser):
    parser.parse("\\patterns{a1b}")
    assert parser.hyphenator.hyphenate("ab") == [1]
    parser.parse("\\patterns{a2b}")
    assert parser.hyphenator.hyphenate("ab") == []


def test_hyphenator_cache_invalidated_by_exceptions(parser):
    parser.parse("\\patterns{a1b}")
    assert parser.hyphenator.hyphenate("ab") == [1]
    parser.parse("\\hyphenation{ab}")
    assert parser.hyphenator.hyphenate("ab") == []
