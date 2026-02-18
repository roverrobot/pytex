import io
import json

from pytex.parser import Parser
from pytex import serialization
from pytex.token import CATCODE


def _set_common_catcodes(parser):
    parser.state.catcode[ord("{")] = CATCODE.BEGIN_GROUP
    parser.state.catcode[ord("}")] = CATCODE.END_GROUP
    parser.state.catcode[ord("$")] = CATCODE.MATH_SHIFT
    parser.state.catcode[ord("&")] = CATCODE.ALIGNMENT_TAB
    parser.state.catcode[ord("#")] = CATCODE.PARAMETER
    parser.state.catcode[ord("^")] = CATCODE.SUPERSCRIPT
    parser.state.catcode[ord("_")] = CATCODE.SUBSCRIPT


def test_hyphenator_dump_load_roundtrip(parser):
    parser.parse("\\hyphenation{tech-ni-cal}")
    parser.parse("\\language 1 \\hyphenation{micro-wave}")
    parser.hyphenator.setLanguage(parser.state.parameters["language"])
    parser.hyphenator._insertPattern(
        parser.hyphenator.pattern_trie,
        "abc",
        [0, 1, 0, 2],
    )

    data = parser.dump()

    loaded = Parser()
    _set_common_catcodes(loaded)
    loaded.load(io.StringIO(data))

    assert loaded.hyphenator.dicts[0]["technical"] == [4, 6]
    assert loaded.hyphenator.dicts[1]["microwave"] == [5]
    assert loaded.hyphenator.language == 1
    assert loaded.hyphenator.words is loaded.hyphenator.dicts[1]
    assert loaded.hyphenator._dumpPatternTrie(loaded.hyphenator.pattern_tries[1]) == [
        ["abc", [0, 1, 0, 2]]
    ]


def test_parser_load_backward_compatible_state_only_dump(parser):
    parser.parse("\\count0=123")
    old_style = json.dumps(serialization.serialize(parser.state.dump()))

    loaded = Parser()
    _set_common_catcodes(loaded)
    loaded.load(io.StringIO(old_style))

    assert loaded.state.count[0] == 123


def test_patterns_parsed_into_trie(parser):
    parser.parse("\\patterns{a1bc .T2e}")
    got = sorted(parser.hyphenator._dumpPatternTrie(parser.hyphenator.pattern_tries[0]))
    assert got == sorted(
        [
            ["abc", [0, 1, 0, 0]],
            [".te", [0, 0, 2, 0]],
        ]
    )


def test_patterns_duplicate_uses_latter_weights(parser):
    parser.parse("\\patterns{a3b4c a1bc}")
    got = parser.hyphenator._dumpPatternTrie(parser.hyphenator.pattern_tries[0])
    assert got == [["abc", [0, 1, 0, 0]]]
    assert "duplicate hyphenation pattern 'abc'" in parser.logContent()


def test_patterns_are_language_scoped(parser):
    parser.parse("\\patterns{a1b}")
    parser.parse("\\language 5 \\patterns{c2d}")
    root0 = parser.hyphenator._dumpPatternTrie(parser.hyphenator.pattern_tries[0])
    root5 = parser.hyphenator._dumpPatternTrie(parser.hyphenator.pattern_tries[5])
    assert root0 == [["ab", [0, 1, 0]]]
    assert root5 == [["cd", [0, 2, 0]]]
