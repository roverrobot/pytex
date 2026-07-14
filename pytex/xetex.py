"""
Minimal XeTeX compatibility primitives.

This module supplies the XeTeX engine marker, Unicode character generation
primitives required by expl3, and the font-name parsing needed to route XeTeX
font declarations to the existing font backends.
"""

import os
import re
from dataclasses import dataclass

from pytex import etex  # registers the e-TeX layer
from pytex.pdftex import expandable as pdftex_expandable  # registers pdfTeX utilities
from pytex.pdftex import sys as pdftex_sys  # registers timer/shell utilities
from pytex import accessor
from pytex import box as bx
from pytex import lists
from pytex import mmode
from pytex import node as nd
from pytex import token
from pytex.define import EquitableAccessor
from pytex.dimen import Dimen, UNITS
from pytex.etex import StringCommand
from pytex.font_backend import FontSpec
from pytex.glue import Glue
from pytex.integer import FixedInteger, IntegerArrayItemAccessor
from pytex.serialization import Serializable
from pytex.module import Module
from pytex.state import Array, Dict
from pytex.typeset.dvipdfm import _encode_pdf_string, serialize_xObject


version = "0.999995"

UNICODE_MAX = 0x10FFFF
INTERCHAR_CLASS_MAX = 4096
UCHARCAT_CATCODES = {
    token.CATCODE.BEGIN_GROUP,
    token.CATCODE.END_GROUP,
    token.CATCODE.MATH_SHIFT,
    token.CATCODE.ALIGNMENT_TAB,
    token.CATCODE.PARAMETER,
    token.CATCODE.SUPERSCRIPT,
    token.CATCODE.SUBSCRIPT,
    token.CATCODE.SPACE,
    token.CATCODE.LETTER,
    token.CATCODE.OTHER,
    token.CATCODE.ACTIVE,
}
COLLECTION_FONT_RE = re.compile(r"^(.+\.(?:otc|ttc|dfont)):(\d+)$", re.IGNORECASE)
PDF_FILE_FALLBACK_SIZE = Dimen(1)
PDF_FILE_PAGEBOX_KEYWORDS = {
    "media": "mediabox",
    "crop": "cropbox",
    "bleed": "bleedbox",
    "trim": "trimbox",
    "art": "artbox",
}


def _read_unicode_scalar(parser, primitive):
    value = parser.readInteger()
    if value < 0 or value > UNICODE_MAX:
        raise ValueError(
            f"{primitive} character code {value} out of range",
            parser.input.position(),
        )
    return value


def _read_interchar_class(parser, primitive):
    value = parser.readInteger()
    if value < 0 or value > INTERCHAR_CLASS_MAX:
        raise ValueError(
            f"{primitive} character class {value} out of range",
            parser.input.position(),
        )
    return value


def _read_ucharcat_catcode(parser):
    catcode = parser.readInteger()
    if catcode not in UCHARCAT_CATCODES:
        raise ValueError(
            f"Invalid code ({catcode}), should be in the ranges 1..4, 6..8, 10..13",
            parser.input.position(),
        )
    return catcode


def _character_token(parser, char_code, catcode):
    t = token.Token.token(chr(char_code), catcode)
    if t.catcode == token.CATCODE.ACTIVE:
        t.entry = parser.equitable.entry(t.name)
    return t


def _split_font_suffix(value, leading_option: bool = False):
    option_pos = value.find("/") if leading_option else value.find("/", 1)
    feature_pos = value.find(":")
    stops = [pos for pos in (option_pos, feature_pos) if pos >= 0]
    if not stops:
        return value, "", ""
    stop = min(stops)
    name = value[:stop]
    suffix = value[stop:]
    options = ""
    features = ""
    if suffix.startswith("/"):
        feature_start = suffix.find(":")
        if feature_start >= 0:
            options = suffix[:feature_start]
            features = suffix[feature_start + 1:]
        else:
            options = suffix
    else:
        features = suffix[1:]
    return name, options, features


def _split_collection_index(value):
    match = COLLECTION_FONT_RE.match(value)
    if match is None:
        return value, 0
    return match.group(1), int(match.group(2))


def parseFontName(parser, name):
    """
    Parse XeTeX's extended quoted font-name syntax.

    Bracketed names force file lookup; unbracketed names use the classic
    auto path after stripping XeTeX options/features for lookup.
    """
    if not isinstance(name, str):
        return name
    if name.startswith("file:"):
        lookup_name, font_number = _split_collection_index(name[5:])
        return FontSpec(lookup_name, lookup="file", font_number=font_number)
    if name.startswith("name:"):
        return FontSpec(name[5:], lookup="system")
    if name.startswith("["):
        end = name.find("]")
        if end >= 0:
            lookup_name, font_number = _split_collection_index(name[1:end])
            _suffix, options, features = _split_font_suffix(name[end + 1:], leading_option=True)
            return FontSpec(
                lookup_name,
                lookup="file",
                font_number=font_number,
                options=options,
                features=features,
            )
    lookup_name, options, features = _split_font_suffix(name)
    if lookup_name != name:
        return FontSpec(lookup_name, lookup="auto", options=options, features=features)
    return FontSpec(name, lookup="auto")


def _dimen_option(value):
    return f"{repr(Dimen(value))}pt"


def _number_option(value):
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return repr(value)


def _special_tokens(text):
    return [
        token.Token.token(" ", token.CATCODE.SPACE)
        if ch.isspace()
        else token.Token.token(ch, token.CATCODE.OTHER)
        for ch in text
    ]


def _read_option_word(parser):
    try:
        first = parser.skipSpaces()
    except EOFError:
        raise ValueError("expecting an option value", parser.input.position())
    toks = [first]
    while True:
        try:
            t = parser.token_expand()
        except EOFError:
            break
        if t.isSpace(True):
            break
        if t.catcode is None or t.catcode in (token.CATCODE.BEGIN_GROUP, token.CATCODE.END_GROUP):
            parser.input.unread(t)
            break
        toks.append(t)
    return parser.expandedToksToString(toks)


def _bp_to_dimen(value):
    num, den = UNITS["bp"]
    scaled = round(float(value) * 1000000)
    return Dimen(integer=Dimen._trunc_div(scaled * num * Dimen.scale, den * 1000000))


def _read_pdf_page_box(parser, filename, page_number, pagebox="cropbox"):
    try:
        path = parser.resolver._sourcePath(filename)
    except ValueError:
        return None
    if not os.path.exists(path):
        return None
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        page = reader.pages[page_number - 1]
        box = getattr(page, pagebox, page.cropbox)
        llx, lly, urx, ury = tuple(map(float, box))
    except Exception:
        return None
    width = _bp_to_dimen(urx - llx)
    height = _bp_to_dimen(ury - lly)
    bbox = tuple(_number_option(v) for v in (llx, lly, urx, ury))
    return width, height, bbox


def _bbox_size(bbox):
    try:
        llx, lly, urx, ury = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return None
    return _bp_to_dimen(urx - llx), _bp_to_dimen(ury - lly)


def _bbox_ratio(bbox):
    try:
        llx, lly, urx, ury = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return None
    return urx - llx, ury - lly


class XeTeXGraphicFileBox(bx.HBox):
    """
    Pre-packed box used by XeTeX graphic file primitives.

    The contained WHATSIT performs the later shipout work; this box exists only
    to reserve TeX layout space while keeping the primitive backend-neutral.
    """

    def copy(self, content=None):
        box = super().copy(content)
        if content is None and self._packed is self:
            box._packed = box
        return box


def _new_graphic_file_box(parser, width, height, depth, special):
    node = nd.Special(_special_tokens(special))
    box = XeTeXGraphicFileBox(parser, width, Dimen())
    box.width = Dimen(width)
    box.height = Dimen(height)
    box.depth = Dimen(depth)
    box.natural = Glue(width)
    box.list = [node]
    box.raw = [node]
    box._packed = box
    return box


def _read_image_size(parser, filename):
    try:
        path = parser.resolver._sourcePath(filename)
    except ValueError:
        return None
    if not os.path.exists(path):
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
    except Exception:
        return None
    bbox = tuple(_number_option(v) for v in (0, 0, width, height))
    return Dimen(width), Dimen(height), bbox


@dataclass
class XeTeXGraphicSpec:
    filename: str
    kind: str
    page_number: object = 1
    pagebox: object = None
    bbox: object = None
    scale: object = 1.0
    xscale: object = 1.0
    yscale: object = 1.0
    rotate: object = None
    width: object = None
    height: object = None
    depth: object = None


class UChar(token.Command):
    r"""
    \Uchar <integer> expands to a Unicode character token.
    """

    def expand(self, parser):
        char_code = _read_unicode_scalar(parser, "\\Uchar")
        catcode = token.CATCODE.SPACE if char_code == 0x20 else token.CATCODE.OTHER
        parser.input.pushTokenList([_character_token(parser, char_code, catcode)])


class UCharCat(token.Command):
    r"""
    \Ucharcat <integer> <catcode> expands to a character token.
    """

    def expand(self, parser):
        char_code = _read_unicode_scalar(parser, "\\Ucharcat")
        catcode = _read_ucharcat_catcode(parser)
        parser.input.pushTokenList([_character_token(parser, char_code, catcode)])


class XeTeXGraphicFile(lists.ModeDependentCommand):
    r"""
    Base class for XeTeX graphic file primitives.
    """

    kind = None
    primitive = None
    default_pagebox = None
    keyword_spec = {
        "width": ("width", "_read_dimen"),
        "height": ("height", "_read_dimen"),
        "scaled": ("scale", "_read_scaled"),
        "xscaled": ("xscale", "_read_scaled"),
        "yscaled": ("yscale", "_read_scaled"),
        "rotated": ("rotate", "_read_word"),
    }

    def _read_options(self, parser, spec):
        keywords = set(self.keyword_spec)
        while True:
            keyword = parser.readKeyword(keywords)
            if keyword is None:
                break
            attr, reader_name = self.keyword_spec[keyword]
            setattr(spec, attr, getattr(self, reader_name)(parser, keyword))

    def _read_dimen(self, parser, keyword):
        return parser.readDimen()

    def _read_integer(self, parser, keyword):
        return parser.readInteger()

    def _read_scaled(self, parser, keyword):
        return parser.readInteger() / 1000

    def _read_word(self, parser, keyword):
        return _read_option_word(parser)

    def _read_bbox(self, parser, keyword):
        return tuple(_read_option_word(parser) for _ in range(4))

    def _read_pagebox(self, parser, keyword):
        return PDF_FILE_PAGEBOX_KEYWORDS[keyword]

    def _natural_size(self, parser, spec):
        return None

    def _complete_size(self, parser, spec):
        natural = self._natural_size(parser, spec)
        if natural is not None:
            natural_width, natural_height, bbox = natural
            if spec.bbox is None:
                spec.bbox = bbox
            bbox_ratio = _bbox_ratio(spec.bbox)
            if spec.width is None and spec.height is None:
                spec.width = natural_width
                spec.height = natural_height
            elif spec.width is None and bbox_ratio is not None and bbox_ratio[1] != 0:
                spec.width = spec.height * (bbox_ratio[0] / bbox_ratio[1])
            elif spec.width is None and natural_height != 0:
                spec.width = natural_width * (float(spec.height) / float(natural_height))
            elif spec.height is None and bbox_ratio is not None and bbox_ratio[0] != 0:
                spec.height = spec.width * (bbox_ratio[1] / bbox_ratio[0])
            elif spec.height is None and natural_width != 0:
                spec.height = natural_height * (float(spec.width) / float(natural_width))

        if spec.width is None:
            spec.width = PDF_FILE_FALLBACK_SIZE
        if spec.height is None:
            spec.height = PDF_FILE_FALLBACK_SIZE
        if spec.depth is None:
            spec.depth = Dimen()

        spec.width = spec.width * (spec.scale * spec.xscale)
        spec.height = spec.height * (spec.scale * spec.yscale)
        spec.depth = spec.depth * (spec.scale * spec.yscale)

    def _special_options(self, spec):
        options = [
            ("width", _dimen_option(spec.width)),
            ("height", _dimen_option(spec.height)),
        ]
        if spec.depth is not None and int(spec.depth) != 0:
            options.append(("depth", _dimen_option(spec.depth)))
        if spec.rotate is not None:
            options.append(("rotate", spec.rotate))
        return options

    def _serialize_special(self, spec):
        return serialize_xObject(
            spec.kind,
            options=self._special_options(spec),
            source=_encode_pdf_string(spec.filename),
        )

    def readGraphicFileBox(self, parser):
        spec = XeTeXGraphicSpec(
            filename=parser.readFileName(),
            kind=self.kind,
            pagebox=self.default_pagebox,
        )
        self._read_options(parser, spec)
        self._complete_size(parser, spec)
        return _new_graphic_file_box(
            parser,
            spec.width,
            spec.height,
            spec.depth or Dimen(),
            self._serialize_special(spec),
        )

    def _append(self, parser, state):
        state.append(self.readGraphicFileBox(parser))

    def horizontal(self, parser, hlist):
        self._append(parser, hlist)

    def vertical(self, parser, vlist):
        self._append(parser, vlist)


class XeTeXPDFFile(XeTeXGraphicFile):
    r"""
    \XeTeXpdffile <filename> [page <integer>] [crop|media|bleed|trim|art] [scaled <integer>]
    [xscaled <integer>] [yscaled <integer>] [rotated <number>] [width <dimen>] [height <dimen>]
    [depth <dimen>].
    """

    kind = "epdf"
    primitive = "\\XeTeXpdffile"
    default_pagebox = "cropbox"
    keyword_spec = {
        **XeTeXGraphicFile.keyword_spec,
        "page": ("page_number", "_read_integer"),
        "depth": ("depth", "_read_dimen"),
        "bbox": ("bbox", "_read_bbox"),
        **{
            keyword: ("pagebox", "_read_pagebox")
            for keyword in PDF_FILE_PAGEBOX_KEYWORDS
        },
    }

    def _natural_size(self, parser, spec):
        if spec.page_number < 1:
            raise ValueError(f"{self.primitive} page number must be positive", parser.input.position())
        if spec.bbox is not None:
            size = _bbox_size(spec.bbox)
            if size is not None:
                return (*size, spec.bbox)
        return _read_pdf_page_box(parser, spec.filename, spec.page_number, spec.pagebox)

    def _special_options(self, spec):
        options = []
        if spec.page_number != 1:
            options.append(("page", str(spec.page_number)))
        if spec.pagebox is not None:
            options.append(("pagebox", spec.pagebox))
        if spec.bbox is not None:
            options.append(("bbox", spec.bbox))
        options.extend(super()._special_options(spec))
        return options

    def readPDFFileBox(self, parser):
        return self.readGraphicFileBox(parser)


class XeTeXPicFile(XeTeXGraphicFile):
    r"""
    \XeTeXpicfile <filename> [scaled <integer>] [xscaled <integer>] [yscaled <integer>]
    [rotated <number>] [width <dimen>] [height <dimen>].
    """

    kind = "image"
    primitive = "\\XeTeXpicfile"

    def _natural_size(self, parser, spec):
        return _read_image_size(parser, spec.filename)

    def _special_options(self, spec):
        options = [
            ("width", _dimen_option(spec.width)),
            ("height", _dimen_option(spec.height)),
        ]
        if spec.rotate is not None:
            options.append(("rotate", spec.rotate))
        if spec.bbox is not None:
            options.append(("bbox", spec.bbox))
        return options


class UMathCodeArray(Array):
    """
    Sparse Unicode mathcode table.
    """

    def __init__(self, state):
        super().__init__("umathcode", state, 0)


class UDelCodeArray(Array):
    """
    Sparse Unicode delimiter code table.
    """

    def __init__(self, state):
        super().__init__("udelcode", state, -1)


class XeTeXCharClassArray(Array):
    """Sparse Unicode character-to-interchar-class table."""

    def __init__(self, state):
        super().__init__("xetexcharclass", state, 0)


class XeTeXIntercharToksDict(Dict):
    """Grouped map from interchar-class pairs to token lists."""

    def __init__(self, state):
        super().__init__("xetexinterchartoks", state)

    def dump(self):
        # JSON object keys cannot be tuples, so keep tuple keys in memory and
        # encode them only at the format-file boundary.
        return {
            f"{class1},{class2}": toks
            for (class1, class2), toks in super().dump().items()
        }

    def load(self, data):
        for key, toks in data.items():
            if isinstance(key, str):
                class1, class2 = (int(value) for value in key.split(",", 1))
                key = (class1, class2)
            self.setGlobal(key, toks)


class XeTeXCharClassAccessor(accessor.Accessor):
    r"""Readable and assignable \XeTeXcharclass primitive."""

    value_type = accessor.VALUE_TYPE.INT

    def readKey(self, parser):
        return _read_unicode_scalar(parser, "\\XeTeXcharclass")

    def readValue(self, parser):
        return _read_interchar_class(parser, "\\XeTeXcharclass")

    def getTarget(self, parser):
        return accessor.KeyTarget(
            parser.xetexcharclass,
            self.currentKey(parser),
            self.value_type,
        )


class XeTeXIntercharToksAccessor(accessor.Accessor):
    r"""Readable and assignable \XeTeXinterchartoks primitive."""

    value_type = accessor.VALUE_TYPE.TOKS

    def readKey(self, parser):
        return (
            _read_interchar_class(parser, "\\XeTeXinterchartoks"),
            _read_interchar_class(parser, "\\XeTeXinterchartoks"),
        )

    def getTarget(self, parser):
        return accessor.KeyTarget(
            parser.xetexinterchartoks,
            self.currentKey(parser),
            self.value_type,
        )

    def fetchValue(self, parser, requested_type):
        value, value_type = super().fetchValue(parser, requested_type)
        if value_type == self.value_type and value is None:
            value = []
        return value, value_type


class UMathSymbol(mmode.MathSymbol):
    """
    A Unicode math symbol using the XeTeX/LuaTeX packed mathchar form.
    """

    def __init__(self, mathcode, fam):
        self.umath_type = (mathcode >> 21) & 0x7
        super().__init__(mathcode, fam)

    @classmethod
    def decode(cls, mathcode, fam=-1):
        math_type = (mathcode >> 21) & 0x7
        family = mathcode >> 24
        char = mathcode & 0x1FFFFF
        if math_type == 7:
            math_type = mmode.ATOM_TYPE.ORD.value
            if fam != -1:
                family = fam
        return mmode.ATOM_TYPE(math_type), family, chr(char)

    def encode(self):
        return UMathCode.pack(self.umath_type, self.fam, ord(self.char))


class UMathCharValue(mmode.MathCharValue):
    r"""
    A value produced by \Umathchardef.
    """

    def className(self):
        return Serializable.className(self)

    def mathCharValue(self, parser):
        return UMathSymbol(self.mathcode, parser.parameters["fam"])

    def meaning(self, parser):
        s = parser.formatName("\\Umathchar")
        math_type = (self.mathcode >> 21) & 0x7
        family = self.mathcode >> 24
        glyph = self.mathcode & 0x1FFFFF
        return f'{s}"{math_type:X}"{family:X}"{glyph:X}'

    def __eq__(self, other):
        return isinstance(other, UMathCharValue) and self.mathcode == other.mathcode


def _read_packed_umathchar(parser, primitive):
    value = parser.readInteger()
    glyph = value & 0x1FFFFF
    family = value >> 24
    if value < 0:
        raise ValueError(f"{primitive} math character code must be non-negative", parser.input.position())
    if family > 255:
        raise ValueError(f"{primitive} family must be in the range 0..255", parser.input.position())
    if glyph > UNICODE_MAX:
        raise ValueError(f"{primitive} glyph slot out of range", parser.input.position())
    return value


class UMathChar(mmode.MathChar):
    r"""
    \Umathchar <math type> <family> <glyph slot> appends a Unicode math symbol.
    """

    def mathCharValue(self, parser):
        try:
            value = UMathCode.pack(
                parser.readInteger(),
                parser.readInteger(),
                parser.readInteger(),
            )
        except ValueError as exc:
            raise ValueError(str(exc), parser.input.position())
        return UMathSymbol(value, parser.parameters["fam"])


class UMathCharNum(mmode.MathChar):
    r"""
    \Umathcharnum <packed math code> appends a Unicode math symbol.
    """

    def mathCharValue(self, parser):
        value = _read_packed_umathchar(parser, "\\Umathcharnum")
        return UMathSymbol(value, parser.parameters["fam"])


class UMathCode(token.Command):
    r"""
    \Umathcode <char slot> [=] <math type> <family> <glyph slot>.
    """

    @staticmethod
    def pack(math_type, family, glyph):
        if math_type < 0 or math_type > 7:
            raise ValueError("\\Umathcode math type must be in the range 0..7")
        if family < 0 or family > 255:
            raise ValueError("\\Umathcode family must be in the range 0..255")
        if glyph < 0 or glyph > UNICODE_MAX:
            raise ValueError("\\Umathcode glyph slot out of range")
        return (((family << 3) + math_type) << 21) + glyph

    def getAssignment(self, parser):
        char_code = _read_unicode_scalar(parser, "\\Umathcode")
        parser.skipEq(expand=True)
        try:
            value = self.pack(
                parser.readInteger(),
                parser.readInteger(),
                parser.readInteger(),
            )
        except ValueError as exc:
            raise ValueError(str(exc), parser.input.position())
        target = accessor.KeyTarget(
            parser.umathcode,
            char_code,
            accessor.VALUE_TYPE.INT,
        )
        return accessor.Assignment(target, value)

    def execute(self, parser):
        self.getAssignment(parser).apply(parser)


class UMathCodeNum(token.Command):
    r"""
    \Umathcodenum <char slot> [=] <packed math type/family/glyph slot>.
    """

    def _readCharCode(self, parser):
        return _read_unicode_scalar(parser, "\\Umathcodenum")

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        char_code = self._readCharCode(parser)
        return parser.umathcode[char_code], accessor.VALUE_TYPE.INT

    def getAssignment(self, parser):
        char_code = self._readCharCode(parser)
        parser.skipEq(expand=True)
        value = _read_packed_umathchar(parser, "\\Umathcodenum")
        target = accessor.KeyTarget(
            parser.umathcode,
            char_code,
            accessor.VALUE_TYPE.INT,
        )
        return accessor.Assignment(target, value)

    def execute(self, parser):
        self.getAssignment(parser).apply(parser)


class UMathCharDef(EquitableAccessor):
    r"""
    \Umathchardef <control sequence> [=] <math type> <family> <glyph slot>.
    """

    def readValue(self, parser):
        try:
            value = UMathCode.pack(
                parser.readInteger(),
                parser.readInteger(),
                parser.readInteger(),
            )
        except ValueError as exc:
            raise ValueError(str(exc), parser.input.position())
        return UMathCharValue(value)


class UMathCharNumDef(EquitableAccessor):
    r"""
    \Umathcharnumdef <control sequence> [=] <packed math type/family/glyph slot>.
    """

    def readValue(self, parser):
        return UMathCharValue(_read_packed_umathchar(parser, "\\Umathcharnumdef"))


class UDelCode(token.Command):
    r"""
    \Udelcode <char slot> [=] <family> <glyph slot>.
    """

    @staticmethod
    def pack(family, glyph):
        if family < 0 or family > 255:
            raise ValueError("\\Udelcode family must be in the range 0..255")
        if glyph < 0 or glyph > UNICODE_MAX:
            raise ValueError("\\Udelcode glyph slot out of range")
        return ((0x200 + family) << 21) + glyph

    def getAssignment(self, parser):
        char_code = _read_unicode_scalar(parser, "\\Udelcode")
        parser.skipEq(expand=True)
        try:
            value = self.pack(
                parser.readInteger(),
                parser.readInteger(),
            )
        except ValueError as exc:
            raise ValueError(str(exc), parser.input.position())
        target = accessor.KeyTarget(
            parser.udelcode,
            char_code,
            accessor.VALUE_TYPE.INT,
        )
        return accessor.Assignment(target, value)

    def execute(self, parser):
        self.getAssignment(parser).apply(parser)


def init(parser):
    parser.registerEngine("xetex", {
        "XeTeXversion": FixedInteger(int(version.split(".")[0])),
        "XeTeXrevision": StringCommand("." + ".".join(version.split(".")[1:])),
    })


mod = Module(
    "xetex",
    init=init,
    attributes={
        "parseFontName": parseFontName,
    },
    domains={
        "umathcode": {"generator": UMathCodeArray, "accessor": None},
        "udelcode": {"generator": UDelCodeArray, "accessor": None},
        "xetexcharclass": {"generator": XeTeXCharClassArray, "accessor": None},
        "xetexinterchartoks": {"generator": XeTeXIntercharToksDict, "accessor": None},
    },
    commands={
        "Uchar": UChar(),
        "Ucharcat": UCharCat(),
        "XeTeXcharclass": XeTeXCharClassAccessor(),
        "XeTeXinterchartoks": XeTeXIntercharToksAccessor(),
        "XeTeXpdffile": XeTeXPDFFile(),
        "XeTeXpicfile": XeTeXPicFile(),
        "Umathchar": UMathChar(),
        "Umathcharnum": UMathCharNum(),
        "Umathcode": UMathCode(),
        "Umathcodenum": UMathCodeNum(),
        "Umathchardef": UMathCharDef(),
        "Umathcharnumdef": UMathCharNumDef(),
        "Udelcode": UDelCode(),
        # XeTeX spells these pdfTeX-derived utilities without the "pdf" prefix.
        "ifprimitive": pdftex_expandable.IfPDFPrimitive(),
        "primitive": pdftex_expandable.PDFPrimitive(),
        "filedump": pdftex_expandable.PDFFileDump(),
        "filemoddate": pdftex_expandable.PDFFileModDate(),
        "filesize": pdftex_expandable.PDFFileSize(),
        "mdfivesum": pdftex_expandable.PDFMDfiveSum(),
        "strcmp": pdftex_expandable.PDFStrcmp(),
        "elapsedtime": pdftex_sys.PDFElapsedtime(),
        "resettimer": pdftex_sys.PDFResettimer(),
        "shellescape": FixedInteger(0),
    },
    parameters={
        "XeTeXinterchartokenstate": {
            "value": 0,
            "accessor": IntegerArrayItemAccessor,
            "domain": "parameters",
        },
    },
)
