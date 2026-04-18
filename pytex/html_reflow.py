"""HTML reflow backend driven by the outer-vlist raw history."""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import platform
import re
import shutil

from pytex import align
from pytex import mmode
from pytex import node as nd
from pytex import paragraph
from pytex import vmode
from pytex.dimen import Dimen
from pytex.module import Module
from pytex import reflow
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


def _pt(pt):
    return f"{float(pt) / 72.27 * 72}pt"


class Style(dict):
    def __str__(self):
        return  "".join([f"{k}:{v};" for k, v in self.items()])


class DeferredWhatsit:
    def __init__(self, node):
        self.node = node

    def typeset(self, backend):
        self.node.output(backend.parser, backend)
        return None


class HTMLReflowBackend(reflow.Reflow):
    """
    Null shipout backend for reflow mode.

    We still let TeX/LaTeX run the normal page builder and output routine so
    deferred writes, aux replay, and shipout hooks behave normally. The backend
    itself only executes shipped whatsits; the final HTML is emitted once at
    close from the main vertical list's raw ownership history.
    """
    def __init__(self, parser, output=None):
        super().__init__(parser, output)
        self.finished = False
        self.header = builder.HEAD()
        self.body = builder.BODY()
        self._body_font = None
        self._pending_media_blocks = []
        self._font_families = {}
        self._font_faces = {}
        self._next_font_face = 1
        self._container_stack = []
        self._active_links = []

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

    @staticmethod
    def _output_name(output):
        output = os.fspath(output)
        if output.startswith("./"):
            output = output[2:]
        if not output.endswith(".html"):
            output += ".html"
        return output

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

    def _document_css(self, html_path=None):
        math_stack = self._math_font_stack()
        parts = self._font_face_rules(html_path)
        parts.append(f"math{{font-family:{math_stack};}}")
        return "".join(parts)

    def _build_head(self, html_path=None):
        return builder.HEAD(
            builder.META(charset="utf-8"),
            builder.TITLE(self.parser.jobname or "texput"),
            builder.STYLE(self._document_css(html_path)),
        )

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

    def _push_container(self, container):
        self._container_stack.append(container)

    def _pop_container(self):
        self._container_stack.pop()

    def _base_container(self):
        if self._container_stack:
            return self._container_stack[-1]
        return self.body

    def _current_link(self):
        for link in reversed(self._active_links):
            if link is not None:
                return link
        return None

    def _current_parent(self, container=None):
        link = self._current_link()
        if link is not None:
            return link
        return self._base_container() if container is None else container

    def _append_output(self, container, content):
        if content is None:
            return None
        if isinstance(content, str):
            if content == "" or content == " ":
                return None
            content = builder.SPAN(content)
        self._current_parent(container).append(content)
        return content

    @staticmethod
    def _special_marker(text, attr="data-tex-special"):
        span = builder.SPAN()
        span.set("style", "display:none;")
        span.set(attr, text)
        return span

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

    def open(self):
        # Runtime shipout is intentionally side-effect free for HTML reflow.
        return

    def close(self):
        html_path = None
        if hasattr(self.output, "write"):
            file = self.output
        else:
            if self.output is None:
                output = self.parser.jobname or "texput"
            else:
                output = self.output
            output = self._output_name(output)
            if not self.parser.resolver.output_in_memory:
                html_path = Path(self.parser.resolver._outputPath(output))
            file = self.parser.resolver.openOut(output, None)
        self.header = self._build_head(html_path=html_path)
        html = builder.HTML(self.header, self.body)
        html.set("lang", "en")
        s = "<!doctype html>\n" + etree.tostring(
            html, method="html", pretty_print=True, encoding="unicode"
        )
        file.write(s)
        file.close()
    
    def typesetPage(self, tree):
        # the body is the last item 
        body = tree[-1]
        self.body.append(self.typesetVBox(body, mark_last_source=True))

    def _box(self, box, inline, xspacing, yspacing):
        style = Style()
        style["left"] = _pt(xspacing)
        style["top"] = _pt(yspacing)
        if inline:
            style["display"] = "inline-block"
            if  not box.list:
                set_width = True
            elif box.node_type == nd.NODE_TYPE.HLIST:
                justify = self._hbox_justification(box)
                set_width = justify is not None and justify != "justify"
            else:
                set_width = False
            if set_width and int(box.width) > 0:
                style["width"] = _pt(box.width)            
        elif box.node_type == nd.NODE_TYPE.HLIST:
            style["display"] = "flex"
            style["align-items"] = "baseline"
            style["flex-wrap"] = "nowrap"
            style["white-space"] = "nowrap"
            # set width in %
            if len(self.box_stack) > 1: # the top is this box
                enclosing = self.box_stack[-2]
                if int(enclosing.width) != 0 and int(box.width) != 0:
                    style["width"] = f"{float(box.width)/float(enclosing.width)*100}%;"
        return builder.DIV(style=str(style))


    def typesetNBSP(self, width, height=1):
        div = builder.DIV()
        style = Style()
        style["display"] = "inine-block"
        style["width"] = _pt(width)
        style["height"] = _pt(height)
        div.set("style", str(style))
        return div
    
    def typesetParagraph(self, para: reflow.Paragraph, container=None):
        div = builder.DIV() if container is None else container
        style = Style()
        style["text-indent"] = _pt(para.indent)
        style["padding"] = f"{_pt(para.spacing_before)} 0 0 0"
        style["text-align"] = para.justify
        div.set("style", div.get("style", "")+str(style))
        self._push_container(div)
        try:
            for n in para:
                self._append_output(div, n.typeset(self))
        finally:
            self._pop_container()
        return div

    def populateParagraph(self, para, hlist, glue_state):
        class Source:
            def __init__(self):
                self.inline_math = None

            def __call__(self, node):
                if node.node_type == nd.NODE_TYPE.MATH:
                    self.inline_math = node.source if node.on else None
                    return node.source
                if self.inline_math is not None:
                    return self.inline_math
                return node.source

        nodes = iter(hlist)
        while True:
            collection, raw = self._collect(nodes, Source())
            if raw is None:
                break
            if raw.node_type == nd.NODE_TYPE.GLUE:
                if glue_state is None:
                    para.setSpace(raw.glue.dimen)
                elif (
                    glue_state["order"] > 0
                    and not glue_state["shrink"]
                    and glue_state["order"] == raw.glue.stretch.order
                ):
                    para.append(Spring(self._glue_amount(raw, box=None, state=glue_state)))
                else:
                    para.setSpace(self._glue_amount(raw, box=None, state=glue_state))
                continue
            if isinstance(raw, mmode.InlineMathNode):
                para.setInlineMath(raw, collection, left_kern=Dimen(), right_kern=Dimen())
                continue
            if raw.node_type == nd.NODE_TYPE.WHATSIT:
                para.text_run = None
                list.append(para, DeferredWhatsit(raw))
                continue
            if raw.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                para.append(raw)

    def typesetVList(self, parent, vlist: list, glue_state=None, mark_last_source=False):
        def source(node):
            while True:
                s = node.source
                if s is None or s.source is None:
                    return s
                node = s

        spacing = Dimen()
        nodes = iter(vlist)
        self._push_container(parent)
        try:
            while True:
                collection, n = self._collect(nodes, source)
                if n is None:
                    break
                if n is self.last_source:
                    self.last_source = None
                    continue
                if isinstance(n, mmode.DisplayMathNode):
                    self._append_output(parent, self.typesetDisplayMath(n, collection, yspacing=spacing))
                    spacing = Dimen()
                    if mark_last_source:
                        self.last_source = n
                    continue
                if isinstance(n, paragraph.Paragraph):
                    line = None
                    for b in collection:
                        if b.node_type == nd.NODE_TYPE.HLIST:
                            line = b
                            break
                        if b.node_type == nd.NODE_TYPE.GLUE:
                            if glue_state is None:
                                spacing += b.glue.dimen
                            else:
                                spacing += Dimen(integer=self._glue_amount(b, None, glue_state))
                        elif b.node_type == nd.NODE_TYPE.KERN:
                            spacing += b.kern
                    if line is None:
                        continue
                    para = Paragraph(indent=Dimen(), spacing_before=spacing, justify=self._hbox_justification(line))
                    self.populateParagraph(para, n.list, glue_state=None)
                    self._append_output(parent, self.typesetParagraph(para))
                    spacing = Dimen()
                    if mark_last_source:
                        self.last_source = n
                    continue
                if isinstance(n, align.HAlignment):
                    self._append_output(parent, self.typesetHAlignment(n, collection, yspacing=spacing))
                    spacing = Dimen()
                    if mark_last_source:
                        self.last_source = n
                    continue
                assert not isinstance(n, align.MAlignment)
                if n.node_type == nd.NODE_TYPE.VLIST:
                    h = Dimen() if n.shifted is None else n.shifted
                    self._append_output(parent, self.typesetVBox(n, xspacing=h, yspacing=spacing))
                    spacing = Dimen()
                    continue
                if n.node_type == nd.NODE_TYPE.HLIST:
                    self._append_output(parent, self.typesetHBox(n))
                    spacing = Dimen()
                    continue
                if n.node_type == nd.NODE_TYPE.WHATSIT:
                    n.output(self.parser, self)
                    continue
                if n.node_type == nd.NODE_TYPE.GLUE:
                    if glue_state is None:
                        spacing += n.glue.dimen
                    else:
                        spacing += Dimen(integer=self._glue_amount(n, None, glue_state))
                    continue
                if n.node_type == nd.NODE_TYPE.KERN:
                    spacing += n.kern
                    continue
        finally:
            self._pop_container()
        if int(spacing) != 0:
            self._append_output(parent, self.typesetNBSP(1, height=spacing))
        return parent

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
    
    def typesetTextRun(self, text):
        if not text:
            return ""
        span = builder.SPAN()
        style = Style()
        self.define_font(text.font)
        style["font-family"] = self._text_font_family(text.font)
        style["font-size"] = _pt(text.font.at)
        span.set("style", str(style))
        span.text= "".join([n.typeset(self) for n in text])
        return span

    def typesetSpring(self, ratio):
        div = builder.DIV()
        div.set("style", f"flex-grow:{ratio};flex-basis:0;")
        return div

    def typesetChar(self, char, kern):
        return char
    
    def typesetSpace(self, width):
        if width <= 0:
            return ""
        return " "

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

    def _box_flush_justify_content(self, box):
        items = list(getattr(box, "list", None) or ())
        if not items:
            return "flex-start"
        start = 0
        end = len(items) - 1
        while start <= end and not self._node_has_inline_anchor(items[start]):
            start += 1
        while end >= start and not self._node_has_inline_anchor(items[end]):
            end -= 1
        if start > end:
            return "flex-start"
        left_order = self._edge_stretch_order(items[:start])
        right_order = self._edge_stretch_order(items[end + 1:])
        if left_order is None:
            return "flex-start"
        if right_order is None:
            return "flex-end"
        if left_order > right_order:
            return "flex-end"
        if right_order > left_order:
            return "flex-start"
        return "center"
    
    def typesetMList(self, parent, nodes, atom_type: mmode.ATOM_TYPE, style: mmode.Style):
        # we need to consider the atom type (class) and family
        # for consecutive letters of ORD symbols of family 0, they are either names  or digits
        letters = ""
        has_dot = False
        is_digit = False
        nodes = iter(nodes)
        stack = []
        self._push_container(parent)
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
                                    self._append_output(parent, MI(letters, mathvariant="normal"))
                                    letters = ""
                                    is_digit = True
                                has_dot = True
                                letters += char
                                continue
                            if char.isdigit():
                                if not is_digit and letters:
                                    self._append_output(parent, MI(letters, mathvariant="normal"))
                                    letters = ""
                                is_digit = True
                                letters += char
                                continue
                            if is_digit and letters:
                                self._append_output(parent, MN(letters))
                                letters = ""
                                is_digit = False
                                has_dot = False
                            letters += char
                            continue
                if letters:
                    if is_digit:
                        self._append_output(parent, MN(letters))
                    else:
                        self._append_output(parent, MI(letters, mathvariant="normal"))
                    letters = ""
                    is_digit = False
                    has_dot = False
                if node.node_type == nd.NODE_TYPE.MATHNODE: # an atom
                    self._append_output(parent, self.typesetAtom(node, style=style))
                    continue
                if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY, nd.NODE_TYPE.MARK, nd.NODE_TYPE.ADJUST):
                     continue
                if node.node_type == nd.NODE_TYPE.VLIST:
                    self._append_output(parent, self.typesetVBox(node, inline=True))
                    continue
                if node.node_type == nd.NODE_TYPE.HLIST:
                    self._append_output(parent, self.typesetHBox(node, inline=True))
                    continue
                if node.node_type == nd.NODE_TYPE.WHATSIT:
                    node.output(self.parser, self)
                    continue
            if letters:
                if is_digit:
                    self._append_output(parent, MN(letters))
                else:
                    self._append_output(parent, MI(letters, mathvariant="normal"))
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
                nucleus.set("linethickness", _pt(thickness))
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
                    self._append_output(row, MTEXT(text))
                    text = ""
                if n.node_type == nd.NODE_TYPE.HLIST:
                    self._append_output(row, self.typesetMathHBox(n))
                elif n.node_type == nd.NODE_TYPE.VLIST:
                    self._append_output(row, self.typesetMathVBox(n))
                elif n.node_type == nd.NODE_TYPE.WHATSIT:
                    n.output(self.parser, self)
                elif n.node_type == nd.NODE_TYPE.MATH:
                    inline: mmode.InlineMathNode = n.source
                    while True:
                        n = next(nodes, None)
                        assert n is not None
                        if n.node_type == nd.NODE_TYPE.MATH:
                            break
                    self._append_output(
                        row,
                        self.typesetMList(MROW(), inline.list, mmode.ATOM_TYPE.ORD, mmode.Style(mmode.MATH_STYLE.T)),
                    )
            if text:
                self._append_output(row, MTEXT(text))
        finally:
            self._pop_container()
        return row

    def typesetMathVBox(self, vbox):
        matrix = None
        self._push_container(self._base_container())
        try:
            for n in vbox.list:
                if n.node_type == nd.NODE_TYPE.WHATSIT:
                    n.output(self.parser, self)
                elif isinstance(n.source, align.HAlignment):
                    matrix = n.source
        finally:
            self._pop_container()
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
        math = MATH(display="inline")
        style = Style()
        style["left"] = _pt(left_kern)
        style["right"] = _pt(right_kern)
        math.set("style", str(style))
        return self.typesetMList(math, node.list, atom_type=mmode.ATOM_TYPE.ORD, style=mmode.Style(mmode.MATH_STYLE.T))
    
    def typesetDisplayMath(self, node, collection, yspacing):
        math = MATH(display="block")
        style = Style()
        style["display"] = "block"
        style["top"] = _pt(yspacing)
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
    
    def typesetHAlignment(self, node: align.HAlignment, collection, yspacing):
        def noalign(vlist, columns):
            return builder.TR(builder.TD(self.typesetVList(builder.DIV(), vlist), colspan=str(columns), style="padding: 0;"))

        table = builder.TABLE()
        table.set("class", "alignment")
        style = Style()
        style["margin-top"] = _pt(yspacing)
        style["border-spacing"] = "0"
        style["width"]="100%"
        table.set("style", str(style))
        spacers = self._alignment_spacers(node)
        columns = node.columns() + len(spacers)
        if node.noalign:
            table.append(noalign(node.noalign, columns))
        for row in node.rows:
            tr = builder.TR()
            tr.append(builder.TD(style=f"width: {spacers[0]}%;"))
            col = 1
            for cell in row.cells:
                content = self.typesetHBox(cell, inline=False)
                content.set(
                    "style",
                    content.get("style", "") + "display:inline-flex;width:auto;max-width:100%;",
                )
                tr.append(builder.TD(content))
                if col < len(spacers):
                    tr.append(builder.TD(style=f"width: {spacers[col]}%;"))
                    col += cell.span
            table.append(tr)
            if row.noalign:
                table.append(noalign(row.noalign, columns))
        return table

    def rawSpecial(self, text):
        match = _DEST_RE.match(text)
        if match is not None:
            marker = builder.SPAN()
            marker.set("id", self._decode_pdf_string(f"({match.group(1)})"))
            self._append_output(self._base_container(), marker)
            return
        self._append_output(self._base_container(), self._special_marker(text))

    def annotate(self, kind, name=None, dimensions=None, payload=None):
        if kind == "end":
            if self._active_links:
                self._active_links.pop()
            return
        info = self._annotation_info(payload or "")
        link = self._link_element(info, kind)
        if link is None:
            self._append_output(
                self._base_container(),
                self._special_marker(payload or kind, attr="data-tex-annotation"),
            )
            if kind == "begin":
                self._active_links.append(None)
            return
        if kind == "fixed":
            self._append_output(self._base_container(), link)
            return
        if self._current_link() is not None:
            self._active_links.append(None)
            return
        self._append_output(self._base_container(), link)
        self._active_links.append(link)


def init(parser):
    font_subst.installFontSubstitution(parser)
    font_subst.installMathFontArrays(parser)
    parser.shipout = HTMLReflowBackend(parser)


mod = Module(
    "html_reflow",
    attributes={},
    init=init,
)
