"""HTML reflow backend driven by the outer-vlist raw history."""

from __future__ import annotations

from collections import Counter
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

_SPACE_RE = re.compile(r"\s+")
_EPDF_RE = re.compile(r"pdf:epdf\b.*\(([^()]+)\)")
_DEST_RE = re.compile(r"^\s*pdf:\s*dest\s*\(([^()]*)\)", re.IGNORECASE)
_BEGINANN_RE = re.compile(r"^\s*pdf:\s*(?:beginann|bann|annotate|annot|ann)\b", re.IGNORECASE)
_ENDANN_RE = re.compile(r"^\s*pdf:\s*(?:endann|eann|eannot)\b", re.IGNORECASE)
_GOTO_RE = re.compile(r"/S\s*/GoTo\b.*?/D\s*\(([^()]*)\)", re.IGNORECASE | re.DOTALL)
_GOTOR_RE = re.compile(
    r"/S\s*/GoToR\b.*?/F\s*\(([^()]*)\)(?:.*?/D\s*\(([^()]*)\))?",
    re.IGNORECASE | re.DOTALL,
)
_URI_RE = re.compile(r"/S\s*/URI\b.*?/URI\s*\(([^()]*)\)", re.IGNORECASE | re.DOTALL)
_DEFAULT_FONT_ROLE = {
    "family": "serif",
    "weight": "normal",
    "style": "normal",
    "variant": "normal",
}


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
MLABELEDTR = E.mlabeledtr
MTR = E.mtr
MTD = E.mtd


class Style(dict):
    def __str__(self):
        return  "".join([f"{k}:{v};" for k, v in self.items()])


def _color(color: reflow.Color)->str:
    """
    convert the color specification to CSS string
    """
    r, g, b, a = color.rgba
    return f"rgb({int(r*255)},{int(g*255)},{int(b*255)})"


class AnnotationBuilder(reflow.AnnotationBuilder):
    def __init__(self, backend, parent, href):
        super().__init__(backend, parent, href)
        self.container = Line(justify=None, node=builder.A(href=href))

    def beginAnnotation(self, name):
        self.parent.append(self.container)


class FixedAnnotation(reflow.Element):
    def __init__(self, target: str, width: float, height: float, border_color: reflow.Color=reflow.Color.red, border_width: float=1, corner_radius: float=1):
        """here the dimensions are in postscript pt, i.e., tex bp"""
        node = builder.A(href=f"#{target}")
        border = Style()
        border["border-width"] = border_width
        border["border-color"] = _color(border_color)
        border["border-style"] = "solid"
        div = builder.DIV(
            builder.DIV(style=str(border)),
            style="width=0pt;height=0pt;"
        )
        node.append(div)
        super().__init__(node)
        

class TextRun(reflow.TextRun):
    def __init__(self, font: Font, color: reflow.Color=reflow.Color.black):
        span = builder.SPAN("")
        style = Style()
        style["color"] = _color(color)
        # TODO set font family properly
        style["font-family"] = ""
        style["font-size"] = reflow.PT(font.at)
        span.set("style", str(style))
        super().__init__(span, font, color)

    def setKern(self, kern: Dimen):
        pass

    def setChar(self, char: nd.Node):
        if char.node_type == nd.NODE_TYPE.CHAR:
            c = char.char
        elif char.node_type == nd.NODE_TYPE.LIGATURE:
            c = "".join(s.char for s in char.source)
        self.node.text += c

    def setSpace(self, width):
        self.node.text += " "


class Line(reflow.Line):
    def __init__(self, justify, node=None):
        super().__init__(builder.SPAN() if node is None else node, justify)

    def newTextRun(self, font, color) -> TextRun:
        text_run = TextRun(font, color)
        self.append(text_run)
        return text_run

    def newInlineBlock(self, box: bx.Box):
        div = Div(inline=True)
        style = Style()
        style["display"] = "inline-block"
        if box.node_type == nd.NODE_TYPE.HLIST:
            style["width"] = reflow.PT(box.width)            
        div.set("style", div.get("style") + str(style))
        self.append(div)
        return div

    def newInlineMath(self, backend, inlinemath: mmode.InlineMathNode, nodes: list):
        pass

    def setSpace(self, width: Dimen):
        self.node.append(builder.SPAN())


class Paragraph(reflow.Paragraph):
    def __init__(self, reflow_lines:bool, spacing_before=Dimen(), justify="justify"):
        node = builder.DIV()
        style = Style()
        style["padding-top"] = reflow.PT(spacing_before)
        style["justify"] = justify
        node.set("style", str(style))
        super().__init__(node, reflow_lines, spacing_before, justify)

    def newLine(self):
        line = Line(self.justify)
        self.append(line)
        return line


class Math(reflow.Math):
    def __init__(self, inline: bool):
        math = MATH(display="inline" if inline else "block")
        super().__init__(math, inline)


class Cell(reflow.Cell):
    def __init__(self, span, width, justify: str="justify"):
        if width is None:
            width = "auto"
        elif isinstance(width, Dimen):
            width = reflow.PT(width)
        else:
            width = f"{width}%"
        style = Style()
        style["width"] = width
        style["justify"] = justify
        style["display"] = "inline-flex"
        style["max-width"] = "100%"
        td = builder.TD(style=str(style))
        super().__init__(td, span, width, justify)
    
    def newParagraph(self) -> Paragraph:
        para = Paragraph(reflow_lines=True, justify=self.justify)
        self.append(para)
        return para


class Row(reflow.Row):
    def __init__(self):
        tr = builder.TR()
        super().__init__(tr)

    def newCell(self, span=1, width=None, justify="justified") -> Cell:
        td = Cell(span, width, justify)
        self.append(td)
        return td


class Table(reflow.Table):
    def __init__(self, xspacing=Dimen(), yspacing=Dimen()):
        style = Style()
        style["margin-top"] = reflow.PT(yspacing)
        style["border-spacing"] = "0"
        style["width"]="100%"
        style["padding-left"] = reflow.PT(xspacing)
        style["padding-top"] = reflow.PT(yspacing)
        table = builder.TABLE(style=str(style))
        table.set("class", "alignment")
        super().__init__(table, xspacing, yspacing)

    def newRow(self) -> Row:
        tr = Row()
        self.append(tr)
        return tr


class Block(reflow.Block):
    """
    This is an abstraction of HBox and VBox
    """
    def newParagraph(self, spacing_before=Dimen(), justify: str="left") -> Paragraph:
        para = Paragraph(reflow_lines=True, spacing_before=spacing_before, justify=justify)
        self.append(para)
        return para

    def newDisplaymath(self, spacing_before: Dimen=Dimen()) -> Math:
        math = Math(inline=False)
        self.append(math)
        return math

    def newTable(self, xspacing: Dimen=Dimen(), yspacing: Dimen=Dimen()):
        table = Table(xspacing, yspacing)
        self.append(table)
        return table

    def newBlock(self, xspacing=Dimen(), yspacing=Dimen()):
        block = Div(inline=False, xspacing=xspacing, yspacing=yspacing)
        self.append(block)
        return block

    def newGraph(self, key, type, file):
        pass


class Div(Block):
    def __init__(self, inline: bool=False, xspacing=Dimen(), yspacing=Dimen()):
        style = Style()
        style["display"] = "inline" if inline else "block"
        style["padding-left"] = reflow.PT(xspacing)
        style["padding-top"] = reflow.PT(yspacing)
        div = builder.DIV(style=str(style))
        super().__init__(div, inline, xspacing, yspacing)


class Body(Block):
    def __init__(self):
        super().__init__(builder.BODY(), inline=False, xspacing=None, yspacing=None)


class Page(reflow.Page):
    def __init__(self):
        self._body = Body()
        super().__init__(self._body.node, None, None)

    @property
    def header(self) -> Block:
        pass

    @property
    def body(self) -> Block:
        return self._body

    @property
    def footer(self) -> Block:
        pass

    def setBackgroundColor(self, color: reflow.Color):
        pass


class Document(reflow.Document):
    def __init__(self, title: str, output=None):
        """
        output is a file like structure to write to, typically opened by Parser.resolver.openOut
        or None, which means no output
        """
        self.head = builder.HEAD(
            builder.META(charset="utf-8"),
            builder.TITLE(title or "texput"),
        )
        self.body = Page()
        html = builder.HTML(self.head, self.body.node)
        super().__init__(html, title, output)

    def newPage(self, width: Dimen, height: Dimen) -> Page:
        return self.body

    def defineFont(self, font):
        pass

    def definePicture(self, key, type, path):
        pass

    def save(self):
        self.node.set("lang", "en")
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
    def __init__(self, parser):
        super().__init__(parser, paginate=False)
        self._body_font = None
        self._pending_media_blocks = []
        self._font_families = {}
        self._font_faces = {}
        self._next_font_face = 1

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
            math_stack = self._math_font_stack()
            parts = self._font_face_rules(self.html_path)
            parts.append(f"math{{font-family:{math_stack};}}")
            self.document.head.append(builder.STYLE("".join(parts)))
        super().close()        
    
    def newAnnotationBuilder(self, name=None, payload=None):
        info = self._annotation_info(payload or "")
        href = self._annotation_href(info)
        if href is None and name is not None:
            href = "#" + name.lstrip("@")
        return AnnotationBuilder(self, self.builder, href or "#")

    def newFixedAnnotation(self, target, w, h):
        return FixedAnnotation(target, w, h)

    def _css_string(self, text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

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
                family = self._next_font_family()
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

    def _font_face_rules(self, html_path):
        rules = []
        for face in self._font_faces.values():
            src = f'url({self._css_string(self._font_face_url(face, html_path))})'
            if face["format_name"] is not None:
                src += f' format({self._css_string(face["format_name"])})'
            rules.append(
                f"@font-face{{font-family:{self._css_string(face['family'])};src:{src};}}"
            )
        return rules

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

    def _link_element(self, info, annotation_kind):
        href = self._annotation_href(info)
        if href is None:
            return None
        link = builder.A(href=href)
        link.set("data-tex-annotation", annotation_kind)
        return link
    
    def typesetNBSP(self, width, height=1):
        div = builder.DIV()
        style = Style()
        style["display"] = "inine-block"
        style["width"] = reflow.PT(width)
        style["height"] = reflow.PT(height)
        div.set("style", str(style))
        return div

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

    @staticmethod
    def _node_has_inline_anchor(node):
        node_type = getattr(node, "node_type", None)
        if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.DISC, nd.NODE_TYPE.RULE):
            return True
        if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            if (
                Dimen(getattr(node, "width", 0)) > 0
                or Dimen(getattr(node, "height", 0)) > 0
                or Dimen(getattr(node, "depth", 0)) > 0
            ):
                return True
            for child in getattr(node, "list", None) or ():
                if HTMLReflowBackend._node_has_inline_anchor(child):
                    return True
        return False

    @staticmethod
    def _glue_stretch_order(glue):
        if glue is None:
            return None
        stretch = getattr(glue, "stretch", None)
        if stretch is not None and getattr(stretch, "factor", 0) != 0:
            return int(getattr(stretch, "order", 0))
        return None

    def _edge_stretch_order(self, nodes):
        order = None
        for node in nodes:
            if getattr(node, "node_type", None) != nd.NODE_TYPE.GLUE:
                continue
            current = self._glue_stretch_order(getattr(node, "glue", None))
            if current is None:
                continue
            if order is None or current > order:
                order = current
        return order
    
    def typesetMList(self, parent, nodes, atom_type: mmode.ATOM_TYPE, style: mmode.Style):
        # we need to consider the atom type (class) and family
        # for consecutive letters of ORD symbols of family 0, they are either names  or digits
        letters = ""
        has_dot = False
        is_digit = False
        nodes = iter(nodes)
        stack = []
        try:
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
                                if not is_digit and letters:
                                    self.appendOutput(parent, MI(letters, mathvariant="normal"))
                                    letters = ""
                                    is_digit = True
                                has_dot = True
                                letters += char
                                continue
                            if char.isdigit():
                                if not is_digit and letters:
                                    self.appendOutput(parent, MI(letters, mathvariant="normal"))
                                    letters = ""
                                is_digit = True
                                letters += char
                                continue
                            if is_digit and letters:
                                self.appendOutput(parent, MN(letters))
                                letters = ""
                                is_digit = False
                                has_dot = False
                            letters += char
                            continue
                if letters:
                    if is_digit:
                        self.appendOutput(parent, MN(letters))
                    else:
                        self.appendOutput(parent, MI(letters, mathvariant="normal"))
                    letters = ""
                    is_digit = False
                    has_dot = False
                if node.node_type == nd.NODE_TYPE.MATHNODE: # an atom
                    self.appendOutput(parent, self.typesetAtom(node, style=style))
                    continue
                if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY, nd.NODE_TYPE.MARK, nd.NODE_TYPE.ADJUST):
                     continue
                if node.node_type == nd.NODE_TYPE.VLIST:
                    self.appendOutput(parent, self.typesetVBox(node, inline=True))
                    continue
                if node.node_type == nd.NODE_TYPE.HLIST:
                    self.appendOutput(parent, self.typesetHBox(node, inline=True))
                    continue
                if node.node_type == nd.NODE_TYPE.WHATSIT:
                    node.output(self.parser, self)
                    continue
            if letters:
                if is_digit:
                    self.appendOutput(parent, MN(letters))
                else:
                    self.appendOutput(parent, MI(letters, mathvariant="normal"))
        finally:
            self._pop_container()
        if len(parent) == 1 and etree.QName(parent).localname != "math":
            parent = parent[0]
            # if atom_type is an operator, we need to set it as <mo>
            if atom_type in self.operator_types:
                mo = MO(parent)
                mathvariant=parent.get("mathvariant")
                if mathvariant is not None:
                    mo.set("mathvariant", mathvariant)
                return mo
        return parent
    
    def typesetNucleus(self, atom: mmode.Atom, style: mmode.Style):
        # an atom has a nucleus, and optionally subscript and superscript. It may also have left and right delimiters.
        if isinstance(atom, mmode.Over):
            num, den, bar, thickness = atom.nucleus
            nucleus = MFRAC(
                self.typesetMList(MROW(), num.list, mmode.ATOM_TYPE.ORD, style.numerator()),
                self.typesetMList(MROW(), den.list, mmode.ATOM_TYPE.ORD, style.denominator()))
            if not bar:
                thickness = 0
            if thickness is not None:
                nucleus.set("linethickness", reflow.PT(thickness))
            if atom.delims is not None:
                left, right = atom.delims
                open = self.typesetDelim(left)
                close = self.typesetDelim(right)
                nucleus = MROW(open, nucleus, close)
            return nucleus
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
            return MENCLOSE(nucleus, notation=notation)
        if atom_type == mmode.ATOM_TYPE.ACC:
            return MOVER(nucleus, MO(self._math_symbol(atom.accent.char, atom.accent.fam), stretchy="true"), accent="true")
        return MSQRT(nucleus) if atom_type == mmode.ATOM_TYPE.RAD else nucleus
    
    def typesetMathHBox(self, hbox):
        row = MROW()
        text = ""
        nodes = iter(hbox.list)
        self._push_container(row)
        try:
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
                    self.appendOutput(row, MTEXT(text))
                    text = ""
                if n.node_type == nd.NODE_TYPE.HLIST:
                    self.appendOutput(row, self.typesetMathHBox(n))
                elif n.node_type == nd.NODE_TYPE.VLIST:
                    self.appendOutput(row, self.typesetMathVBox(n))
                elif n.node_type == nd.NODE_TYPE.WHATSIT:
                    n.output(self.parser, self)
                elif n.node_type == nd.NODE_TYPE.MATH:
                    inline: mmode.InlineMathNode = n.source
                    while True:
                        n = next(nodes, None)
                        assert n is not None
                        if n.node_type == nd.NODE_TYPE.MATH:
                            break
                    self.appendOutput(
                        row,
                        self.typesetMList(MROW(), inline.list, mmode.ATOM_TYPE.ORD, mmode.Style(mmode.MATH_STYLE.T)),
                    )
            if text:
                self.appendOutput(row, MTEXT(text))
        finally:
            self._pop_container()
        return row

    def typesetMathVBox(self, vbox):
        matrix = None
        for n in vbox.list:
            if n.node_type == nd.NODE_TYPE.WHATSIT:
                n.output(self.parser, self)
            elif isinstance(n.source, align.HAlignment):
                matrix = n.source
        if matrix is None:
            return MI()
        table = MTABLE()
        for row in matrix.rows:
            tr = MTR()
            for cell in row.cells:
                tr.append(MTD(self.typesetMathHBox(cell)))
            table.append(tr)
        return table
                    
    def typesetAtom(self, atom: mmode.Atom, style: mmode.Style):
        nucleus = self.typesetNucleus(atom, style)
        if atom.sub is None:
            if atom.sup is None:
                return nucleus
            return MSUP(nucleus, self.typesetField(atom.sup, mmode.ATOM_TYPE.ORD, style=style.superscript()))
        if atom.sup is None:
            return MSUB(nucleus, self.typesetField(atom.sub, mmode.ATOM_TYPE.ORD, style=style.subscript()))
        return MSUBSUP(
            nucleus, 
            self.typesetField(atom.sub, mmode.ATOM_TYPE.ORD, style=style.subscript()), 
            self.typesetField(atom.sup, mmode.ATOM_TYPE.ORD, style=style.superscript()))

    def typesetField(self, field, atom_type: mmode.ATOM_TYPE, style: mmode.Style):
        if field is None:
            return MROW()
        if isinstance(field, mmode.Subformula):
            row = MROW()
            left = getattr(field, "left_delim")
            right = getattr(field, "right_delim")
            if left is not None:
                row.append(self.typesetDelim(left))
            self.typesetMList(row, field.list, atom_type=atom_type, style=style)
            if right is not None:
                row.append(self.typesetDelim(right))
            return row
        return self.typesetSymbol(field, atom_type=atom_type)
    
    def _math_symbol(self, char, fam):
        return font_subst.mathSlotText(fam, ord(char))
          
    def typesetSymbol(self, symbol: mmode.MathSymbol, atom_type: mmode.ATOM_TYPE = mmode.ATOM_TYPE.ORD):
        text = self._math_symbol(symbol.char, symbol.fam)
        if text is None:
            return MI()
        # if this a dot or a digit?
        if atom_type == mmode.ATOM_TYPE.ORD:
            if symbol.fam == 0:
                if text == "." or text.isdigit():
                    return MN(text)
                return MI(text, mathvariant="normal")
            return MI(text)
        return MO(text or "", mathvariant="normal")

    def typesetDelim(self, delim):
        if delim._isNull():
            return MO()
        text = self._math_symbol(delim.small.char, delim.small.fam)
        if text is None:
            text = self._math_symbol(delim.small.char, delim.small.fam)
        if text is None:
            return MO()
        return MO(text)

    def typesetInlineMath(self, node: mmode.InlineMathNode, collection, left_kern, right_kern):
        return
        math = MATH(display="inline")
        style = Style()
        style["left"] = reflow.PT(left_kern)
        style["right"] = reflow.PT(right_kern)
        math.set("style", str(style))
        return self.typesetMList(math, node.list, atom_type=mmode.ATOM_TYPE.ORD, style=mmode.Style(mmode.MATH_STYLE.T))
    
    def typesetDisplayMath(self, node, collection, yspacing):
        return
        math = MATH(display="block")
        style = Style()
        style["display"] = "block"
        style["top"] = reflow.PT(yspacing)
        math.set("style", str(style))
        self.typesetMList(math, node.list, atom_type=mmode.ATOM_TYPE.ORD, style=mmode.Style(mmode.MATH_STYLE.D))
        if node.eqno is None:
            return math
        eqno_list, left = node.eqno
        eqno = MATH(display="inline")
        self.typesetMList(eqno, eqno_list.list, atom_type=mmode.ATOM_TYPE.ORD, style=mmode.Style(mmode.MATH_STYLE.T))
        seq = [builder.TD(style="width:50%;"), builder.TD(math), builder.TD(style="width:50%;"), builder.TD(eqno)]
        if left:
            seq.reverse()
        tr = builder.TR()
        for n in seq:
            tr.append(n)
        return builder.TABLE(tr, style="width:100%;class=display-math;")
    
    def rawSpecial(self, text):
        match = _DEST_RE.match(text)
        if match is not None:
            marker = reflow.Element(builder.SPAN())
            marker.set("id", self._decode_pdf_string(f"({match.group(1)})"))
            self.builder.append(marker)
            return
        Warning(f"unknown special: {text}")

    def typesetSpring(self, ratio):
        pass

    def typesetHBox(self, box, xspacing=Dimen(), yspacing=Dimen()):
        div = super().typesetHBox(box, xspacing, yspacing)
        # set width in %
        if self.box_stack: # the top is this box
            enclosing = self.box_stack[-1]
            if int(enclosing.width) != 0 and int(box.width) != 0:
                style = Style()
                style["display"] = "flex"
                style["align-items"] = "baseline"
                style["flex-wrap"] = "nowrap"
                style["white-space"] = "nowrap"
                style["width"] =f"{float(box.width)/float(enclosing.width)*100}%"
                div.set("style", div.get("style") + str(style))
        return div

def init(parser):
    font_subst.installFontSubstitution(parser)
    font_subst.installMathFontArrays(parser)
    parser.shipout = HTMLReflowBackend(parser)


mod = Module(
    "html_reflow",
    attributes={},
    init=init,
)
