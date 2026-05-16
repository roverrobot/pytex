from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from pytex import xdv
from pytex.graphics import GraphicSpec


def _native_font_def_payload(data):
    i = data.index(bytes((xdv.XDVBackend.NATIVE_FONT_DEF,)))
    font_id = int.from_bytes(data[i + 1 : i + 5], "big")
    scale = int.from_bytes(data[i + 5 : i + 9], "big", signed=True)
    flags = int.from_bytes(data[i + 9 : i + 11], "big")
    name_len = data[i + 11]
    offset = i + 12
    name = data[offset : offset + name_len]
    offset += name_len
    family_len = data[offset]
    offset += 1
    family = data[offset : offset + family_len]
    offset += family_len
    style_len = data[offset]
    offset += 1
    style = data[offset : offset + style_len]
    offset += style_len
    font_number = int.from_bytes(data[offset : offset + 2], "big")
    return {
        "font_id": font_id,
        "scale": scale,
        "flags": flags,
        "name": name,
        "family": family,
        "style": style,
        "font_number": font_number,
    }


def _xdv_glyphs_payload(data):
    i = data.index(bytes((xdv.XDVBackend.XDV_GLYPHS,)))
    width = int.from_bytes(data[i + 1 : i + 5], "big")
    glyph_count = int.from_bytes(data[i + 5 : i + 7], "big")
    offset = i + 7
    positions = []
    for _ in range(glyph_count):
        x = int.from_bytes(data[offset : offset + 4], "big", signed=True)
        offset += 4
        y = int.from_bytes(data[offset : offset + 4], "big", signed=True)
        offset += 4
        positions.append((x, y))
    glyphs = []
    for _ in range(glyph_count):
        glyphs.append(int.from_bytes(data[offset : offset + 2], "big"))
        offset += 2
    return {
        "width": width,
        "positions": positions,
        "glyphs": glyphs,
    }


def test_xdv_shipout_writes_xdv_file(parser, tmp_path):
    out = tmp_path / "page"
    parser.shipout = xdv.XDVBackend(parser, str(out))
    parser.parse("\\font\\f=cmr10 \\shipout\\vbox{\\hbox{\\f a}}", jobname="page")
    parser.end()

    data = Path(str(out) + ".xdv").read_bytes()
    assert data[:2] == bytes((247, 7))
    post_post = data.index(bytes((249,)))
    assert data[post_post + 5] == 7


def test_xdv_shipout_accepts_binary_file_handle(parser):
    handle = parser.resolver.openOut("memory", "shipout/xdv")
    parser.shipout = xdv.XDVBackend(parser, handle)
    parser.parse("\\font\\f=cmr10 \\shipout\\vbox{\\hbox{\\f a}}", jobname="memory")
    parser.end()

    stored = parser.resolver.in_memory_files["memory.xdv"]
    data = stored.content
    assert data[:2] == bytes((247, 7))
    assert 248 in data


def test_xdv_tfm_fonts_use_regular_dvi_font_def(parser, tmp_path):
    out = tmp_path / "tfm"
    parser.shipout = xdv.XDVBackend(parser, str(out))
    parser.parse("\\font\\f=cmr10 \\shipout\\vbox{\\hbox{\\f a}}", jobname="tfm")
    parser.end()

    data = Path(str(out) + ".xdv").read_bytes()
    assert 243 in data  # fnt_def1
    assert b"cmr10" in data


def test_xdv_opentype_fonts_use_native_font_def(parser, tmp_path):
    handle = parser.resolver.openIn("lmroman10-regular.otf", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    path = handle.name
    handle.close()

    out = tmp_path / "opentype"
    parser.shipout = xdv.XDVBackend(parser, str(out))
    parser.parse(
        r"\font\f=lmroman10-regular.otf at 10pt \shipout\vbox{\hbox{\f A}}",
        jobname="opentype",
    )
    parser.end()

    data = Path(str(out) + ".xdv").read_bytes()
    payload = _native_font_def_payload(data)
    assert payload["font_id"] == 0
    assert payload["scale"] == 10 * 65536
    assert payload["flags"] == 0
    assert payload["name"] == path.encode()
    assert payload["family"] == b""
    assert payload["style"] == b""
    assert payload["font_number"] == 0
    glyphs = _xdv_glyphs_payload(data)
    assert glyphs["width"] == 491520
    assert glyphs["positions"] == [(0, 0)]
    assert glyphs["glyphs"] == [27]
    assert b"lmroman10-regular.otf" in data


def test_xdv_native_font_def_records_collection_index(parser):
    output = BytesIO()
    shipout = xdv.XDVBackend(parser, output)
    shipout.file = output
    font_backend = SimpleNamespace(
        kind="opentype",
        path="/fonts/collection.ttc",
        name="collection.ttc",
        font_number=7,
    )
    font = SimpleNamespace(backend=font_backend, at=10 * 65536)

    shipout._write_native_font_def(12, font)

    payload = _native_font_def_payload(output.getvalue())
    assert payload["font_id"] == 12
    assert payload["name"] == b"/fonts/collection.ttc"
    assert payload["font_number"] == 7


def test_xdv_native_font_chars_emit_xdv_glyphs(parser):
    output = BytesIO()
    shipout = xdv.XDVBackend(parser, output)
    shipout.file = output

    class Backend:
        kind = "opentype"

        def glyphId(self, char):
            return {"A": 27}[char]

    font = SimpleNamespace(backend=Backend())
    node = SimpleNamespace(char="A", width=12345, font=font)

    shipout.set_char(node)

    payload = _xdv_glyphs_payload(output.getvalue())
    assert payload["width"] == 12345
    assert payload["positions"] == [(0, 0)]
    assert payload["glyphs"] == [27]
    assert shipout.dvi_h == 12345


def test_xdv_graphic_special_is_serialized(parser):
    output = BytesIO()
    shipout = xdv.XDVBackend(parser, output)
    shipout.file = output

    shipout.graphic(
        GraphicSpec(
            kind="epdf",
            source="figure.pdf",
            options=(("bbox", ("0", "0", "10", "20")), ("width", "5pt")),
            format="pdf",
        )
    )

    assert b"pdf: epdf bbox 0 0 10 20 width 5pt (figure.pdf)" in output.getvalue()
