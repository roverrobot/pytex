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
    parser.hyphenator.setLanguage(1)
    parser.parse("\\hyphenation{micro-wave}")
    parser.hyphenator._insertPattern(
        parser.hyphenator.pattern_tries[1],
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
