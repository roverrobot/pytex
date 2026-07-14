"""XeTeX Unicode math characters, mathcodes, and delimiter codes."""

from pytex import accessor
from pytex import mmode
from pytex import token
from pytex.define import EquitableAccessor
from pytex.module import Module
from pytex.serialization import Serializable
from pytex.state import Array
from .unicode import UNICODE_MAX, readUnicodeScalar


class UMathCodeArray(Array):
    """Sparse Unicode mathcode table."""

    def __init__(self, state):
        super().__init__("umathcode", state, 0)


class UDelCodeArray(Array):
    """Sparse Unicode delimiter code table."""

    def __init__(self, state):
        super().__init__("udelcode", state, -1)


class UMathSymbol(mmode.MathSymbol):
    """A Unicode math symbol using the XeTeX/LuaTeX packed mathchar form."""

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
    r"""A value produced by \Umathchardef."""

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
        raise ValueError(
            f"{primitive} math character code must be non-negative",
            parser.input.position(),
        )
    if family > 255:
        raise ValueError(
            f"{primitive} family must be in the range 0..255",
            parser.input.position(),
        )
    if glyph > UNICODE_MAX:
        raise ValueError(
            f"{primitive} glyph slot out of range",
            parser.input.position(),
        )
    return value


class UMathChar(mmode.MathChar):
    r"""\Umathchar <math type> <family> <glyph slot>."""

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
    r"""\Umathcharnum <packed math code>."""

    def mathCharValue(self, parser):
        value = _read_packed_umathchar(parser, "\\Umathcharnum")
        return UMathSymbol(value, parser.parameters["fam"])


class UMathCode(token.Command):
    r"""\Umathcode <char slot> [=] <math type> <family> <glyph slot>."""

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
        char_code = readUnicodeScalar(parser, "\\Umathcode")
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
    r"""\Umathcodenum <char slot> [=] <packed math code>."""

    def _readCharCode(self, parser):
        return readUnicodeScalar(parser, "\\Umathcodenum")

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
    r"""\Umathchardef <control sequence> [=] <type> <family> <glyph>."""

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
    r"""\Umathcharnumdef <control sequence> [=] <packed math code>."""

    def readValue(self, parser):
        return UMathCharValue(_read_packed_umathchar(parser, "\\Umathcharnumdef"))


class UDelCode(token.Command):
    r"""\Udelcode <char slot> [=] <family> <glyph slot>."""

    @staticmethod
    def pack(family, glyph):
        if family < 0 or family > 255:
            raise ValueError("\\Udelcode family must be in the range 0..255")
        if glyph < 0 or glyph > UNICODE_MAX:
            raise ValueError("\\Udelcode glyph slot out of range")
        return ((0x200 + family) << 21) + glyph

    def getAssignment(self, parser):
        char_code = readUnicodeScalar(parser, "\\Udelcode")
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
    "xetex.math",
    domains={
        "umathcode": {"generator": UMathCodeArray, "accessor": None},
        "udelcode": {"generator": UDelCodeArray, "accessor": None},
    },
    commands={
        "Umathchar": UMathChar(),
        "Umathcharnum": UMathCharNum(),
        "Umathcode": UMathCode(),
        "Umathcodenum": UMathCodeNum(),
        "Umathchardef": UMathCharDef(),
        "Umathcharnumdef": UMathCharNumDef(),
        "Udelcode": UDelCode(),
    },
)
