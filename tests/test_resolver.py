from pathlib import Path

import pytest
from pytex import texlive
from pytex.parser import Parser
from pytex.resolver import InMemoryTextFile
import os


def test_resolve_read(parser):
    f = parser.resolver.openIn(str(Path(__file__).resolve()))
    assert f is not None
    f.close()
    f = parser.resolver.openIn("plain", "source")
    assert f is not None
    f.close()


def test_parser_resolver_is_local():
    first = Parser()
    second = Parser()
    assert first.resolver is not second.resolver
    first.resolver.in_memory_files["local.tex"] = InMemoryTextFile("abc")
    assert "local.tex" not in second.resolver.in_memory_files


def test_project_dir_allows_absolute_source_paths(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.tex"
    source.write_text("hello")
    parser = Parser(project_dir=str(project))
    f = parser.resolver.openIn(str(source), "source")
    assert f is not None
    assert f.read() == "hello"
    f.close()


def test_project_dir_rejects_source_paths_outside_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "secret.tex"
    outside.write_text("secret")
    parser = Parser(project_dir=str(project))
    with pytest.raises(ValueError, match="outside project directory"):
        parser.resolver.openIn(str(outside), "source")
    with pytest.raises(ValueError, match="outside project directory"):
        parser.resolver.openIn("../secret", "source")


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


def test_texlive_resolver_instances_share_directory_cache(tmp_path, monkeypatch):
    texmf = tmp_path / "2026" / "texmf-dist"
    plain = texmf / "tex" / "plain" / "base"
    plain.mkdir(parents=True)
    (plain / "foo.tex").write_text("foo")
    (plain / "bar.tex").write_text("bar")
    first = texlive.TexliveResolver(texlive_path=str(tmp_path), format="plain")
    second = texlive.TexliveResolver(texlive_path=str(tmp_path), format="plain")
    walk_calls = []
    original_walk = texlive.os.walk

    def counting_walk(path):
        walk_calls.append(path)
        yield from original_walk(path)

    monkeypatch.setattr(texlive.os, "walk", counting_walk)
    f = first.openIn("foo", "source")
    assert f is not None
    assert f.read() == "foo"
    f.close()
    f = second.openIn("bar", "source")
    assert f is not None
    assert f.read() == "bar"
    f.close()
    plain_root = os.path.join(str(texmf), "tex", "plain")
    assert walk_calls.count(plain_root) == 1
