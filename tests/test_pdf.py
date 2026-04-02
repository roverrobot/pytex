from pathlib import Path

import pytest

from pytex import pdf
from pytex import texlive


def test_output_pages_uses_pdf_backend(cmr10, tmp_path):
    cmr10.shipout = pdf.PDFBackend(cmr10)
    cmr10.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}", jobname="out")
    cmr10.jobname = str(tmp_path / "out")
    cmr10.end()
    assert isinstance(cmr10.shipout, pdf.PDFBackend)
    assert Path(str(tmp_path / "out.pdf")).exists()


def test_output_pages_uses_explicit_output_name(cmr10, tmp_path):
    out = tmp_path / "named-output"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}", jobname="ignored")
    cmr10.end()
    assert Path(str(out) + ".pdf").exists()


def test_pdf_shipout_accepts_binary_file_handle(cmr10):
    handle = cmr10.resolver.openOut("memory", "shipout/pdf")
    cmr10.shipout = pdf.PDFBackend(cmr10, handle)
    cmr10.parse("\\vsize=20pt\\topskip=0pt\\hbox{A}", jobname="memory")
    cmr10.end()
    stored = cmr10.resolver.in_memory_files["memory.pdf"]
    data = stored.content
    assert data.startswith(b"%PDF-")


def test_pdf_shipout_writes_minimal_page(cmr10, tmp_path):
    out = tmp_path / "page"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse("\\shipout\\vbox{\\hbox{a}}", jobname="page")
    cmr10.end()
    data = Path(str(out) + ".pdf").read_bytes()
    assert data.startswith(b"%PDF-")
    assert b"/Type /Page" in data


def test_pdf_dvipdfm_color_special_is_emitted(cmr10, tmp_path):
    out = tmp_path / "pdf-color"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse(r"\shipout\vbox{\special{pdf: bc [ 1 0 0 ]}\hbox{a}}", jobname="pdf-color")
    cmr10.end()
    data = Path(str(out) + ".pdf").read_bytes()
    assert b"1 0 0 rg" in data
