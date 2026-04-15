from io import BytesIO
import os
import types

from pypdf import PdfReader
from reportlab.pdfbase.pdfmetrics import EmbeddedType1Face, Font as ReportLabFont, registerFont, registerTypeFace
from reportlab.pdfgen import canvas

from pytex import pdf


def _cmr12_type1_paths():
    candidates = [
        (
            "/usr/share/texlive/texmf-dist/fonts/afm/public/amsfonts/cm/cmr12.afm",
            "/usr/share/texlive/texmf-dist/fonts/type1/public/amsfonts/cm/cmr12.pfb",
        ),
        (
            "/usr/local/texlive/2023/texmf-dist/fonts/afm/public/amsfonts/cm/cmr12.afm",
            "/usr/local/texlive/2023/texmf-dist/fonts/type1/public/amsfonts/cm/cmr12.pfb",
        ),
    ]
    for afm, pfb in candidates:
        if os.path.exists(afm) and os.path.exists(pfb):
            return afm, pfb
    raise FileNotFoundError("cmr12 Type 1 resources not found")


def _register_cmr12(font_name="TestCMR12LigaturePDF"):
    afm, pfb = _cmr12_type1_paths()
    face = EmbeddedType1Face(afm, pfb)
    registerTypeFace(face)
    encoding = getattr(face, "requiredEncoding", None) or f"rl_dynamic_{face.name}_encoding"
    registerFont(ReportLabFont(font_name, face.name, encoding))
    return font_name


def test_pdf_backend_emits_raw_8bit_tfm_ligature_codes():
    font_name = _register_cmr12()
    out = BytesIO()
    backend = pdf.PDFBackend.__new__(pdf.PDFBackend)
    backend.canvas = canvas.Canvas(out, pagesize=(200, 200), pageCompression=0)
    backend.canvas.setFont(font_name, 12)
    backend.current_font_name = font_name
    backend.current_font = types.SimpleNamespace(at=12, backend=types.SimpleNamespace(kind="tfm", name="cmr12"))
    backend._active_annotations = []
    backend._reportlab_bug_warnings = set()
    backend.parser = types.SimpleNamespace(message=lambda *args, **kwargs: None)
    backend.page_height = 200
    backend._origin_x = 0
    backend._origin_y = 0
    backend.h = 0
    backend.v = 0

    node = types.SimpleNamespace(char=chr(14), width=0)
    backend.set_char(node)
    backend.canvas.save()

    data = out.getvalue()
    assert b"ZapfDingbats" not in data

    reader = PdfReader(BytesIO(data))
    page = reader.pages[0]
    content = page.get_contents().get_data().decode("latin1", "replace")
    assert r"(\016) Tj" in content
