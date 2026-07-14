import json
from pathlib import Path

import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from pytex import dvi
from pytex import opentype
from pytex import font_subst
from pytex import pdf
from pytex import serialization
from pytex import texlive  # noqa: F401
from pytex import mmode
from pytex import lists
from pytex.dimen import Dimen
from pytex.font_backend import FontSpec
from pytex import state
from pytex.token import CATCODE, Token


@pytest.fixture(scope="module", autouse=True)
def _enable_xetex_module():
    from pytex import xetex  # register xetex module for this test file


def test_xetex_version_primitives_expand_like_engine_identity(collector):
    collector.parse("\\number\\XeTeXversion\\XeTeXrevision")
    assert collector.getString().strip() == "0.999995"


def test_xetex_interchar_state_defaults(parser):
    assert parser.xetexcharclass[ord("A")] == 0
    assert parser.xetexcharclass[0x1F600] == 0
    assert parser.xetexinterchartoks[(1, 2)] is None


def test_xetex_interchar_state_respects_groups(parser):
    char = 0x1F600
    unassigned_char = 0x1F642
    pair = (7, 8)
    unassigned_pair = (8, 9)
    outer_tokens = [Token.token("A", CATCODE.OTHER)]
    inner_tokens = [Token.token("B", CATCODE.OTHER)]

    parser.xetexcharclass[char] = 7
    parser.xetexinterchartoks[pair] = outer_tokens
    parser.beginGroup(position=0, group_type=state.GROUP_TYPE.SEMI_SIMPLE)
    parser.xetexcharclass[char] = 8
    parser.xetexcharclass[unassigned_char] = 9
    parser.xetexinterchartoks[pair] = inner_tokens
    parser.xetexinterchartoks[unassigned_pair] = inner_tokens

    assert parser.xetexcharclass[char] == 8
    assert parser.xetexcharclass[unassigned_char] == 9
    assert parser.xetexinterchartoks[pair] is inner_tokens
    assert parser.xetexinterchartoks[unassigned_pair] is inner_tokens

    parser.endGroup(position=1, group_type=state.GROUP_TYPE.SEMI_SIMPLE)

    assert parser.xetexcharclass[char] == 7
    assert parser.xetexcharclass[unassigned_char] == 0
    assert parser.xetexinterchartoks[pair] is outer_tokens
    assert parser.xetexinterchartoks[unassigned_pair] is None


def test_xetex_interchar_state_dump_uses_json_safe_pair_keys(parser):
    toks = [Token.token("A", CATCODE.OTHER)]
    parser.xetexcharclass[0x1F600] = 7
    parser.xetexinterchartoks[(7, 8)] = toks

    state_data = parser.dumpState()

    assert state_data["xetexcharclass"][0x1F600] == 7
    assert state_data["xetexinterchartoks"] == {"7,8": toks}

    encoded = json.dumps(serialization.serialize(state_data))
    decoded = serialization.deserialize(parser, json.loads(encoded))
    restored = type(parser.xetexinterchartoks)(parser)
    restored.load(decoded["xetexinterchartoks"])
    assert restored[(7, 8)] == toks


def test_xetex_charclass_accessor_reads_and_writes_unicode_slots(collector):
    collector.parse(
        "\\XeTeXcharclass\"1F600=7 "
        "\\number\\XeTeXcharclass\"1F600"
    )

    assert collector.xetexcharclass[0x1F600] == 7
    assert collector.getString().strip() == "7"


def test_xetex_interchartoks_accessor_reads_and_writes_token_lists(collector):
    collector.parse(
        "\\XeTeXinterchartoks 7 8={A B}"
        "\\the\\XeTeXinterchartoks 7 8"
    )

    assert collector.expandedToksToString(collector.xetexinterchartoks[(7, 8)]) == "A B"
    assert collector.getString().strip() == "A B"


def test_xetex_unassigned_interchartoks_expands_to_empty(collector):
    collector.parse("\\the\\XeTeXinterchartoks 7 8")

    assert collector.getString().strip() == ""


def test_xetex_interchar_accessors_respect_local_and_global_assignments(parser):
    parser.parse(
        "\\XeTeXcharclass65=1 "
        "\\XeTeXinterchartoks 1 2={A}"
        "{\\XeTeXcharclass65=2 \\XeTeXinterchartoks 1 2={B}}"
    )

    assert parser.xetexcharclass[65] == 1
    assert parser.expandedToksToString(parser.xetexinterchartoks[(1, 2)]) == "A"

    parser.parse(
        "{\\global\\XeTeXcharclass65=3 "
        "\\global\\XeTeXinterchartoks 1 2={C}}"
    )

    assert parser.xetexcharclass[65] == 3
    assert parser.expandedToksToString(parser.xetexinterchartoks[(1, 2)]) == "C"


def test_xetex_interchartokenstate_is_grouped_integer_accessor(parser):
    assert parser.parameters["XeTeXinterchartokenstate"] == 0

    parser.parse(
        "\\XeTeXinterchartokenstate=1"
        "{\\XeTeXinterchartokenstate=2}"
    )

    assert parser.parameters["XeTeXinterchartokenstate"] == 1


def test_xetex_interchar_accessors_accept_class_4096(parser):
    parser.parse(
        "\\XeTeXcharclass65=4096 "
        "\\XeTeXinterchartoks 4096 0={A}"
    )

    assert parser.xetexcharclass[65] == 4096
    assert parser.expandedToksToString(parser.xetexinterchartoks[(4096, 0)]) == "A"


@pytest.mark.parametrize(
    "source, message",
    [
        ("\\XeTeXcharclass\"110000=1", "character code"),
        ("\\XeTeXcharclass65=4097", "character class"),
        ("\\XeTeXinterchartoks -1 0={}", "character class"),
        ("\\XeTeXinterchartoks 0 4097={}", "character class"),
    ],
)
def test_xetex_interchar_accessors_reject_out_of_range_values(parser, source, message):
    with pytest.raises(ValueError, match=message):
        parser.parse(source)


def _write_test_pdf(path, pages=1):
    c = canvas.Canvas(str(path), pagesize=(200, 100))
    for page in range(pages):
        c.drawString(20, 50, f"FIG {page + 1}")
        if page + 1 < pages:
            c.showPage()
    c.save()


def _write_test_png(path):
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", (200, 100), "white").save(path)


def test_xetex_pdffile_builds_sized_hbox_with_epdf_special(parser, tmp_path):
    fig = tmp_path / "fig.pdf"
    _write_test_pdf(fig)

    parser.parse(
        r'\setbox0=\hbox{\XeTeXpdffile "'
        + str(fig)
        + r'" width 72pt height 36pt depth 3pt}'
    )

    outer = parser.box[0]
    graphic = outer.list[0]
    assert graphic.width == Dimen(72)
    assert graphic.height == Dimen(36)
    assert graphic.depth == Dimen(3)
    special = parser.expandedToksToString(graphic.list[0].text)
    assert special.startswith("pdf: epdf")
    assert "width 72.0pt" in special
    assert "height 36.0pt" in special
    assert "depth 3.0pt" in special


def test_xetex_pdffile_dvi_contains_epdf_special(parser, tmp_path):
    fig = tmp_path / "fig.pdf"
    _write_test_pdf(fig)
    out = tmp_path / "xetex-pdffile"

    parser.shipout = dvi.DVIBackend(parser, str(out))
    parser.parse(
        r'\shipout\hbox{\XeTeXpdffile "'
        + str(fig)
        + r'" width 72pt height 36pt depth 3pt}',
        jobname="xetex-pdffile",
    )
    parser.end()

    data = Path(str(out) + ".dvi").read_bytes()
    assert parser.shipout.max_width == int(Dimen(72))
    assert parser.shipout.max_height == int(Dimen(39))
    assert b"pdf: epdf" in data
    assert b"width 72.0pt" in data
    assert b"height 36.0pt" in data
    assert b"depth 3.0pt" in data
    assert str(fig).encode() in data


def test_xetex_pdffile_accepts_crop_bbox_before_size(parser, tmp_path):
    fig = tmp_path / "fig.pdf"
    _write_test_pdf(fig)

    parser.parse(
        r'\setbox0=\hbox{\XeTeXpdffile "'
        + str(fig)
        + r'" crop bbox 0 0 200 100 width 50pt}'
    )

    graphic = parser.box[0].list[0]
    special = parser.expandedToksToString(graphic.list[0].text)
    assert graphic.width == Dimen(50)
    assert round(float(graphic.height), 4) == 25.0
    assert "pagebox cropbox" in special
    assert "bbox 0 0 200 100" in special
    assert "width 50.0pt" in special


def test_xetex_pdffile_maps_pagebox_keywords(parser, tmp_path):
    fig = tmp_path / "fig.pdf"
    _write_test_pdf(fig)

    expected = {
        "media": "mediabox",
        "crop": "cropbox",
        "bleed": "bleedbox",
        "trim": "trimbox",
        "art": "artbox",
    }
    for keyword, pagebox in expected.items():
        parser.parse(
            r'\setbox0=\hbox{\XeTeXpdffile "'
            + str(fig)
            + f'" {keyword} width 10pt height 10pt}}'
        )
        graphic = parser.box[0].list[0]
        special = parser.expandedToksToString(graphic.list[0].text)
        assert f"pagebox {pagebox}" in special


def test_xetex_pdffile_accepts_page_crop_and_explicit_size(parser, tmp_path):
    fig = tmp_path / "fig.pdf"
    _write_test_pdf(fig, pages=2)

    parser.parse(
        r'\setbox0=\hbox{\XeTeXpdffile "'
        + str(fig)
        + r'" page 2 crop width 100pt height 50pt}'
    )

    graphic = parser.box[0].list[0]
    special = parser.expandedToksToString(graphic.list[0].text)
    assert graphic.width == Dimen(100)
    assert graphic.height == Dimen(50)
    assert "page 2" in special
    assert "pagebox cropbox" in special
    assert "width 100.0pt" in special
    assert "height 50.0pt" in special


def test_xetex_pdffile_scaled_affects_box_and_special(parser, tmp_path):
    fig = tmp_path / "fig.pdf"
    _write_test_pdf(fig)

    parser.parse(
        r'\setbox0=\hbox{\XeTeXpdffile "'
        + str(fig)
        + r'" bbox 0 0 200 100 scaled 500 width 50pt}'
    )

    graphic = parser.box[0].list[0]
    special = parser.expandedToksToString(graphic.list[0].text)
    assert graphic.width == Dimen(25)
    assert round(float(graphic.height), 4) == 12.5
    assert "scale 0.5" not in special
    assert "width 25.0pt" in special
    assert "height 12.5pt" in special


def test_xetex_picfile_builds_sized_hbox_with_image_special(parser, tmp_path):
    img = tmp_path / "fig.png"
    _write_test_png(img)

    parser.parse(
        r'\setbox0=\hbox{\XeTeXpicfile "'
        + str(img)
        + r'" width 100pt height 50pt}'
    )

    graphic = parser.box[0].list[0]
    special = parser.expandedToksToString(graphic.list[0].text)
    assert graphic.width == Dimen(100)
    assert graphic.height == Dimen(50)
    assert graphic.depth == Dimen()
    assert special.startswith("pdf: image")
    assert "width 100.0pt" in special
    assert "height 50.0pt" in special
    assert "bbox 0 0 200 100" in special
    assert str(img) in special


def test_xetex_picfile_dvi_contains_image_special(parser, tmp_path):
    img = tmp_path / "fig.png"
    _write_test_png(img)
    out = tmp_path / "xetex-picfile"

    parser.shipout = dvi.DVIBackend(parser, str(out))
    parser.parse(
        r'\shipout\hbox{\XeTeXpicfile "'
        + str(img)
        + r'" width 72pt height 36pt}',
        jobname="xetex-picfile",
    )
    parser.end()

    data = Path(str(out) + ".dvi").read_bytes()
    assert parser.shipout.max_width == int(Dimen(72))
    assert parser.shipout.max_height == int(Dimen(36))
    assert b"pdf: image" in data
    assert b"width 72.0pt" in data
    assert b"height 36.0pt" in data
    assert str(img).encode() in data


def test_xetex_picfile_scaled_affects_box_and_special(parser, tmp_path):
    img = tmp_path / "fig.png"
    _write_test_png(img)

    parser.parse(
        r'\setbox0=\hbox{\XeTeXpicfile "'
        + str(img)
        + r'" width 50pt scaled 500}'
    )

    graphic = parser.box[0].list[0]
    special = parser.expandedToksToString(graphic.list[0].text)
    assert graphic.width == Dimen(25)
    assert round(float(graphic.height), 4) == 12.5
    assert "scale 0.5" not in special
    assert "width 25.0pt" in special
    assert "height 12.5pt" in special
    assert "bbox 0 0 200 100" in special


def test_xetex_pdffile_pdf_backend_includes_figure(parser, tmp_path):
    fig = tmp_path / "fig.pdf"
    _write_test_pdf(fig)
    out = tmp_path / "xetex-pdffile-pdf"

    parser.shipout = pdf.PDFBackend(parser, str(out))
    parser.parse(
        r'\shipout\hbox{\XeTeXpdffile "'
        + str(fig)
        + r'" width 72pt height 36pt}',
        jobname="xetex-pdffile-pdf",
    )
    parser.end()

    reader = PdfReader(str(out) + ".pdf")
    assert "FIG" in (reader.pages[0].extract_text() or "")


def test_xetex_pdffile_pdf_backend_honors_width_after_bbox(parser, tmp_path):
    fig = tmp_path / "fig.pdf"
    _write_test_pdf(fig)
    out = tmp_path / "xetex-pdffile-bbox-width"

    parser.shipout = pdf.PDFBackend(parser, str(out))
    parser.parse(
        r'\shipout\hbox{\XeTeXpdffile "'
        + str(fig)
        + r'" crop bbox 0 0 200 100 width 50pt}',
        jobname="xetex-pdffile-bbox-width",
    )
    parser.end()

    reader = PdfReader(str(out) + ".pdf")
    content = reader.pages[0].get_contents().get_data().decode("latin1", "replace")
    assert "FIG" in (reader.pages[0].extract_text() or "")
    expected_scale = 50 * 72 / 72.27 / 200
    assert f"{expected_scale:.6f} 0.0 0.0 {expected_scale:.6f}" in content


def test_xetex_font_name_parser_marks_bracketed_file_specs(parser):
    spec = parser.parseFontName("[myfont.ttc:2]/OT:script=latn;+liga")

    assert spec == FontSpec(
        "myfont.ttc",
        lookup="file",
        font_number=2,
        options="/OT",
        features="script=latn;+liga",
    )


def test_xetex_bracketed_extensionless_font_file_loads(parser):
    handle = parser.resolver.openIn("lmroman10-regular", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    handle.close()

    parser.parse('\\font\\f="[lmroman10-regular]" at 10pt')

    font = parser.equitable["\\f"]
    assert font.backend.kind == "opentype"
    assert font.backend.name == "lmroman10-regular"
    assert font.backend.path.endswith("lmroman10-regular.otf")


def test_xetex_font_file_suffixes_are_ignored_for_lookup(parser):
    handle = parser.resolver.openIn("lmroman10-regular.otf", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    handle.close()

    parser.parse('\\font\\f="[lmroman10-regular.otf]/OT:script=latn;+liga" at 10pt')

    font = parser.equitable["\\f"]
    assert font.backend.kind == "opentype"
    assert font.backend.name == "lmroman10-regular.otf"
    assert font.backend.path.endswith("lmroman10-regular.otf")


def test_xetex_fontspec_tfm_loads_with_font_substitution(parser):
    font_subst.installFontSubstitution(parser)

    parser.parse('\\font\\f="cmr10" ')

    font = parser.equitable["\\f"]
    assert font.backend.dvi_name == "cmr10"


def test_xetex_name_prefix_forces_system_font_lookup(parser, monkeypatch):
    handle = parser.resolver.openIn("lmroman10-regular.otf", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    path = handle.name
    handle.close()

    @classmethod
    def fake_system_path(cls, name):
        return (path, 0) if name == "Latin Modern Roman" else None

    monkeypatch.setattr(opentype.OpenTypeBackend, "_systemFontPath", fake_system_path)
    parser.parse('\\font\\f="name:Latin Modern Roman" at 10pt')

    font = parser.equitable["\\f"]
    assert font.backend.kind == "opentype"
    assert font.backend.name == "Latin Modern Roman"
    assert font.backend.path == path


def test_uchar_generates_other_tokens_and_space_tokens(parser):
    parser.readFrom("\\Uchar65 \\Uchar32 \\Uchar\"03B2")

    a = parser.token_expand()
    space = parser.token_expand()
    beta = parser.token_expand()

    assert (a.name, a.catcode) == ("A", CATCODE.OTHER)
    assert (space.name, space.catcode) == (" ", CATCODE.SPACE)
    assert (beta.name, beta.catcode) == ("\u03b2", CATCODE.OTHER)


def test_ucharcat_generates_requested_catcode(parser):
    parser.readFrom("\\Ucharcat65 11\\Ucharcat65 12")

    letter = parser.token_expand()
    other = parser.token_expand()

    assert (letter.name, letter.catcode) == ("A", CATCODE.LETTER)
    assert (other.name, other.catcode) == ("A", CATCODE.OTHER)


def test_ucharcat_generates_active_token_without_expanding_it(parser):
    parser.readFrom("65 13")
    parser.lookup("\\Ucharcat").expand(parser)

    active = parser.token()

    assert (active.name, active.catcode) == ("A", CATCODE.ACTIVE)
    assert active.entry is parser.equitable.entry("A")


def test_ucharcat_rejects_invalid_catcodes(parser):
    with pytest.raises(ValueError, match="Invalid code"):
        parser.parse("\\Ucharcat65 0")


def test_umathcode_accepts_xetex_three_integer_assignment(parser):
    parser.parse("\\Umathcode`A=7 1 65")

    assert parser.umathcode[ord("A")] == (((1 << 3) + 7) << 21) + 65


def test_umathcodenum_reads_and_writes_packed_mathcode(collector):
    packed = (((1 << 3) + 7) << 21) + 0x03B2

    collector.parse("\\Umathcodenum`A=%d \\number\\Umathcodenum`A" % packed)

    assert collector.getString().strip() == str(packed)


def test_umathchardef_defines_readable_unicode_math_char(collector):
    collector.parse("\\Umathchardef\\foo=7 1 \"03B2 \\number\\foo")

    assert collector.getString().strip() == str((((1 << 3) + 7) << 21) + 0x03B2)


def test_umathcharnumdef_defines_readable_packed_unicode_math_char(collector):
    packed = (((1 << 3) + 7) << 21) + 0x03B2

    collector.parse("\\Umathcharnumdef\\foo=%d \\number\\foo" % packed)

    assert collector.getString().strip() == str(packed)


def test_umathcharnumdef_accepts_umathcodenum_value(collector):
    packed = (((1 << 3) + 7) << 21) + 0x03B2

    collector.parse(
        "\\Umathcode`A=7 1 \"03B2 "
        "\\Umathcharnumdef\\foo=\\Umathcodenum`A "
        "\\number\\foo"
    )

    assert collector.getString().strip() == str(packed)


def test_umathchardef_appends_unicode_math_symbol(parser):
    parser.parse("\\Umathchardef\\foo=7 1 \"03B2 $\\foo")

    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 1
    atom = top[0]
    assert isinstance(atom, mmode.Atom)
    assert atom.atom_type == mmode.ATOM_TYPE.ORD
    assert atom.nucleus.fam == 1
    assert atom.nucleus.char == "\u03b2"


def test_umathchar_and_umathcharnum_append_unicode_math_symbols(parser):
    packed = (((1 << 3) + 7) << 21) + 0x03B2
    parser.parse("$\\Umathchar 7 1 \"03B2 \\Umathcharnum %d" % packed)

    top = parser.lists[-1]
    assert top.type == lists.LISTTYPE.MATH
    assert len(top) == 2
    assert [atom.nucleus.char for atom in top] == ["\u03b2", "\u03b2"]
    assert [atom.nucleus.fam for atom in top] == [1, 1]


def test_udelcode_accepts_xetex_family_and_glyph_assignment(parser):
    parser.parse("\\Udelcode`A=1 65")

    assert parser.udelcode[ord("A")] == ((0x200 + 1) << 21) + 65
