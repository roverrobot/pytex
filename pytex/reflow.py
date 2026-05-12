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
from dataclasses import dataclass, field
import colorsys


def PT(pt):
    return f"{round(float(pt) / 72.27 * 72 * 20) / 20 }pt"


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

    def __len__(self):
        return len(self.nodes)


class Text(Element):
    def setKern(self, kern: Dimen):
        pass

    def setChar(self, char: str):
        pass

    def setSpring(self, width, percent):
        """
        Here width is the typeset width of the infinite glue set by tex, and percent is its percentage in stretching
        """
        pass


class TextRun(Element):
    def __init__(self, node, font: Font=None, color: Color=Color.black):
        super().__init__(node)
        self.color = color
        self.text: Text = None
        self.setFont(font)

    def setFont(self, font):
        # the font may not have been known when the run is created
        self.font = font

    def newText(self) -> Text:
        pass

    def newInlineVBox(self, box: bx.Box):
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


@dataclass
class LineSpec:
    line_box: bx.HBox
    spacing_before: Dimen
    color: Color

class Line(Element):
    def __init__(self, node, line_spec: LineSpec):
        super().__init__(node)
        self.color = line_spec.color
        self.font = None
        self._text_run = None
        self.lign_height = line_spec.line_box.height + line_spec.line_box.depth

    def textRun(self, new: bool=False):
        if self._text_run is None or new:
            self._text_run = self.newTextRun(self.font, self.color)
        return self._text_run

    def newTextRun(self, font, color) -> Text:
        pass

    def setFont(self, font: Font):
        if self._text_run is None:
            self.font = font
            return
        if self._text_run.font is None:
            self._text_run.setFont(font)
        elif self.font is not font:
            self.font = font
            self._text_run = self.newTextRun(self.font, self.color)
            return
        self.font = font

    def setColor(self, color: Color):
        if self._text_run is None:
            self.color = color
            return
        if self.color != color:
            self.color = color
            self._text_run = self.newTextRun(self.font, self.color)
            return
        self.color = color

    def newSpace(self, width, breakable: bool):
        pass

    def setSpace(self, width, breakable: bool):
        if int(width) != 0:
            self._text_run = None
            self.newSpace(width, breakable)


class Paragraph(Element):
    def __init__(self, node, spacing_before=Dimen(), justify: str="justify"):
        super().__init__(node)
        self.setJustify(justify)
        self.justify = justify
        self.inline_math_segment = 0 # 0 means not in inline math, i>0 means the ith segment (separated by line breaks)
        self.inline_math_node = None

    def setJustify(self, justify):
        pass

    def newLine(self, line_spec: LineSpec) -> Line:
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

    def newParagraph(self) -> Paragraph:
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

    def newParagraph(self, spacing_before=Dimen(), justify: str="left") -> Paragraph:
        pass

    def newTable(self, xspacing=Dimen(), yspacing=Dimen()):
        pass

    def newGraph(self, key, type, file):
        pass


@dataclass
class PageSpec:
    width: Dimen
    height: Dimen
    margin_left: Dimen
    margin_top: Dimen
    margin_right: Dimen
    margin_bottom: Dimen

    def signature(self):
        return f"w:{self.width};h:{self.height};l:{self.margin_left};t:{self.margin_top};r:{self.margin_right};b:{self.margin_bottom}"


@dataclass
class VBoxContext:
    box: bx.Box
    left: Dimen
    top: Dimen
    xspacing: Dimen = field(default_factory=Dimen)
    yspacing: Dimen = field(default_factory=Dimen)


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

    def newPage(self, PageSpec):
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

    def enter(self):
        self.backend.builder_stack.append(self.backend.builder)
        self.backend.builder = self

    def __enter__(self):
        return self.enter()

    def exit(self):
        assert self.backend.builder == self
        self.backend.builder = self.backend.builder_stack.pop()

    def __exit__(self, exc_type, exc, tb):
        return self.exit()

    def append(self, node):
        self.container.append(node)

    def __getattr__(self, name):
        return getattr(self.container, name)


class ParagraphBuilder(Builder):
    def __init__(self, backend, container):
        super().__init__(backend, container)
        self.saved = None

    def enter(self):
        self.saved = self.backend.paragraph
        self.backend.paragraph = self.container
        super().enter()

    def exit(self):
        super().exit()
        self.backend.paragraph = self.saved
        self.saved = None


class LineBuilder(Builder):
    def enter(self):
        self.saved_in_line = self.backend.in_line
        super().enter()
        self.backend.in_line = True
        if self.backend.pending_annotation is not None:
            name = self.backend.pending_annotation
            self.backend.pending_annotation = None
            ann = self.backend.newAnnotationBuilder(name=name)
            ann.enter()

    def exit(self):
        current = self.backend.builder
        if isinstance(current, AnnotationBuilder):
            current.exit()
            self.backend.pending_annotation = current.name
            assert self.backend.builder == self
        super().exit()
        self.backend.in_line = self.saved_in_line


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

    def enter(self):
        assert self.backend.in_line
        self.beginAnnotation(self.name)
        super().enter()

    def exit(self):
        super().exit()
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
        s = getattr(node, "source", None)
        if s is None:
            return s
        if getattr(s, "source", None) is None:
            if isinstance(s, bx.Box):
                return None
            return s
        node = s


class Reflow(shipout.Shipout):
    def __init__(self, parser, paginate=False, ext=""):
        super().__init__(parser)
        self.paginate = paginate
        self.last_source = (None, None)
        self.vbox_stack: list[VBoxContext] = []
        self.document: Document = None
        self.builder_stack = []
        self.builder = None
        self.paragraph = None
        self.color: Color = Color.black
        self.color_stack: list = []
        self.pending_annotation = None
        self.in_line = False

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
            if self.in_line and self.builder is not None:
                set_color = getattr(self.builder, "setColor", None)
                if set_color is not None:
                    set_color(color)

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
            builder.enter()
        elif kind == "end":
            if self.pending_annotation is not None:
                if name is not None:
                    assert self.pending_annotation == name
                self.pending_annotation = None
                return
            assert isinstance(self.builder, AnnotationBuilder)
            if name is not None:
                assert self.builder.name == name
            self.builder.exit()
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
        body_tree, margin_left, margin_top = self._find_body(box)
        if body_tree is None:
            # we have not found one box that is a vbox and contains \topskip
            # in this case the body is body
            body_tree = [box]
        body = body_tree[-1]
        margin_right = box.width - margin_left - body.width
        margin_bottom = box.height + box.depth - margin_top - body.height - body.depth
        page_spec = PageSpec(box.width, box.height, margin_left, margin_top, margin_right, margin_bottom)
        self.document.newPage(page_spec)
        return body_tree

    def end_page(self, box):
        pass

    def shipout(self, box):
        self.pages.append(box)
        if self.document is None:
            self.document = self.open()
        body_tree = self.begin_page(box)
        self.typesetHeader(body_tree)
        self.typesetBody(body_tree)
        self.typesetFooter(body_tree)
        self.end_page(box)

    def _find_body(self, box):
        """ return a box tree which leaf points to the page body """
        tree = [box]
        x_offset = Dimen()
        y_offset = Dimen()
        vertical = box.node_type == nd.NODE_TYPE.VLIST
        glue_state = self._glue_state(box)
        for n in box.list:
            if n.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                tail, xoff, yoff = self._find_body(n)
                if tail is not None:
                    tree.extend(tail)
                    if vertical:
                        x_offset += n.shifted
                    else:
                        y_offset += n.shifted
                    return tree, x_offset + xoff, y_offset + yoff
                if vertical:
                    y_offset += n.height + n.depth
                    x_offset += n.shifted
                else:
                    x_offset += n.width
                    y_offset += n.shifted
                continue
            if n.node_type == nd.NODE_TYPE.GLUE:
                if n.name == "\\topskip":
                    return [box], Dimen(), Dimen()
                amount = Dimen(integer=self._glue_amount(n, box, glue_state))
                if vertical:
                    y_offset += amount
                else:
                    x_offset += amount
                continue
            if n.node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                if vertical:
                    y_offset += n.kern
                else:
                    x_offset += n.kern
                continue
            if not vertical and n.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                x_offset += n.width
        return None, Dimen(), Dimen()

    def typesetHeader(self, tree):
        pass

    def typesetFooter(self, tree):
        pass

    def typesetBody(self, tree):
        box = tree[-1]
        with Builder(self, self.document.body):
            self._push_vbox(box, Dimen(), Dimen())
            try:
                self.typesetVList(box.list, self._glue_state(box), top_level=True)
            finally:
                self.vbox_stack.pop()

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

    def typesetVList(self, vlist: list, glue_state=None, top_level=False, yspacing=Dimen()):
        self._require_builder("typesetVList", "newParagraph", "newTable")
        # pagenate or not, if a source/raw node spans multiple paragraphs, we can always use the same
        # paragraph or table from the previous page to continue. For pagenation, if we control the vertical
        # layout correctly, continuation shoudl simply flow to the next page. For reflow, there is no page boundary.
        # If the vlist is not at the top_level (i.e., laying out a page), then we do not need to worry about page spanning.
        # for this reason, out .last_source should contain a pair of the source node and the container (paragraph)
        # For a table, it is fully laid out in the previous page, and so we shoudl ignore the continuation on the second page
        spacing = Dimen(yspacing)
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
                    para = self.builder.newParagraph(spacing_before=spacing)
                self.typesetParagraph(para, n, collection)
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
                shifted = getattr(n, "shifted", None)
                h = Dimen() if shifted is None else shifted
                self.typesetVBox(n, xspacing=h, yspacing=spacing)
                spacing = Dimen()
                if top_level:
                    self.last_source = (None, None)
                continue
            if n.node_type == nd.NODE_TYPE.HLIST:
                # this hbox is manually constructed (i.e., without a source)
                self.typesetHBox(n, yspacing=spacing)
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

    def _push_vbox(self, box, xspacing=Dimen(), yspacing=Dimen()):
        if self.vbox_stack:
            parent = self.vbox_stack[-1]
            left = parent.left + xspacing
            top = parent.top + yspacing
        else:
            left = Dimen(xspacing)
            top = Dimen(yspacing)
        context = VBoxContext(box, left, top, Dimen(xspacing), Dimen(yspacing))
        self.vbox_stack.append(context)
        return context

    def typesetVBox(self, box, xspacing=Dimen(), yspacing=Dimen()):
        self._push_vbox(box, xspacing, yspacing)
        glue_state = self._glue_state(box)
        try:
            self.typesetVList(box.list, glue_state, top_level=False, yspacing=yspacing)
        finally:
            self.vbox_stack.pop()
        return self.builder

    def typesetHBox(self, box: bx.HBox, xspacing=Dimen(), yspacing=Dimen()):
        self._require_builder("typesetHBox", "newParagraph")
        # A standalone hbox in a vertical flow lowers like a single paragraph.
        para = self.builder.newParagraph(spacing_before=yspacing, justify=self._hbox_justification(box))
        with ParagraphBuilder(self, para):
            line_spec = LineSpec(box, spacing_before=Dimen(), color=self.color)
            line = para.newLine(line_spec)
            with LineBuilder(self, line):
                self.typesetLine(box)
        return para

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
                if spacers:
                    self.builder.newCell(width=spacers[0])
                col = 1
                for cell in row.cells:
                    cell_alignment = self._hbox_alignment_glue_state(cell, allow_unset=True)
                    td = self.builder.newCell(
                        cell.span,
                        justify=self._hbox_justification(cell, allow_unset=True),
                    )
                    para = td.newParagraph()
                    with ParagraphBuilder(self, para):
                        line_spec = LineSpec(cell, spacing_before=Dimen(), color=self.color)
                        line = para.newLine(line_spec)
                        with LineBuilder(self, line):
                            self.typesetLine(cell, alignment_state=cell_alignment)
                    if col < len(spacers):
                        self.builder.newCell(width=spacers[col])
                    col += cell.span
                if row.noalign:
                    noalign(table, row.noalign, columns)

    _hlist_concrete_type = (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.HLIST)

    def _hlist_has_visible_content(self, box):
        for node in getattr(box, "list", ()):
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.CHAR:
                if not getattr(node, "char", "").isspace():
                    return True
            elif node_type == nd.NODE_TYPE.LIGATURE:
                return True
            elif node_type == nd.NODE_TYPE.HLIST:
                if self._hlist_has_visible_content(node):
                    return True
            elif node_type in (nd.NODE_TYPE.VLIST, nd.NODE_TYPE.RULE, nd.NODE_TYPE.MATH):
                return True
        return False

    def _hbox_alignment_glue_state(self, box, allow_unset=False):
        glue_state = self._glue_state(box)
        if glue_state is not None and glue_state["order"] > 0:
            return glue_state
        if not allow_unset:
            return None
        natural = getattr(box, "natural", None)
        if natural is None or natural.stretch.order <= 0:
            return None
        return {"order": natural.stretch.order, "shrink": False}

    def _hbox_justification(self, box, allow_unset=False):
        """
        if the box has no concrete node, return None. Otherwise, return "left"/"cneter"/"right"
        depending on whether there are nonzero glues on either side
        """
        alignment_state = self._hbox_alignment_glue_state(box, allow_unset=allow_unset)
        if alignment_state is None or alignment_state["order"] == 0:
            return "justify"
        order = alignment_state["order"]
        shrink = alignment_state["shrink"]

        def active_part(glue):
            return glue.shrink if shrink else glue.stretch

        def find_glue(nodes, order):
            # returns the total glue and whether met a concrete node
            total = Glue()
            for n in nodes:
                if n.node_type == nd.NODE_TYPE.GLUE and active_part(n.glue).order == order:
                    total += n.glue
                elif n.node_type in self._hlist_concrete_type:
                    return active_part(total).factor, True
            return active_part(total).factor, False

        left, met = find_glue(box.list, order)
        if not met:
            return None
        right, met = find_glue(reversed(box.list), order)
        if int(left) <= 0:
            return "justify"
        return "center" if int(right) > 0 else "right"

    def _hbox_line_nodes(self, box, alignment_state=None):
        nodes = list(box.list)
        if alignment_state is None:
            alignment_state = self._hbox_alignment_glue_state(box)
        if alignment_state is None or alignment_state["order"] == 0:
            return nodes
        order = alignment_state["order"]
        shrink = alignment_state["shrink"]

        def is_alignment_glue(node):
            if getattr(node, "node_type", None) != nd.NODE_TYPE.GLUE:
                return False
            part = node.glue.shrink if shrink else node.glue.stretch
            return part.order == order and order > 0 and int(part.factor) != 0

        first = None
        last = None
        for i, node in enumerate(nodes):
            if getattr(node, "node_type", None) in self._hlist_concrete_type:
                first = i
                break
        for i in range(len(nodes) - 1, -1, -1):
            if getattr(nodes[i], "node_type", None) in self._hlist_concrete_type:
                last = i
                break
        if first is None or last is None:
            return [node for node in nodes if not is_alignment_glue(node)]
        # remove all leading and trailing glues
        return (
            [node for node in nodes[:first] if node.node_type != nd.NODE_TYPE.GLUE] 
            + nodes[first:last + 1]
            + [node for node in nodes[last + 1:] if node.node_type != nd.NODE_TYPE.GLUE]
        )

    def typesetParagraph(self,  para: Paragraph, _: paragraph.Paragraph, nodes: list, glue_state=None):
        if not nodes:
            return
        # we add all the interline glues
        spacing = Dimen()
        pb = ParagraphBuilder(self, para)
        pb.enter()
        for n in nodes:
            if n.node_type == nd.NODE_TYPE.KERN:
                spacing += n.kern
            elif n.node_type == nd.NODE_TYPE.GLUE:
                spacing += Dimen(integer=self._glue_amount(n, None, glue_state))
            elif n.node_type == nd.NODE_TYPE.WHATSIT:
                n.output(self.parser, self)
            elif n.node_type == nd.NODE_TYPE.HLIST: # a line box
                just = self._hbox_justification(n)
                if len(para) == 0: # first line
                    para.setJustify(just)
                elif just != para.justify:
                    pb.exit()
                    inline_math_segment = para.inline_math_segment
                    inline_math_node = para.inline_math_node
                    para = self.builder.newParagraph(spacing, just)
                    para.inline_math_segment = inline_math_segment
                    para.inline_math_node = inline_math_node
                    pb = ParagraphBuilder(self, para)
                    pb.enter()
                line_spec = LineSpec(n, spacing_before=spacing, color=self.color)
                line = para.newLine(line_spec)
                with LineBuilder(self, line):
                    self.typesetLine(n, spacing)
                spacing = Dimen()
        pb.exit()

    def typesetLine(
        self,
        line: bx.HBox,
        yspacing: Dimen=Dimen(),
        glue_state=None,
        inline=False, # if inline is True, it is from an inline \hbox, and so we need to keep the right spacing
        alignment_state=None,
    ):
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
                            self.typesetInlineVBox(vbox)
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

        assert isinstance(self.builder, (LineBuilder, AnnotationBuilder)) or isinstance(line, (list, tuple))
        self._require_builder("typesetLine", "newTextRun", "setSpace")
        if isinstance(line, (list, tuple)):
            nodes = list(line)
        else:
            if inline:
                nodes = list(getattr(line, "list", ()))
            else:
                nodes = line.list if self.paginate else self._hbox_line_nodes(line, alignment_state=alignment_state)
            if glue_state is None:
                glue_state = self._glue_state(line)
        inline_math_nodes = []

        for n in nodes:
            node_type = n.node_type
            if self.paragraph.inline_math_segment > 0:
                if node_type == nd.NODE_TYPE.MATH:
                    assert not n.on
                    math_box = pack_inline_math_nodes(self.parser, inline_math_nodes, glue_state)
                    text_run = self.builder.textRun()
                    with Builder(self, text_run):
                        typeset_inline_math(self.paragraph.inline_math_node, math_box, self.paragraph.inline_math_segment)
                    text_run.setKern(n.kern)
                    inline_math_nodes = []
                    self.paragraph.inline_math_segment = 0
                    self.paragraph.inline_math_node = None
                else:
                    inline_math_nodes.append(n)
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                width = Dimen(integer=self._glue_amount(n, None, glue_state)) if glue_state is not None else n.glue.dimen
                self.builder.setSpace(width, breakable=True)
            elif node_type == nd.NODE_TYPE.KERN:
                self.builder.setSpace(n.kern, breakable=False)
            elif node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                self.builder.setFont(n.font)
                self.builder.textRun().setChar(n)
            elif node_type == nd.NODE_TYPE.MATH:
                assert n.on
                self.builder.textRun().setKern(n.kern)
                self.paragraph.inline_math_segment = 1
                self.paragraph.inline_math_node = n.source
            elif node_type == nd.NODE_TYPE.HLIST:
                if not n.list:
                    self.builder.setSpace(n.width, breakable=False)
                    continue
                self.typesetLine(n, glue_state=self._glue_state(n), inline=True)
            elif node_type == nd.NODE_TYPE.VLIST:
                with Builder(self, self.builder.textRun()):
                    self.typesetInlineVBox(n)
            elif n.node_type == nd.NODE_TYPE.WHATSIT:
                # Specials can change annotation/color state, so they are explicit
                # text-run boundaries in the source line.
                n.output(self.parser, self)
                self.builder.textRun(new=True)
        if self.paragraph.inline_math_segment > 0:
            # we finish a line inside an inline math
            text_run = self.builder.textRun()
            math_box = pack_inline_math_nodes(self.parser, inline_math_nodes, glue_state)
            with Builder(self, text_run):
                typeset_inline_math(self.paragraph.inline_math_node, math_box, self.paragraph.inline_math_segment)
            # we increment the piece by 1 in the new line
            self.paragraph.inline_math_segment += 1

    def typesetInlineVBox(self, box: bx.Box):
        self._require_builder("typesetInlineVBox", "newInlineVBox")
        block: Block = self.builder.newInlineVBox(box)
        assert box.node_type == nd.NODE_TYPE.VLIST
        with Builder(self, block):
            self.typesetVList(box.list, self._glue_state(box), top_level=False)
        return block
