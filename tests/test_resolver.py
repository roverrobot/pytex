import pytest
from pytex import texlive
from pytex.resolver import InMemoryTextFile
import os


def test_resolve_read(parser):
    f = parser.resolver.openIn("tests/test_resolver.py")
    assert f is not None
    f.close()
    f = parser.resolver.openIn("plain", "source")
    assert f is not None
    f.close()


def test_read_file_name(parser):
    parser.readFrom("\\relax abc.def g")
    name = parser.readFileName()
    assert name == "abc.def"
    t = parser.token()
    assert t.name == "g"
    parser.readFrom("abc.def{a}")
    name = parser.readFileName()
    assert name == "abc.def{a}"
    parser.readFrom("abc.def}")
    name = parser.readFileName()
    assert name == "abc.def"
    t = parser.token()
    assert t.name == "}"

        
def test_in_memory_file(parser):
    parser.resolver.in_memory_files["test.tex"] = InMemoryTextFile("abc")
    f = parser.resolver.openIn("test.tex", "source")
    assert f is not None
    assert f.read() == "abc"
    f.close()
    f = parser.resolver.openIn("test", "source")
    assert f is not None
    assert f.read() == "abc"
    f.close()
