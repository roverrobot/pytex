from pathlib import Path

from pytex import dvi
from pytex import resolver
from pytex import texlive


def _find_subsequence(data: bytes, needle: bytes) -> int:
    return data.find(needle)


def test_output_pages_uses_dvi_shipout(parser, tmp_path):
    parser.shipout = dvi.DVIShipout(parser)
    parser.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}", jobname="out")
    parser.jobname = str(tmp_path / "out")
    parser.end()
    shipout = parser.shipout
    assert isinstance(shipout, dvi.DVIShipout)
    assert Path(str(tmp_path / "out.dvi")).exists()


def test_output_pages_uses_explicit_output_name(parser, tmp_path):
    out = tmp_path / "named-output"
    parser.shipout = dvi.DVIShipout(parser, str(out))
    parser.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}", jobname="ignored")
    parser.end()
    shipout = parser.shipout
    assert isinstance(shipout, dvi.DVIShipout)
    assert Path(str(out) + ".dvi").exists()


def test_dvi_shipout_writes_minimal_page(cmr10, tmp_path):
    out = tmp_path / "page"
    cmr10.shipout = dvi.DVIShipout(cmr10, str(out))
    cmr10.parse("\\shipout\\vbox{\\hbox{a}}", jobname="page")
    cmr10.end()
    shipout = cmr10.shipout
    path = Path(str(out) + ".dvi")
    data = path.read_bytes()
    assert data[:2] == bytes((247, 2))
    assert 139 in data  # bop
    assert 140 in data  # eop
    assert 248 in data  # post
    assert 249 in data  # post_post
    assert ord("a") in data
    assert len(shipout.pages) == 1


def test_dvi_adjacent_chars_do_not_emit_explicit_move(cmr10, tmp_path):
    out = tmp_path / "pair"
    cmr10.shipout = dvi.DVIShipout(cmr10, str(out))
    cmr10.parse("\\shipout\\vbox{\\hbox{ab}}", jobname="pair")
    cmr10.end()
    data = Path(str(out) + ".dvi").read_bytes()
    assert bytes((ord("a"), ord("b"))) in data


def test_dvi_hlist_rule_emits_depth_offset(cmr10, tmp_path):
    out = tmp_path / "vrule"
    cmr10.shipout = dvi.DVIShipout(cmr10, str(out))
    cmr10.parse("\\shipout\\vbox{\\hbox{\\vrule height 10pt depth 2pt width 0.4pt a}}", jobname="vrule")
    cmr10.end()
    data = Path(str(out) + ".dvi").read_bytes()
    sequence = bytes((
        160, 0, 2, 0, 0,      # down4 2pt
        132, 0, 12, 0, 0,     # set_rule height 12pt
        0, 0, 102, 102,       # width 0.4pt
        160, 255, 254, 0, 0,  # down4 -2pt
    ))
    assert _find_subsequence(data, sequence) != -1


def test_dvi_shipout_accepts_binary_file_handle(parser):
    handle = parser.resolver.openOut("memory", "shipout/dvi")
    parser.shipout = dvi.DVIShipout(parser, handle)
    parser.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}", jobname="memory")
    parser.end()
    stored = parser.resolver.in_memory_files["memory.dvi"]
    assert isinstance(stored, resolver.InMemoryBinaryFile)
    data = stored.content
    assert data[:2] == bytes((247, 2))
    assert 248 in data
