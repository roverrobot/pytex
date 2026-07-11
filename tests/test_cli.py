import subprocess
import sys


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
    assert "file" in result.stdout
