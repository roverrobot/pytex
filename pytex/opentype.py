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

from pytex.font_backend import (
    FontBackend,
    FontSpec,
    GlyphAssembly,
    GlyphAssemblyPart,
    GlyphInfo,
    registerBackend,
    registerFontConverter,
)
from pytex.module import Module
from pytex.tfm import TFMBackend


@registerBackend
class OpenTypeBackend(FontBackend):
    kind = "opentype"
    DEFAULT_DESIGN_SIZE = 10.0
    _system_font_paths = None
    _system_font_match_cache = {}

    def __init__(
        self,
        name: str,
        font: TTFont,
        path: Optional[str] = None,
        font_number: int = 0,
        font_data: Optional[bytes] = None,
    ):
        self._name = name
        self.font = font
        self.path = path
        self.font_number = font_number
        self._font_data = font_data
        self.units_per_em = font["head"].unitsPerEm
        self._cmap = font.getBestCmap() or {}
        self._reverse_cmap = {}
        for codepoint, glyph_name in self._cmap.items():
            current = self._reverse_cmap.get(glyph_name)
            if current is None or codepoint < current:
                self._reverse_cmap[glyph_name] = codepoint
        self._glyph_set = font.getGlyphSet()
        self._glyph_info = {}
        self._synthetic_chars = {}
        self._synthetic_glyphs = {}
        self._next_synthetic_codepoint = 0xF0000
        self._variant_info = None
        self._fontdimen = None
        self._x_height = None

    @staticmethod
    def _backendClass(font):
        if "glyf" in font:
            return TrueTypeBackend
        if "CFF " in font:
            return CFFBackend
        return OpenTypeBackend

    @classmethod
    def _newBackend(cls, name, font, path=None, font_number=0, font_data=None):
        backend_cls = cls._backendClass(font)
        return backend_cls(
            name,
            font,
            path=path,
            font_number=font_number,
            font_data=font_data,
        )

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
        return cls._newBackend(
            backend_name,
            cls._loadPath(path, font_number=font_number),
            path=path,
            font_number=font_number,
        )

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
                return cls._newBackend(
                    backend_name,
                    cls._loadFont(file, font_number=font_number),
                    path=path,
                    font_number=font_number,
                )
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

    def fontData(self):
        if self._font_data is not None:
            return self._font_data
        if (
            isinstance(self.path, str)
            and os.path.isfile(self.path)
            and self.font_number == 0
            and os.path.splitext(self.path)[1].lower() not in {".ttc", ".otc"}
        ):
            with open(self.path, "rb") as font_file:
                return font_file.read()
        out = BytesIO()
        self.font.save(out)
        return out.getvalue()

    def _scaled(self, value):
        return value / self.units_per_em

    def _glyphName(self, char: str):
        glyph_name = self._synthetic_glyphs.get(char)
        if glyph_name is not None:
            return glyph_name
        return self._cmap.get(ord(char))

    def _charForGlyphName(self, glyph_name: str):
        codepoint = self._reverse_cmap.get(glyph_name)
        if codepoint is not None:
            return chr(codepoint)
        char = self._synthetic_chars.get(glyph_name)
        if char is not None:
            return char
        if self._next_synthetic_codepoint > 0x10FFFD:
            raise ValueError("out of synthetic code points for OpenType math variants")
        char = chr(self._next_synthetic_codepoint)
        self._next_synthetic_codepoint += 1
        self._synthetic_chars[glyph_name] = char
        self._synthetic_glyphs[char] = glyph_name
        return char

    def _variantAssembly(self, construction, *, vertical=True):
        assembly = getattr(construction, "GlyphAssembly", None)
        if assembly is None:
            return None
        parts = []
        top = 0
        middle = 0
        bottom = 0
        repeat = 0
        non_ext = []
        records = list(getattr(assembly, "PartRecords", ()) or ())
        for index, part in enumerate(records):
            glyph_char = self._charForGlyphName(part.glyph)
            codepoint = ord(glyph_char)
            extender = bool(getattr(part, "PartFlags", 0))
            parts.append(
                GlyphAssemblyPart(
                    glyph=glyph_char,
                    start_connector=self._scaled(getattr(part, "StartConnectorLength", 0)),
                    end_connector=self._scaled(getattr(part, "EndConnectorLength", 0)),
                    full_advance=self._scaled(getattr(part, "FullAdvance", 0)),
                    extender=extender,
                )
            )
            if extender:
                repeat = codepoint
                continue
            non_ext.append(codepoint)
        if vertical:
            parts = list(reversed(parts))
            if len(non_ext) >= 1:
                bottom = non_ext[0]
                top = non_ext[-1]
            if len(non_ext) >= 3:
                middle = non_ext[1]
        else:
            if len(non_ext) >= 1:
                top = non_ext[0]
                bottom = non_ext[-1]
            if len(non_ext) >= 3:
                middle = non_ext[1]
        return GlyphAssembly(
            parts=parts,
            top=top,
            middle=middle,
            bottom=bottom,
            repeat=repeat,
            vertical=True,
            italic=0,
            min_connector_overlap=self._scaled(getattr(self.font["MATH"].table.MathVariants, "MinConnectorOverlap", 0)),
        )

    def _buildVariantInfo(self):
        info = {}
        table = self.font.get("MATH")
        if table is None:
            return info
        variants = getattr(table.table, "MathVariants", None)
        if variants is None:
            return info
        for coverage_name, construction_name, vertical in (
            ("VertGlyphCoverage", "VertGlyphConstruction", True),
            ("HorizGlyphCoverage", "HorizGlyphConstruction", False),
        ):
            coverage = getattr(variants, coverage_name, None)
            constructions = getattr(variants, construction_name, None)
            if coverage is None or constructions is None:
                continue
            glyphs = list(getattr(coverage, "glyphs", ()) or ())
            for index, _base_glyph in enumerate(glyphs):
                construction = constructions[index]
                records = list(getattr(construction, "MathGlyphVariantRecord", ()) or ())
                assembly = self._variantAssembly(construction, vertical=vertical)
                for rec_index, record in enumerate(records):
                    glyph_name = record.VariantGlyph
                    entry = info.setdefault(glyph_name, {"next_larger": None, "assembly": None})
                    if rec_index + 1 < len(records):
                        entry["next_larger"] = self._charForGlyphName(records[rec_index + 1].VariantGlyph)
                    if assembly is not None and entry["assembly"] is None:
                        entry["assembly"] = GlyphAssembly(
                            parts=assembly.parts,
                            top=assembly.top,
                            middle=assembly.middle,
                            bottom=assembly.bottom,
                            repeat=assembly.repeat,
                            vertical=vertical,
                            italic=assembly.italic,
                            min_connector_overlap=assembly.min_connector_overlap,
                        )
        return info

    def _variantInfo(self, glyph_name: str):
        if self._variant_info is None:
            self._variant_info = self._buildVariantInfo()
        return self._variant_info.get(glyph_name)

    def glyphId(self, char: str):
        glyph_name = self._glyphName(char)
        if glyph_name is None:
            return 0
        return self.font.getGlyphID(glyph_name)

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
        variant = self._variantInfo(glyph_name) or {}
        info = GlyphInfo(
            char=char,
            width=self._scaled(advance),
            height=self._scaled(height),
            depth=self._scaled(depth),
            italic=0,
            glyph_name=glyph_name,
            glyph_id=self.font.getGlyphID(glyph_name),
            program=None,
            next_larger=variant.get("next_larger"),
            assembly=variant.get("assembly"),
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
            glyph_name=self._glyphName(char),
            glyph_id=self.font.getGlyphID(self._glyphName(char)) if self._glyphName(char) is not None else None,
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

    @staticmethod
    def _mathRecordValue(value):
        if value is None:
            return None
        return getattr(value, "Value", value)

    def hasMathTable(self):
        return self.font.get("MATH") is not None

    def mathConstants(self):
        table = self.font.get("MATH")
        if table is None:
            return None
        return getattr(getattr(table, "table", None), "MathConstants", None)

    def mathConstant(self, name: str, default: float = 0.0, *, scale: bool = True):
        constants = self.mathConstants()
        if constants is None:
            return default
        value = self._mathRecordValue(getattr(constants, name, None))
        if value is None:
            return default
        value = float(value)
        return self._scaled(value) if scale else value

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


class TrueTypeBackend(OpenTypeBackend):
    """OpenType font with quadratic TrueType outlines."""


class CFFBackend(OpenTypeBackend):
    """OpenType font with CFF 1 outlines."""


class Type1TrueTypeBackend(TrueTypeBackend):
    """TrueType outlines paired with the metrics of a TeX Type 1 font."""

    def __init__(self, name, font, source_backend, font_data):
        super().__init__(name, font, font_data=font_data)
        self.source_backend = source_backend
        self._type1_glyph_info = {}

    @property
    def dvi_name(self):
        return self.source_backend.dvi_name

    @property
    def design_size(self):
        return self.source_backend.design_size

    @property
    def checksum(self):
        return self.source_backend.checksum

    @property
    def fontdimen(self):
        return self.source_backend.fontdimen

    def glyphInfo(self, char: str):
        cached = self._type1_glyph_info.get(char)
        if cached is not None:
            return cached
        metric = self.source_backend.glyphInfo(char)
        if metric is None:
            return None
        outline = super().glyphInfo(char)
        if outline is None:
            return None
        info = GlyphInfo(
            char=metric.char,
            width=metric.width,
            height=metric.height,
            depth=metric.depth,
            italic=metric.italic,
            glyph_name=outline.glyph_name,
            glyph_id=outline.glyph_id,
            program=metric.program,
            next_larger=metric.next_larger,
            assembly=metric.assembly,
        )
        self._type1_glyph_info[char] = info
        return info

    def glyphInfos(self):
        for metric in self.source_backend.glyphInfos():
            info = self.glyphInfo(metric.char)
            if info is not None:
                yield info

    def fallbackGlyphInfo(self, char: str):
        metric = self.source_backend.fallbackGlyphInfo(char)
        outline = super().fallbackGlyphInfo(char)
        if metric is None:
            return outline
        return GlyphInfo(
            char=metric.char,
            width=metric.width,
            height=metric.height,
            depth=metric.depth,
            italic=metric.italic,
            glyph_name=outline.glyph_name,
            glyph_id=outline.glyph_id,
            program=metric.program,
            next_larger=metric.next_larger,
            assembly=metric.assembly,
        )

    def leftBoundaryProgram(self):
        return self.source_backend.leftBoundaryProgram()

    def rightBoundaryChar(self):
        return self.source_backend.rightBoundaryChar()

    def _spaceWidth(self):
        info = self.source_backend.glyphInfo(" ")
        if info is not None and info.width > 0:
            return info.width
        return super()._spaceWidth()


@registerFontConverter(CFFBackend, TrueTypeBackend)
def convertCFFToTrueType(parser, backend):
    from afdko.otf2ttf import otf_to_ttf

    if isinstance(backend.path, str) and os.path.isfile(backend.path):
        font = TTFont(
            backend.path,
            fontNumber=backend.font_number,
            lazy=False,
            recalcTimestamp=False,
        )
    else:
        font = TTFont(
            BytesIO(backend.fontData()),
            lazy=False,
            recalcTimestamp=False,
        )
    try:
        otf_to_ttf(font)
        converted = BytesIO()
        font.save(converted)
        data = converted.getvalue()
    finally:
        font.close()
    converted_font = TTFont(
        BytesIO(data),
        lazy=False,
        recalcBBoxes=False,
        recalcTimestamp=False,
    )
    return TrueTypeBackend(
        backend.name,
        converted_font,
        font_data=data,
    )


def _type1UnitsPerEm(font):
    matrix = font.get("FontMatrix") or ()
    if len(matrix) >= 4:
        x_scale = abs(float(matrix[0]))
        y_scale = abs(float(matrix[3]))
        if x_scale > 0 and math.isclose(x_scale, y_scale):
            units_per_em = round(1 / x_scale)
            if 16 <= units_per_em <= 16384:
                return units_per_em
    return 1000


def _type1PostScriptName(value):
    value = re.sub(r"[^A-Za-z0-9-]", "", str(value or "Type1Font"))
    return value or "Type1Font"


def _type1Style(font_info):
    weight = str(font_info.get("Weight") or "Regular")
    italic_angle = float(font_info.get("ItalicAngle", 0))
    style_key = weight.casefold()
    bold = any(value in style_key for value in ("bold", "demi", "semibold"))
    italic = italic_angle != 0 or any(value in style_key for value in ("italic", "oblique"))
    if bold and italic:
        style = "Bold Italic"
    elif bold:
        style = "Bold"
    elif italic:
        style = "Italic"
    else:
        style = "Regular"
    return style, weight, italic_angle, bold, italic


def _type1OpenTypeData(backend):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    type1_font = backend.font
    if type1_font is None:
        return None
    glyph_set = type1_font.getGlyphSet()
    source = type1_font.font
    font_info = source.get("FontInfo", {})
    glyph_order = list(source.get("CharStrings", glyph_set).keys())
    if ".notdef" in glyph_order:
        glyph_order.remove(".notdef")
    glyph_order.insert(0, ".notdef")

    metrics = {}
    char_strings = {}
    for glyph_name in glyph_order:
        glyph = glyph_set[glyph_name]
        bounds_pen = BoundsPen(glyph_set)
        glyph.draw(bounds_pen)
        width = round(getattr(glyph, "width", 0))
        left_side_bearing = 0 if bounds_pen.bounds is None else round(bounds_pen.bounds[0])
        metrics[glyph_name] = (width, left_side_bearing)
        char_string_pen = T2CharStringPen(width, glyph_set)
        glyph.draw(char_string_pen)
        char_strings[glyph_name] = char_string_pen.getCharString()

    encoding = source.get("Encoding", ())
    cmap = {
        codepoint: glyph_name
        for codepoint, glyph_name in enumerate(encoding)
        if glyph_name != ".notdef" and glyph_name in glyph_set
    }
    postscript_name = _type1PostScriptName(source.get("FontName"))
    family = font_info.get("FamilyName") or postscript_name
    full_name = font_info.get("FullName") or postscript_name
    style, weight, italic_angle, bold, italic = _type1Style(font_info)
    fs_selection = (1 << 5 if bold else 0) | (1 << 0 if italic else 0)
    if not bold and not italic:
        fs_selection |= 1 << 6

    bbox = source.get("FontBBox", (0, -200, 1000, 800))
    ascent = round(bbox[3])
    descent = round(bbox[1])
    builder = FontBuilder(_type1UnitsPerEm(source), isTTF=False)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(cmap)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=ascent, descent=descent)
    builder.setupNameTable(
        {
            "familyName": family,
            "styleName": style,
            "uniqueFontIdentifier": full_name,
            "fullName": full_name,
            "psName": postscript_name,
        }
    )
    builder.setupOS2(
        sTypoAscender=ascent,
        sTypoDescender=descent,
        usWinAscent=max(0, ascent),
        usWinDescent=max(0, -descent),
        usWeightClass=700 if bold else 400,
        fsSelection=fs_selection,
        fsType=0,
    )
    builder.setupPost(italicAngle=italic_angle)
    builder.font["head"].macStyle = (1 if bold else 0) | (2 if italic else 0)
    builder.setupCFF(
        postscript_name,
        {
            "FullName": full_name,
            "FamilyName": family,
            "Weight": weight,
            "ItalicAngle": italic_angle,
        },
        char_strings,
        {},
    )
    data = BytesIO()
    builder.font.save(data)
    return data.getvalue()


def _correctConvertedType1Metadata(font, backend):
    font_info = backend.font.font.get("FontInfo", {})
    style, _weight, _italic_angle, _bold, _italic = _type1Style(font_info)
    os2 = font.get("OS/2")
    if os2 is not None:
        os2.fsType = 0
    name_table = font.get("name")
    if name_table is None:
        return
    for record in list(name_table.names):
        if record.nameID in (2, 17):
            name_table.setName(
                style,
                record.nameID,
                record.platformID,
                record.platEncID,
                record.langID,
            )
    name_table.setName(style, 2, 3, 1, 0x0409)
    name_table.setName(style, 17, 3, 1, 0x0409)


@registerFontConverter(TFMBackend, TrueTypeBackend)
def convertType1ToTrueType(parser, backend):
    if backend.pfb_file is None:
        return None
    cff_data = _type1OpenTypeData(backend)
    if cff_data is None:
        return None
    cff_font = TTFont(
        BytesIO(cff_data),
        lazy=False,
        recalcBBoxes=False,
        recalcTimestamp=False,
    )
    cff_backend = CFFBackend(backend.name, cff_font, font_data=cff_data)
    try:
        converted = convertCFFToTrueType(parser, cff_backend)
    finally:
        cff_font.close()
    _correctConvertedType1Metadata(converted.font, backend)
    data = BytesIO()
    converted.font.save(data)
    return Type1TrueTypeBackend(
        backend.name,
        converted.font,
        source_backend=backend,
        font_data=data.getvalue(),
    )
