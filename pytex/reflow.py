"""
The base class for reflow shipout backends. providing common utilities for reflow backends such as HTML and DOCX.
"""

from pytex import box as bx
from pytex import graphics
from pytex.dimen import Dimen, UNITS
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


_ONE_INCH = Dimen(integer=Dimen._trunc_div(UNITS["in"][0] * Dimen.scale, UNITS["in"][1]))


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
    default_font: Font


@dataclass
class LineAdvance:
    emitted: Dimen = field(default_factory=Dimen)
    pending: Dimen = field(default_factory=Dimen)
    breakable: bool = False


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

    def setTextBaselineFromBottom(self, baseline: Dimen):
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
    def newCell(self, span=1, width=None, relative_width=None, justify="justify") -> Cell:
        pass


class Table(Element):
    def __init__(self, node, xspacing=Dimen(), yspacing=Dimen()):
        super().__init__(node)

    def newRow(self, row_box=None, spacing_before=Dimen()) -> Row:
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
    header_distance: object = None
    footer_distance: object = None

    def signature(self):
        signature = f"w:{self.width};h:{self.height};l:{self.margin_left};t:{self.margin_top};r:{self.margin_right};b:{self.margin_bottom}"
        if self.header_distance is not None:
            signature += f";hd:{self.header_distance}"
        if self.footer_distance is not None:
            signature += f";fd:{self.footer_distance}"
        return signature


@dataclass
class VModeRegionItem:
    node: nd.Node
    # Horizontal position of this item in the extracted vertical region.
    x: Dimen = field(default_factory=Dimen)
    # Vertical advance before this item in the extracted vertical region.
    y: Dimen = field(default_factory=Dimen)


@dataclass
class HModeRegionItem:
    node: nd.Node
    # Horizontal advance before this item in the extracted horizontal region.
    x: Dimen = field(default_factory=Dimen)
    # Vertical position of this item in the extracted horizontal region.
    y: Dimen = field(default_factory=Dimen)


@dataclass
class PageRegions:
    body: object = None
    body_x: Dimen = field(default_factory=Dimen)
    body_y: Dimen = field(default_factory=Dimen)
    header_y: object = None
    footer_y: object = None
    header: list[VModeRegionItem] = field(default_factory=list)
    footer: list[VModeRegionItem] = field(default_factory=list)
    left_margin: list[HModeRegionItem] = field(default_factory=list)
    right_margin: list[HModeRegionItem] = field(default_factory=list)


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
        finalize = getattr(self.container, "finalizeLine", None)
        if finalize is not None:
            finalize()
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
        self.transform_stack = [(1.0, 1.0)]
        self.pending_annotation = None
        self.in_line = False
        self._last_graphic_advance = None
        self._inline_paint_flush = None
        self._line_baseline_shift_stack: list[Dimen] = []

    support_annotation = False

    def open(self):
        raise NotImplementedError("should be implemented by each subclass")

    def close(self):
        if self.document is not None:
            self.document.save()

    def define_font(self, font):
        raise NotImplementedError("should be implemented by each subclass")

    def _define_font_once(self, font):
        if font is None:
            return
        key = id(font)
        if key in self._defined_fonts:
            return
        self.define_font(font)
        self._defined_fonts.add(key)

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

    def currentTransformScale(self):
        return self.transform_stack[-1]

    def beginTransform(self):
        self.transform_stack.append(self.transform_stack[-1])

    def scaleTransform(self, sx, sy):
        curx, cury = self.transform_stack[-1]
        self.transform_stack[-1] = (curx * float(sx), cury * float(sy))

    def endTransform(self):
        if len(self.transform_stack) > 1:
            self.transform_stack.pop()

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
        if not self.support_annotation:
            return
        if kind == "begin":
            if self.builder is None or not self.in_line:
                return
            builder = self.newAnnotationBuilder(name=name, payload=payload)
            builder.enter()
        elif kind == "end":
            if self.pending_annotation is not None:
                if name is not None:
                    assert self.pending_annotation == name
                self.pending_annotation = None
                return
            if self.builder is None or not self.in_line:
                return
            assert isinstance(self.builder, AnnotationBuilder)
            if name is not None:
                assert self.builder.name == name
            self.builder.exit()
        else:
            assert kind == "fixed", "kind can only be begin, end, fixed"
            if self.builder is None:
                return
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
        if kind not in ("epdf", "image") or not source:
            return
        self.graphic(
            graphics.GraphicSpec.from_dvipdfm(
                kind,
                name=name,
                options=options,
                source=source,
            )
        )

    def graphic(self, spec):
        if self.builder is None:
            return
        request = self.graphicRequestFromSpec(spec)
        if request is None:
            return
        asset = self.prepareGraphicAsset(request)
        if asset is None:
            return
        flush = self._inline_paint_flush
        if flush is not None:
            flush()
        advance = self.typesetGraphicAsset(asset, request)
        if advance is None:
            advance = request.width or asset.width
        if advance is not None:
            advance = Dimen(advance)
            self._last_graphic_advance = advance
            return advance

    def typesetGraphicAsset(self, asset, request):
        pass

    def open(self):
        """returns a new document"""
        raise NotImplementedError("This method should be implemented by each subclass")

    def close(self):
        if self.document is not None:
            self.document.save()
            self.document = None

    def begin_page(self, box, page_spec=None):
        if page_spec is None:
            page_spec = self._page_spec_for_body(box, box, Dimen(), Dimen())
        self.document.newPage(page_spec)

    def _page_spec_for_body(self, page_box, body, body_x, body_y, regions=None):
        page_width, page_height, origin_x, origin_y = self._page_geometry(page_box)
        margin_left = origin_x + body_x
        margin_top = origin_y + body_y
        margin_right = page_width - margin_left - body.width
        margin_bottom = page_height - margin_top - body.height - body.depth
        header_distance = None
        footer_distance = None
        if regions is not None:
            if regions.header_y is not None:
                header_distance = origin_y + regions.header_y
            if regions.footer_y is not None:
                footer_distance = page_height - origin_y - regions.footer_y
        return PageSpec(
            page_width,
            page_height,
            margin_left,
            margin_top,
            margin_right,
            margin_bottom,
            self._nonnegative_dimen(header_distance),
            self._nonnegative_dimen(footer_distance),
        )

    @staticmethod
    def _nonnegative_dimen(value):
        if value is None:
            return None
        value = Dimen(value)
        if int(value) < 0:
            return Dimen()
        return value

    def _page_geometry(self, box):
        page_width = self._page_dimension_parameter("pdfpagewidth")
        page_height = self._page_dimension_parameter("pdfpageheight")
        origin_x = _ONE_INCH + self.parser.layout["hoffset"]
        origin_y = _ONE_INCH + self.parser.layout["voffset"]
        if page_width is None:
            page_width = box.width + 2 * origin_x
        if page_height is None:
            page_height = box.height + box.depth + 2 * origin_y
        return page_width, page_height, origin_x, origin_y

    def _page_dimension_parameter(self, name):
        try:
            value = self.parser.parameters[name]
        except KeyError:
            return None
        if value is None or int(value) <= 0:
            return None
        return Dimen(value)

    def end_page(self, box):
        pass

    def shipout(self, box):
        self.pages.append(box)
        if self.document is None:
            self.document = self.open()
        regions = self.walkPage(box)
        page_spec = self._page_spec_for_body(box, regions.body, regions.body_x, regions.body_y, regions)
        self.begin_page(box, page_spec)
        self.typesetHeaderRegion(regions.header)
        self.typesetLeftMarginRegion(regions.left_margin)
        self.typesetBodyBox(regions.body)
        self.typesetRightMarginRegion(regions.right_margin)
        self.typesetFooterRegion(regions.footer)
        self.end_page(box)

    def _is_body_vlist(self, box):
        if getattr(box, "node_type", None) != nd.NODE_TYPE.VLIST:
            return False
        return any(
            getattr(node, "node_type", None) == nd.NODE_TYPE.GLUE
            and getattr(node, "name", None) == "\\topskip"
            for node in getattr(box, "list", ())
        )

    def walkPage(self, box):
        start_y = box.height if getattr(box, "node_type", None) == nd.NODE_TYPE.HLIST else Dimen()
        regions = self._walkPageBox(box, Dimen(), start_y)
        if regions.body is None:
            regions.body = box
            regions.body_x = Dimen()
            regions.body_y = Dimen()
        return regions

    def _walkPageBox(self, box, x, y):
        node_type = getattr(box, "node_type", None)
        if node_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            return PageRegions()
        if self._is_body_vlist(box):
            return PageRegions(body=box, body_x=Dimen(x), body_y=Dimen(y))

        positioned = self._page_region_positions(box, x, y)
        for index, (node, item_x, item_y) in enumerate(positioned):
            child_type = getattr(node, "node_type", None)
            if child_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                continue
            child_regions = self._walkPageBox(node, item_x, item_y)
            if child_regions.body is None:
                continue
            before = positioned[:index]
            after = positioned[index + 1:]
            if node_type == nd.NODE_TYPE.VLIST:
                child_regions.header = self._vmode_region_items(before) + child_regions.header
                child_regions.footer = child_regions.footer + self._vmode_region_items(after)
                child_regions.header_y = self._merge_region_y(
                    child_regions.header_y,
                    self._vmode_region_start(before),
                )
                child_regions.footer_y = self._merge_region_y(
                    child_regions.footer_y,
                    self._vmode_region_first_layout_bottom(after),
                )
            else:
                child_regions.left_margin = self._hmode_region_items(before) + child_regions.left_margin
                child_regions.right_margin = child_regions.right_margin + self._hmode_region_items(after)
            return child_regions
        return PageRegions()

    @staticmethod
    def _merge_region_y(current, candidate):
        if candidate is None:
            return current
        candidate = Dimen(candidate)
        if current is None or candidate < current:
            return candidate
        return current

    def _node_shift(self, node):
        return Dimen(getattr(node, "shifted", Dimen()))

    def _page_region_positions(self, box, x, y):
        items = []
        node_type = getattr(box, "node_type", None)
        vertical = node_type == nd.NODE_TYPE.VLIST
        glue_state = self._glue_state(box)
        cursor_x = Dimen(x)
        cursor_y = Dimen(y)
        for node in getattr(box, "list", ()):
            if vertical:
                item_x, item_y = self._vmode_item_position(node, cursor_x, cursor_y)
                items.append((node, item_x, item_y))
                cursor_y += self._vertical_advance(box, node, glue_state)
            else:
                item_x, item_y = self._hmode_item_position(node, cursor_x, cursor_y)
                items.append((node, item_x, item_y))
                cursor_x += self._horizontal_advance(box, node, glue_state)
        return items

    def _vmode_item_position(self, node, x, y):
        node_type = getattr(node, "node_type", None)
        if node_type == nd.NODE_TYPE.HLIST:
            return x + self._node_shift(node), y + node.height
        if node_type == nd.NODE_TYPE.VLIST:
            return x + self._node_shift(node), Dimen(y)
        return Dimen(x), Dimen(y)

    def _hmode_item_position(self, node, x, y):
        node_type = getattr(node, "node_type", None)
        if node_type == nd.NODE_TYPE.HLIST:
            return Dimen(x), y + self._node_shift(node)
        if node_type == nd.NODE_TYPE.VLIST:
            return Dimen(x), y + self._node_shift(node) - node.height
        return Dimen(x), Dimen(y)

    def _vertical_advance(self, box, node, glue_state):
        node_type = getattr(node, "node_type", None)
        if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            return node.height + node.depth
        if node_type == nd.NODE_TYPE.GLUE:
            return Dimen(integer=self._glue_amount(node, box, glue_state))
        if node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
            return node.kern
        if node_type == nd.NODE_TYPE.RULE:
            return node.height
        return Dimen()

    def _horizontal_advance(self, box, node, glue_state):
        node_type = getattr(node, "node_type", None)
        if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
            return node.width
        if node_type == nd.NODE_TYPE.GLUE:
            return Dimen(integer=self._glue_amount(node, box, glue_state))
        if node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
            return node.kern
        if node_type == nd.NODE_TYPE.RULE:
            return node.width
        return Dimen()

    def _vmode_region_items(self, positioned):
        """Convert page-positioned vmode items to region-flow items.

        The page walker uses absolute page coordinates internally to find the
        body and classify page regions. Header/footer consumers, however, are
        reflow stories. They need the vertical advance before each visible item,
        not an absolute page y coordinate. Region-level glue/kern therefore
        contributes only through the coordinate difference before the next
        visible box; trailing positioning resets are ignored.
        """
        if not positioned:
            return []
        region_start = self._vmode_region_start(positioned)
        cursor_bottom = region_start
        if cursor_bottom is None:
            cursor_bottom = self._vmode_region_top(positioned[0])
        items = []
        for node, x, y in positioned:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.WHATSIT:
                items.append(VModeRegionItem(node, Dimen(x), Dimen()))
                continue
            if node_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                continue
            top = self._vmode_region_top((node, x, y))
            if (
                region_start is not None
                and top < region_start
                and not self._region_node_has_layout(node)
            ):
                items.append(VModeRegionItem(node, Dimen(x), Dimen()))
                continue
            items.append(VModeRegionItem(node, Dimen(x), top - cursor_bottom))
            cursor_bottom = top + node.height + node.depth
        return items

    @staticmethod
    def _vmode_region_top(positioned_item):
        node, _, y = positioned_item
        if getattr(node, "node_type", None) == nd.NODE_TYPE.HLIST:
            return Dimen(y) - node.height
        return Dimen(y)

    def _vmode_region_start(self, positioned):
        first_layout = None
        for index, (node, _, _) in enumerate(positioned):
            if self._region_node_has_layout(node):
                first_layout = index
                break
        if first_layout is None:
            return None

        start = first_layout
        while start > 0 and self._is_region_spacing_node(positioned[start - 1][0]):
            start -= 1
        return self._vmode_region_top(positioned[start])

    def _vmode_region_first_layout_bottom(self, positioned):
        for node, x, y in positioned:
            if self._region_node_has_layout(node):
                top = self._vmode_region_top((node, x, y))
                return top + node.height + node.depth
        return None

    @staticmethod
    def _is_region_spacing_node(node):
        return getattr(node, "node_type", None) in (
            nd.NODE_TYPE.GLUE,
            nd.NODE_TYPE.KERN,
            nd.NODE_TYPE.MATH,
        )

    def _region_node_has_layout(self, node):
        node_type = getattr(node, "node_type", None)
        if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            if (
                int(getattr(node, "width", Dimen())) != 0
                or int(getattr(node, "height", Dimen())) != 0
                or int(getattr(node, "depth", Dimen())) != 0
            ):
                return True
            return any(self._region_node_has_layout(child) for child in getattr(node, "list", ()))
        if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
            return True
        if node_type == nd.NODE_TYPE.RULE:
            return (
                int(getattr(node, "width", Dimen())) != 0
                or int(getattr(node, "height", Dimen())) != 0
                or int(getattr(node, "depth", Dimen())) != 0
            )
        return False

    def _hmode_region_items(self, positioned):
        """Convert page-positioned hmode items to region-flow items."""
        if not positioned:
            return []
        cursor_right = Dimen(positioned[0][1])
        items = []
        for node, x, y in positioned:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.WHATSIT:
                items.append(HModeRegionItem(node, Dimen(), Dimen(y)))
                continue
            if node_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                continue
            x = Dimen(x)
            items.append(HModeRegionItem(node, x - cursor_right, Dimen(y)))
            width = getattr(node, "width", Dimen())
            cursor_right = x + width
        return items

    def typesetHeaderRegion(self, items):
        self.scanVModeRegionItems(items)

    def typesetFooterRegion(self, items):
        self.scanVModeRegionItems(items)

    def typesetLeftMarginRegion(self, items):
        self.scanHModeRegionItems(items)

    def typesetRightMarginRegion(self, items):
        self.scanHModeRegionItems(items)

    def scanVModeRegionItems(self, items):
        self.scanWhatsits([item.node for item in items])

    def scanHModeRegionItems(self, items):
        self.scanWhatsits([item.node for item in items])

    def scanWhatsits(self, nodes):
        for node in nodes:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.WHATSIT:
                self.handleUnsupportedRegionWhatsit(node)
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self.scanWhatsits(getattr(node, "list", ()))

    def handleUnsupportedRegionWhatsit(self, node):
        node.output(self.parser, self)

    def typesetBodyBox(self, box):
        with Builder(self, self.document.body):
            self._push_vbox(box, Dimen(), Dimen())
            try:
                self.typesetVList(box.list, self._glue_state(box), top_level=True)
            finally:
                self.vbox_stack.pop()

    def typesetHeader(self, tree):
        pass

    def typesetFooter(self, tree):
        pass

    def typesetBody(self, tree):
        self.typesetBodyBox(tree[-1])

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
                display_spacing = self.typesetDisplayMath(n, collection, yspacing=spacing, glue_state=glue_state)
                spacing = Dimen() if display_spacing is None else display_spacing
                # display math node does not span multiple pages
                if top_level:
                    self.last_source = (None, None)
                continue
            if isinstance(n, paragraph.Paragraph):
                if not any(node.node_type == nd.NODE_TYPE.HLIST for node in collection):
                    for node in collection:
                        if node.node_type == nd.NODE_TYPE.KERN:
                            spacing += node.kern
                        elif node.node_type == nd.NODE_TYPE.GLUE:
                            if glue_state is None:
                                spacing += node.glue.dimen
                            else:
                                spacing += Dimen(integer=self._glue_amount(node, None, glue_state))
                        elif node.node_type == nd.NODE_TYPE.WHATSIT:
                            node.output(self.parser, self)
                    continue
                if top_level and self.last_source[0] is n and int(spacing) == 0:
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
                    self.typesetHAlignment(n, collection, yspacing=spacing, glue_state=glue_state)
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
        if int(spacing) != 0:
            self.typesetTrailingVListSpacing(spacing, top_level=top_level)

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
            line_spec = LineSpec(box, spacing_before=Dimen(), color=self.color, default_font=self.parser.parameters["currentfont"])
            line = para.newLine(line_spec)
            with LineBuilder(self, line):
                self.typesetLine(box)
        return para

    def typesetSpring(self, ratio):
        pass

    def typesetTrailingVListSpacing(self, spacing: Dimen, top_level: bool=False):
        pass

    def typesetDisplayMath(self, node, collection, yspacing:Dimen=Dimen(), glue_state=None):
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

    def _alignment_row_specs(self, collection, yspacing, glue_state=None):
        spacing = Dimen(yspacing)
        specs = []
        for n in collection:
            node_type = getattr(n, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                if glue_state is None:
                    spacing += n.glue.dimen
                else:
                    spacing += Dimen(integer=self._glue_amount(n, None, glue_state))
                continue
            if node_type == nd.NODE_TYPE.KERN:
                spacing += n.kern
                continue
            if node_type == nd.NODE_TYPE.HLIST:
                specs.append((n, spacing))
                spacing = Dimen()
        return specs

    def _hbox_extent(self, box):
        x = Dimen()
        left = None
        right = None
        glue_state = self._glue_state(box)
        for node in getattr(box, "list", ()):
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.GLUE:
                if glue_state is None:
                    x += node.glue.dimen
                else:
                    x += Dimen(integer=self._glue_amount(node, box, glue_state))
                continue
            if node_type == nd.NODE_TYPE.KERN:
                x += node.kern
                continue
            if node_type == nd.NODE_TYPE.PENALTY:
                continue
            if node_type == nd.NODE_TYPE.MATH:
                x += getattr(node, "kern", Dimen())
                continue
            node_left, node_right = self._node_extent(node)
            if left is None or x + node_left < left:
                left = x + node_left
            if right is None or x + node_right > right:
                right = x + node_right
            width = getattr(node, "width", None)
            if width is not None:
                x += width
        if left is None:
            return Dimen(), Dimen()
        return left, right

    def _node_extent(self, node):
        if getattr(node, "node_type", None) == nd.NODE_TYPE.HLIST:
            return self._hbox_extent(node)
        width = getattr(node, "width", None)
        if width is None:
            return Dimen(), Dimen()
        return Dimen(), Dimen(width)

    def _subtract_previous_alignment_width(self, widths, amount):
        if not widths or int(amount) == 0:
            return
        prev_width, prev_is_spacer, prev_cell = widths[-1]
        widths[-1] = (prev_width - amount, prev_is_spacer, prev_cell)

    def _alignment_widths(self, row_box):
        # returns width, relative_width, cell (or None if it is a glue)
        assert row_box is not None
        glue_state = self._glue_state(row_box)
        cells = []
        total_glue = Dimen()
        for n in row_box.list:
            if n.node_type == nd.NODE_TYPE.GLUE:
                width = Dimen(integer=self._glue_amount(n, row_box, glue_state))
                cells.append((width, None))
                total_glue += width
            else:
                assert n.node_type == nd.NODE_TYPE.HLIST
                cells.append((n.width, n))
        widths = []
        debit_next = Dimen()
        for i in range(len(cells)):
            width, cell = cells[i]
            width -= debit_next
            debit_next = Dimen()
            if cell is None:
                widths.append((width, True, None))
                continue
            if cell.width == 0:
                left, right = self._hbox_extent(cell)
                if int(right - left) > 0:
                    if int(left) < 0:
                        self._subtract_previous_alignment_width(widths, -left)
                    if int(right) > 0:
                        debit_next += right
                    width = right - left
            widths.append((width, False, cell))
        total_spacer = sum((width for width, is_spacer, _ in widths if is_spacer), Dimen())
        return [
            (
                width,
                float(width) / total_spacer if is_spacer and int(total_spacer) != 0 else None,
                cell,
            )
            for width, is_spacer, cell in widths
        ]

    def typesetHAlignment(self, node: align.HAlignment, collection, yspacing, glue_state=None):
        self._require_builder("typesetHAlignment", "newRow")
        def noalign(table, vlist, columns):
            """
            returns the total glue/spaces
            """
            for n in vlist:
                if n.node_type == nd.NODE_TYPE.WHATSIT:
                    n.output(self.parser, self)

        columns = node.columns() + len(node.tabskips)
        table: Table = self.builder
        row_specs = iter(self._alignment_row_specs(collection, yspacing, glue_state))
        if node.noalign:
            noalign(table, node.noalign, columns)
        for row in node.rows:
            cells = iter(row.cells)
            row_box, spacing_before = next(row_specs, (None, Dimen()))
            widths = self._alignment_widths(row_box)
            tr = table.newRow(row_box=row_box, spacing_before=spacing_before)
            with Builder(self, tr):
                for width, relative_width, cell in widths:
                    if cell is None:
                        self.builder.newCell(width=width, relative_width=relative_width)
                        continue
                    cell_alignment = self._hbox_alignment_glue_state(cell, allow_unset=True)
                    td = self.builder.newCell(
                        next(cells).span,
                        width=width,
                        justify=self._hbox_justification(cell, allow_unset=True),
                    )
                    para = td.newParagraph()
                    with ParagraphBuilder(self, para):
                        line_spec = LineSpec(cell, spacing_before=Dimen(), color=self.color, default_font=self.parser.parameters["currentfont"])
                        line = para.newLine(line_spec)
                        with LineBuilder(self, line):
                            self.typesetLine(cell, alignment_state=cell_alignment)
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

    def _line_text_box(self, nodes):
        text_nodes = []

        def collect(items, in_math=False):
            for node in items:
                node_type = getattr(node, "node_type", None)
                if node_type == nd.NODE_TYPE.MATH:
                    in_math = node.on
                    continue
                if in_math:
                    continue
                if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                    text_nodes.append(node)
                elif node_type == nd.NODE_TYPE.HLIST:
                    collect(getattr(node, "list", ()), in_math=False)

        paragraph = getattr(self, "paragraph", None)
        collect(nodes, in_math=getattr(paragraph, "inline_math_segment", 0) > 0)
        if not text_nodes:
            return None
        text_box = bx.HBox(self.parser, None, None)
        text_box.list = text_nodes
        return text_box.typeset(self.parser)

    def currentLineBaselineShift(self):
        if not self._line_baseline_shift_stack:
            return Dimen()
        return Dimen(self._line_baseline_shift_stack[-1])

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
        # remove the leading/trailing alignment glues while preserving fixed
        # template spacing that TeX has already measured.
        return (
            [node for node in nodes[:first] if not is_alignment_glue(node)] 
            + nodes[first:last + 1]
            + [node for node in nodes[last + 1:] if not is_alignment_glue(node)]
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
                line_spec = LineSpec(n, spacing_before=spacing, color=self.color, default_font=self.parser.parameters["currentfont"])
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
        line_baseline_shift=None,
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
        if line_baseline_shift is None:
            line_baseline_shift = self.currentLineBaselineShift() if inline else Dimen()
        line_baseline_shift = Dimen(line_baseline_shift)
        self._line_baseline_shift_stack.append(line_baseline_shift)
        set_current_shift = getattr(self.builder, "setCurrentBaselineShift", None)
        saved_current_shift = None
        if set_current_shift is not None:
            saved_current_shift = set_current_shift(line_baseline_shift)
        inline_math_nodes = []
        emitted_advance = Dimen()
        pending_effective_kern = Dimen()
        pending_breakable = False

        def finish(result):
            if set_current_shift is not None:
                set_current_shift(saved_current_shift)
            self._line_baseline_shift_stack.pop()
            return result

        text_box = self._line_text_box(nodes)
        if text_box is not None:
            set_text_baseline = getattr(self.builder, "setTextBaselineFromBottom", None)
            if set_text_baseline is not None:
                set_text_baseline(text_box.depth)

        def flush_pending_effective_kern():
            nonlocal emitted_advance, pending_effective_kern, pending_breakable
            if int(pending_effective_kern) == 0:
                return
            self.builder.setSpace(pending_effective_kern, breakable=pending_breakable)
            emitted_advance += pending_effective_kern
            pending_effective_kern = Dimen()
            pending_breakable = False

        def emit_spacing(width, breakable):
            nonlocal pending_effective_kern, pending_breakable
            if int(pending_effective_kern) == 0:
                pending_breakable = breakable
            else:
                pending_breakable = pending_breakable and breakable
            pending_effective_kern += Dimen(width)
            return pending_effective_kern

        def record_paint(tex_advance, reflow_advance):
            nonlocal emitted_advance, pending_effective_kern
            reflow_advance = Dimen(reflow_advance)
            emitted_advance += reflow_advance
            pending_effective_kern += Dimen(tex_advance) - reflow_advance

        def emit_inline_math(node, math_box, piece):
            flush_pending_effective_kern()
            text_run = self.builder.textRun(new=True)
            with Builder(self, text_run):
                typeset_inline_math(node, math_box, piece)
            self.builder.container._text_run = None
            record_paint(math_box.width, math_box.width)
            return text_run

        for n in nodes:
            node_type = n.node_type
            if self.paragraph.inline_math_segment > 0:
                if node_type == nd.NODE_TYPE.MATH:
                    assert not n.on
                    math_box = pack_inline_math_nodes(self.parser, inline_math_nodes, glue_state)
                    emit_inline_math(self.paragraph.inline_math_node, math_box, self.paragraph.inline_math_segment)
                    emit_spacing(n.kern, breakable=False)
                    inline_math_nodes = []
                    self.paragraph.inline_math_segment = 0
                    self.paragraph.inline_math_node = None
                else:
                    inline_math_nodes.append(n)
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                width = Dimen(integer=self._glue_amount(n, None, glue_state)) if glue_state is not None else n.glue.dimen
                emit_spacing(width, breakable=True)
            elif node_type == nd.NODE_TYPE.KERN:
                emit_spacing(n.kern, breakable=False)
            elif node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                flush_pending_effective_kern()
                self._define_font_once(n.font)
                self.builder.setFont(n.font)
                text_run = self.builder.textRun()
                text_run.setChar(n)
                if int(line_baseline_shift) != 0:
                    set_baseline = getattr(text_run, "setBaselineFromBottom", None)
                    if set_baseline is not None:
                        set_baseline(n.depth + line_baseline_shift, word_baseline=n.depth)
                record_paint(n.width, n.width)
            elif node_type == nd.NODE_TYPE.MATH:
                assert n.on
                emit_spacing(n.kern, breakable=False)
                self.paragraph.inline_math_segment = 1
                self.paragraph.inline_math_node = n.source
            elif node_type == nd.NODE_TYPE.HLIST:
                if not n.list:
                    emit_spacing(n.width, breakable=False)
                    continue
                flush_pending_effective_kern()
                child_shift = line_baseline_shift + self._node_shift(n)
                if int(self._node_shift(n)) != 0:
                    self.builder.textRun(new=True)
                child_advance = self.typesetLine(
                    n,
                    glue_state=self._glue_state(n),
                    inline=True,
                    line_baseline_shift=child_shift,
                )
                if int(self._node_shift(n)) != 0:
                    self.builder.textRun(new=True)
                record_paint(n.width, child_advance.emitted)
            elif node_type == nd.NODE_TYPE.VLIST:
                flush_pending_effective_kern()
                vbox_shift = line_baseline_shift + self._node_shift(n)
                self._line_baseline_shift_stack.append(vbox_shift)
                saved_vbox_shift = None
                if set_current_shift is not None:
                    saved_vbox_shift = set_current_shift(vbox_shift)
                try:
                    with Builder(self, self.builder.textRun(new=True)):
                        self.typesetInlineVBox(n)
                finally:
                    if set_current_shift is not None:
                        set_current_shift(saved_vbox_shift)
                    self._line_baseline_shift_stack.pop()
                self.builder.container._text_run = None
                record_paint(n.width, n.width)
            elif n.node_type == nd.NODE_TYPE.WHATSIT:
                # Specials can change annotation/color state, so they are explicit
                # text-run boundaries in the source line.
                old_advance = self._last_graphic_advance
                old_flush = self._inline_paint_flush
                self._last_graphic_advance = None
                self._inline_paint_flush = flush_pending_effective_kern
                try:
                    n.output(self.parser, self)
                    if self._last_graphic_advance is not None:
                        record_paint(Dimen(), self._last_graphic_advance)
                finally:
                    self._last_graphic_advance = old_advance
                    self._inline_paint_flush = old_flush
                self.builder.textRun(new=True)
        if self.paragraph.inline_math_segment > 0:
            # we finish a line inside an inline math
            math_box = pack_inline_math_nodes(self.parser, inline_math_nodes, glue_state)
            emit_inline_math(self.paragraph.inline_math_node, math_box, self.paragraph.inline_math_segment)
            # we increment the piece by 1 in the new line
            self.paragraph.inline_math_segment += 1
        if inline:
            return finish(LineAdvance(emitted_advance, pending_effective_kern, pending_breakable))
        if self.paginate:
            return finish(LineAdvance(emitted_advance, Dimen(), False))
        flush_pending_effective_kern()
        return finish(LineAdvance(emitted_advance, Dimen(), False))

    def typesetInlineVBox(self, box: bx.Box):
        self._require_builder("typesetInlineVBox", "newInlineVBox")
        block: Block = self.builder.newInlineVBox(box)
        assert box.node_type == nd.NODE_TYPE.VLIST
        with Builder(self, block):
            self.typesetVList(box.list, self._glue_state(box), top_level=False)
        return block
