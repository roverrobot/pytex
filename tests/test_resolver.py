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


def test_texlive_resolver_caches_directory_walks(tmp_path, monkeypatch):
    texmf = tmp_path / "2026" / "texmf-dist"
    plain = texmf / "tex" / "plain" / "base"
    plain.mkdir(parents=True)
    (plain / "foo.tex").write_text("foo")
    (plain / "bar.tex").write_text("bar")
    resolver = texlive.TexliveResolver(texlive_path=str(tmp_path), format="plain")
    walk_calls = []
    original_walk = texlive.os.walk

    def counting_walk(path):
        walk_calls.append(path)
        yield from original_walk(path)

    monkeypatch.setattr(texlive.os, "walk", counting_walk)
    f = resolver.openIn("foo", "source")
    assert f is not None
    assert f.read() == "foo"
    f.close()
    f = resolver.openIn("bar", "source")
    assert f is not None
    assert f.read() == "bar"
    f.close()
    plain_root = os.path.join(str(texmf), "tex", "plain")
    assert walk_calls.count(plain_root) == 1
