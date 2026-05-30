"""HTML reflow backend driven by the outer-vlist raw history."""

from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import shutil

from pytex import align
from pytex import box as bx
from pytex import mmode
from pytex import node as nd
from pytex.dimen import Dimen
from pytex.module import Module
from pytex import reflow
from pytex.font import Font
from pytex import font_subst
from lxml.html import builder
from lxml import etree
from lxml.builder import ElementMaker

_GOTO_RE = re.compile(r"/S\s*/GoTo\b.*?/D\s*\(([^()]*)\)", re.IGNORECASE | re.DOTALL)
_GOTOR_RE = re.compile(
    r"/S\s*/GoToR\b.*?/F\s*\(([^()]*)\)(?:.*?/D\s*\(([^()]*)\))?",
    re.IGNORECASE | re.DOTALL,
)
_URI_RE = re.compile(r"/S\s*/URI\b.*?/URI\s*\(([^()]*)\)", re.IGNORECASE | re.DOTALL)


def _font_family_name(backend):
    return font_subst.fontBackendName(backend) or getattr(backend, "name", None)


_CSS_POINTS_PER_TEX_POINT_NUM = 7200
_CSS_POINTS_PER_TEX_POINT_DEN = 7227
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


# Define shortcuts for common MathML tags
E = ElementMaker(namespace="http://www.w3.org/1998/Math/MathML",
                 nsmap={None: "http://www.w3.org/1998/Math/MathML"})
MATH = E.math
MI = E.mi
MO = E.mo
MN = E.mn
MROW = E.mrow
MSUP = E.msup
MSUB = E.msub
MSUBSUP = E.msubsup
MFRAC = E.mfrac
MENCLOSE = E.menclose
MOVER = E.mover
MSQRT = E.msqrt
MTEXT = E.mtext
MTABLE = E.mtable
MTR = E.mtr
MTD = E.mtd


def _color(color: reflow.Color)->str:
    """
    convert the color specification to CSS string
    """
    r, g, b, a = color.rgba
    return f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"


def _style(style: dict):
    return "".join([f"{key}:{val};" for key, val in style.items()])


class StyledNode:
    def __init__(self, node=None):
        self._style = None

    @property
    def style(self):
        if self._style is None:
            self._style = {}
        return self._style

    @property
    def node(self):
        if self._style is not None:
            self._node.set("style",  _style(self._style))
        return super().node


class AnnotationBuilder(reflow.AnnotationBuilder):
    def __init__(self, backend, parent, href):
        super().__init__(backend, parent, href)
        self.link = reflow.Element(builder.A(href=href))
        line_box = bx.HBox(self.backend.parser, None, None)
        line_box.typeset(self.backend.parser, [])
        line_spec = reflow.LineSpec(self.backend, line_box, spacing_before=Dimen())
        self.container = Line(line_spec)
        self.link.append(self.container)

    def beginAnnotation(self, name):
        self.parent.append(self.link)


class FixedAnnotation(StyledNode, reflow.Element):
    def __init__(self, target: str, width: float, height: float, border_color: reflow.Color=reflow.Color.red, border_width: float=1, corner_radius: float=1):
        """here the dimensions are in postscript pt, i.e., tex bp"""
        node = builder.A(href=f"#{target}")
        reflow.Element.__init__(self, node)
        StyledNode.__init__(self)
        self.style["border-width"] = border_width
        self.style["border-color"] = _color(border_color)
        self.style["border-style"] = "solid"
        self.style["width"] = Dimen()
        self.style["hright"] = Dimen()
        div = builder.DIV(style=f"width={width}pt;height={height}pt;")
        node.append(div)


class TextRun(StyledNode, reflow.TextRun):
    def __init__(
        self,
        line,
        text,
        font: Font,
        color: reflow.Color=reflow.Color.black,
        baseline_from_bottom: Dimen=Dimen(),
    ):
        if text is None:
            text = ""
        span = builder.SPAN(text)
        StyledNode.__init__(self)
        self.line = line
        reflow.TextRun.__init__(
            self,
            span,
            text=text,
            font=font,
            color=color,
            baseline_from_bottom=baseline_from_bottom,
        )
        self.style["color"] = _color(color)
        if font is not None:
            self.style["font-family"] = _font_family_name(font.backend)
            self.style["font-size"] = reflow.PT(font.at)

    def newSpace(self, width: Dimen, breakable: bool):
        self._node.text = "" if breakable else "\xa0"
        self.style["display"] = "inline-block"
        if int(width) < 0:
            self.style["margin-left"] = reflow.PT(width)
        else:
            self.style["width"] = reflow.PT(width)

    def newInlineVBox(self, box: bx.Box):
        div = Div(inline=True)
        self.append(div)
        return div

    def newInlineMath(self):
        math = Math(inline=True)
        self.append(math)
        return math


class Space(StyledNode, reflow.Element):
    def __init__(self, width: Dimen, breakable: bool):
        space = "" if breakable else "\xa0"
        StyledNode.__init__(self)
        reflow.Element.__init__(self, builder.SPAN(space))
        self.style["display"] = "inline-block"
        if int(width) < 0:
            self.style["margin-left"] = reflow.PT(width)
        else:
            self.style["width"] = reflow.PT(width)


class Line(StyledNode, reflow.Line):
    def __init__(self, line_spec: reflow.LineSpec):
        StyledNode.__init__(self)
        reflow.Line.__init__(self, builder.SPAN(), line_spec)

    def newTextRun(self, text, font, color, baseline_from_bottom):
        self.registerBackendBaseline(font)
        text_run = TextRun(self, text, font, color, baseline_from_bottom=baseline_from_bottom)
        self.append(text_run)
        return text_run
    
    def newSpace(self, width: Dimen, breakable: bool):
        if reflow.PT(width) == "0.0pt":
            return None
        s =Space(width, breakable)
        self.append(s)
        return s


class Paragraph(StyledNode, reflow.Paragraph):
    def __init__(self, spacing_before=Dimen(), justify="justify"):
        node = builder.DIV()
        StyledNode.__init__(self)
        reflow.Paragraph.__init__(self, node, spacing_before, justify)
        self.style["padding-top"] = reflow.PT(spacing_before)
        self.style["width"] = "100%"
        self.last_line = None

    def setJustify(self, justify):
        self.style["justify"] = justify
        self.style["text-align"] = justify
        self.justify = justify

    def newLine(self, line_spec: reflow.LineSpec) -> Line:
        if self.last_line is not None:
            self.last_line.newSpace(self.last_line.font.param[1], breakable=True)
        line = Line(line_spec)
        self.last_line = line
        self.append(line)
        return line


class MFrac(reflow.Element):
    def __init__(self, num, den, bar, thickness):
        super().__init__(MFRAC())
        self.append(num)
        self.append(den)
        if not bar:
            thickness = 0
        if thickness is not None:
            self._node.set("linethickness", reflow.PT(thickness))


class MRow(reflow.Element):
    def __init__(self):
        super().__init__(MROW())


class Math(StyledNode, reflow.Math):
    def __init__(self, inline: bool):
        math = MATH(display="inline" if inline else "block")
        StyledNode.__init__(self)
        reflow.Math.__init__(self, math, inline)


class Graphic(StyledNode, reflow.Element):
    def __init__(self, src, media_type, width=None, height=None, inline=True, transform_scale=(1.0, 1.0)):
        if media_type == "pdf":
            node = builder.OBJECT(
                builder.A("PDF", href=src),
                data=src,
                type="application/pdf",
            )
        else:
            node = builder.IMG(src=src, alt="")
        StyledNode.__init__(self)
        reflow.Element.__init__(self, node)
        self.style["display"] = "inline-block" if inline else "block"
        self.style["vertical-align"] = "baseline"
        if width is not None:
            self.style["width"] = width
        if height is not None:
            self.style["height"] = height
        if media_type == "pdf":
            self.style["border"] = "0"
        sx, sy = transform_scale
        if sx != 1.0 or sy != 1.0:
            self.style["transform"] = f"scale({sx},{sy})"
            self.style["transform-origin"] = "left bottom"


class Cell(StyledNode, reflow.Cell):
    def __init__(self, span, width, relative_width=None, justify: str="justify"):
        StyledNode.__init__(self)
        reflow.Cell.__init__(self, builder.TD(), span, width, justify)
        if relative_width is None:
            width = "auto" if width is None else reflow.PT(width)
        else:
            width = f"{relative_width*100}%"
        self.style["width"] = width
        text_align = justify
        if text_align == "justified":
            text_align = "justify"
        self.style["justify"] = justify
        self.style["white-space"] = "nowrap"
        if text_align in ("left", "right", "center", "justify"):
            self.style["text-align"] = text_align
        self.style["vertical-align"] = "baseline"

    def newParagraph(self) -> Paragraph:
        para = Paragraph(justify=self.justify)
        self.append(para)
        return para


class Row(StyledNode, reflow.Row):
    def __init__(self):
        tr = builder.TR()
        StyledNode.__init__(self)
        reflow.Row.__init__(self, tr)
        self.style["width"] = "100%"

    def newCell(self, span=1, width=None, relative_width=None, justify="justify") -> Cell:
        td = Cell(span, width, relative_width, justify)
        self.append(td)
        return td


class Table(StyledNode, reflow.Table):
    def __init__(self, xspacing=Dimen(), yspacing=Dimen()):
        table = builder.TABLE()
        table.set("class", "alignment")
        StyledNode.__init__(self)
        reflow.Table.__init__(self, table, xspacing, yspacing)
        self.style["margin-top"] = reflow.PT(yspacing)
        self.style["border-spacing"] = "0"
        self.style["width"]="100%"
        self.style["padding-left"] = reflow.PT(xspacing)
        self.style["padding-top"] = reflow.PT(yspacing)

    def newRow(self, row_box=None, spacing_before=Dimen()) -> Row:
        tr = Row()
        self.append(tr)
        return tr


class Block(StyledNode, reflow.Block):
    """
    This is an abstraction of HBox and VBox
    """
    def __init__(self, node, inline = False, xspacing=Dimen(), yspacing=Dimen()):
        StyledNode.__init__(self)
        reflow.Block.__init__(self, node, inline, xspacing, yspacing)

    def newParagraph(self, spacing_before=Dimen(), justify: str="left") -> Paragraph:
        para = Paragraph(spacing_before=spacing_before, justify=justify)
        self.append(para)
        return para

    def newTable(self, xspacing: Dimen=Dimen(), yspacing: Dimen=Dimen()):
        table = Table(xspacing, yspacing)
        self.append(table)
        return table

    def newGraph(self, key, type, file):
        pass


class Div(Block):
    def __init__(self, inline: bool=False, xspacing=Dimen(), yspacing=Dimen()):
        div = builder.DIV()
        super().__init__(div, inline, xspacing, yspacing)
        self.style["display"] = "inline-block" if inline else "block"
        self.style["padding-left"] = reflow.PT(xspacing)
        self.style["padding-top"] = reflow.PT(yspacing)


class Head(reflow.Element):
    def __init__(self, title):
        node = builder.HEAD(
            builder.META(charset="utf-8"),
            builder.TITLE(title or "texput"),
        )
        reflow.Element.__init__(self, node)
        self.rules = []
        self._style_node = builder.STYLE("")

    def addRule(self, selector, style):
        self.rules.append((selector, style))

    def clearRules(self):
        self.rules.clear()

    @property
    def node(self):
        css = "".join([f"{selector}{{{_style(style)}}}" for selector, style in self.rules])
        if css:
            self._style_node.text = css
            if self._style_node.getparent() is not self._node:
                self._node.append(self._style_node)
        elif self._style_node.getparent() is self._node:
            self._node.remove(self._style_node)
        return reflow.Element.node.fget(self)


class Document(reflow.Document):
    def __init__(self, title: str, output=None):
        """
        output is a file like structure to write to, typically opened by Parser.resolver.openOut
        or None, which means no output
        """
        super().__init__(builder.HTML(), title, output)
        self._head = Head(title)
        self._body = reflow.Element(builder.BODY())
        self._body_div = Div()
        self._body.append(self._body_div)
        self.append(self._head)
        self.append(self._body)
        self.margin_left = Dimen()

    @property
    def header(self) -> Block:
        pass

    @property
    def body(self) -> Block:
        return self._body_div

    @property
    def footer(self) -> Block:
        pass

    def setBackgroundColor(self, color: reflow.Color):
        pass

    def newPage(self, page_spec: reflow.PageSpec):
        if self.margin_left < page_spec.margin_left:
            self.margin_left = page_spec.margin_left
            self._body_div.style["padding-left"] = reflow.PT(page_spec.margin_left)
            self._body_div.style["padding-right"] = reflow.PT(page_spec.margin_right)
        return self

    def defineFont(self, font):
        pass

    def definePicture(self, key, type, path):
        pass

    def save(self):
        self._node.set("lang", "en")
        s = "<!doctype html>\n" + etree.tostring(
            self.node, method="html", pretty_print=True, encoding="unicode"
        )
        self.output.write(s)
        self.output.close()


class HTMLReflowBackend(reflow.Reflow):
    """
    Null shipout backend for reflow mode.

    We still let TeX/LaTeX run the normal page builder and output routine so
    deferred writes, aux replay, and shipout hooks behave normally. The backend
    itself only executes shipped whatsits; the final HTML is emitted once at
    close from the main vertical list's raw ownership history.
    """

    supported_graphic_formats = ("svg", "png", "jpg", "gif", "webp")

    def __init__(self, parser):
        super().__init__(parser, paginate=False)
        self._pending_media_blocks = []
        self._font_families = {}
        self._font_faces = {}
        self._next_font_face = 1
        self._graphic_assets = {}
        self._next_graphic_asset = 1

    def open(self):
        output = self.parser.jobname
        output = os.fspath(output)
        if output.startswith("./"):
            output = output[2:]
        if not output.endswith(".html"):
            output += ".html"
        self.html_path = Path(self.parser.resolver._outputPath(output))
        output = self.parser.resolver.openOut(output, "shipout")
        return Document(self.parser.jobname, output)

    def close(self):
        if self.document is not None:
            head = self.document._head
            head.clearRules()
            for face in self._font_faces.values():
                src = f'url({self._css_string(self._font_face_url(face, self.html_path))})'
                if face["format_name"] is not None:
                    src += f' format({self._css_string(face["format_name"])})'
                head.addRule(
                    "@font-face",
                    {
                        "font-family": self._css_string(face["family"]),
                        "src": src,
                    },
                )
            head.addRule("math", {"font-family": self._math_font_stack()})
        super().close()

    def newAnnotationBuilder(self, name=None, payload=None):
        info = self._annotation_info(payload or "")
        href = self._annotation_href(info)
        if href is None and name is not None:
            if "#" in name or ":" in name:
                href = name
            else:
                href = "#" + name.lstrip("@")
        return AnnotationBuilder(self, self.builder, href or "#")

    def newFixedAnnotation(self, target, w, h):
        return FixedAnnotation(target, w, h)

    def _css_string(self, text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _annotation_info(self, payload):
        goto = _GOTO_RE.search(payload)
        if goto is not None:
            return {
                "kind": "goto",
                "destination": self._decode_pdf_string(f"({goto.group(1)})"),
            }
        gotor = _GOTOR_RE.search(payload)
        if gotor is not None:
            return {
                "kind": "gotor",
                "file": self._decode_pdf_string(f"({gotor.group(1)})"),
                "destination": None if gotor.group(2) is None else self._decode_pdf_string(f"({gotor.group(2)})"),
            }
        uri = _URI_RE.search(payload)
        if uri is not None:
            return {
                "kind": "uri",
                "url": self._decode_pdf_string(f"({uri.group(1)})"),
            }
        return {
            "kind": "raw",
            "payload": payload,
        }

    @staticmethod
    def _annotation_href(info):
        kind = info.get("kind")
        if kind == "goto":
            return "#" + info["destination"]
        if kind == "gotor":
            href = info["file"]
            if info.get("destination"):
                href += "#" + info["destination"]
            return href
        if kind == "uri":
            return info["url"]
        return None

    @staticmethod
    def _font_face_format(path):
        return {
            ".ttf": "truetype",
            ".otf": "opentype",
        }.get(Path(path).suffix.lower())

    @staticmethod
    def _system_font_dirs():
        home = os.path.expanduser("~")
        system = platform.system()
        if system == "Darwin":
            return (
                "/System/Library/Fonts",
                "/System/Library/AssetsV2",
                "/Library/Fonts",
                os.path.join(home, "Library", "Fonts"),
            )
        if system == "Windows":
            windir = os.environ.get("WINDIR", r"C:\Windows")
            return (os.path.join(windir, "Fonts"),)
        return (
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.join(home, ".local", "share", "fonts"),
            os.path.join(home, ".fonts"),
        )

    @classmethod
    def _is_system_font_path(cls, path):
        try:
            resolved = os.path.realpath(path)
        except Exception:
            return False
        for root in cls._system_font_dirs():
            try:
                if os.path.commonpath((resolved, os.path.realpath(root))) == os.path.realpath(root):
                    return True
            except ValueError:
                continue
        return False

    def _font_key(self, backend):
        path = getattr(backend, "path", None)
        if path:
            try:
                path = os.path.realpath(path)
            except Exception:
                pass
        return (
            getattr(backend, "kind", None),
            path,
            getattr(backend, "font_number", 0),
            getattr(backend, "name", None),
        )

    def _next_font_family(self):
        family = f"pytex-font-{self._next_font_face}"
        self._next_font_face += 1
        return family

    def _register_backend_font(self, backend):
        if backend is None:
            return None
        key = self._font_key(backend)
        family = self._font_families.get(key)
        if family is not None:
            return family
        path = getattr(backend, "path", None)
        format_name = None if not path else self._font_face_format(path)
        if (
            getattr(backend, "kind", None) == "opentype"
            and isinstance(path, str)
            and path
            and os.path.isfile(path)
            and format_name is not None
            and not self._is_system_font_path(path)
        ):
            face = self._font_faces.get(key)
            if face is None:
                family = _font_family_name(backend) or self._next_font_family()
                face = {
                    "family": family,
                    "path": os.path.realpath(path),
                    "suffix": Path(path).suffix.lower(),
                    "format_name": format_name,
                }
                self._font_faces[key] = face
            family = face["family"]
            self._font_families[key] = family
            return family
        family = font_subst.fontBackendName(backend)
        if family is not None:
            self._font_families[key] = family
        return family

    def _font_face_url(self, face, html_path):
        source = Path(face["path"]).resolve()
        if html_path is None:
            return source.as_uri()
        asset_dir = html_path.with_name(f"{html_path.stem}.assets") / "fonts"
        target = asset_dir / f"{face['family']}{face['suffix']}"
        try:
            asset_dir.mkdir(parents=True, exist_ok=True)
            if source != target.resolve():
                shutil.copyfile(source, target)
            return os.path.relpath(target, html_path.parent).replace(os.sep, "/")
        except Exception:
            return source.as_uri()

    def _math_font_stack(self):
        stack = []
        backend = font_subst.resolveMathFontBackend(self.parser)
        family = self._register_backend_font(backend) if backend is not None else None
        if family and font_subst.usableFontName(family):
            stack.append(family)
        for name in font_subst.MATH_FONT_CANDIDATES:
            if font_subst.usableFontName(name) and name not in stack:
                stack.append(name)
        stack.append("math")
        items = [self._css_string(name) for name in stack[:-1]]
        items.append(stack[-1])
        return ",".join(items)

    @staticmethod
    def _css_pt(value):
        text = f"{float(value):.6f}".rstrip("0").rstrip(".")
        return f"{text or '0'}pt"

    def _graphic_css_size(self, value):
        if value is None:
            return None
        css_points = float(value) * _CSS_POINTS_PER_TEX_POINT_NUM / _CSS_POINTS_PER_TEX_POINT_DEN
        return self._css_pt(css_points)

    def _graphic_asset_target(self, suffix):
        asset_dir = self.html_path.with_name(f"{self.html_path.stem}.assets") / "graphics"
        target = asset_dir / f"graphic-{self._next_graphic_asset}{suffix}"
        self._next_graphic_asset += 1
        return asset_dir, target

    def _graphic_asset_url_for_file(self, path, format):
        real_path = os.path.realpath(path)
        key = ("file", format, real_path)
        cached = self._graphic_assets.get(key)
        if cached is not None:
            return cached
        suffix = Path(real_path).suffix.lower()
        if not suffix and format:
            suffix = "." + format
        if not suffix:
            suffix = ".bin"
        asset_dir, target = self._graphic_asset_target(suffix)
        try:
            asset_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(real_path, target)
            url = os.path.relpath(target, self.html_path.parent).replace(os.sep, "/")
        except Exception:
            url = Path(real_path).resolve().as_uri()
        self._graphic_assets[key] = url
        return url

    def _graphic_asset_url_for_data(self, asset, request):
        key = (
            "data",
            asset.format,
            request.source,
            request.page,
            request.pagebox,
            request.bbox,
            None if request.width is None else int(request.width),
            None if request.height is None else int(request.height),
            int(request.depth),
            request.rotate,
        )
        cached = self._graphic_assets.get(key)
        if cached is not None:
            return cached
        suffix = "." + (asset.format or "bin")
        asset_dir, target = self._graphic_asset_target(suffix)
        data = asset.data
        if isinstance(data, str):
            data = data.encode("utf-8")
        try:
            asset_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data or b"")
            url = os.path.relpath(target, self.html_path.parent).replace(os.sep, "/")
        except Exception:
            return ""
        self._graphic_assets[key] = url
        return url

    def _graphic_asset_url(self, asset, request):
        if asset.path is not None:
            return self._graphic_asset_url_for_file(asset.path, asset.format)
        if asset.data is not None:
            return self._graphic_asset_url_for_data(asset, request)
        return request.source

    def typesetGraphicAsset(self, asset, request):
        if self.builder is None:
            return
        if asset.format not in self.supported_graphic_formats:
            return
        url = self._graphic_asset_url(asset, request)
        if not url:
            return
        graphic = Graphic(
            url,
            asset.format,
            width=self._graphic_css_size(request.width or asset.width),
            height=self._graphic_css_size(request.height or asset.height),
            inline=self.in_line,
        )
        self.builder.append(graphic)
        return request.width or asset.width

    def _text_font_family(self, font):
        family = self.define_font(font)
        if family is not None:
            return family
        backend = font.backend
        assert (
            getattr(backend, "kind", None) == "opentype"
            or getattr(backend, "subst_font_name", None)
        ), (
            "HTML reflow requires OpenType-backed text fonts; "
            f"got backend kind {getattr(backend, 'kind', None)!r} "
            f"for {getattr(backend, 'name', None)!r}"
        )
        family = font_subst.fontBackendName(backend)
        assert family is not None, (
            "HTML reflow could not resolve a browser-usable font family for "
            f"{getattr(backend, 'name', None)!r}"
        )
        return family

    def define_font(self, font):
        backend = getattr(font, "backend", None)
        if backend is None:
            return None
        if (
            getattr(backend, "kind", None) == "opentype"
            or getattr(backend, "subst_font_name", None)
        ):
            return self._register_backend_font(backend)
        return None

    operator_types = (mmode.ATOM_TYPE.BIN, mmode.ATOM_TYPE.REL, mmode.ATOM_TYPE.OP,
                      mmode.ATOM_TYPE.OPEN, mmode.ATOM_TYPE.CLOSE, mmode.ATOM_TYPE.PUNCT)


    def typesetMList(self, nodes, atom_type: mmode.ATOM_TYPE, style: mmode.Style):
        # we need to consider the atom type (class) and family
        # for consecutive letters of ORD symbols of family 0, they are either names  or digits
        letters = ""
        has_dot = False
        is_digit = False
        nodes = iter(nodes)
        stack = []
        while True:
            node = next(nodes, None)
            if node is None:
                if not stack:
                    break
                nodes = stack.pop()
                continue
            # we skip kerns and glues, and rely on MathML to handle them by default
            if isinstance(node, mmode.StyleNode):
                style = node.style
                continue
            if isinstance(node, mmode.ChoiceNode):
                if style.style == mmode.MATH_STYLE.D:
                    new = node.display
                elif style.style == mmode.MATH_STYLE.T:
                    new = node.text
                elif style.style == mmode.MATH_STYLE.S:
                    new = node.script
                else:
                    new = node.scriptscript
                stack.append(nodes)
                nodes = iter(new.list)
                continue
            if node.node_type == nd.NODE_TYPE.MATHNODE: # an atom
                if node.atom_type == mmode.ATOM_TYPE.ORD and node.sup is None and node.sub is None and isinstance(node.nucleus, mmode.MathSymbol):
                    symbol: mmode.MathSymbol = node.nucleus
                    if symbol.fam == 0:
                        char = self._math_symbol(symbol.char, symbol.fam)
                        if char is None:
                            char = symbol.char
                        if char == "." and not has_dot:
                            if not is_digit:
                                if letters:
                                    self.builder.append(reflow.Element(MI(letters, mathvariant="normal")))
                                    letters = ""
                                is_digit = True
                            has_dot = True
                            letters += char
                            continue
                        if char.isdigit():
                            if not is_digit and letters:
                                self.builder.append(reflow.Element(MI(letters, mathvariant="normal")))
                                letters = ""
                            is_digit = True
                            letters += char
                            continue
                        if is_digit and letters:
                            self.builder.append(reflow.Element(MN(letters)))
                            letters = ""
                            is_digit = False
                            has_dot = False
                        letters += char
                        continue
            if letters:
                if is_digit:
                    self.builder.append(reflow.Element(MN(letters)))
                else:
                    self.builder.append(reflow.Element(MI(letters, mathvariant="normal")))
                letters = ""
                is_digit = False
                has_dot = False
            if node.node_type == nd.NODE_TYPE.MATHNODE: # an atom
                self.builder.append(self.typesetAtom(node, style=style))
                continue
            if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY, nd.NODE_TYPE.MARK, nd.NODE_TYPE.ADJUST):
                    continue
            if node.node_type == nd.NODE_TYPE.VLIST:
                self.builder.append(self.typesetMathVBox(node))
                continue
            if node.node_type == nd.NODE_TYPE.HLIST:
                self.builder.append(self.typesetMathHBox(node))
            if node.node_type == nd.NODE_TYPE.WHATSIT:
                node.output(self.parser, self)
                continue
        if letters:
            if is_digit:
                self.builder.append(reflow.Element(MN(letters)))
            else:
                self.builder.append(reflow.Element(MI(letters, mathvariant="normal")))

    def typesetFraction(self, atom, style):
        top, bottom, bar, thickness = atom.nucleus
        num = MRow()
        with reflow.Builder(self, num):
            self.typesetMList(top.list, mmode.ATOM_TYPE.ORD, style.numerator())
        den = MRow()
        with reflow.Builder(self, den):
            self.typesetMList(bottom.list, mmode.ATOM_TYPE.ORD, style.denominator())
        frac = MFrac(num, den, bar, thickness)
        if atom.delims is None:
            return frac
        open, close = atom.delims
        left = self.typesetDelim(open)
        right = self.typesetDelim(close)
        return reflow.Element(MROW(left, frac.node, right))

    def typesetNucleus(self, atom: mmode.Atom, style: mmode.Style):
        # an atom has a nucleus, and optionally subscript and superscript. It may also have left and right delimiters.
        if isinstance(atom, mmode.Over):
            return self.typesetFraction(atom, style)
        node_type = getattr(atom.nucleus, "node_type", None)
        if node_type == nd.NODE_TYPE.HLIST:
            return self.typesetMathHBox(atom.nucleus)
        if node_type == nd.NODE_TYPE.VLIST:
            return self.typesetMathVBox(atom.nucleus)
        atom_type = atom.atom_type
        t = mmode.ATOM_TYPE.ORD if atom_type.value > 7 else atom_type
        s = style if atom_type.value > 7 else mmode.Style(style.style, cramped=True)
        nucleus = self.typesetField(atom.nucleus, atom_type=t, style=s)
        if atom_type in (mmode.ATOM_TYPE.OVER, mmode.ATOM_TYPE.UNDER):
            notation = "top" if atom_type == mmode.ATOM_TYPE.OVER else "bottom"
            return reflow.Element(MENCLOSE(nucleus.node, notation=notation))
        if atom_type == mmode.ATOM_TYPE.ACC:
            return reflow.Element(MOVER(nucleus.node, MO(self._math_symbol(atom.accent.char, atom.accent.fam), stretchy="true"), accent="true"))
        return reflow.Element(MSQRT(nucleus.node)) if atom_type == mmode.ATOM_TYPE.RAD else nucleus

    def typesetMathHBox(self, hbox):
        row = MRow()
        text = ""
        nodes = iter(hbox.list)
        with reflow.Builder(self, row):
            while True:
                n = next(nodes, None)
                if n is None:
                    break
                if n.node_type == nd.NODE_TYPE.CHAR:
                    text += n.char
                    continue
                if n.node_type == nd.NODE_TYPE.LIGATURE:
                    for p in n.source:
                        text += p.char
                    continue
                if n.node_type == nd.NODE_TYPE.GLUE:
                    text += " "
                    continue
                if text:
                    self.builder.append(reflow.Element(MTEXT(text)))
                    text = ""
                if n.node_type == nd.NODE_TYPE.HLIST:
                    self.builder.append(self.typesetMathHBox(n))
                elif n.node_type == nd.NODE_TYPE.VLIST:
                    self.builder.append(self.typesetMathVBox(n))
                elif n.node_type == nd.NODE_TYPE.WHATSIT:
                    n.output(self.parser, self)
                elif n.node_type == nd.NODE_TYPE.MATH:
                    inline: mmode.InlineMathNode = n.source
                    while True:
                        n = next(nodes, None)
                        assert n is not None
                        if n.node_type == nd.NODE_TYPE.MATH:
                            break
                    r = MRow()
                    with reflow.Builder(self, r):
                        self.typesetMList(inline.list, mmode.ATOM_TYPE.ORD, mmode.Style(mmode.MATH_STYLE.T))
                    self.builder.append(r)
            if text:
                self.builder.append(reflow.Element(MTEXT(text)))
        return row

    def typesetMathVBox(self, vbox):
        matrix = None
        for n in vbox.list:
            if n.node_type == nd.NODE_TYPE.WHATSIT:
                n.output(self.parser, self)
            elif isinstance(n.source, align.HAlignment):
                matrix = n.source
        if matrix is None:
            return reflow.Element(MI())
        table = reflow.Element(MTABLE())
        for row in matrix.rows:
            tr = reflow.Element(MTR())
            for cell in row.cells:
                td = reflow.Element(MTD())
                td.append(self.typesetMathHBox(cell))
                tr.append(td)
            table.append(tr)
        return table

    def typesetAtom(self, atom: mmode.Atom, style: mmode.Style):
        nucleus = self.typesetNucleus(atom, style)
        if atom.sub is None:
            if atom.sup is None:
                return nucleus
            a = reflow.Element(MSUP())
            a.append(nucleus)
            a.append(self.typesetField(atom.sup, mmode.ATOM_TYPE.ORD, style=style.superscript()))
            return a
        if atom.sup is None:
            a = reflow.Element(MSUB())
            a.append(nucleus)
            a.append(self.typesetField(atom.sub, mmode.ATOM_TYPE.ORD, style=style.subscript()))
            return a
        a = reflow.Element(MSUBSUP())
        a.append(nucleus)
        a.append(self.typesetField(atom.sub, mmode.ATOM_TYPE.ORD, style=style.subscript()))
        a.append(self.typesetField(atom.sup, mmode.ATOM_TYPE.ORD, style=style.superscript()))
        return a

    def typesetField(self, field, atom_type: mmode.ATOM_TYPE, style: mmode.Style):
        if field is None:
            return MRow()
        if isinstance(field, mmode.Subformula):
            row = MRow()
            with reflow.Builder(self, row):
                left = getattr(field, "left_delim")
                right = getattr(field, "right_delim")
                if left is not None:
                    self.builder.append(self.typesetDelim(left))
                self.typesetMList(field.list, atom_type=atom_type, style=style)
                if right is not None:
                    self.builder.append(self.typesetDelim(right))
            return row
        return self.typesetSymbol(field, atom_type=atom_type)

    def _math_symbol(self, char, fam):
        return font_subst.mathSlotText(fam, ord(char))

    def typesetSymbol(self, symbol: mmode.MathSymbol, atom_type: mmode.ATOM_TYPE = mmode.ATOM_TYPE.ORD):
        text = self._math_symbol(symbol.char, symbol.fam)
        if text is None:
            return reflow.Element(MI())
        # if this a dot or a digit?
        if atom_type == mmode.ATOM_TYPE.ORD:
            if symbol.fam == 0:
                if text == "." or text.isdigit():
                    return reflow.Element(MN(text))
                return reflow.Element(MI(text, mathvariant="normal"))
            return reflow.Element(MI(text))
        return reflow.Element(MO(text or "", mathvariant="normal"))

    def typesetDelim(self, delim):
        if delim._isNull():
            return reflow.Element(MO())
        text = self._math_symbol(delim.small.char, delim.small.fam)
        if text is None:
            text = self._math_symbol(delim.small.char, delim.small.fam)
        return reflow.Element(MO("" if text is None else text))

    def typesetInlineMath(self, node: mmode.InlineMathNode, box:bx.HBox, piece: int):
        if piece == 1:
            # we typeset from the node, which contains all pieces. So we only handle the first piece.
            math = self.builder.newInlineMath()
            with reflow.Builder(self, math):
                self.typesetMList(node.list, atom_type=mmode.ATOM_TYPE.ORD, style=mmode.Style(mmode.MATH_STYLE.T))

    def typesetDisplayMath(self, node, collection, yspacing: Dimen=Dimen(), glue_state=None):
        math = Math(inline=False)
        with reflow.Builder(self, math):
            self.typesetMList(node.list, atom_type=mmode.ATOM_TYPE.ORD, style=mmode.Style(mmode.MATH_STYLE.D))
        if node.eqno is None:
            math.style["padding-top"] = reflow.PT(yspacing)
            self.builder.append(math)
            return
        eqno_list, left = node.eqno
        eqno = Math(inline=True)
        with reflow.Builder(self, eqno):
            self.typesetMList(eqno_list.list, atom_type=mmode.ATOM_TYPE.ORD, style=mmode.Style(mmode.MATH_STYLE.T))
        table = Table(yspacing=yspacing)
        row = table.newRow()
        if left:
            mark = row.newCell()
            mark.append(eqno)
            row.newCell(relative_width=0.5)
            body = row.newCell()
            body.append(math)
            row.newCell(width=0.5)
        else:
            row.newCell(relative_width=0.5)
            body = row.newCell()
            body.append(math)
            row.newCell(relative_width=0.5)
            mark = row.newCell()
            mark.append(eqno)
        self.builder.append(table)

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

    def setTarget(self, name):
        if self.builder is None:
            return
        container = getattr(self.builder, "container", None)
        if container is None:
            return
        container._node.set("id", name)

    def rawSpecial(self, text):
        pass


def init(parser):
#    font_subst.installFontSubstitution(parser)
#    font_subst.installMathFontArrays(parser)
    parser.shipout = HTMLReflowBackend(parser)
    parser.font_size_in_bp = True


mod = Module(
    "html_reflow",
    attributes={},
    init=init,
)
