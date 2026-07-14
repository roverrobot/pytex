"""XeTeX character classes and intercharacter token lists."""

from pytex import accessor
from pytex.integer import IntegerArrayItemAccessor
from pytex.module import Module
from pytex.state import Array, Dict
from .unicode import readUnicodeScalar


INTERCHAR_CLASS_MAX = 4096


def _read_interchar_class(parser, primitive):
    value = parser.readInteger()
    if value < 0 or value > INTERCHAR_CLASS_MAX:
        raise ValueError(
            f"{primitive} character class {value} out of range",
            parser.input.position(),
        )
    return value


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
        return readUnicodeScalar(parser, "\\XeTeXcharclass")

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


mod = Module(
    "xetex.interchar",
    domains={
        "xetexcharclass": {
            "generator": XeTeXCharClassArray,
            "accessor": None,
        },
        "xetexinterchartoks": {
            "generator": XeTeXIntercharToksDict,
            "accessor": None,
        },
    },
    commands={
        "XeTeXcharclass": XeTeXCharClassAccessor(),
        "XeTeXinterchartoks": XeTeXIntercharToksAccessor(),
    },
    parameters={
        "XeTeXinterchartokenstate": {
            "value": 0,
            "accessor": IntegerArrayItemAccessor,
            "domain": "parameters",
        },
    },
)
