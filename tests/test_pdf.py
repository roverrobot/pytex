from io import BytesIO
from pathlib import Path
import re

import pytest
from pypdf import PdfReader
from reportlab.pdfgen import canvas

from pytex import font as txfont
from pytex import graphics
from pytex import opentype
from pytex import pdf
from pytex import texlive
from pytex.dimen import Dimen


def _page_content_text(path):
    reader = PdfReader(str(path))
    page = reader.pages[0]
    content = page.get_contents()
    if isinstance(content, list):
        data = b"".join(c.get_data() for c in content)
    else:
        data = content.get_data()
    return page, data.decode("latin1", "replace")


def test_pdf_warns_once_for_non_bmp_character(cmr10):
    backend = pdf.PDFBackend(cmr10)
    backend.current_font = type("FontHolder", (), {"backend": type("Backend", (), {"name": "Apple Color Emoji"})()})()
    backend._warn_reportlab_non_bmp("😄")
    backend._warn_reportlab_non_bmp("😄")
    log = cmr10.logContent()
    assert log.count("Warning: direct PDF output via ReportLab may misrender non-BMP character") == 1
    assert "U+1F604" in log
    assert "Apple Color Emoji" in log


def test_pdf_registers_converted_cff_font_from_backend_bytes(parser):
    handle = parser.resolver.openIn("lmroman10-regular.otf", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    path = handle.name
    handle.close()

    parser.registerSupportedFontClasses()
    source = parser.loadFontBackend("lmroman10-regular.otf")
    if not isinstance(source, opentype.CFFBackend):
        pytest.skip("lmroman10-regular.otf is not a CFF font")
    parser.registerSupportedFontClasses(opentype.TrueTypeBackend)
    converted = parser.loadFontBackend("lmroman10-regular.otf")
    assert converted.path is None

    backend = pdf.PDFBackend(parser)
    backend._register_opentype(txfont.Font(converted, Dimen(10)), "ConvertedCFF")


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


def test_pdf_shipout_uses_tex_origin(cmr10, tmp_path):
    out = tmp_path / "origin"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse("\\shipout\\vbox{\\hbox{a}}", jobname="origin")
    cmr10.end()
    _page, text = _page_content_text(str(out) + ".pdf")
    match = re.search(r"BT /F\d+ ([0-9.]+) Tf 1 0 0 1 ([0-9.]+) ([0-9.]+) Tm <61> Tj ET", text)
    assert match is not None
    assert float(match.group(1)) == pytest.approx(10 * 72 / 72.27)
    x = float(match.group(2))
    assert x == pytest.approx(72.0)


def test_pdf_shipout_embeds_cff_opentype_without_reportlab_font_parser(parser, tmp_path):
    handle = parser.resolver.openIn("lmroman10-regular.otf", "fonts/opentype")
    if handle is None:
        pytest.skip("lmroman10-regular.otf not found")
    handle.close()

    out = tmp_path / "cff-opentype"
    parser.shipout = pdf.PDFBackend(parser, str(out))
    parser.parse(r"\font\f=lmroman10-regular.otf at 12pt \shipout\vbox{\hbox{\f A}}", jobname="cff-opentype")
    parser.end()

    reader = PdfReader(str(out) + ".pdf")
    page = reader.pages[0]
    assert "A" in (page.extract_text() or "")
    fonts = page["/Resources"]["/Font"].get_object()
    raw_font = fonts["/PyTeXFont0"].get_object()
    assert raw_font["/Subtype"] == "/Type0"
    descendant = raw_font["/DescendantFonts"][0].get_object()
    assert descendant["/Subtype"] == "/CIDFontType0"
    descriptor = descendant["/FontDescriptor"].get_object()
    font_file = descriptor["/FontFile3"].get_object()
    assert font_file["/Subtype"] == "/OpenType"
    assert len(font_file.get_data()) > 1000


def test_pdf_shipout_reuses_type1_companion_font_file(parser, tmp_path):
    out = tmp_path / "type1-reuse"
    parser.shipout = pdf.PDFBackend(parser, str(out))
    parser.parse(
        r"\font\a=cmsy10 at 10pt \font\b=cmsy10 at 12pt "
        r"\shipout\vbox{\hbox{\a A\b B}}",
        jobname="type1-reuse",
    )
    parser.end()

    assert Path(str(out) + ".pdf").exists()


def test_pdf_shipout_type1_text_slots_have_to_unicode(cmr10, tmp_path):
    out = tmp_path / "type1-text"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse("\\shipout\\vbox{\\hbox{a}}", jobname="type1-text")
    cmr10.end()

    page, text = _page_content_text(str(out) + ".pdf")
    assert "<61> Tj" in text
    assert "a" in (page.extract_text() or "")
    fonts = page["/Resources"]["/Font"].get_object()
    assert any(font.get_object().get("/ToUnicode") is not None for font in fonts.values())


def test_pdf_shipout_type1_math_slots_use_glyph_unicode(parser, tmp_path):
    out = tmp_path / "type1-math"
    parser.shipout = pdf.PDFBackend(parser, str(out))
    parser.parse(r"\font\f=cmsy10 \shipout\vbox{\hbox{\f\char121}}", jobname="type1-math")
    parser.end()

    page, text = _page_content_text(str(out) + ".pdf")
    assert "<79> Tj" in text
    assert "/F4" not in text
    assert "†" in (page.extract_text() or "")


def test_pdf_shipout_type1_math_low_slots_use_glyph_unicode(parser, tmp_path):
    out = tmp_path / "type1-math-low"
    parser.shipout = pdf.PDFBackend(parser, str(out))
    parser.parse(r"\font\f=cmmi10 \shipout\vbox{\hbox{\f\char12}}", jobname="type1-math-low")
    parser.end()

    page, text = _page_content_text(str(out) + ".pdf")
    assert "<0C> Tj" in text
    assert "/F4" not in text
    assert "β" in (page.extract_text() or "")


def test_pdf_pagesize_special_changes_page_size(cmr10, tmp_path):
    out = tmp_path / "pagesize"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse(r"\shipout\vbox{\special{pdf:pagesize width 300pt height 200pt}\hbox{a}}", jobname="pagesize")
    cmr10.end()
    page, _text = _page_content_text(str(out) + ".pdf")
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    assert width == pytest.approx(300 * 72 / 72.27, abs=0.01)
    assert height == pytest.approx(200 * 72 / 72.27, abs=0.01)


def test_pdf_shipout_converts_tex_page_dimensions_to_pdf_points(cmr10, tmp_path):
    out = tmp_path / "letter"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse(
        r"\shipout\vbox{\special{pdf:pagesize width 8.5in height 11in}\hbox{a}}",
        jobname="letter",
    )
    cmr10.end()
    page, _text = _page_content_text(str(out) + ".pdf")
    assert float(page.mediabox.width) == pytest.approx(612.0, abs=0.01)
    assert float(page.mediabox.height) == pytest.approx(792.0, abs=0.01)


def test_pdf_epdf_special_includes_pdf_figure(cmr10, tmp_path):
    fig = tmp_path / "fig.pdf"
    c = canvas.Canvas(str(fig), pagesize=(200, 100))
    c.drawString(20, 50, "FIG")
    c.save()
    out = tmp_path / "epdf"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse(
        r"\shipout\vbox{\hbox{\special{pdf: epdf bbox 0 0 200 100 width 72pt (fig.pdf)}\kern72pt}}",
        jobname="epdf",
    )
    cmr10.end()
    reader = PdfReader(str(out) + ".pdf")
    assert "FIG" in (reader.pages[0].extract_text() or "")


def test_pdf_dvips_eps_special_converts_to_pdf_overlay(
    cmr10, tmp_path, monkeypatch
):
    eps = tmp_path / "fig.eps"
    eps.write_text(
        "%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 200 100\n"
    )
    converted = BytesIO()
    c = canvas.Canvas(converted, pagesize=(200, 100))
    c.drawString(20, 50, "EPS FIG")
    c.save()

    class FakeEPSToPDFConverter:
        def __init__(self):
            self.requests = []

        def convert(self, request):
            self.requests.append(request)
            return graphics.GraphicAsset(
                format="pdf",
                data=converted.getvalue(),
                width=request.width,
                height=request.height,
                depth=request.depth,
            )

    converter = FakeEPSToPDFConverter()
    monkeypatch.setitem(graphics._CONVERTERS, ("eps", "pdf"), converter)
    out = tmp_path / "eps-overlay"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse(
        r'\shipout\vbox{\hbox{\special{PSfile="fig.eps" llx=0 lly=0 '
        r'urx=200 ury=100 rwi=720}\kern72bp}}',
        jobname="eps-overlay",
    )
    cmr10.end()

    reader = PdfReader(str(out) + ".pdf")
    assert "EPS FIG" in (reader.pages[0].extract_text() or "")
    assert len(converter.requests) == 1
    request = converter.requests[0]
    assert request.source == "fig.eps"
    assert request.source_format == "eps"
    assert request.bbox == ("0", "0", "200", "100")


def test_pdf_epdf_special_honors_xdvipdfmx_scale_transform(cmr10, tmp_path):
    fig = tmp_path / "fig.pdf"
    c = canvas.Canvas(str(fig), pagesize=(200, 100))
    c.drawString(20, 50, "FIG")
    c.save()
    out = tmp_path / "epdf-transform"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse(
        r"\shipout\vbox{\hbox{"
        r"\special{pdf:btrans}"
        r"\special{x:scale 0.5 0.5}"
        r"\special{pdf: epdf bbox 0 0 200 100 (fig.pdf)}"
        r"\special{pdf:etrans}"
        r"\kern100bp}}",
        jobname="epdf-transform",
    )
    cmr10.end()
    reader = PdfReader(str(out) + ".pdf")
    content = reader.pages[0].get_contents().get_data().decode("latin1", "replace")
    assert "FIG" in (reader.pages[0].extract_text() or "")
    assert "0.5 0.0 0.0 0.5" in content


def test_pdf_dvipdfm_color_special_is_emitted(cmr10, tmp_path):
    out = tmp_path / "pdf-color"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse(r"\shipout\vbox{\special{pdf: bc [ 1 0 0 ]}\hbox{a}}", jobname="pdf-color")
    cmr10.end()
    data = Path(str(out) + ".pdf").read_bytes()
    assert b"1 0 0 rg" in data


def test_pdf_skips_zero_width_rules(cmr10, tmp_path):
    out = tmp_path / "pdf-zero-rule"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse(r"\shipout\vbox{\hbox{\vrule width0pt height 10pt depth 2pt a}}", jobname="pdf-zero-rule")
    cmr10.end()
    _page, text = _page_content_text(str(out) + ".pdf")
    assert re.search(r"\b0(?:\\.0+)? 12(?:\\.0+)? re\\b", text) is None


def test_pdf_ignored_multiline_special_is_sanitized(cmr10, tmp_path):
    out = tmp_path / "pdf-special"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse("\\shipout\\vbox{\\special{foo^^Jbar}\\hbox{a}}", jobname="pdf-special")
    cmr10.end()
    data = Path(str(out) + ".pdf").read_bytes()
    assert b"% rawSpecial ignored: foo\\nbar" in data
    assert b"% rawSpecial ignored: foo\nbar" not in data


def test_pdf_ignored_unicode_special_is_sanitized(cmr10, tmp_path):
    out = tmp_path / "pdf-unicode-special"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse("\\shipout\\vbox{\\special{foo\ufeffbar}\\hbox{a}}", jobname="pdf-unicode-special")
    cmr10.end()
    data = Path(str(out) + ".pdf").read_bytes()
    assert b"% rawSpecial ignored: foo\\uFEFFbar" in data
    assert "\ufeff".encode("utf-8") not in data


def test_pdf_beginann_endann_and_dest_create_link(cmr10, tmp_path):
    out = tmp_path / "pdf-link"
    cmr10.shipout = pdf.PDFBackend(cmr10, str(out))
    cmr10.parse(
        r"\shipout\vbox{"
        r"\special{pdf:dest (target.1)[@thispage/XYZ @xpos @ypos null]}"
        r"\special{pdf: beginann <</Type/Annot/Border [0 0 1] /H /I /C [0.7 0.4 0.41] /Subtype/Link/A<</S/GoTo/D(target.1)>>>>}"
        r"\hbox{a}"
        r"\special{pdf: endann}"
        r"}",
        jobname="pdf-link",
    )
    cmr10.end()
    reader = PdfReader(str(out) + ".pdf", strict=False)
    page = reader.pages[0]
    annots = page.get("/Annots")
    assert annots is not None
    assert len(annots) == 1
    annot = annots[0].get_object()
    assert list(annot["/Border"]) == [0, 0, 1]
    assert annot["/H"] == "/I"
    assert list(annot["/C"]) == [0.7, 0.4, 0.41]
