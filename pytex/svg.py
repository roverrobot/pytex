"""
A SVG shipout backend
"""
from pytex.typeset.shipout import Shipout
from pytex.dimen import NEG_MAX_DIMEN, Dimen
from pytex.node import NODE_TYPE
from io import StringIO
import drawsvg as draw
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen


def _float(x):
    if not isinstance(x, Dimen):
        x = Dimen(integer=x)
    return float(x) * 72 / 72.27


class GlyphCache(dict):
    def __init__(self, font):
        self.font = font.backend.font
        self.glyph_set = self.font.getGlyphSet()
        get_best_cmap = getattr(self.font, "getBestCmap", None)
        if get_best_cmap is None:
            self.cmap = self.font.font["Encoding"]
            self.scale = _float(font.at) / 1000
        else:
            self.cmap = get_best_cmap() or {}
            self.scale = _float(font.at) / self.font['head'].unitsPerEm

    def __getitem__(self, char):
        name = getattr(char, "glyph_name", None)
        glyph_id = getattr(char, "glyph_id", None)
        if name is None and glyph_id is not None:
            name = self.font.getGlyphName(glyph_id)
        char_info = getattr(char, "char_info", None)
        if name is None:
            name = getattr(char_info, "glyph_name", None)
        if name is None:
            try:
                name = self.cmap[ord(char.char)]
            except Exception:
                name = char.char
        return self.glyph_set[name]


def _font_key(font):
    return (
        getattr(font, "name", None)
        or getattr(getattr(font, "backend", None), "name", None)
        or str(id(font))
    )


class SVGShipoutBackend(Shipout):
    def __init__(self, parser, output=None):
        super().__init__(parser, output)
        self.canvas = None
        self.cache = {}
        self.font = None
        self.x = 0
        self.y = 0
        self.page=1

    def begin_page(self, box):
        self.canvas = draw.Drawing(_float(box.width), _float(box.height + box.depth))

    def end_page(self, box):
        if self.output is not None:
            self.canvas.save_svg(f"{self.output}-{self.page}.svg")
        self.page += 1

    def define_font(self, font):
        name = _font_key(font)
        if name not in self.cache:
            self.cache[name] = GlyphCache(font)

    def select_font(self, font):
        self.font = self.cache[_font_key(font)]

    def move_to(self, h, v):
        self.x = _float(h)
        self.y = _float(v)

    def set_char(self, node):
        self.select_font(node.font)
        glyph = self.font[node]
        transform = (self.font.scale, 0, 0, -self.font.scale, self.x, self.y)
        svg_pen = SVGPathPen(self.font.glyph_set)
        t_pen = TransformPen(svg_pen, transform)
        glyph.draw(t_pen)
        self.canvas.append(draw.Path(d=svg_pen.getCommands(), fill='black'))
        self.x += glyph.width * self.font.scale

    def set_glyph(self, node):
        self.set_char(node)

    def set_rule(self, node, box, move):
        width = _float(box.width) if node.width == NEG_MAX_DIMEN else _float(node.width)
        height = _float(box.height) if node.height == NEG_MAX_DIMEN else _float(node.height)
        depth = _float(box.depth) if node.depth == NEG_MAX_DIMEN else _float(node.depth)
        if box.node_type == NODE_TYPE.HLIST:
            self.canvas.append(draw.Rectangle(self.x, self.y-height, width, height+depth, fill='black'))
            if move:
                self.x += width
            return
        self.canvas.append(draw.Rectangle(self.x, self.y, width, height+depth, fill='black'))
        if move:
            self.y += height + depth

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

    def graphic(self, spec):
        pass
