"""HTML reflow backend driven by the outer-vlist raw history."""

from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import re

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
_DEFAULT_FONT_ROLE = {
    "family": "serif",
    "weight": "normal",
    "style": "normal",
    "variant": "normal",
}


_CSS_POINTS_PER_TEX_POINT_NUM = 7200
_CSS_POINTS_PER_TEX_POINT_DEN = 7227


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

    def _css_string(self, text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _math_font_face_rule(self):
        backend = font_subst.resolveMathFontBackend(self.parser)
        if backend is None:
            return ""
        family = font_subst.fontBackendName(backend)
        path = getattr(backend, "path", None)
        if not family or not path:
            return ""
        try:
            uri = Path(path).resolve().as_uri()
        except Exception:
            return ""
        ext = Path(path).suffix.lower()
        format_name = {
            ".ttf": "truetype",
            ".otf": "opentype",
            ".ttc": "truetype",
            ".otc": "opentype",
        }.get(ext)
        src = f'url({self._css_string(uri)})'
        if format_name is not None:
            src += f' format({self._css_string(format_name)})'
        return f"@font-face{{font-family:{self._css_string(family)};src:{src};}}"

    def _math_font_stack(self):
        stack = []
        backend = font_subst.resolveMathFontBackend(self.parser)
        family = font_subst.fontBackendName(backend) if backend is not None else None
        if family and font_subst.usableFontName(family):
            stack.append(family)
        for name in font_subst.MATH_FONT_CANDIDATES:
            if font_subst.usableFontName(name) and name not in stack:
                stack.append(name)
        stack.append("math")
        items = [self._css_string(name) for name in stack[:-1]]
        items.append(stack[-1])
        return ",".join(items)

    def _document_css(self):
        parts = []
        font_face = self._math_font_face_rule()
        if font_face:
            parts.append(font_face)
        parts.append(f"math{{font-family:{self._math_font_stack()};}}")
        return "".join(parts)

    def _build_head(self):
        return builder.HEAD(
            builder.META(charset="utf-8"),
            builder.TITLE(self.parser.jobname or "texput"),
            builder.STYLE(self._document_css()),
        )

    def open(self):
        # Runtime shipout is intentionally side-effect free for HTML reflow.
        return

    def close(self):
        if hasattr(self.output, "write"):
            file = self.output
        else:
            if self.output is None:
                output = self.parser.jobname or "texput"
            if not output.endswith(".html"):
                output += ".html"
            file = self.parser.resolver.openOut(output, None)
        self.header = self._build_head()
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
            style["width"] = _pt(box.width)
        elif box.node_type == nd.NODE_TYPE.HLIST:
            style["display"] = "flex"
            style["align-items"] = "baseline"
            style["flex-wrap"] = "nowrap"
            style["white-space"] = "nowrap"
            style["width"] = _pt(box.width)
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
        div.set("style", div.get("style", "")+str(style))
        for n in para:
            s = n.typeset(self)
            if isinstance(s, str):
                s = builder.SPAN(s)
            div.append(s)
        return div

    def _text_font_family(self, font):
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
    
    def typesetTextRun(self, text):
        span = builder.SPAN()
        style = Style()
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
                                parent.append(MI(letters, mathvariant="normal"))
                                letters = ""
                                is_digit = True
                            has_dot = True
                            letters += char
                            continue
                        if char.isdigit():
                            if not is_digit and letters:
                                parent.append(MI(letters, mathvariant="normal"))
                                letters = ""
                            is_digit = True
                            letters += char
                            continue
                        if is_digit and letters:
                            parent.append(MN(letters))
                            letters = ""
                            is_digit = False
                            has_dot = False
                        letters += char
                        continue
            if letters:
                if is_digit:
                    parent.append(MN(letters))
                else:
                    parent.append(MI(letters, mathvariant="normal"))
                letters = ""
                is_digit = False
                has_dot = False
            if node.node_type == nd.NODE_TYPE.MATHNODE: # an atom
                parent.append(self.typesetAtom(node, style=style))
                continue
            if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY, nd.NODE_TYPE.MARK, nd.NODE_TYPE.ADJUST):
                 continue
            if node.node_type == nd.NODE_TYPE.VLIST:
                parent.append(self.typesetVBox(node, inline=True))
                continue
            if node.node_type == nd.NODE_TYPE.HLIST:
                parent.append(self.typesetHBox(node, inline=True))
                continue
            if node.node_type == nd.NODE_TYPE.WHATSIT:
                node.output(self.parser, self)
                continue
            if node.node_type == nd.NODE_TYPE.INS:
                node.output(self.parser, self)
        if letters:
            if is_digit:
                parent.append(MN(letters))
            else:
                parent.append(MI(letters, mathvariant="normal"))
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
                row.append(MTEXT(text))
                text = ""
            if n.node_type == nd.NODE_TYPE.HLIST:
                row.append(self.typesetMathHBox(n))
            elif n.node_type == nd.NODE_TYPE.VLIST:
                row.append(self.typesetMathVBox(n))
            elif n.node_type == nd.NODE_TYPE.WHATSIT:
                n.output(self.parser, self)
            elif n.node_type == nd.NODE_TYPE.MATH:
                inline: mmode.InlineMathNode = n.source
                while True:
                    n = next(nodes, None)
                    assert n is not None
                    if n.node_type == nd.NODE_TYPE.MATH:
                        break
                row.append(self.typesetMList(MROW(), inline.list, mmode.ATOM_TYPE.ORD, mmode.Style(mmode.MATH_STYLE.T)))
        if text:
            row.append(MTEXT(text))
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
            return self.typesetMList(MROW(), field.list, atom_type=atom_type, style=style)
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


def init(parser):
    font_subst.installFontSubstitution(parser)
    font_subst.installMathFontArrays(parser)
    parser.shipout = HTMLReflowBackend(parser)


mod = Module(
    "html_reflow",
    attributes={},
    init=init,
)
