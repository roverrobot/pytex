"""
OpenType/TrueType font backend support.
"""


from io import BytesIO
import math
import os

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont

from pytex.font_backend import FontBackend, GlyphInfo, registerBackend
from pytex.module import Module


@registerBackend
class OpenTypeBackend(FontBackend):
    kind = "opentype"
    DEFAULT_DESIGN_SIZE = 10.0

    def __init__(self, name: str, font: TTFont):
        self._name = name
        self.font = font
        self.units_per_em = font["head"].unitsPerEm
        self._cmap = font.getBestCmap() or {}
        self._glyph_set = font.getGlyphSet()
        self._glyph_info = {}
        self._fontdimen = None
        self._x_height = None

    @classmethod
    def _type(cls, name: str):
        ext = os.path.splitext(name)[1].lower()
        if ext == ".otf":
            return "fonts/opentype"
        if ext == ".ttf":
            return "fonts/truetype"
        return None

    @classmethod
    def _loadFont(cls, file):
        path = getattr(file, "name", None)
        if isinstance(path, str) and path and os.path.exists(path):
            return TTFont(path, lazy=False, recalcBBoxes=False, recalcTimestamp=False)
        data = file.read()
        return TTFont(BytesIO(data), lazy=False, recalcBBoxes=False, recalcTimestamp=False)

    @classmethod
    def load(cls, parser, name: str):
        type = cls._type(name)
        if type is None:
            return None
        file = parser.resolver.openIn(name, type)
        if file is None:
            raise FileNotFoundError(f"OpenType font {name} not found")
        try:
            return cls(name, cls._loadFont(file))
        finally:
            file.close()

    @property
    def name(self):
        return self._name

    @property
    def dvi_name(self):
        return None

    @property
    def design_size(self):
        # OpenType fonts do not expose a TeX design size, so we follow the
        # conventional 10pt default unless the user specifies `at`/`scaled`.
        return self.DEFAULT_DESIGN_SIZE

    @property
    def checksum(self):
        return int(getattr(self.font["head"], "checkSumAdjustment", 0))

    def _scaled(self, value):
        return value / self.units_per_em

    def _glyphName(self, char: str):
        return self._cmap.get(ord(char))

    def _glyphBounds(self, glyph_name):
        glyph = self._glyph_set[glyph_name]
        pen = BoundsPen(self._glyph_set)
        glyph.draw(pen)
        return pen.bounds

    def _glyphInfoByName(self, char: str, glyph_name: str):
        info = self._glyph_info.get(char)
        if info is not None:
            return info
        advance, _ = self.font["hmtx"].metrics[glyph_name]
        bounds = self._glyphBounds(glyph_name)
        if bounds is None:
            height = 0
            depth = 0
        else:
            _, y_min, _, y_max = bounds
            height = max(0, y_max)
            depth = max(0, -y_min)
        info = GlyphInfo(
            char=char,
            width=self._scaled(advance),
            height=self._scaled(height),
            depth=self._scaled(depth),
            italic=0,
            program=None,
            next_larger=None,
            assembly=None,
        )
        self._glyph_info[char] = info
        return info

    def glyphInfo(self, char: str):
        info = self._glyph_info.get(char)
        if info is not None:
            return info
        glyph_name = self._glyphName(char)
        if glyph_name is None:
            return None
        return self._glyphInfoByName(char, glyph_name)

    def glyphInfos(self):
        for codepoint in sorted(self._cmap.keys()):
            info = self.glyphInfo(chr(codepoint))
            if info is not None:
                yield info

    def fallbackGlyphInfo(self, char: str):
        return GlyphInfo(
            char=char,
            width=0,
            height=0,
            depth=0,
            italic=0,
            program=None,
            next_larger=None,
            assembly=None,
        )

    def _spaceWidth(self):
        space = self.glyphInfo(" ")
        if space is not None and space.width > 0:
            return space.width
        return self._scaled(self.units_per_em // 3)

    def _xHeight(self):
        if self._x_height is not None:
            return self._x_height
        os2 = self.font.get("OS/2")
        x_height = getattr(os2, "sxHeight", 0) if os2 is not None else 0
        if x_height > 0:
            self._x_height = self._scaled(x_height)
            return self._x_height
        x = self.glyphInfo("x")
        if x is not None:
            self._x_height = x.height
            return self._x_height
        self._x_height = self._scaled(getattr(self.font["hhea"], "ascent", 0)) / 2
        return self._x_height

    @property
    def fontdimen(self):
        if self._fontdimen is not None:
            return self._fontdimen
        post = self.font.get("post")
        italic_angle = getattr(post, "italicAngle", 0.0) if post is not None else 0.0
        slant = -math.tan(math.radians(italic_angle))
        space = self._spaceWidth()
        self._fontdimen = [
            slant,
            space,
            space / 2,
            space / 3,
            self._xHeight(),
            1.0,
            space / 3,
        ]
        return self._fontdimen
