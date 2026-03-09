import pytest
from pytex import texlive
from pytex import resolver
from pytex import token
from pytex import font
from pytex import lists
from pytex import node as nd
from pytex import paragraph
import json
import io


@pytest.fixture()
def plain_dump(parser):
    dump = parser.resolver.openOut('plain', "dump")
    plain = parser.resolver.openIn('plain', "source")
    assert plain is not None
    parser.parse(plain)
    assert parser.state.parameters["currentfont"].tfm.name != "nullfont"
    data = parser.dump()
    dump.write(data)
    dump.close()
    return parser.resolver.in_memory_files["plain.json"].content


@pytest.fixture()
def plain(parser, plain_dump):
    format = io.StringIO(plain_dump)
    parser.load(format)
    format.close()
    return parser

def test_plain(plain):
    plain.parse(r"Hello, world! $\int_0^1 f(x) dx$\end")
    # the content of the log file
    top = plain.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    hlist = next(node for node in top if isinstance(node, paragraph.Paragraph))
    # The stored paragraph keeps raw characters; ligatures/kerns are formed later.
    assert len(hlist.list) == 18
    assert hlist.list[-3].node_type == nd.NODE_TYPE.MATH


def test_plain_preserves_fontchar(plain):
    current = plain.state.parameters["currentfont"]
    assert current.name == "\\tenrm"
    assert current.fontchar["hyphenchar"] == 45
    assert current.hyphenChar() is not None
    assert current.hyphenChar().char == "-"
