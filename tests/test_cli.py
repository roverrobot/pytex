import subprocess
import sys

from pytex import __version__


def test_python_m_pytex_exposes_compiler_cli():
    result = subprocess.run(
        [sys.executable, "-m", "pytex", "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.startswith("usage: python -m pytex")
    assert "[-e {xetex,pdftex}]" in result.stdout
    assert "[-o {dvi,xdv,pdf,html-reflow,docx,svg}]" in result.stdout
    assert "--texlive DIRECTORY" in result.stdout
    assert "file" in result.stdout


def test_python_m_pytex_prints_package_version():
    result = subprocess.run(
        [sys.executable, "-m", "pytex", "--version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == f"pytex {__version__}\n"
    assert result.stderr == ""


def test_texlive_option_replaces_parser_resolver(tmp_path):
    from pytex import __main__ as compiler

    texlive_root = tmp_path / "texlive"
    plain = texlive_root / "2026" / "texmf-dist" / "tex" / "plain" / "base"
    plain.mkdir(parents=True)
    (plain / "plain.tex").write_text("ignored by fake parser")

    class FakeParser:
        resolver = None

    parser = FakeParser()
    compiler.configureTexliveResolver(
        parser, str(texlive_root), "plain", str(tmp_path)
    )
    resolver = parser.resolver
    assert type(resolver).__name__ == "TexliveResolver"
    assert resolver.paths == [str(texlive_root / "2026" / "texmf-dist")]
    assert resolver.project_dir == str(tmp_path)
