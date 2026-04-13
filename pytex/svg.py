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
    return float(x) * 72 / 72.27


class GlyphCache(dict):
    def __init__(self, font):
        self.font = font.backend.font
        self.glyph_set = self.font.getGlyphSet()
        self.cmap = getattr(self.font, "getBestCmap", None)
        if self.cmap is None:
            self.cmap = self.font.font["Encoding"]
            self.scale = _float(font.at) / 1000
        else:
            self.scale = _float(font.at) / self.font['head'].unitsPerEm
        self.svg_pen = SVGPathPen(self.glyph_set)

    def __getitem__(self, char):
        try:
            name = self.cmap[ord(char.char)]
        except:
            name = char.char_info.glyph_name
        return self.glyph_set[name]
        

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
        name = font.name
        if name not in self.cache:
            self.cache[name] = GlyphCache(font)

    def select_font(self, font):
        self.font = self.cache[font.name]

    def move_to(self, h, v):
        self.x =_float(Dimen(integer=h))
        self.y = _float(Dimen(integer=v))

    def set_char(self, node):
        self.select_font(node.font)
        glyph = self.font[node]
        # 2. Define the Matrix: (scale, 0, 0, -scale, x_offset, y_offset)
        # We use -scale for Y to flip the glyph upright.
        # y_offset is 15 because that is where the baseline sits.
        transform = (self.font.scale, 0, 0, -self.font.scale, self.x, self.y)
        # 3. Draw the glyph through the transform
        t_pen = TransformPen(self.font.svg_pen, transform)
        glyph.draw(t_pen)        
        # 4. Append to canvas
        self.canvas.append(draw.Path(d=self.font.svg_pen.getCommands(), fill='black'))
        # 5. Move current_x forward by the glyph's width
        self.x += glyph.width * self.font.scale

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

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def open(self):
        pass

    def close(self):
        pass
