"""XeTeX Unicode character primitives."""

from pytex import token
from pytex.module import Module


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


def readUnicodeScalar(parser, primitive):
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
    r"""\Uchar <integer> expands to a Unicode character token."""

    def expand(self, parser):
        char_code = readUnicodeScalar(parser, "\\Uchar")
        catcode = token.CATCODE.SPACE if char_code == 0x20 else token.CATCODE.OTHER
        parser.input.pushTokenList([_character_token(parser, char_code, catcode)])


class UCharCat(token.Command):
    r"""\Ucharcat <integer> <catcode> expands to a character token."""

    def expand(self, parser):
        char_code = readUnicodeScalar(parser, "\\Ucharcat")
        catcode = _read_ucharcat_catcode(parser)
        parser.input.pushTokenList([_character_token(parser, char_code, catcode)])


mod = Module(
    "xetex.unicode",
    commands={
        "Uchar": UChar(),
        "Ucharcat": UCharCat(),
    },
)
