from pathlib import Path

from pytex import dvi
from pytex import texlive


def test_output_pages_uses_dvi_shipout(parser, tmp_path):
    parser.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}", jobname="out")
    parser.jobname = str(tmp_path / "out")
    shipout = parser.outputPages()
    assert isinstance(shipout, dvi.DVIShipout)
    assert Path(str(tmp_path / "out.dvi")).exists()


def test_output_pages_uses_explicit_output_name(parser, tmp_path):
    parser.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}", jobname="ignored")
    out = tmp_path / "named-output"
    shipout = parser.outputPages(str(out))
    assert isinstance(shipout, dvi.DVIShipout)
    assert Path(str(out) + ".dvi").exists()


def test_dvi_shipout_writes_minimal_page(cmr10, tmp_path):
    cmr10.parse("\\shipout\\vbox{\\hbox{a}}", jobname="page")
    cmr10.jobname = str(tmp_path / "page")
    shipout = cmr10.outputPages()
    path = Path(str(tmp_path / "page.dvi"))
    data = path.read_bytes()
    assert data[:2] == bytes((247, 2))
    assert 139 in data  # bop
    assert 140 in data  # eop
    assert 248 in data  # post
    assert 249 in data  # post_post
    assert ord("a") in data
    assert len(shipout.pages) == 1
