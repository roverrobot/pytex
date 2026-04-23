"""
The base class for reflow shipout backends. providing common utilities for reflow backends such as HTML and DOCX.
"""

from __future__ import annotations

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
        return self._node
    
    def append(self, child):
        self._node.append(child.node)
        self.nodes.append(child)

    def set(self, key, value):
        self._node.set(key, value)

    def get(self, key):
        return self._node.get(key)


class TextRun(Element):
    def __init__(self, node, font: Font, color: Color=Color.black):
        super().__init__(node)
        self.font = font
        self.color = color

    def setKern(self, kern: Dimen):
        pass

    def setChar(self, char: str):
        pass


class Line(Element):
    def __init__(self, node, justify):
        super().__init__(node)
        self.jutify = justify

    def newTextRun(self, font, color) -> TextRun:
        pass

    def newInlineBlock(self, box: bx.Box):
        pass

    def newInlineMath(self, backend, inlinemath: InlineMathNode, nodes: list):
        pass

    def setSpace(self, width: Dimen):
        pass


class Paragraph(Element):
    def __init__(self, node, reflow:bool, spacing_before=Dimen(), justify: str="justify"):
        super().__init__(node)
        self.reflow = reflow
        self.last_source = None
        self.justify = justify

    def newLine(self):
        pass

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
    
    def newParagraph(self) -> Paragraph:
        pass


class Row(Element):
    def __init__(self, node):
        super().__init__(node)

    def newCell(self, span=1, width=None, justified="justififed") -> Cell:
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

    def newDisplaymath(self, spacing_before: Dimen=Dimen()) -> Math:
        pass

    def newTable(self, xspacing=Dimen(), yspacing=Dimen()):
        pass

    def newBlock(self, xspacing=Dimen(), yspacing=Dimen()):
        pass 

    def newGraph(self, key, type, file):
        pass


class Page(Element):
    def __init__(self, node, width: Dimen, height: Dimen):
        super().__init__(node)
        self.width = width
        self.height = height

    @property
    def header(self) -> Block:
        pass

    @property
    def body(self) -> Block:
        pass

    @property
    def footer(self) -> Block:
        pass

    def setBackgroundColor(self, color: Color):
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

    def newPage(self, width: Dimen, height: Dimen) -> Page:
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


class HListSource:
    def __init__(self):
        self.inline_math = None
    
    def __call__(self, node):
        if node.node_type == nd.NODE_TYPE.MATH:
            self.inline_math = node.source if node.on else None
            return node.source
        if self.inline_math is not None:
            return self.inline_math
        return node.source


class Reflow(shipout.Shipout):
    def __init__(self, parser, paginate=False, ext=""):
        super().__init__(parser)
        self.paginate = paginate
        self.last_source = None
        self.box_stack = []
        self.document: Document = None
        self.page: Page = None
        self.builder_stack = []
        self.builder = None
        self.color: Color = Color.black
        self.color_stack: list = []
        # we do not need to store the current font, as each CharNode stores it

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
            self.page.setBackgroundColor(color)
            return
        if mode == "push":
            self.color_stack.append(self.color)
        elif mode == "pop":
            color = self.color_stack.pop() if self.color_stack else Color.black
        else:
            assert mode == "set", "mode can only be set, push, pop, background"
        if self.color != color:
            self.color = color

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
        self.page = self.document.newPage(box.width, box.height)

    def end_page(self, box):
        self.page = None

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
        with Builder(self, self.page.body):
            self.typesetVList(box.list, self._glue_state(box), True)

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

    def typesetVList(self, vlist: list, glue_state=None, mark_last_source=False):
        self._require_builder("typesetVList", "newParagraph", "newTable", "newBlock")
        # we only need to layout this box
        # we need to consider two things: paragraphs and boxes that are not originated from paragraphs.
        # we first collect glues and kerns to figure out vertical spacing
        # clear block level and lower
        spacing = Dimen()
        collections = collect(vlist, vlist_source)
        for collection, n in collections:
            if n is None:
                break
            if not self.paginate and n is self.last_source:
                self.last_source = None
                continue
            if isinstance(n, mmode.DisplayMathNode):
                self.typesetDisplayMath(n, collection, yspacing=spacing)
                spacing = Dimen()
                if not self.paginate:
                    self.last_source = n
                continue
            if isinstance(n, paragraph.Paragraph):
                para = self.builder.newParagraph(spacing_before=spacing)
                with Builder(self, para):
                    self.typesetParagraph(n, collection)
                spacing = Dimen()
                if mark_last_source:
                    self.last_source = n
                continue
            if isinstance(n, align.HAlignment):
                with Builder(self, self.builder.newTable(yspacing=spacing)):
                    self.typesetHAlignment(n, collection, yspacing=spacing)
                spacing = Dimen()
                if mark_last_source:
                    self.last_source = n
                continue
            assert not isinstance(n, align.MAlignment)
            if n.node_type == nd.NODE_TYPE.VLIST:
                h = Dimen() if n.shifted is None else n.shifted
                self.typesetVBox(n, xspacing=h, yspacing=spacing)
                spacing = Dimen()
                continue
            if n.node_type == nd.NODE_TYPE.HLIST:
                # this hbox is manually constructed (i.e., without a source)
                h = Dimen() if n.shifted is None else n.shifted
                self.typesetHBox(n, xspacing=h, yspacing=spacing)
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
    
    def typesetVBox(self, box, xspacing=Dimen(), yspacing=Dimen(), mark_last_source=False):
        self._require_builder("typesetVBox", "newBlock")
        self.box_stack.append(box)
        vbox = self.builder.newBlock(xspacing, yspacing)
        glue_state = self._glue_state(box)
        with Builder(self, vbox):
            self.typesetVList(box.list, glue_state, mark_last_source)
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
        para = div.newParagraph(justify=self._hbox_justification(box))
        with Builder(self, para):
            self.typesetParagraph(box.list, [box], self._glue_state(box))
        self.box_stack.pop()
        return div
     
    def typesetSpring(self, ratio):
        pass

    def typesetDisplayMath(self, node, collection, yspacing):
        pass

    def typesetInlineMath(self, node, collection, left_kern, right_kern):
        pass

    def _alignment_spacers(self, node):
        def ratio(stretch, total):
            return 0 if stretch.order < total.order else stretch.factor / total.factor * 100.0
        tabskips = node.tabskips
        if not tabskips:
            return []
        total = Glue()
        for g in tabskips:
            total += g
        if total.stretch.order > 0:
            return [ratio(g.stretch, total.stretch) for g in tabskips]
        return [float(g.dimen)/float(total.dimen)*100 for g in tabskips]

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
                tr.newCell(width=spacers[0])
            col = 1
            for cell in row.cells:
                td = tr.newCell(cell.span, justify=self._hbox_justification(cell))
                para = td.newParagraph()
                line = para.newLine()
                with Builder(self, line):
                    self.typesetLine(cell, nodes=self._hbox_line_nodes(cell))
                if col < len(spacers):
                    tr.newCell(width=spacers[col])
                    col += cell.span
            if row.noalign:
                noalign(table, row.noalign, columns)

    _hlist_concrete_type = (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.HLIST)
        
    def _hbox_justification(self, box):
        """
        if the box has no concrete node, return None. Otherwise, return "left"/"cneter"/"right"
        depending on whether there are nonzero glues on either side
        """
        def find_glue(box, left=True):
            # returns the total glue and whether met a concrete node
            glue_state = self._glue_state(box)
            nodes = box.list if left else reversed(box.list)
            total = Dimen()
            for n in nodes:
                node_type = getattr(n, "node_type", None)
                if node_type == nd.NODE_TYPE.GLUE:
                    total += self._glue_amount(n, box, glue_state)
                    continue
                if node_type == nd.NODE_TYPE.HLIST:
                    g, met = find_glue(n, left)
                    total += g
                    if met:
                        return total, True
                    continue
                if node_type in self._hlist_concrete_type:
                    return total, True
            return total, False
        
        left, met = find_glue(box, left=True)
        if not met:
            return None
        right, met = find_glue(box, left=False)
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
        self._require_builder("typesetParagraph", "newLine", "setLineSpacing")
        # first the first line box
        lb = None
        spacing = Dimen()
        ci = iter(nodes)
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
        line = self.builder.newLine()
        with Builder(self, line):
            last_source = self.typesetLine(lb, nodes=self._hbox_line_nodes(lb))
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
                line: Line = self.builder.newLine()
                with Builder(self, line):
                    self.typesetInlineBox(b)
            elif b.node_type == nd.NODE_TYPE.HLIST:
                line = self.builder.newLine()
                with Builder(self, line):
                    last_source = self.typesetLine(b, last_source, nodes=self._hbox_line_nodes(b))
                lines += 1
        if lines > 1:
            self.builder.setLineSpacing(spacing / (lines-1))
    
    def typesetLine(self, box: bx.HBox, last_source=None, nodes=None):
        self._require_builder("typesetLine", "newTextRun", "setSpace", "newInlineBlock")
        text_run = None
        collection = collect(box.list if nodes is None else nodes, HListSource())
        glue_state = self._glue_state(box)
        for nodes, source in collection:
            if not self.paginate and source is last_source:
                continue
            last_source = source
            node_type = getattr(source, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                width = self._glue_amount(source, box, glue_state)
                target = self.builder if text_run is None else text_run
                target.setSpace(width)
            elif node_type == nd.NODE_TYPE.KERN:
                target = self.builder if text_run is None else text_run
                target.setSpace(source.kern)
            elif node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                if text_run is None:
                    text_run = self.builder.newTextRun(source.font, self.color)
                text_run.setChar(source)
            elif isinstance(source, mmode.InlineMathNode):
                text_run = None
                self.typesetInlineMath(source, collection, left_kern=Dimen(), right_kern=Dimen())
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                text_run = None
                self.typesetInlineBox(source)
            elif source.node_type == nd.NODE_TYPE.WHATSIT:
                text_run = None
                source.output(self.parser, self)
        return last_source

    def typesetInlineBox(self, box: bx.Box):
        self._require_builder("typesetInlineBox", "newInlineBlock")
        block: Block = self.builder.newInlineBlock(box)
        if box.node_type == nd.NODE_TYPE.HLIST:
            para = block.newParagraph(justify=self._hbox_justification(box))
            line = para.newLine()
            with Builder(self, line):
                self.typesetLine(box, nodes=self._hbox_line_nodes(box))
        else:
            with Builder(self, block):
                self.typesetVList(box.list, self._glue_state(box))
        return block
