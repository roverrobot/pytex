import os
import subprocess
from pathlib import Path

import pytest

from pytex import graphics
from pytex.dimen import Dimen


class _FakePDFConverter:
    def __init__(self):
        self.requests = []

    def convert(self, request):
        self.requests.append(request)
        assert Path(request.path).read_bytes() == b"%PDF-converted"
        return graphics.GraphicAsset(
            format="svg",
            data="<svg/>",
            width=request.width,
            height=request.height,
            depth=request.depth,
        )


def _eps_request(path):
    return graphics.GraphicRequest(
        source=os.fspath(path),
        path=os.fspath(path),
        source_format="eps",
        bbox=(10, 20, 110, 70),
        width=Dimen(72),
        height=Dimen(36),
        depth=Dimen(2),
    )


def _write_converted_pdf(command, cwd):
    output_option = next(
        option
        for option in command
        if option.startswith("--outfile=") or option.startswith("-sOutputFile=")
    )
    (Path(cwd) / output_option.split("=", 1)[1]).write_bytes(b"%PDF-converted")
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_eps_converter_prefers_epstopdf_and_reuses_pdf_converter(tmp_path, monkeypatch):
    eps = tmp_path / "figure.eps"
    eps.write_text("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 10 20 110 70\n")
    commands = []
    lookups = []

    def fake_which(name):
        lookups.append(name)
        return "/texbin/epstopdf" if name == "epstopdf" else "/usr/bin/gs"

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        return _write_converted_pdf(command, kwargs["cwd"])

    monkeypatch.setattr(graphics.shutil, "which", fake_which)
    monkeypatch.setattr(graphics.subprocess, "run", fake_run)
    pdf_converter = _FakePDFConverter()

    asset = graphics.EPSToSVGConverter(pdf_converter).convert(_eps_request(eps))

    assert lookups == ["epstopdf"]
    assert commands[0][0][0] == "/texbin/epstopdf"
    assert "--restricted" in commands[0][0]
    assert commands[0][0][-1] == "graphic.eps"
    assert commands[0][1] == {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "check": False,
        "cwd": commands[0][1]["cwd"],
    }
    assert asset.format == "svg"
    assert asset.width == Dimen(72)
    assert asset.height == Dimen(36)
    pdf_request = pdf_converter.requests[0]
    assert pdf_request.source_format == "pdf"
    assert pdf_request.bbox is None
    assert pdf_request.depth == Dimen(2)


def test_eps_converter_falls_back_to_ghostscript_with_eps_crop(tmp_path, monkeypatch):
    eps = tmp_path / "figure.eps"
    eps.write_text("%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 100 50\n")
    commands = []

    def fake_which(name):
        return None if name == "epstopdf" else "/usr/bin/gs"

    def fake_run(command, **kwargs):
        commands.append(command)
        return _write_converted_pdf(command, kwargs["cwd"])

    monkeypatch.setattr(graphics.shutil, "which", fake_which)
    monkeypatch.setattr(graphics.subprocess, "run", fake_run)

    graphics.EPSToSVGConverter(_FakePDFConverter()).convert(_eps_request(eps))

    command = commands[0]
    assert command[0] == "/usr/bin/gs"
    assert "-dSAFER" in command
    assert "-dBATCH" in command
    assert "-dNOPAUSE" in command
    assert "-sDEVICE=pdfwrite" in command
    assert "-dEPSCrop" in command
    assert command[-1] == "graphic.eps"


def test_eps_converter_fails_when_no_converter_is_installed(tmp_path, monkeypatch):
    eps = tmp_path / "figure.eps"
    eps.write_text("%!PS-Adobe-3.0 EPSF-3.0\n")
    monkeypatch.setattr(graphics.shutil, "which", lambda name: None)

    with pytest.raises(RuntimeError, match="neither epstopdf nor Ghostscript"):
        graphics.EPSToSVGConverter(_FakePDFConverter()).convert(_eps_request(eps))


def test_eps_converter_reports_command_failure_stderr(tmp_path, monkeypatch):
    eps = tmp_path / "broken.eps"
    eps.write_text("not PostScript")
    monkeypatch.setattr(graphics.shutil, "which", lambda name: "/texbin/epstopdf")
    monkeypatch.setattr(
        graphics.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="invalid EPS header",
        ),
    )

    with pytest.raises(RuntimeError, match="epstopdf failed.*invalid EPS header"):
        graphics.EPSToSVGConverter(_FakePDFConverter()).convert(_eps_request(eps))
