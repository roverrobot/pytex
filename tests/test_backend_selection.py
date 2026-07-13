import subprocess
import sys


def test_importing_reflow_backend_does_not_change_default_parser_metrics():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pytex import docx, texlive; from pytex.parser import Parser; "
            "parser = Parser(); "
            "assert parser.font_size_in_bp is False; "
            "parser.parse(r'\\font\\f=cmr10 \\f'); "
            "assert parser.lookup('\\\\f').at == 10.0",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
