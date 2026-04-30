"""
Minimal XeTeX compatibility primitives.

This module supplies the XeTeX engine marker, Unicode character generation
primitives required by expl3, and the font-name parsing needed to route XeTeX
font declarations to the existing font backends.
"""

import re

from pytex import etex  # registers the e-TeX layer
from pytex.pdftex import expandable as pdftex_expandable  # registers pdfTeX utilities
from pytex.pdftex import sys as pdftex_sys  # registers timer/shell utilities
from pytex import accessor
from pytex import mmode
from pytex import token
from pytex.define import EquitableAccessor
from pytex.etex import StringCommand
from pytex.font_backend import FontSpec
from pytex.integer import FixedInteger
from pytex.serialization import Serializable
from pytex.module import Module
from pytex.state import Array


version = "0.999995"

UNICODE_MAX = 0x10FFFF
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


def _read_unicode_scalar(parser, primitive):
    value = parser.readInteger()
    if value < 0 or value > UNICODE_MAX:
        raise ValueError(
            f"{primitive} character code {value} out of range",
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


mod = Module(
    "xetex",
    attributes={
        "parseFontName": parseFontName,
    },
    domains={
        "umathcode": {"generator": UMathCodeArray, "accessor": None},
        "udelcode": {"generator": UDelCodeArray, "accessor": None},
    },
    commands={
        "XeTeXversion": FixedInteger(int(version.split(".")[0])),
        "XeTeXrevision": StringCommand("." + ".".join(version.split(".")[1:])),
        "Uchar": UChar(),
        "Ucharcat": UCharCat(),
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
)
