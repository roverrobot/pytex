from pathlib import Path
import subprocess
import sys


def test_docx_imports_in_clean_interpreter():
    result = subprocess.run(
        [sys.executable, "-c", "from pytex import docx"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_xetex_package_imports_in_clean_interpreter():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from pytex import xetex; "
                "from pytex.xetex import parseFontName, UMathCode, XeTeXPDFFile"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_glyph_model_does_not_eagerly_import_hmode_or_box():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "from pytex import glyph; "
                "assert 'pytex.hmode' not in sys.modules; "
                "assert 'pytex.box' not in sys.modules; "
                "assert glyph.GlyphCluster.node_type.name == 'GLYPH_CLUSTER'"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
