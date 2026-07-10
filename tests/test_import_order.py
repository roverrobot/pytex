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
