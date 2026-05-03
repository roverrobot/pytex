"""
The base class for reflow shipout backends. providing common utilities for reflow backends such as HTML and DOCX.
"""

from __future__ import annotations

from pytex import box as bx
from pytex.dimen import Dimen
from pytex.font import Font
from pytex.glue import Glue
from pytex.typeset import shipout
from pytex import node as nd
from pytex import mmode
from pytex import align
from pytex import paragraph
from enum import IntEnum
from dataclasses import dataclass
import colorsys


def PT(pt):
    return f"{float(pt) / 72.27 * 72}pt"


@dataclass
class Color:
    rgba: tuple

    @staticmethod
    def _numbers(values):
        if isinstance(values, (str, int, float)):
            values = (values,)
        return tuple(float(v) for v in values)

    @classmethod
    def cmyk(cls, cmyk: tuple):
        c, m, y, k = cls._numbers(cmyk)
        r = (1 - c) * (1 - k)
        g = (1 - m) * (1 - k)
        b = (1 - y) * (1 - k)
        return cls(rgba=(r, g, b, 1))

    cymk = cmyk

    @classmethod
    def hsv(cls, hsv: tuple):
        h, s, v = cls._numbers(hsv)
        r, g, b = colorsys.hsv_to_rgb(h, s, v)
        return cls((r, g, b, 1))

    @classmethod
    def gray(cls, level):
        level = cls._numbers(level)[0]
        return cls((level, level, level, 1))

    @classmethod
    def rgb(cls, rgb: tuple):
        r, g, b = cls._numbers(rgb)
        return cls((r, g, b, 1))

    def __eq__(self, color):
        if not isinstance(color, Color):
            return False
        return self.rgba == color.rgba


Color.black = Color((0, 0, 0, 1))
Color.red = Color((1,0,0,1))


class Element:
    def __init__(self, node):
        self._node = node
        self.nodes = []

    @property
    def node(self):
        for n in self.nodes:
            self._node.append(n.node)
        return self._node

    def append(self, child):
        self.nodes.append(child)

    def set(self, key, value):
        self._node.set(key, value)

    def get(self, key):
        return self._node.get(key)

    def __len__(self):
        return len(self.nodes)


class Text(Element):
    def setKern(self, kern: Dimen):
        pass

    def setChar(self, char: str):
        pass

    def setSpace(self, char: str, breakable: bool=True):
        pass


class TextRun(Element):
    def __init__(self, node, font: Font=None, color: Color=Color.black):
        super().__init__(node)
        self.setFont(font)
        self.color = color
        self.text: Text = None

    def setFont(self, font):
        # the font may not have been known when the run is created
        self.font = font

    def newText(self) -> Text:
        pass

    def newInlineBlock(self, box: bx.Box):
        pass

    def newInlineMath(self):
        pass

    def setKern(self, kern: Dimen):
        if self.text is None:
            self.newText()
        self.text.setKern(kern)

    def setChar(self, char: str):
        if self.text is None:
            self.newText()
        self.text.setChar(char)

    def setSpace(self, width: Dimen, breakable:bool=True):
        if self.text is None:
            self.newText()
        self.text.setSpace(width, breakable)


class Paragraph(Element):
    def __init__(self, node, reflow:bool, color: Color=Color.black, spacing_before=Dimen(), justify: str="justify"):
        super().__init__(node)
        self.reflow = reflow
        self.setJustify(justify)
        self.color = color
        self.font = None
        self.text_run = self.newTextRun(None, color)
        self.inline_math_segment = 0 # 0 means not in inline math, i>0 means the ith segment (separated by line breaks)
        self.inline_math_node = None

    def setJustify(self, justify):
        pass

    def newTextRun(self, font, color) -> Text:
        pass

    def setFont(self, font: Font):
        if self.text_run.font is None:
            self.text_run.setFont(font)
        elif self.font is not font:
            self.text_run = self.newTextRun(font, self.color)
        self.font = font

    def setColor(self, color: Color):
        if self.color != color:
            self.text_run = self.newTextRun(self.font, color)
        self.color = color

    def setLineSpacing(self, spacing: Dimen):
        pass


class Math(Element):
    def __init__(self, node, inline: bool):
        super().__init__(node)
        self.inline = inline


class Cell(Element):
    def __init__(self, node, span=1, width=None, justify: str="justify"):
        super().__init__(node)
        self.justify = justify
        self.width = width
        self.span = span

    def newParagraph(self, color) -> Paragraph:
        pass


class Row(Element):
    def newCell(self, span=1, width=None, justify="justify") -> Cell:
        pass


class Table(Element):
    def __init__(self, node, xspacing=Dimen(), yspacing=Dimen()):
        super().__init__(node)

    def newRow(self) -> Row:
        pass


class Block(Element):
    """
    This is an abstraction of HBox and VBox
    """
    def __init__(self, node, inline: bool=False, xspacing=Dimen(), yspacing=Dimen()):
        super().__init__(node)
        self.inline = inline

    def newParagraph(self, color, spacing_before=Dimen(), justify: str="left") -> Paragraph:
        pass

    def newTable(self, xspacing=Dimen(), yspacing=Dimen()):
        pass

    def newBlock(self, xspacing=Dimen(), yspacing=Dimen()):
        pass

    def newGraph(self, key, type, file):
        pass


class Document(Element):
    def __init__(self, node, title: str, output=None):
        """
        output is a file like structure to write to, typically opened by Parser.resolver.openOut
        or None, which means no output
        """
        super().__init__(node)
        self.title = title
        self.output = output

    @property
    def body(self):
        pass

    @property
    def header(self):
        pass

    @property
    def footer(self):
        pass

    def newPage(self, width: Dimen, height: Dimen):
        pass

    def setBackgroundColor(self, color: Color):
        pass

    def defineFont(self, font):
        pass

    def definePicture(self, key, type, path):
        pass

    def save(self):
        pass


class Builder:
    def __init__(self, backend, container):
        self.backend = backend
        self.container = container

    def __enter__(self):
        self.backend.builder_stack.append(self.backend.builder)
        self.backend.builder = self

    def __exit__(self, exc_type, exc, tb):
        assert self.backend.builder == self
        self.backend.builder = self.backend.builder_stack.pop()

    def append(self, node):
        self.container.append(node)

    def get(self, key, default=None):
        return self.container.get(key, default)

    def set(self, key, value):
        self.container.set(key, value)

    def __getattr__(self, name):
        return getattr(self.container, name)


class ParagraphBuilder(Builder):
    def __init__(self, backend, container):
        super().__init__(backend, container)
        self.saved = None

    def __enter__(self):
        self.saved = self.backend.paragraph
        self.backend.paragraph = self.container
        super().__enter__()

    def __exit__(self, exc_type, exc, tb):
        super().__exit__(exc_type, exec, tb)
        self.backend.paragraph = self.saved
        self.saved = None


class AnnotationBuilder(Builder):
    def __init__(self, backend, parent, name):
        self.backend = backend
        self.name = name
        self.parent = parent
        self.container = None

    def beginAnnotation(self, name):
        pass

    def endAnnotation(self, name):
        pass

    def __enter__(self):
        self.beginAnnotation(self.name)
        super().__enter__()

    def __exit__(self, exc_type, exc, tb):
        super().__exit__(exc_type, exc, tb)
        self.endAnnotation(self.name)


def collect(nodes: list, source: callable):
    nodes = iter(nodes)
    collection = []
    part = []
    p = None
    while True:
        if p is None:
            p = next(nodes, None)
        if p is None:
            return collection
        s = source(p)
        if s is None:
            collection.append(([p], p))
            p = None
            continue
        part = []
        while p and source(p) == s:
            part.append(p)
            p = next(nodes, None)
        collection.append((part, s))


def vlist_source(node):
    while True:
        s = node.source
        if s is None or s.source is None:
            return s
        node = s


class Reflow(shipout.Shipout):
    def __init__(self, parser, paginate=False, ext=""):
        super().__init__(parser)
        self.paginate = paginate
        self.last_source = (None, None)
        self.box_stack = []
        self.document: Document = None
        self.builder_stack = []
        self.builder = None
        self.paragraph = None
        self.color: Color = Color.black
        self.color_stack: list = []

    def open(self):
        raise NotImplementedError("should be implemented by each subclass")

    def close(self):
        if self.document is not None:
            self.document.save()

    def define_font(self, font):
        raise NotImplementedError("should be implemented by each subclass")

    def select_font(self, font):
        pass

    def move_to(self, h, v):
        pass

    def set_char(self, node):
        pass

    def set_rule(self, node, box, move):
        pass

    def special(self, text):
        if not self._dvipdfm.emit(text):
            self.rawSpecial(text)

    def rawSpecial(self, text):
        pass

    def setColor(self, mode, space=None, values=None):
        color = self.color
        if space == "rgb":
            color = Color.rgb(values)
        elif space == "gray":
            color = Color.gray(values)
        elif space == "cmyk":
            color = Color.cmyk(values)
        elif mode != "pop":
            raise ValueError(f"unsupported color space {space}")
        if mode == "background":
            self.document.setBackgroundColor(color)
            return
        if mode == "push":
            self.color_stack.append(self.color)
        elif mode == "pop":
            color = self.color_stack.pop() if self.color_stack else Color.black
        else:
            assert mode == "set", "mode can only be set, push, pop, background"
        if self.color != color:
            self.color = color
            if self.paragraph is not None:
                self.paragraph.setColor(color)

    def setTarget(self, name):
        pass

    def _pdf_unit(self, value: str):
        assert value[-2:] == "pt"
        return float(value[:-2])

    def newAnnotationBuilder(self, name=None, payload=None):
        pass

    def newFixedAnnotation(self, name, w, h):
        pass

    def annotate(self, kind, name=None, dimensions=None, payload=None):
        if kind == "begin":
            builder = self.newAnnotationBuilder(name=name, payload=payload)
            builder.__enter__()
        elif kind == "end":
            assert isinstance(self.builder, AnnotationBuilder)
            if name is not None:
                assert self.builder.name == name
            self.builder.__exit__(None, None, None)
        else:
            assert kind == "fixed", "kind can only be begin, end, fixed"
            assert dimensions is not None
            for key, value in dimensions:
                if key == "width":
                    w = self._pdf_unit(value)
                elif key == "height":
                    h = self._pdf_unit(value)
            # TODO parse payload
            ann = self.newFixedAnnotation(name, w, h)
            if ann is not None:
                self.builder.append(ann)

    def xObject(self, kind, name=None, options=None, source=None):
        pass

    def open(self):
        """returns a new document"""
        raise NotImplementedError("This method should be implemented by each subclass")

    def close(self):
        if self.document is not None:
            self.document.save()
            self.document = None

    def begin_page(self, box):
        self.document.newPage(box.width, box.height)

    def end_page(self, box):
        pass

    def shipout(self, box):
        self.pages.append(box)
        if self.document is None:
            self.document = self.open()
        self.begin_page(box)
        body_tree = self._find_body(box)
        if body_tree is None:
            # we have not found one box that is a vbox and contains \topskip
            # in this case the body is body
            body_tree = [box]
        self.typesetHeader(body_tree)
        self.typesetBody(body_tree)
        self.typesetFooter(body_tree)
        self.end_page(box)

    def _find_body(self, box):
        """ return a box tree which leaf points to the page body """
        tree = [box]
        for n in box.list:
            if n.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                tail = self._find_body(n)
                if tail is not None:
                    tree.extend(tail)
                    return tree
                continue
            if box.node_type == nd.NODE_TYPE.VLIST and n.node_type == nd.NODE_TYPE.GLUE and n.name == "\\topskip":
                return [box]
        return None

    def typesetHeader(self, tree):
        pass

    def typesetFooter(self, tree):
        pass

    def typesetBody(self, tree):
        box = tree[-1]
        with Builder(self, self.document.body):
            self.typesetVList(box.list, self._glue_state(box), top_level=True)

    def _require_builder(self, method, *capabilities):
        builder = self.builder
        assert builder is not None, f"{method} requires a current reflow builder"
        missing = []
        for capability in capabilities:
            try:
                attr = getattr(builder, capability)
            except AttributeError:
                missing.append(capability)
                continue
            if not callable(attr):
                missing.append(capability)
        if missing:
            container = getattr(builder, "container", None)
            container_name = type(container).__name__ if container is not None else type(builder).__name__
            required = ", ".join(capabilities)
            missing = ", ".join(missing)
            raise AssertionError(
                f"{method} requires a builder with {required}; "
                f"{container_name} is missing {missing}"
            )
        return builder

    def typesetVList(self, vlist: list, glue_state=None, top_level=False):
        self._require_builder("typesetVList", "newParagraph", "newTable", "newBlock")
        # pagenate or not, if a source/raw node spans multiple paragraphs, we can always use the same
        # paragraph or table from the previous page to continue. For pagenation, if we control the vertical
        # layout correctly, continuation shoudl simply flow to the next page. For reflow, there is no page boundary.
        # If the vlist is not at the top_level (i.e., laying out a page), then we do not need to worry about page spanning.
        # for this reason, out .last_source should contain a pair of the source node and the container (paragraph)
        # For a table, it is fully laid out in the previous page, and so we shoudl ignore the continuation on the second page
        spacing = Dimen()
        collections = collect(vlist, vlist_source)
        for collection, n in collections:
            if n is None:
                break
            if isinstance(n, mmode.DisplayMathNode):
                # here the display math may have equation numbers, which may be implemented by a table.
                # alternatively, this can also be implemented as an SVG picture
                # so we let typesetDisplayMath to determine how to build it without specifying a container
                self.typesetDisplayMath(n, collection, yspacing=spacing)
                spacing = Dimen()
                # display math node does not span multiple pages
                if top_level:
                    self.last_source = (None, None)
                continue
            if isinstance(n, paragraph.Paragraph):
                if top_level and self.last_source[0] is n:
                    para = self.last_source[1]
                else:
                    para = self.builder.newParagraph(color=self.color, spacing_before=spacing)
                with ParagraphBuilder(self, para):
                    self.typesetParagraph(n, collection)
                spacing = Dimen()
                if top_level:
                    self.last_source = (n, para)
                continue
            if isinstance(n, align.HAlignment):
                if top_level and self.last_source[0]is n:
                    self.last_source = (None, None)
                    continue
                table = self.builder.newTable(yspacing=spacing)
                with Builder(self, table):
                    self.typesetHAlignment(n, collection, yspacing=spacing)
                spacing = Dimen()
                if top_level:
                    self.last_source = (n, table)
                continue
            assert not isinstance(n, align.MAlignment)
            if n.node_type == nd.NODE_TYPE.VLIST:
                h = Dimen() if n.shifted is None else n.shifted
                self.typesetVBox(n, xspacing=h, yspacing=spacing)
                spacing = Dimen()
                if top_level:
                    self.last_source = (None, None)
                continue
            if n.node_type == nd.NODE_TYPE.HLIST:
                # this hbox is manually constructed (i.e., without a source)
                h = Dimen() if n.shifted is None else n.shifted
                self.typesetHBox(n, xspacing=h, yspacing=spacing)
                spacing = Dimen()
                if top_level:
                    self.last_source = (None, None)
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

    def typesetVBox(self, box, xspacing=Dimen(), yspacing=Dimen()):
        self._require_builder("typesetVBox", "newBlock")
        self.box_stack.append(box)
        vbox = self.builder.newBlock(xspacing, yspacing)
        glue_state = self._glue_state(box)
        with Builder(self, vbox):
            self.typesetVList(box.list, glue_state, top_level=False)
        self.box_stack.pop()
        return vbox

    def typesetHBox(self, box: bx.HBox, xspacing=Dimen(), yspacing=Dimen()):
        self._require_builder("typesetHBox", "newBlock")
        # this method is called for a standalone (manually constructed) hbox. We treat it as paragraph.
        self.box_stack.append(box)
        shifted = Dimen() if box.shifted is None else box.shifted
        h = xspacing + shifted
        # we start a new paragraph:
        div: Block = self.builder.newBlock(h, yspacing)
        para = div.newParagraph(color=self.color, justify=self._hbox_justification(box))
        with ParagraphBuilder(self, para):
            self.typesetParagraph(box.list, [box], self._glue_state(box))
        self.box_stack.pop()
        return div

    def typesetSpring(self, ratio):
        pass

    def typesetDisplayMath(self, node, collection, yspacing:Dimen=Dimen()):
        pass

    def typesetInlineMath(self, node, box, piece):
        pass

    def _alignment_spacers(self, node):
        def ratio(stretch, total):
            return 0.0 if stretch.order < total.order else float(stretch.factor) / float(total.factor)
        tabskips = node.tabskips
        if not tabskips:
            return []
        total = Glue()
        for g in tabskips:
            total += g
        if total.stretch.order > 0:
            return [ratio(g.stretch, total.stretch) for g in tabskips]
        if int(total.dimen) == 0:
            return [0.0] * len(tabskips)
        return [float(g.dimen)/float(total.dimen) for g in tabskips]

    def typesetHAlignment(self, node: align.HAlignment, collection, yspacing):
        self._require_builder("typesetHAlignment", "newRow")
        def noalign(table, vlist, columns):
            """
            returns the total glue/spaces
            """
            for n in vlist:
                if n.node_type == nd.NODE_TYPE.WHATSIT:
                    n.output(self.parser, self)

        spacers = self._alignment_spacers(node)
        columns = node.columns() + len(spacers)
        table: Table = self.builder
        if node.noalign:
            noalign(table, node.noalign, columns)
        for row in node.rows:
            tr = table.newRow()
            with Builder(self, tr):
                if spacers[0] != 0.0:
                    self.builder.newCell(width=spacers[0])
                col = 1
                for cell in row.cells:
                    td = self.builder.newCell(cell.span, justify=self._hbox_justification(cell))
                    para = td.newParagraph(color=self.color)
                    with ParagraphBuilder(self, para):
                        self.typesetLine(nodes=self._hbox_line_nodes(cell), glue_state=self._glue_state(cell))
                    if col < len(spacers) and spacers[col] != 0.0:
                        self.builder.newCell(width=spacers[col])
                    col += cell.span
                if row.noalign:
                    noalign(table, row.noalign, columns)

    _hlist_concrete_type = (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.HLIST)

    def _hbox_justification(self, box):
        """
        if the box has no concrete node, return None. Otherwise, return "left"/"cneter"/"right"
        depending on whether there are nonzero glues on either side
        """
        def find_glue(nodes, order):
            # returns the total glue and whether met a concrete node
            total = Glue()
            for n in nodes:
                if n.node_type == nd.NODE_TYPE.GLUE and n.glue.stretch.order == order:
                    total += n.glue
                elif n.node_type in self._hlist_concrete_type:
                    return total.stretch.factor, True
            return total.stretch.factor, False

        order = 0 if box.natural is None else box.natural.stretch.order
        if order == 0:
            return "justify"
        left, met = find_glue(box.list, order)
        if not met:
            return None
        right, met = find_glue(reversed(box.list), order)
        if int(left) <= 0:
            return "left" if int(right) > 0 else "justify"
        return "center" if int(right) > 0 else "right"

    def _hbox_line_nodes(self, box):
        nodes = list(box.list)
        start = 0
        end = len(nodes)
        while start < end and getattr(nodes[start], "node_type", None) == nd.NODE_TYPE.GLUE:
            start += 1
        while end > start and getattr(nodes[end - 1], "node_type", None) == nd.NODE_TYPE.GLUE:
            end -= 1
        return nodes[start:end]

    def typesetParagraph(self,  _: paragraph.Paragraph, nodes: list, glue_state=None):
        self._require_builder("typesetParagraph", "newTextRun", "setLineSpacing")
        # first the first line box
        lb = None
        spacing = Dimen()
        ci = iter(nodes)
        # we iterate through the nodes to find the first line box, while collecting the glues and kerns before it
        while True:
            b = next(ci, None)
            if b is None:
                break
            if b.node_type == nd.NODE_TYPE.HLIST:
                lb = b
                break
            if b.node_type == nd.NODE_TYPE.GLUE:
                if glue_state is None:
                    spacing += b.glue.dimen
                else:
                    spacing += Dimen(integer=self._glue_amount(b, None, glue_state))
            elif b.node_type == nd.NODE_TYPE.KERN:
                spacing += b.kern
        if lb is None:
            return
        just = self._hbox_justification(lb)
        self.builder.setJustify(just)
        self.typesetLine(nodes=self._hbox_line_nodes(lb), glue_state=self._glue_state(lb))
        # we add all the interline glues
        spacing = Dimen()
        lines = 1
        while True:
            b = next(ci, None)
            if b is None:
                break
            if b.node_type == nd.NODE_TYPE.KERN:
                spacing += b.kern
            elif b.node_type == nd.NODE_TYPE.GLUE:
                spacing += self._glue_amount(b, None, glue_state)
            elif b.node_type == nd.NODE_TYPE.WHATSIT:
                b.output(self.parser, self)
            elif b.node_type == nd.NODE_TYPE.VLIST:
                self.typesetInlineBox(b)
            elif b.node_type == nd.NODE_TYPE.HLIST:
                self.typesetLine(nodes=self._hbox_line_nodes(b), glue_state=self._glue_state(b))
                lines += 1
        if lines > 1:
            self.builder.setLineSpacing(spacing / (lines-1))

    def typesetLine(self, nodes: list, glue_state=None):
        def typeset_inline_math(node: mmode.InlineMathNode, math_box, piece):
            if len(node.list) == 1:
                atom = node.list[0]
                if isinstance(atom, mmode.Box) and isinstance(atom.nucleus, bx.VBox) and atom.sub is None and atom.sup is None:
                    vbox = atom.nucleus
                    if vbox.list:
                        is_align = False
                        for n in vbox.list:
                            if isinstance(n.source, align.HAlignment):
                                is_align = True
                                break
                        if is_align:
                            self.typesetInlineBox(vbox)
                            return
            self.typesetInlineMath(node, math_box, piece)

        def pack_inline_math_nodes(parser, nodes, glue_state):
            math = bx.HBox(parser, None, None)
            math.list = nodes
            math.typeset(parser, [])
            if glue_state is not None:
                width = math.width
                num = glue_state["num"]
                stretch = math.natural.shrink if glue_state["shrink"] else math.natural.stretch
                if num != 0 and stretch.order == glue_state["order"] and int(stretch.factor) != 0:
                    sign = 1 if num > 0 else -1
                    math.glue_ratio = bx.GlueRatio(sign, abs(num), glue_state["den"])
                for n in nodes:
                    if n.node_type == nd.NODE_TYPE.GLUE:
                        amount = Dimen(integer=self._glue_amount(n, None, glue_state))
                        width += amount - n.glue.dimen
                math.width = width
                math.to = width
                math.spread = width - math.natural.dimen
            return math

        self._require_builder("typesetLine", "newTextRun")
        if len(self.paragraph) > 0:
            self.paragraph.text_run.setSpace(width=Dimen())
        inline_math_nodes = []
        for n in nodes:
            text_run = self.builder.text_run
            node_type = n.node_type
            if self.paragraph.inline_math_segment > 0:
                if node_type == nd.NODE_TYPE.MATH:
                    assert not n.on
                    math_box = pack_inline_math_nodes(self.parser, inline_math_nodes, glue_state)
                    with Builder(self, text_run):
                        typeset_inline_math(self.paragraph.inline_math_node, math_box, self.paragraph.inline_math_segment)
                    text_run.setSpace(n.kern)
                    inline_math_nodes = []
                    self.paragraph.inline_math_segment = 0
                    self.paragraph.inline_math_node = None
                else:
                    inline_math_nodes.append(n)
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                width = self._glue_amount(n, None, glue_state) if glue_state is not None else n.glue.dimen
                text_run.setSpace(width)
            elif node_type == nd.NODE_TYPE.KERN:
                text_run.setSpace(n.kern)
            elif node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                if text_run.font is not n.font:
                    self.builder.setFont(n.font)
                    text_run = self.builder.text_run
                text_run.setChar(n)
            elif node_type == nd.NODE_TYPE.MATH:
                assert n.on
                text_run.setSpace(n.kern)
                self.paragraph.inline_math_segment = 1
                self.paragraph.inline_math_node = n.source
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                with Builder(self, text_run):
                    self.typesetInlineBox(n)
            elif n.node_type == nd.NODE_TYPE.WHATSIT:
                n.output(self.parser, self)
        if self.paragraph.inline_math_segment > 0:
            # we finish a line inside an inline math
            text_run = self.builder.text_run
            math_box = pack_inline_math_nodes(self.parser, inline_math_nodes, glue_state)
            with Builder(self, text_run):
                typeset_inline_math(self.paragraph.inline_math_node, math_box, self.paragraph.inline_math_segment)
            # we increment the piece by 1 in the new line
            self.paragraph.inline_math_segment += 1

    def typesetInlineBox(self, box: bx.Box):
        self._require_builder("typesetInlineBox", "newInlineBlock")
        block: Block = self.builder.newInlineBlock(box)
        if box.node_type == nd.NODE_TYPE.HLIST:
            para = block.newParagraph(color=self.color, justify=self._hbox_justification(box))
            with ParagraphBuilder(self, para):
                self.typesetLine(nodes=self._hbox_line_nodes(box), glue_state=self._glue_state(box))
        else:
            with Builder(self, block):
                self.typesetVList(box.list, self._glue_state(box), top_level=False)
        return block
