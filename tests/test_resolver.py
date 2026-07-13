from pathlib import Path
import subprocess
import sys

import pytest
from reportlab.pdfgen import canvas
from pytex import texlive
from pytex import pipes
from pytex import formatfile
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


@pytest.mark.parametrize(
    "format_name",
    [
        "plain-xetex",
        "eplain-xetex",
        "latex-xetex",
        "plain-pdftex",
        "eplain-pdftex",
        "latex-pdftex",
    ],
)
def test_bundled_standard_format_is_available(tmp_path, format_name):
    engine = format_name.rsplit("-", 1)[1]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import importlib; "
            "from pytex import etex, opentype, texlive; "
            f"importlib.import_module('pytex.{engine}'); "
            "from pytex.parser import Parser; "
            "from pytex import formatfile; "
            "parser = Parser(); "
            f"f = parser.resolver.openIn('{format_name}', 'dump'); "
            "assert f is not None; "
            "data = f.read(); f.close(); "
            "assert formatfile.isContainer(data); "
            "parser.load(__import__('io').BytesIO(data)); "
            "assert parser.formatfile is not None; "
            "parser.close()",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_bundled_format_lookup_works_with_namespace_package_directory(tmp_path):
    (tmp_path / "pytex").mkdir()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pytex.parser import Parser; "
            "f = Parser().resolver.openIn('latex-xetex', 'dump'); "
            "assert f is not None; f.close()",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_local_standard_format_overrides_bundled_copy(parser, tmp_path):
    local = tmp_path / "plain-xetex.pfmt"
    local.write_bytes(b"project format")
    f = parser.resolver.openIn("plain-xetex", "dump")
    assert f is not None
    assert f.read() == b"project format"
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


def test_project_dir_writes_relative_output_in_project_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    parser = Parser(project_dir=str(project))
    handle = parser.resolver.openOut("output", "source")
    handle.write("hello")
    handle.close()
    parser.close()
    assert (project / "output.tex").read_text() == "hello"
    assert not (work / "output.tex").exists()


def test_project_dir_rejects_output_paths_outside_root_and_absolute(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    parser = Parser(project_dir=str(project))
    with pytest.raises(ValueError, match="outside project directory"):
        parser.resolver.openOut("../secret", "source")
    with pytest.raises(ValueError, match="absolute output paths not allowed"):
        parser.resolver.openOut(str(project / "output"), "source")
    parser.close()


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


def test_open_pipe_command_returns_named_string_stream(parser):
    seen = {}

    def handler(resolver, args):
        seen["resolver"] = resolver
        seen["args"] = args
        return "alpha\nbeta\n"

    pipes.registerPipeCommand("fakepipe", handler)
    try:
        f = parser.resolver.openIn('|fakepipe "two words" tail', "source")
        assert f is not None
        assert f.name == '|fakepipe "two words" tail'
        assert f.read() == "alpha\nbeta\n"
        assert seen["resolver"] is parser.resolver
        assert seen["args"] == ["two words", "tail"]
        f.close()
    finally:
        pipes.unregisterPipeCommand("fakepipe")


def test_unknown_pipe_command_returns_none(parser):
    assert parser.resolver.openIn("|missingpipe arg", "source") is None


def test_extractbb_pipe_reads_pdf_boxes(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    pdf = project / "figure.pdf"
    c = canvas.Canvas(str(pdf), pagesize=(200, 100))
    c.drawString(10, 10, "page1")
    c.showPage()
    c.setPageSize((120, 80))
    c.drawString(10, 10, "page2")
    c.save()
    parser = Parser(project_dir=str(project))
    try:
        f = parser.resolver.openIn("|extractbb -B cropbox -p 2 -O figure.pdf", "source")
        assert f is not None
        text = f.read()
        assert "%%Title: figure.pdf" in text
        assert "%%BoundingBox: 0 0 120 80" in text
        assert "%%HiResBoundingBox: 0.000000 0.000000 120.000000 80.000000" in text
        assert "%%Pages: 2" in text
        f.close()
    finally:
        parser.close()


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


def test_deferred_texlive_resolver_validates_when_it_is_first_used(tmp_path):
    missing = tmp_path / "missing"
    resolver = texlive.TexliveResolver(texlive_path=str(missing), defer=True)
    with pytest.raises(ValueError, match="texlive path does not exist"):
        resolver.openIn("plain", "source")


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
