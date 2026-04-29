"""
Minimal XeTeX compatibility primitives.

This module supplies the XeTeX engine marker and the Unicode character
generation primitives required by expl3.  It deliberately does not attempt to
implement XeTeX's font machinery.
"""

from pytex import etex  # registers the e-TeX layer
from pytex.pdftex import expandable as pdftex_expandable  # registers pdfTeX utilities
from pytex.pdftex import sys as pdftex_sys  # registers timer/shell utilities
from pytex import accessor
from pytex import mmode
from pytex import token
from pytex.define import EquitableAccessor
from pytex.etex import StringCommand
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
    domains={
        "umathcode": {"generator": UMathCodeArray, "accessor": None},
        "udelcode": {"generator": UDelCodeArray, "accessor": None},
    },
    commands={
        "XeTeXversion": FixedInteger(int(version.split(".")[0])),
        "XeTeXrevision": StringCommand("." + ".".join(version.split(".")[1:])),
        "Uchar": UChar(),
        "Ucharcat": UCharCat(),
        "Umathcode": UMathCode(),
        "Umathchardef": UMathCharDef(),
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
