"""
OpenType/TrueType font backend support.
"""


from io import BytesIO
import math
import os
import platform
import re
from typing import Optional

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTCollection, TTFont, TTLibError, TTLibFileIsCollectionError

from pytex.font_backend import FontBackend, FontSpec, GlyphInfo, registerBackend
from pytex.module import Module


@registerBackend
class OpenTypeBackend(FontBackend):
    kind = "opentype"
    DEFAULT_DESIGN_SIZE = 10.0
    _system_font_paths = None
    _system_font_match_cache = {}

    def __init__(self, name: str, font: TTFont, path: Optional[str] = None, font_number: int = 0):
        self._name = name
        self.font = font
        self.path = path
        self.font_number = font_number
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
        if ext == ".otc":
            return "fonts/opentype"
        if ext == ".ttf":
            return "fonts/truetype"
        if ext == ".ttc":
            return "fonts/truetype"
        return None

    @classmethod
    def _fileTypes(cls, name: str, extensionless: bool = False):
        type = cls._type(name)
        if type is not None:
            return [type]
        if extensionless and not os.path.splitext(name)[1]:
            return ["fonts/opentype", "fonts/truetype"]
        return []

    @staticmethod
    def _normalizeSystemName(name: str):
        return re.sub(r"\s+", " ", name.strip()).casefold()

    @staticmethod
    def _systemFontDirs():
        sys = platform.system()
        home = os.path.expanduser("~")
        if sys == "Darwin":
            return [
                "/System/Library/Fonts",
                "/System/Library/AssetsV2",
                "/Library/Fonts",
                os.path.join(home, "Library", "Fonts"),
            ]
        if sys == "Windows":
            windir = os.environ.get("WINDIR", r"C:\Windows")
            return [os.path.join(windir, "Fonts")]
        return [
            "/usr/share/fonts",
            "/usr/local/share/fonts",
            os.path.join(home, ".local", "share", "fonts"),
            os.path.join(home, ".fonts"),
        ]

    @classmethod
    def _regularScore(cls, names):
        regular = {"regular", "roman", "book", "normal", "plain"}
        return 0 if any(name in regular for name in names) else 1

    @classmethod
    def _fontNameCandidates(cls, path: str):
        def collect(font, font_number):
            table = font.get("name")
            if table is None:
                return []
            families = set()
            full = set()
            postscript = set()
            styles = set()
            for record in table.names:
                try:
                    text = record.toUnicode().strip()
                except Exception:
                    continue
                if not text:
                    continue
                norm = cls._normalizeSystemName(text)
                if record.nameID in (1, 16):
                    families.add(norm)
                elif record.nameID == 4:
                    full.add(norm)
                elif record.nameID == 6:
                    postscript.add(norm)
                elif record.nameID in (2, 17):
                    styles.add(norm)
            candidates = []
            regular_score = cls._regularScore(styles)
            for value in postscript:
                candidates.append((value, 0, regular_score, path, font_number))
            for value in full:
                candidates.append((value, 1, regular_score, path, font_number))
            for value in families:
                candidates.append((value, 2, regular_score, path, font_number))
            return candidates

        try:
            font = TTFont(path, lazy=True, recalcBBoxes=False, recalcTimestamp=False)
        except TTLibFileIsCollectionError:
            try:
                collection = TTCollection(path, lazy=True)
            except (OSError, TTLibError):
                return []
            try:
                candidates = []
                for font_number, subfont in enumerate(collection.fonts):
                    candidates.extend(collect(subfont, font_number))
                return candidates
            finally:
                collection.close()
        except (OSError, TTLibError):
            return []
        try:
            return collect(font, 0)
        finally:
            font.close()

    @classmethod
    def _systemFontPath(cls, name: str):
        key = cls._normalizeSystemName(name)
        cached = cls._system_font_match_cache.get(key)
        if cached is not None:
            return cached
        if cls._system_font_paths is None:
            index = {}
            for root in cls._systemFontDirs():
                if not os.path.isdir(root):
                    continue
                for base, _dirs, files in os.walk(root):
                    for filename in files:
                        ext = os.path.splitext(filename)[1].lower()
                        if ext not in {".otf", ".ttf", ".otc", ".ttc"}:
                            continue
                        path = os.path.join(base, filename)
                        for candidate, priority, regular_score, path, font_number in cls._fontNameCandidates(path):
                            current = index.get(candidate)
                            value = (priority, regular_score, path, font_number)
                            if current is None or value < current:
                                index[candidate] = value
            cls._system_font_paths = {
                name: (path, font_number)
                for name, (_priority, _regular, path, font_number) in index.items()
            }
        match = cls._system_font_paths.get(key)
        cls._system_font_match_cache[key] = match
        return match

    @classmethod
    def _loadPath(cls, path: str, font_number: int = 0):
        return TTFont(path, fontNumber=font_number, lazy=False, recalcBBoxes=False, recalcTimestamp=False)

    @classmethod
    def _loadFont(cls, file, font_number: int = 0):
        path = getattr(file, "name", None)
        if isinstance(path, str) and path and os.path.exists(path):
            try:
                return cls._loadPath(path, font_number=font_number)
            except TTLibFileIsCollectionError:
                return cls._loadPath(path, font_number=font_number)
        data = file.read()
        return TTFont(BytesIO(data), fontNumber=font_number, lazy=False, recalcBBoxes=False, recalcTimestamp=False)

    @classmethod
    def _loadSystemFont(cls, name: str, backend_name: str):
        match = cls._systemFontPath(name)
        if match is None:
            return None
        if isinstance(match, str):
            path, font_number = match, 0
        else:
            path, font_number = match
        return cls(backend_name, cls._loadPath(path, font_number=font_number), path=path, font_number=font_number)

    @classmethod
    def _loadFileFont(cls, parser, name: str, backend_name: str, font_number: int = 0, extensionless: bool = False):
        types = cls._fileTypes(name, extensionless=extensionless)
        if not types:
            return None
        for type in types:
            file = parser.resolver.openIn(name, type)
            if file is None:
                continue
            path = getattr(file, "name", None)
            if not isinstance(path, str) or not os.path.exists(path):
                path = None
            try:
                return cls(backend_name, cls._loadFont(file, font_number=font_number), path=path, font_number=font_number)
            finally:
                file.close()
        return None

    @classmethod
    def load(cls, parser, name: str):
        if isinstance(name, FontSpec):
            backend_name = name.backend_name
            if name.lookup != "system":
                backend = cls._loadFileFont(
                    parser,
                    name.name,
                    backend_name,
                    font_number=name.font_number,
                    extensionless=name.lookup == "file",
                )
                if backend is not None or name.lookup == "file":
                    return backend
            return cls._loadSystemFont(name.name, backend_name)

        type = cls._type(name)
        if type is None:
            return cls._loadSystemFont(name, name)
        backend = cls._loadFileFont(parser, name, name)
        if backend is None:
            raise FileNotFoundError(f"OpenType font {name} not found")
        return backend

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
