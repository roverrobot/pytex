import pytest
from pytex import texlive
from pytex import token
from pytex import font
from pytex import lists
from pytex import node as nd
from pytex import paragraph
from pytex import mmode
import io


def _raw_nodes(vlist):
    return vlist.rawNodes() if hasattr(vlist, "rawNodes") else getattr(vlist, "raw", vlist)


def _source_nodes(vlist, cls):
    seen = set()
    out = []
    nodes = vlist.concreteNodes() if hasattr(vlist, "concreteNodes") else list(vlist)
    for node in nodes:
        source = getattr(node, "source", None)
        if not isinstance(source, cls):
            continue
        key = id(source)
        if key in seen:
            continue
        seen.add(key)
        out.append(source)
    return out


@pytest.fixture()
def plain_dump(parser):
    dump = parser.resolver.openOut('plain', "dump")
    plain = parser.resolver.openIn('plain', "source")
    assert plain is not None
    parser.parse(plain)
    assert parser.parameters["currentfont"].backend.name != "nullfont"
    data = parser.dump()
    dump.write(data)
    dump.close()
    return parser.resolver.in_memory_files["plain.pfmt"].content


@pytest.fixture()
def plain(parser, plain_dump):
    format = io.BytesIO(plain_dump)
    parser.load(format)
    format.close()
    return parser

def test_plain(plain):
    plain.parse(r"Hello, world! $\int_0^1 f(x) dx$\par")
    # the content of the log file
    top = plain.lists[-1]
    assert top.type == lists.LISTTYPE.VERTICAL
    hlist = _source_nodes(top, paragraph.Paragraph)[0]
    # Paragraphs now keep raw input separately from the live concrete list.
    assert len(hlist.raw) == 18
    assert any(node.node_type == nd.NODE_TYPE.MATH for node in hlist.list)
    assert not any(isinstance(node, mmode.InlineMathNode) for node in hlist.list)
    assert isinstance(hlist.raw[-3], mmode.InlineMathNode)


def test_plain_preserves_fontchar(plain):
    current = plain.parameters["currentfont"]
    assert current.name == "\\tenrm"
    assert current.fontchar["hyphenchar"] == 45
    assert current.hyphenChar() is not None
    assert current.hyphenChar().char == "-"
