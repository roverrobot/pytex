"""ReportLab-backed PDF shipout backend."""

from __future__ import annotations

from io import BytesIO
import os
import re

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.pdfbase.pdfdoc import PDFArray, PDFName
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import EmbeddedType1Face, Font as ReportLabFont, registerFont, registerTypeFace
from reportlab.pdfbase.ttfonts import TTFont as ReportLabTTFont
from reportlab.pdfgen import canvas as reportlab_canvas
from reportlab.lib.rl_accel import fp_str

from pytex import node as nd
from pytex.dimen import Dimen, NEG_MAX_DIMEN, UNITS
from pytex.module import Module
from pytex.typeset.shipout import Shipout


_DIMEN_RE = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))([A-Za-z]+)\s*$")
_PDF_PAGESIZE_RE = re.compile(
    r"^\s*pdf:\s*pagesize\s+width\s+(\S+)\s+height\s+(\S+)\s*$",
    re.IGNORECASE,
)
_PAPERSIZE_RE = re.compile(r"^\s*papersize=(\S+),(\S+)\s*$", re.IGNORECASE)
_PDF_DEST_RE = re.compile(
    r"^\s*pdf:\s*dest\s+(\(.*\))\s*\[\s*@thispage\s*/XYZ\s+@xpos\s+@ypos\s+null\s*\]\s*$",
    re.IGNORECASE,
)
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
_ONE_INCH = Dimen(integer=Dimen._trunc_div(UNITS["in"][0] * Dimen.scale, UNITS["in"][1]))


class PDFBackend(Shipout):
    """Direct PDF backend built on top of ReportLab."""

    def __init__(self, parser, output=None):
        super().__init__(parser, output)
        self.file = None
        self._canvas_output = None
        self.canvas = None
        self._canvas_buffer = None
        self.current_font = None
        self.current_font_name = None
        self._font_names = {}
        self._font_counter = 0
        self._type1_faces = {}
        self.page_width = 0
        self.page_height = 0
        self._color_stack = []
        self._current_color = ("gray", ("0",))
        self._origin_x = int(_ONE_INCH)
        self._origin_y = int(_ONE_INCH)
        self._page_overlays = []
        self._pdf_sources = {}
        self._active_annotations = []
        self._reportlab_bug_warnings = set()

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
        return value * num / den * Dimen.scale

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
        origin_x = int(_ONE_INCH) + int(self.parser.layout["hoffset"])
        origin_y = int(_ONE_INCH) + int(self.parser.layout["voffset"])
        if width <= 0:
            width = int(box.width) + 2 * origin_x
        if height <= 0:
            height = int(box.height + box.depth) + 2 * origin_y
        return width, height

    def _x(self, h):
        return self._pt(self._origin_x + int(h))

    def _page_y(self, v):
        return self._pt(self.page_height - (self._origin_y + int(v)))

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

    def _raw_pagesize(self, text):
        match = _PDF_PAGESIZE_RE.match(text)
        if match is None:
            match = _PAPERSIZE_RE.match(text)
        if match is None:
            return False
        width = int(self._parse_special_dimen(match.group(1)))
        height = int(self._parse_special_dimen(match.group(2)))
        self.page_width = width
        self.page_height = height
        self.canvas.setPageSize((self._pt(width), self._pt(height)))
        return True

    def _raw_dest(self, text):
        match = _PDF_DEST_RE.match(text)
        if match is None:
            return False
        name = self._decode_pdf_string(match.group(1))
        self.canvas.bookmarkHorizontalAbsolute(name, self._page_y(self.v), left=self._x(self.h))
        return True

    @staticmethod
    def _options_map(options):
        return {key: value for key, value in options or ()}

    @classmethod
    def _source_path(cls, parser, source):
        name = cls._decode_pdf_string(source)
        try:
            path = parser.resolver._sourcePath(name)
        except ValueError:
            return name, None
        if not os.path.exists(path):
            return name, None
        return name, path

    @staticmethod
    def _bbox_from_options(options):
        bbox = options.get("bbox")
        if bbox is None:
            return (0.0, 0.0, 0.0, 0.0)
        return tuple(float(v) for v in bbox)

    @classmethod
    def _target_size(cls, options, bbox):
        natural_width = bbox[2] - bbox[0]
        natural_height = bbox[3] - bbox[1]
        width = options.get("width")
        height = options.get("height")
        width = None if width is None else cls._pt(cls._parse_special_dimen(width))
        height = None if height is None else cls._pt(cls._parse_special_dimen(height))
        if width is None and height is None:
            width = natural_width
            height = natural_height
        elif width is None:
            width = natural_width * height / natural_height
        elif height is None:
            height = natural_height * width / natural_width
        scale = float(options.get("scale", "1"))
        xscale = float(options.get("xscale", "1"))
        yscale = float(options.get("yscale", "1"))
        width *= scale * xscale
        height *= scale * yscale
        return width, height

    def _queue_epdf_overlay(self, options, source):
        page_number = int(options.get("page", "1"))
        pagebox = str(options.get("pagebox", "cropbox")).lower()
        bbox = self._bbox_from_options(options)
        target_width, target_height = self._target_size(options, bbox)
        x = self._x(self.h)
        y = self._page_y(self.v) - target_height
        self._page_overlays[-1].append(
            {
                "kind": "epdf",
                "source": source,
                "page": page_number,
                "pagebox": pagebox,
                "bbox": bbox,
                "width": target_width,
                "height": target_height,
                "x": x,
                "y": self._page_y(self.v),
                "rotate": float(options.get("rotate", "0")),
            }
        )

    @staticmethod
    def _parse_annotation_payload(payload):
        info = {"kind": "raw", "payload": payload}
        border = re.search(r"/Border\s*\[(.*?)\]", payload)
        if border is not None:
            info["border"] = [float(part) for part in border.group(1).split()]
        color = re.search(r"/C\s*\[(.*?)\]", payload)
        if color is not None:
            info["color"] = [float(part) for part in color.group(1).split()]
        highlight = re.search(r"/H\s*/([A-Za-z]+)", payload)
        if highlight is not None:
            info["highlight"] = highlight.group(1)
        goto = re.search(r"/S\s*/GoTo\s*/D\s*\((.*?)\)", payload)
        if goto is not None:
            info["kind"] = "goto"
            info["destination"] = goto.group(1)
            return info
        uri = re.search(r"/S\s*/URI\s*/URI\s*\((.*?)\)", payload)
        if uri is not None:
            info["kind"] = "uri"
            info["url"] = uri.group(1)
            return info
        return info

    def _new_annotation_rect(self):
        return [None, None, None, None]

    def _grow_annotation_rect(self, x0, y0, x1, y1):
        for ann in self._active_annotations:
            rect = ann["rect"]
            rect[0] = x0 if rect[0] is None else min(rect[0], x0)
            rect[1] = y0 if rect[1] is None else min(rect[1], y0)
            rect[2] = x1 if rect[2] is None else max(rect[2], x1)
            rect[3] = y1 if rect[3] is None else max(rect[3], y1)

    def _annotation_rect_tuple(self, rect):
        if rect[0] is None:
            return None
        return tuple(rect)

    @staticmethod
    def _annotation_style_kwargs(info):
        kwargs = {}
        if "border" in info:
            kwargs["Border"] = PDFArray(info["border"])
        if "color" in info:
            kwargs["C"] = PDFArray(info["color"])
        if "highlight" in info:
            kwargs["H"] = PDFName(info["highlight"])
        return kwargs

    def _annotation_font_box(self, x, y, width):
        size = float(getattr(self.current_font, "at", 10.0) or 10.0)
        return x, y - 0.2 * size, x + width, y + 0.8 * size

    def _pdf_source_reader(self, name):
        reader = self._pdf_sources.get(name)
        if reader is not None:
            return reader
        _decoded, path = self._source_path(self.parser, f"({name})")
        if path is None:
            raise FileNotFoundError(name)
        reader = PdfReader(path)
        self._pdf_sources[name] = reader
        return reader

    @staticmethod
    def _page_box(page, pagebox):
        if pagebox == "mediabox":
            return tuple(map(float, page.mediabox))
        if pagebox == "cropbox":
            return tuple(map(float, page.cropbox))
        if pagebox == "bleedbox":
            return tuple(map(float, page.bleedbox))
        if pagebox == "trimbox":
            return tuple(map(float, page.trimbox))
        if pagebox == "artbox":
            return tuple(map(float, page.artbox))
        return tuple(map(float, page.cropbox))

    def _apply_overlays(self, data):
        if not any(self._page_overlays):
            return data
        writer = PdfWriter(clone_from=BytesIO(data))
        for page_index, page in enumerate(writer.pages):
            for overlay in self._page_overlays[page_index]:
                if overlay["kind"] != "epdf":
                    continue
                source_reader = self._pdf_source_reader(overlay["source"])
                source_page = source_reader.pages[overlay["page"] - 1]
                source_box = self._page_box(source_page, overlay["pagebox"])
                llx, lly, urx, ury = overlay["bbox"]
                if llx == lly == urx == ury == 0.0:
                    llx, lly, urx, ury = source_box
                sx = overlay["width"] / (urx - llx)
                sy = overlay["height"] / (ury - lly)
                transform = Transformation().scale(sx, sy)
                if overlay["rotate"]:
                    transform = transform.rotate(overlay["rotate"])
                transform = transform.translate(overlay["x"] - llx * sx, overlay["y"] - lly * sy)
                page.merge_transformed_page(source_page, transform, over=True)
        out = BytesIO()
        writer.write(out)
        return out.getvalue()

    def _register_opentype(self, font, font_name):
        path = getattr(font.backend, "path", None)
        if not path:
            raise ValueError(
                f"PDF backend needs a filesystem-backed font file for OpenType font {font.backend.name}"
            )
        registerFont(ReportLabTTFont(font_name, path, subfontIndex=getattr(font.backend, "font_number", 0)))

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
        safe = message.replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")
        self.canvas.addLiteral(f"% {safe}")

    def _warn_reportlab_non_bmp(self, char):
        code = ord(char)
        if code <= 0xFFFF:
            return
        if code in self._reportlab_bug_warnings:
            return
        self._reportlab_bug_warnings.add(code)
        font_name = getattr(getattr(self.current_font, "backend", None), "name", "<unknown>")
        self.parser.message(
            f"Warning: direct PDF output via ReportLab may misrender non-BMP character {char} (U+{code:04X}) in font {font_name}.",
            console=False,
        )

    def open(self, output=None):
        if self.canvas is not None:
            return
        if output is None:
            output = self.output
        if output is None:
            output = self.parser.jobname or "texput"
        if hasattr(output, "write"):
            self._canvas_output = output
        else:
            name = os.fspath(output)
            if os.path.isabs(name):
                if not name.endswith(".pdf"):
                    name += ".pdf"
                self._canvas_output = open(name, "wb")
            else:
                self._canvas_output = self.parser.resolver.openOut(name, "shipout/pdf")
        self._canvas_buffer = BytesIO()
        self.canvas = reportlab_canvas.Canvas(self._canvas_buffer, pagesize=(1, 1), pageCompression=0)
        self.canvas.setTitle(self.parser.jobname or "texput")

    def close(self):
        canvas = self.canvas
        if canvas is None:
            return
        self.canvas = None
        canvas.save()
        data = self._canvas_buffer.getvalue()
        data = self._apply_overlays(data)
        self._canvas_output.write(data)
        self._canvas_buffer = None
        self.current_font = None
        self.current_font_name = None
        self._page_overlays = []
        self._pdf_sources = {}
        if self._canvas_output is not None:
            self._canvas_output.close()
            self._canvas_output = None

    def begin_page(self, box):
        if self.canvas is None:
            self.open()
        self.page_width, self.page_height = self._page_size(box)
        self._origin_x = int(_ONE_INCH) + int(self.parser.layout["hoffset"])
        self._origin_y = int(_ONE_INCH) + int(self.parser.layout["voffset"])
        self.canvas.setPageSize((self._pt(self.page_width), self._pt(self.page_height)))
        self.current_font = None
        self.current_font_name = None
        self._color_stack = []
        self._current_color = ("gray", ("0",))
        self._page_overlays.append([])
        self._active_annotations = []
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

    def _draw_raw_8bit_char(self, char, x, y, size):
        font_name = self.current_font_name
        if font_name is None:
            return False
        font = pdfmetrics.getFont(font_name)
        if getattr(font, "_dynamicFont", False) or getattr(font, "_multiByte", False):
            return False
        code = ord(char)
        if code < 0 or code > 0xFF:
            return False
        internal_name = self.canvas._doc.getInternalFontName(font_name)
        escaped = self.canvas._escape(bytes((code,)))
        self.canvas.addLiteral(
            f"BT 1 0 0 1 {fp_str(x)} {fp_str(y)} Tm {internal_name} {fp_str(size)} Tf {fp_str(size * 1.2)} TL ({escaped}) Tj T* ET"
        )
        return True

    def set_char(self, node):
        self._warn_reportlab_non_bmp(node.char)
        x = self._x(self.h)
        y = self._page_y(self.v)
        if getattr(getattr(self.current_font, "backend", None), "kind", None) == "tfm" and self._draw_raw_8bit_char(
            node.char, x, y, float(self.current_font.at)
        ):
            pass
        else:
            self.canvas.drawString(x, y, node.char)
        if self._active_annotations:
            self._grow_annotation_rect(*self._annotation_font_box(x, y, self._pt(node.width)))

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
        x = self._x(self.h)
        y = self._page_y(self.v) - total_height
        self.canvas.rect(x, y, self._pt(width), total_height, stroke=0, fill=1)
        if self._active_annotations:
            self._grow_annotation_rect(x, y, x + self._pt(width), y + total_height)

    def rawSpecial(self, text):
        if not self._raw_pagesize(text) and not self._raw_dest(text):
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
        if kind == "begin":
            self._active_annotations.append(
                {
                    "info": self._parse_annotation_payload(payload),
                    "rect": self._new_annotation_rect(),
                }
            )
            return
        if kind == "end":
            if not self._active_annotations:
                return
            ann = self._active_annotations.pop()
            rect = self._annotation_rect_tuple(ann["rect"])
            if rect is None:
                return
            info = ann["info"]
            style = self._annotation_style_kwargs(info)
            if info["kind"] == "goto":
                self.canvas.linkAbsolute("", info["destination"], Rect=rect, **style)
                return
            if info["kind"] == "uri":
                self.canvas.linkURL(info["url"], rect, relative=0, **style)
                return
            self._note_ignored(f"annotate ignored: {payload}")
            return
        if kind == "fixed":
            dims = dict(dimensions or ())
            width = self._pt(self._parse_special_dimen(dims.get("width", "0pt")))
            height = self._pt(self._parse_special_dimen(dims.get("height", "0pt")))
            depth = self._pt(self._parse_special_dimen(dims.get("depth", "0pt")))
            x = self._x(self.h)
            y = self._page_y(self.v) - depth
            rect = (x, y, x + width, y + height)
            info = self._parse_annotation_payload(payload)
            style = self._annotation_style_kwargs(info)
            if info["kind"] == "goto":
                self.canvas.linkAbsolute("", info["destination"], Rect=rect, **style)
                return
            if info["kind"] == "uri":
                self.canvas.linkURL(info["url"], rect, relative=0, **style)
                return
        self._note_ignored(f"annotate ignored: {kind}")

    def xObject(self, kind, name=None, options=None, source=None):
        options = self._options_map(options)
        if kind == "image" and source:
            decoded, path = self._source_path(self.parser, source)
            if path is None:
                self._note_ignored(f"xObject image missing: {decoded}")
                return
            bbox = self._bbox_from_options(options)
            target_width, target_height = self._target_size(options, bbox)
            x = self._x(self.h)
            y = self._page_y(self.v)
            self.canvas.drawImage(path, x, y, width=target_width, height=target_height)
            if self._active_annotations:
                self._grow_annotation_rect(x, y, x + target_width, y + target_height)
            return
        if kind == "epdf" and source:
            decoded = self._decode_pdf_string(source)
            self._queue_epdf_overlay(options, decoded)
            if self._active_annotations:
                bbox = self._bbox_from_options(options)
                target_width, target_height = self._target_size(options, bbox)
                x = self._x(self.h)
                y = self._page_y(self.v)
                self._grow_annotation_rect(x, y, x + target_width, y + target_height)
            return
        self._note_ignored(f"xObject ignored: {kind}")


def init(parser):
    parser.shipout = PDFBackend(parser)


mod = Module(
    "pdf",
    init=init,
    attributes={}
)
