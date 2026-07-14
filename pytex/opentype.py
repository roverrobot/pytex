"""
OpenType/TrueType font backend support.
"""


from io import BytesIO
import math
import os
import platform
import re
import unicodedata
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
from pytex.tfm import KernOp, TFMBackend


@registerBackend
class OpenTypeBackend(FontBackend):
    kind = "opentype"
    uses_font_program_kerning = True
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
        self._kerning_programs = None
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

    @staticmethod
    def _pairAdjustment(record):
        adjustment = 0
        for value in (getattr(record, "Value1", None), getattr(record, "Value2", None)):
            adjustment += getattr(value, "XAdvance", 0) or 0
        return adjustment

    def _buildKerningPrograms(self):
        """Translate active GPOS ``kern`` pairs into TeX kern programs."""
        table = self.font.get("GPOS")
        if table is None or table.table.FeatureList is None or table.table.LookupList is None:
            return {}
        lookup_indices = {
            index
            for record in table.table.FeatureList.FeatureRecord
            if record.FeatureTag == "kern"
            for index in record.Feature.LookupListIndex
        }
        pairs = {}

        def add_pair(left, right, adjustment):
            left_char = self._reverse_cmap.get(left)
            right_char = self._reverse_cmap.get(right)
            if left_char is None or right_char is None or not adjustment:
                return
            pairs.setdefault(left, {})[right_char] = KernOp(
                chr(right_char), self._scaled(adjustment)
            )

        def add_subtable(subtable):
            if getattr(subtable, "Format", None) == 1:
                coverage = getattr(getattr(subtable, "Coverage", None), "glyphs", ())
                for left, pair_set in zip(coverage, getattr(subtable, "PairSet", ())):
                    for record in pair_set.PairValueRecord:
                        add_pair(left, record.SecondGlyph, self._pairAdjustment(record))
                return
            if getattr(subtable, "Format", None) != 2:
                return
            coverage = getattr(getattr(subtable, "Coverage", None), "glyphs", ())
            right_by_class = {}
            class2 = getattr(getattr(subtable, "ClassDef2", None), "classDefs", {})
            for right in self._reverse_cmap:
                right_by_class.setdefault(class2.get(right, 0), []).append(right)
            class1 = getattr(getattr(subtable, "ClassDef1", None), "classDefs", {})
            records = getattr(subtable, "Class1Record", ())
            for left in coverage:
                left_class = class1.get(left, 0)
                if left_class >= len(records):
                    continue
                for right_class, record in enumerate(records[left_class].Class2Record):
                    adjustment = self._pairAdjustment(record)
                    if not adjustment:
                        continue
                    for right in right_by_class.get(right_class, ()):
                        add_pair(left, right, adjustment)

        lookups = table.table.LookupList.Lookup
        for index in lookup_indices:
            lookup = lookups[index]
            for subtable in lookup.SubTable:
                if lookup.LookupType == 2:
                    add_subtable(subtable)
                elif lookup.LookupType == 9 and getattr(subtable, "ExtensionLookupType", None) == 2:
                    add_subtable(subtable.ExtSubTable)
        return pairs

    def _kerningProgram(self, glyph_name):
        if self._kerning_programs is None:
            self._kerning_programs = self._buildKerningPrograms()
        return self._kerning_programs.get(glyph_name)

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
            program=self._kerningProgram(glyph_name),
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

    def shape(self, font, source, **kwargs):
        # Transitional path: retain the GPOS-derived TeX kern programs until
        # HarfBuzz replaces this method with full OpenType shaping.
        return self._shapeLigKern(font, source, **kwargs)

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
    """Converted TrueType metrics paired with TeX ligature/kern programs."""

    uses_font_program_kerning = True

    def __init__(self, name, font, source_backend, font_data):
        super().__init__(name, font, font_data=font_data)
        self.source_backend = source_backend
        source = source_backend.font.font if source_backend.font is not None else {}
        self._type1_encoding = tuple(source.get("Encoding", ()))
        self._type1_glyph_info = {}

    def _glyphName(self, char: str):
        codepoint = ord(char)
        if 0 <= codepoint < len(self._type1_encoding):
            glyph_name = self._type1_encoding[codepoint]
            if glyph_name != ".notdef" and glyph_name in self._glyph_set:
                return glyph_name
        return super()._glyphName(char)

    def unicodeChar(self, char: str) -> str:
        glyph_name = self._glyphName(char)
        value = _type1GlyphUnicode(glyph_name)
        if value is not None:
            return value
        if unicodedata.category(char) not in {"Cc", "Cs"}:
            return char
        return ""

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
        params = super().fontdimen
        source_params = self.source_backend.fontdimen
        if len(source_params) > len(params):
            params.extend(source_params[len(params):])
        return params

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
            char=outline.char,
            width=outline.width,
            height=outline.height,
            depth=outline.depth,
            italic=outline.italic,
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
            char=outline.char,
            width=outline.width,
            height=outline.height,
            depth=outline.depth,
            italic=outline.italic,
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
        glyph_name = self._cmap.get(ord(" "))
        if glyph_name is not None:
            advance, _ = self.font["hmtx"].metrics[glyph_name]
            if advance > 0:
                return self._scaled(advance)
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


_TYPE1_LIGATURE_UNICODE = {
    "ff": "\ufb00",
    "fi": "\ufb01",
    "fl": "\ufb02",
    "ffi": "\ufb03",
    "ffl": "\ufb04",
}


def _type1GlyphUnicode(glyph_name):
    if not glyph_name or glyph_name == ".notdef":
        return None
    value = _TYPE1_LIGATURE_UNICODE.get(glyph_name)
    if value is None:
        from fontTools import agl

        value = agl.toUnicode(glyph_name)
    if len(value) != 1 or unicodedata.category(value) in {"Cc", "Cs"}:
        return None
    return value


def _type1UnicodeCmap(glyph_order):
    cmap = {}
    for glyph_name in glyph_order:
        value = _type1GlyphUnicode(glyph_name)
        if value is not None:
            cmap.setdefault(ord(value), glyph_name)
    if "space" in glyph_order:
        cmap.setdefault(0x00A0, "space")
    return cmap


def _type1FontMetadata(backend, font_info):
    source_name = font_info.get("FamilyName") or backend.name or "Type1 Font"
    try:
        design_size = float(backend.design_size)
    except (TypeError, ValueError):
        design_size = 0
    size_suffix = f" {design_size:g}" if design_size > 0 else ""
    family = f"PyTeX {source_name}{size_suffix}"[:31].rstrip()
    style, weight, italic_angle, bold, italic = _type1Style(font_info)
    full_name = family if style == "Regular" else f"{family} {style}"
    ps_family = _type1PostScriptName(family.replace(" ", ""))
    ps_style = style.replace(" ", "")
    postscript_name = f"{ps_family}-{ps_style}"[:63]
    return {
        "family": family,
        "style": style,
        "weight": weight,
        "italic_angle": italic_angle,
        "bold": bold,
        "italic": italic,
        "full_name": full_name,
        "postscript_name": postscript_name,
        "unique_id": f"PYTX;1.000;{postscript_name}",
        "version": "Version 1.000",
    }


def _type1GlyphTop(glyph_set, glyph_name, fallback):
    if glyph_name not in glyph_set:
        return fallback
    pen = BoundsPen(glyph_set)
    glyph_set[glyph_name].draw(pen)
    return fallback if pen.bounds is None else round(pen.bounds[3])


def _type1LigatureRules(backend, glyph_order):
    """Return OpenType ligature rules equivalent to simple TFM ligatures."""
    encoding = tuple(backend.font.font.get("Encoding", ()))
    available = set(glyph_order)
    direct = []
    for metric in backend.glyphInfos():
        if metric.program is None:
            continue
        left_code = ord(metric.char)
        if not 0 <= left_code < len(encoding):
            continue
        left = encoding[left_code]
        for right_code, step in metric.program.items():
            # A GSUB ligature replaces all input glyphs with one output glyph.
            # Other TeX ligature opcodes retain an input and cannot be represented
            # by a standard OpenType ligature substitution.
            if (
                step.isKern
                or not step.delete_current
                or step.keep_next
                or not 0 <= right_code < len(encoding)
                or not 0 <= step.insert < len(encoding)
            ):
                continue
            right = encoding[right_code]
            output = encoding[step.insert]
            if left in available and right in available and output in available:
                direct.append(((left, right), output))

    # TFM programs form longer ligatures in stages (f+f=ff, ff+i=ffi).
    # A single GSUB lookup does not revisit its replacement, so also emit the
    # recursively expanded source sequence (f f i -> ffi).
    definitions = {}
    for inputs, output in direct:
        definitions.setdefault(output, []).append(inputs)

    def expand(glyph, active=frozenset()):
        values = {(glyph,)}
        if glyph in active:
            return values
        for inputs in definitions.get(glyph, ()):
            left_values = expand(inputs[0], active | {glyph})
            right_values = expand(inputs[1], active | {glyph})
            values.update(left + right for left in left_values for right in right_values)
        return values

    rules = set(direct)
    for inputs, output in direct:
        for left in expand(inputs[0]):
            for right in expand(inputs[1]):
                rules.add((left + right, output))
    return sorted(rules, key=lambda rule: (-len(rule[0]), rule[0], rule[1]))


def _type1KerningRules(backend, glyph_order, units_per_em):
    """Return GPOS pair adjustments equivalent to the TFM kern program."""
    encoding = tuple(backend.font.font.get("Encoding", ()))
    available = set(glyph_order)
    rules = set()
    for metric in backend.glyphInfos():
        if metric.program is None:
            continue
        left_code = ord(metric.char)
        if not 0 <= left_code < len(encoding):
            continue
        left = encoding[left_code]
        for right_code, step in metric.program.items():
            if (
                not step.isKern
                or not 0 <= right_code < len(encoding)
                or left not in available
            ):
                continue
            right = encoding[right_code]
            adjustment = round(step.kern * units_per_em)
            if right in available and adjustment:
                rules.add((left, right, adjustment))
    return sorted(rules)


def _addType1LayoutFeatures(font, backend, glyph_order, units_per_em):
    from fontTools.feaLib.builder import addOpenTypeFeaturesFromString

    ligature_rules = [
        f"sub {' '.join(inputs)} by {output};"
        for inputs, output in _type1LigatureRules(backend, glyph_order)
    ]
    kerning_rules = [
        f"pos {left} {right} {adjustment};"
        for left, right, adjustment in _type1KerningRules(
            backend, glyph_order, units_per_em
        )
    ]
    # Office associates Latin text with the ``latn`` script and does not
    # reliably fall back to DFLT for GPOS kerning.  Register both so the same
    # TFM layout programs are active in generic shapers and in Word.
    features = ["languagesystem DFLT dflt;\nlanguagesystem latn dflt;\n"]
    if ligature_rules:
        features.append(
            "feature liga {\n  " + "\n  ".join(ligature_rules) + "\n} liga;\n"
        )
    if kerning_rules:
        features.append(
            "feature kern {\n  " + "\n  ".join(kerning_rules) + "\n} kern;\n"
        )
    if ligature_rules or kerning_rules:
        addOpenTypeFeaturesFromString(font, "".join(features))


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

    cmap = _type1UnicodeCmap(glyph_order)
    metadata = _type1FontMetadata(backend, font_info)
    family = metadata["family"]
    style = metadata["style"]
    weight = metadata["weight"]
    italic_angle = metadata["italic_angle"]
    bold = metadata["bold"]
    italic = metadata["italic"]
    full_name = metadata["full_name"]
    postscript_name = metadata["postscript_name"]
    fs_selection = (1 << 5 if bold else 0) | (1 << 0 if italic else 0)
    if not bold and not italic:
        fs_selection |= 1 << 6

    bbox = source.get("FontBBox", (0, -200, 1000, 800))
    units_per_em = _type1UnitsPerEm(source)
    ascent = round(bbox[3])
    descent = round(bbox[1])
    x_height = _type1GlyphTop(glyph_set, "x", round(units_per_em * 0.45))
    cap_height = _type1GlyphTop(glyph_set, "H", round(units_per_em * 0.7))
    builder = FontBuilder(units_per_em, isTTF=False)
    builder.setupGlyphOrder(glyph_order)
    builder.setupCharacterMap(cmap)
    builder.setupHorizontalMetrics(metrics)
    builder.setupHorizontalHeader(ascent=ascent, descent=descent)
    builder.setupNameTable(
        {
            "familyName": family,
            "styleName": style,
            "uniqueFontIdentifier": metadata["unique_id"],
            "fullName": full_name,
            "psName": postscript_name,
            "version": metadata["version"],
        }
    )
    builder.setupOS2(
        version=4,
        sTypoAscender=ascent,
        sTypoDescender=descent,
        usWinAscent=max(0, ascent),
        usWinDescent=max(0, -descent),
        usWeightClass=700 if bold else 400,
        fsSelection=fs_selection,
        fsType=0,
        achVendID="PYTX",
        sxHeight=x_height,
        sCapHeight=cap_height,
        ySubscriptXSize=round(units_per_em * 0.65),
        ySubscriptYSize=round(units_per_em * 0.6),
        ySubscriptXOffset=0,
        ySubscriptYOffset=round(units_per_em * 0.075),
        ySuperscriptXSize=round(units_per_em * 0.65),
        ySuperscriptYSize=round(units_per_em * 0.6),
        ySuperscriptXOffset=0,
        ySuperscriptYOffset=round(units_per_em * 0.35),
        yStrikeoutSize=max(1, round(units_per_em * 0.05)),
        yStrikeoutPosition=round(x_height * 0.6),
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
    _addType1LayoutFeatures(builder.font, backend, glyph_order, units_per_em)
    data = BytesIO()
    builder.font.save(data)
    return data.getvalue()


def _correctConvertedType1Metadata(font, backend):
    font_info = backend.font.font.get("FontInfo", {})
    metadata = _type1FontMetadata(backend, font_info)
    os2 = font.get("OS/2")
    if os2 is not None:
        os2.version = 4
        os2.fsType = 0
        os2.achVendID = "PYTX"
        os2.recalcAvgCharWidth(font)
        os2.recalcUnicodeRanges(font)
        os2.recalcCodePageRanges(font)
        panose = os2.panose
        panose.bFamilyType = 2
        panose.bSerifStyle = 2
        panose.bWeight = 8 if metadata["bold"] else 5
        panose.bProportion = 3
        panose.bContrast = 5
        panose.bStrokeVariation = 3
        panose.bArmStyle = 4
        panose.bLetterForm = 9 if metadata["italic"] else 2
        panose.bMidline = 3
        panose.bXHeight = 4
    name_table = font.get("name")
    if name_table is None:
        return
    names = {
        1: metadata["family"],
        2: metadata["style"],
        3: metadata["unique_id"],
        4: metadata["full_name"],
        5: metadata["version"],
        6: metadata["postscript_name"],
        16: metadata["family"],
        17: metadata["style"],
    }
    for record in list(name_table.names):
        value = names.get(record.nameID)
        if value is not None:
            name_table.setName(
                value,
                record.nameID,
                record.platformID,
                record.platEncID,
                record.langID,
            )
    for name_id, value in names.items():
        name_table.setName(value, name_id, 1, 0, 0)
        name_table.setName(value, name_id, 3, 1, 0x0409)


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
