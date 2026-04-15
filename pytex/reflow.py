"""
The base class for reflow shipout backends. providing common utilities for reflow backends such as HTML and DOCX.
"""


from pytex.dimen import Dimen
from pytex.font import Font
from pytex.typeset import shipout
from pytex import node as nd
from pytex import mmode
from pytex import align
from pytex import paragraph
from enum import IntEnum
from dataclasses import dataclass


@dataclass
class Char:
    char: str
    kern: Dimen

    def typeset(self, backend):
        return backend.typesetChar(self.char, self.kern)


@dataclass
class Space:
    width: Dimen

    def typeset(self, backend):
        return backend.typesetSpace(self.width)


class TextRun(list):
    def __init__(self, font: Font):
        self.font = font
        self.kern = None

    def setKern(self, kern):
        self.kern = kern

    def setChar(self, char):
        self.append(Char(char, self.kern))
        self.kern = None
    
    def typeset(self, backend):
        return backend.typesetTextRun(self)


class NBSP:
    def __init__(self, font, width):
        self.font = font
        self.width = width
    
    def typeset(self, backend):
        return backend.typesetNBSP(self.width)
    

class ParagraphJustification(IntEnum):
    LEFT = 0
    CENTER = 1
    RIGHT = 2


@dataclass
class InlineBox:
    box : nd.Box

    def typeset(self, backend):
        if self.box.node_type == nd.NODE_TYPE.HLIST:
            return backend.typesetHBox(self.box, inline=True)
        return backend.typesetVBox(self.box, inline=True)


@dataclass
class Spring:
    ratio: float

    def typeset(self, backend):
        return backend.typesetSpring(self.ratio)

class Paragraph(list):
    def __init__(self, indent=Dimen(), spacing_before = Dimen()):
        self.spacing_before = spacing_before
        self.indent = indent
        self.text_run = None

    def setChar(self, char: nd.CharNode):
        if self.text_run is None or self.text_run.font is not char.font:
            self.text_run = TextRun(char.font)
            super().append(self.text_run)
        self.text_run.setChar(char.char)

    def setKern(self, width: Dimen):
        if self.text_run is not None:
            self.text_run.setKern(width)
        else:
            self.setNBSP(width)

    def setSpace(self, width: Dimen):
        self.text_run = None
        super().append(Space(width))

    def setNBSP(self, width):
        self.text_run = None
        super().append(NBSP(self.parser.currentfont, width))

    def append(self, node):
        if node.node_type == nd.NODE_TYPE.CHAR:
            self.setChar(node)
        elif node.node_type == nd.NODE_TYPE.LIGATURE:
            for s in node.source:
                self.setChar(s)
        elif node.node_type == nd.NODE_TYPE.KERN:
            self.setKern(node.kern)
        elif node.node_type == nd.NODE_TYPE.HLIST:
            super().append(InlineBox(box=node))
        elif node.node_type == nd.NODE_TYPE.VLIST:
            super().append(InlineBox(box=node))
        else:
            super().append(node)


class Reflow(shipout.Shipout):
    def begin_page(self, box):
        pass

    def end_page(self, box):
        pass

    def define_font(self, font):
        pass

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
        pass

    def annotate(self, kind, name=None, dimensions=None, payload=None):
        pass

    def xObject(self, kind, name=None, options=None, source=None):
        pass

    def open(self):
        pass

    def close(self):
        pass

    def shipout(self, box):
        self.open()
        self.pages.append(box)
        self.begin_page(box)
        body_tree = self.findBody(box)
        if body_tree is None:
            # we have not found one box that is a vbox and contains \topskip
            # in this case the body is body
            body_tree = [box]
        self.typesetPage(body_tree)
        self.end_page(box)

    def findBody(self, box):
        tree = [box]
        for n in box.list:
            if n.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                tail = self.findBody(n)
                if tail is not None:
                    tree.extend(tail)
                    return tree
                continue
            if box.node_type == nd.NODE_TYPE.VLIST and n.node_type == nd.NODE_TYPE.GLUE and n.name == "\\topskip":
                return [box]
        return None
    
    def typesetPage(self, tree):
        pass

    def typesetVBox(self, box, inline=False, xspacing=Dimen(), yspacing=Dimen()):
        # we only need to layout this box
        # we need to consider two things: paragraphs and boxes that are not originated from paragraphs.
        # we first collect glues and kerns to figure out vertical spacing
        def collect(source, p, nodes):
            while p and p.source != n:
                p = next(nodes, None)
            collection = []
            while p and p.source == n:
                collection.append(p)
                p = next(nodes, None)
            return collection, p
        spacing = Dimen()
        glue_state = self._glue_state(box)
        vbox = self._box(box, inline, xspacing, yspacing)
        nodes = iter(box.list)
        p = next(nodes, None)
        for n in box.raw:
            if isinstance(n, mmode.DisplayMathNode):
                collection, p = collect(n, p, nodes)
                node = self.typesetDisplayMath(n, collection, yspacing=spacing)
                vbox.append(node)
                spacing = Dimen()
                continue
            if isinstance(n, paragraph.Paragraph):
                collection, p = collect(n, p, nodes)
                para = Paragraph(indent = Dimen(), spacing_before=spacing)
                self.populateParagraph(para, n.raw, collection, glue_state=None)
                vbox.append(self.typesetParagraph(para))
                spacing = Dimen()
                continue
            if isinstance(n, align.HAlignment):
                collection, p = collect(n, p, nodes)
                node = self.typesetHAlignment(n, collection, yspacing=spacing)
                vbox.append(node)
                spacing = Dimen()
                continue
            if isinstance(n, align.MAlignment):
                collection, p = collect(n, p, nodes)
                node = self.typesetMAlignment(n, collection, yspacing=spacing)
                vbox.append(node)
                spacing = Dimen()
                continue
            if n.node_type == nd.NODE_TYPE.VLIST:
                h = Dimen() if n.shifted is None else n.shifted
                vbox.append(self.typesetVBox(n, xspacing=h, yspacing=spacing))
                spacing = Dimen()
                continue
            if n.node_type == nd.NODE_TYPE.HLIST:
                # this hbox is manually constructed (i.e., without a source)
                vbox.append(self.typesetHBox(n))
                spacing = Dimen()
                continue
            if n.node_type == nd.NODE_TYPE.WHATSIT:
                n.output(self.parser, self)
                continue
            if n.node_type == nd.NODE_TYPE.GLUE:
                spacing += Dimen(integer=self._glue_amount(n, box, glue_state))
                continue
            if n.node_type == nd.NODE_TYPE.KERN:
                spacing += n.kern
                continue
            if n.node_type == nd.NODE_TYPE.INSERT:
                n.output(self.parser, self)
                spacing = Dimen()
                continue
        if int(spacing) != 0:
            vbox.append(self.typesetNBSP(1, height=spacing))
        return vbox
    
    def typesetHBox(self, box, inline=False, xspacing=Dimen(), yspacing=Dimen()):
        # this method is called for a standalone (manually constructed) hbox. We treat it as paragraph.
        glue_state = self._glue_state(box)
        shifted = Dimen() if box.shifted is None else box.shifted
        h = xspacing + shifted
        nodes = box.list
        # we start a new paragraph:
        para = Paragraph(indent=h, spacing_before=yspacing)
        self.populateParagraph(para, box.raw, [box], glue_state=glue_state)
        return self.typesetParagraph(para)
        
    def populateParagraph(self, para, raw, collection, glue_state):
        pass

    def typesetParagraph(self, para: Paragraph):
        pass

    def setChar(self, char, kern):
        pass

    def setSpace(self, width):
        pass

    def typesetNBSP(self, width, height=1):
        pass

    def typesetTextRun(self, text):
        pass

    def populateParagraph(self, para, raw, collection, glue_state):
        pass

    def typesetSpring(self, ratio):
        pass

    def typesetDisplayMath(self, node, collection, yspacing):
        pass

    def typesetHAlignment(self, node, collection, yspacing):
        pass

    def typesetMAlignment(self, node, collection, yspacing):
        pass

    def typesetInlineMath(self, node, collection, left_kern, right_kern):
        pass

    def _box(self, box, inline, xspacing, yspacing):
        raise NotImplementedError("subclass must implement _box method")
