"""
The base class for reflow shipout backends. providing common utilities for reflow backends such as HTML and DOCX.
"""


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

@dataclass
class InlineMath:
    node: mmode.InlineMathNode
    collection: list
    left_kern: Dimen
    right_kern: Dimen

    def typeset(self, backend):
        return backend.typesetInlineMath(self.node, self.collection, self.left_kern, self.right_kern)

class Paragraph(list):
    def __init__(self, indent=Dimen(), spacing_before = Dimen(), justify: str="left"):
        self.spacing_before = spacing_before
        self.indent = indent
        self.text_run = None
        self.justify = justify

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

    def setInlineMath(self, node: mmode.InlineMathNode, collection: list, left_kern: Dimen, right_kern: Dimen):
        super().append(InlineMath(node, collection, left_kern, right_kern))

    def append(self, node):
        if isinstance(node, Spring):
            self.text_run = None
            super().append(node)
            return
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


class Reflow(shipout.Shipout):
    def __init__(self, parser, output=None):
        super().__init__(parser, output)
        self.last_source = None
        self.box_stack = []

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

    def _collect(self, iter, source):
        p = next(iter, None)
        if p is None:
            return [], None
        s = source(p)
        if s is None:
            return [p], p
        collection = []
        while p and source(p) == s:
            collection.append(p)
            p = next(iter, None)
        return collection, s

    def typesetVList(self, parent, vlist: list, glue_state=None, mark_last_source=False):
        # we only need to layout this box
        # we need to consider two things: paragraphs and boxes that are not originated from paragraphs.
        # we first collect glues and kerns to figure out vertical spacing
        def source(node):
            while True:
                s = node.source
                if s is None or s.source is None:
                    return s
                node = s
        spacing = Dimen()
        nodes = iter(vlist)
        while True:
            collection, n = self._collect(nodes, source)
            if n is None:
                break
            if n is self.last_source:
                self.last_source = None
                continue
            if isinstance(n, mmode.DisplayMathNode):
                node = self.typesetDisplayMath(n, collection, yspacing=spacing)
                parent.append(node)
                spacing = Dimen()
                if mark_last_source:
                    self.last_source = n
                continue
            if isinstance(n, paragraph.Paragraph):
                # first the first line box
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
                    # this is an empty graph. We only count spacing
                    continue
                para = Paragraph(indent = Dimen(), spacing_before=spacing, justify=self._hbox_justification(line))
                self.populateParagraph(para, n.list, glue_state=None)
                parent.append(self.typesetParagraph(para))
                spacing = Dimen()
                if mark_last_source:
                    self.last_source = n
                continue
            if isinstance(n, align.HAlignment):
                node = self.typesetHAlignment(n, collection, yspacing=spacing)
                parent.append(node)
                spacing = Dimen()
                if mark_last_source:
                    self.last_source = n
                continue
            assert not isinstance(n, align.MAlignment)
            if n.node_type == nd.NODE_TYPE.VLIST:
                h = Dimen() if n.shifted is None else n.shifted
                parent.append(self.typesetVBox(n, xspacing=h, yspacing=spacing))
                spacing = Dimen()
                continue
            if n.node_type == nd.NODE_TYPE.HLIST:
                # this hbox is manually constructed (i.e., without a source)
                parent.append(self.typesetHBox(n))
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
            if n.node_type == nd.NODE_TYPE.INS:
                n.output(self.parser, self)
                spacing = Dimen()
                continue
        if int(spacing) != 0:
            parent.append(self.typesetNBSP(1, height=spacing))
        return parent
    
    def typesetVBox(self, box, inline=False, xspacing=Dimen(), yspacing=Dimen(), mark_last_source=False):
        self.box_stack.append(box)
        vbox = self._box(box, inline, xspacing, yspacing)
        glue_state = self._glue_state(box)
        content = self.typesetVList(vbox, box.list, glue_state, mark_last_source)
        self.box_stack.pop()
        return content

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
            if (raw.node_type == nd.NODE_TYPE.GLUE):
                if glue_state is None:
                    para.setSpace(raw.glue.dimen)
                elif (glue_state["order"] > 0 and
                    not glue_state["shrink"] and
                    glue_state["order"] == raw.glue.stretch.order
                ):
                    para.append(Spring(self._glue_amount(raw, box=None, state=glue_state)))
                else:
                    para.setSpace(self._glue_amount(raw, box=None, state=glue_state))
            elif isinstance(raw, mmode.InlineMathNode):
                para.setInlineMath(raw, collection, left_kern=Dimen(), right_kern=Dimen())
            elif raw.node_type == nd.NODE_TYPE.WHATSIT:
                raw.output(self.parser, self)
            if raw.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE, nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                para.append(raw)
            
    def typesetHBox(self, box, inline=False, xspacing=Dimen(), yspacing=Dimen()):
        # this method is called for a standalone (manually constructed) hbox. We treat it as paragraph.
        self.box_stack.append(box)
        glue_state = self._glue_state(box)
        shifted = Dimen() if box.shifted is None else box.shifted
        h = xspacing + shifted
        # we start a new paragraph:
        div = self._box(box, inline, h, yspacing)
        para = Paragraph(indent=Dimen(), spacing_before=yspacing, justify=self._hbox_justification(box))
        self.populateParagraph(para, box.list, glue_state=glue_state)
        self.typesetParagraph(para, container=div)
        self.box_stack.pop()
        return div
     
    def typesetParagraph(self, para: Paragraph, container=None):
        pass

    def setChar(self, char, kern):
        pass

    def setSpace(self, width):
        pass

    def typesetNBSP(self, width, height=1):
        pass

    def typesetTextRun(self, text):
        pass

    def typesetSpring(self, ratio):
        pass

    def typesetDisplayMath(self, node, collection, yspacing):
        pass

    def typesetHAlignment(self, node, collection, yspacing):
        pass

    def typesetInlineMath(self, node, collection, left_kern, right_kern):
        pass

    def _box(self, box, inline, xspacing, yspacing):
        raise NotImplementedError("subclass must implement _box method")

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
        