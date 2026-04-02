"""ReportLab-backed PDF shipout backend."""

from __future__ import annotations

import os
import re

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import EmbeddedType1Face, Font as ReportLabFont, registerFont, registerTypeFace
from reportlab.pdfbase.ttfonts import TTFont as ReportLabTTFont
from reportlab.pdfgen import canvas as reportlab_canvas

from pytex import node as nd
from pytex.dimen import Dimen, NEG_MAX_DIMEN, UNITS
from pytex.module import Module
from pytex.typeset.shipout import Shipout


_DIMEN_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))([A-Za-z]+)\s*$")
_PDF_STRING_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "b": "\b",
    "f": "\f",
    "\\": "\\",
    "(": "(",
    ")": ")",
}


class PDFBackend(Shipout):
    """Direct PDF backend built on top of ReportLab."""

    def __init__(self, parser, output=None):
        super().__init__(parser, output)
        self.file = None
        self.canvas = None
        self.current_font = None
        self.current_font_name = None
        self._font_names = {}
        self._font_counter = 0
        self._type1_faces = {}
        self.page_width = 0
        self.page_height = 0
        self._color_stack = []
        self._current_color = ("gray", ("0",))

    @staticmethod
    def _pt(value):
        return int(value) / Dimen.scale

    @staticmethod
    def _resource_path(parser, name, file_type):
        try:
            handle = parser.resolver.openIn(name, file_type)
        except FileNotFoundError:
            return None
        if handle is None:
            return None
        try:
            path = getattr(handle, "name", None)
        finally:
            handle.close()
        if isinstance(path, str) and os.path.exists(path):
            return path
        return None

    @staticmethod
    def _parse_special_dimen(token):
        match = _DIMEN_RE.match(token)
        if match is None:
            raise ValueError(f"invalid special dimension {token}")
        value = float(match.group(1))
        unit = match.group(2).lower()
        if unit not in UNITS:
            raise ValueError(f"unsupported special unit {unit}")
        num, den = UNITS[unit]
        return value * num / den

    @staticmethod
    def _decode_pdf_string(token):
        if len(token) < 2 or token[0] != "(" or token[-1] != ")":
            return token
        out = []
        i = 1
        while i < len(token) - 1:
            ch = token[i]
            if ch == "\\" and i + 1 < len(token) - 1:
                i += 1
                esc = token[i]
                out.append(_PDF_STRING_ESCAPES.get(esc, esc))
            else:
                out.append(ch)
            i += 1
        return "".join(out)

    def _page_size(self, box):
        width_param = self.parser.parameters["pdfpagewidth"]
        height_param = self.parser.parameters["pdfpageheight"]
        width = 0 if width_param is None else int(width_param)
        height = 0 if height_param is None else int(height_param)
        if width <= 0:
            width = int(box.width) + 2 * int(self.parser.layout["hoffset"])
        if height <= 0:
            height = int(box.height + box.depth) + 2 * int(self.parser.layout["voffset"])
        return width, height

    def _baseline(self, v):
        return self._pt(self.page_height - int(v))

    def _top(self, v):
        return self._pt(self.page_height - int(v))

    def _set_canvas_color(self, space, values):
        vals = tuple(float(v) for v in (values or ()))
        if space == "gray":
            gray = vals[0]
            self.canvas.setFillGray(gray)
            self.canvas.setStrokeGray(gray)
            return
        if space == "rgb":
            r, g, b = vals
            self.canvas.setFillColorRGB(r, g, b)
            self.canvas.setStrokeColorRGB(r, g, b)
            return
        if space == "cmyk":
            c, m, y, k = vals
            self.canvas.setFillColorCMYK(c, m, y, k)
            self.canvas.setStrokeColorCMYK(c, m, y, k)
            return
        raise ValueError(f"unsupported color space {space}")

    def _register_opentype(self, font, font_name):
        path = getattr(font.backend, "path", None)
        if not path:
            raise ValueError(
                f"PDF backend needs a filesystem-backed font file for OpenType font {font.backend.name}"
            )
        registerFont(ReportLabTTFont(font_name, path))

    def _register_type1(self, font, font_name):
        base = font.backend.name
        face_info = self._type1_faces.get(base)
        if face_info is None:
            afm = self._resource_path(self.parser, base + ".afm", "fonts/afm")
            pfb = self._resource_path(self.parser, base + ".pfb", "fonts/type1")
            if afm is None or pfb is None:
                raise ValueError(f"PDF backend could not find companion Type 1 files for {base}")
            face = EmbeddedType1Face(afm, pfb)
            registerTypeFace(face)
            face_info = (face.name, getattr(face, "requiredEncoding", None) or f"rl_dynamic_{face.name}_encoding")
            self._type1_faces[base] = face_info
        face_name, encoding = face_info
        registerFont(ReportLabFont(font_name, face_name, encoding))

    def _register_companion_outline(self, font, font_name):
        base = font.backend.name
        for resource_name, resource_type in (
            (base + ".otf", "fonts/opentype"),
            (base + ".ttf", "fonts/truetype"),
        ):
            path = self._resource_path(self.parser, resource_name, resource_type)
            if path is not None:
                registerFont(ReportLabTTFont(font_name, path))
                return
        self._register_type1(font, font_name)

    def _font_name(self, font):
        name = self._font_names.get(id(font))
        if name is not None:
            return name
        name = f"PyTeXFont{self._font_counter}"
        self._font_counter += 1
        kind = getattr(font.backend, "kind", None)
        if kind == "opentype":
            self._register_opentype(font, name)
        elif kind == "tfm":
            self._register_companion_outline(font, name)
        else:
            raise ValueError(f"PDF backend does not support backend kind {kind}")
        self._font_names[id(font)] = name
        return name

    def _note_ignored(self, message):
        self.canvas.addLiteral(f"% {message}")

    def open(self, output=None):
        if self.canvas is not None:
            return
        if output is None:
            output = self.output
        if output is None:
            output = self.parser.jobname or "texput"
        if hasattr(output, "write"):
            self.file = output
        else:
            name = os.fspath(output)
            if os.path.isabs(name):
                if not name.endswith(".pdf"):
                    name += ".pdf"
                self.file = open(name, "wb")
            else:
                self.file = self.parser.resolver.openOut(name, "shipout/pdf")
        self.canvas = reportlab_canvas.Canvas(self.file, pagesize=(1, 1), pageCompression=0)
        self.canvas.setTitle(self.parser.jobname or "texput")

    def close(self):
        if self.canvas is None:
            return
        self.canvas.save()
        self.canvas = None
        self.current_font = None
        self.current_font_name = None
        if self.file is not None:
            self.file.close()
            self.file = None

    def begin_page(self, box):
        if self.canvas is None:
            self.open()
        self.page_width, self.page_height = self._page_size(box)
        self.canvas.setPageSize((self._pt(self.page_width), self._pt(self.page_height)))
        self.current_font = None
        self.current_font_name = None
        self._color_stack = []
        self._current_color = ("gray", ("0",))
        self._set_canvas_color(*self._current_color)

    def end_page(self, box):
        self.canvas.showPage()

    def define_font(self, font):
        self._font_name(font)

    def select_font(self, font):
        if self.current_font is font:
            return
        font_name = self._font_name(font)
        self.canvas.setFont(font_name, float(font.at))
        self.current_font = font
        self.current_font_name = font_name

    def move_to(self, h, v):
        self.h = 0 if h is None else int(h)
        self.v = 0 if v is None else int(v)

    def set_char(self, node):
        self.canvas.drawString(self._pt(self.h), self._baseline(self.v), node.char)

    def set_rule(self, node, box, move):
        def running(d):
            return int(d) <= int(NEG_MAX_DIMEN)

        if box.node_type == nd.NODE_TYPE.VLIST:
            width = int(box.width) if running(node.width) else int(node.width)
            height = int(node.height)
            depth = int(node.depth)
        else:
            width = int(node.width)
            height = int(box.height) if running(node.height) else int(node.height)
            depth = int(box.depth) if running(node.depth) else int(node.depth)
        total_height = self._pt(height + depth)
        x = self._pt(self.h)
        y = self._top(self.v) - total_height
        self.canvas.rect(x, y, self._pt(width), total_height, stroke=0, fill=1)

    def rawSpecial(self, text):
        self._note_ignored(f"rawSpecial ignored: {text}")

    def setColor(self, mode, space=None, values=None):
        if mode == "push":
            self._color_stack.append(self._current_color)
            self._current_color = (space, tuple(values))
            self._set_canvas_color(space, values)
            return
        if mode == "pop":
            self._current_color = self._color_stack.pop() if self._color_stack else ("gray", ("0",))
            self._set_canvas_color(*self._current_color)
            return
        if mode == "set":
            self._current_color = (space, tuple(values))
            self._set_canvas_color(space, values)
            return
        if mode == "background":
            saved = self._current_color
            self._set_canvas_color(space, values)
            self.canvas.rect(0, 0, self._pt(self.page_width), self._pt(self.page_height), stroke=0, fill=1)
            self._set_canvas_color(*saved)
            return
        raise ValueError(f"unsupported color mode {mode}")

    def annotate(self, kind, name=None, dimensions=None, payload=None):
        self._note_ignored(f"annotate ignored: {kind}")

    def xObject(self, kind, name=None, options=None, source=None):
        if kind == "image" and source:
            self._note_ignored(f"xObject image not yet implemented: {source}")
            return
        self._note_ignored(f"xObject ignored: {kind}")


def init(parser):
    parser.shipout = PDFBackend(parser)


mod = Module(
    "pdf",
    init=init,
    attributes={}
)
