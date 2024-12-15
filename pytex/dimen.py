"""
This module implements dimension parsing and handling.
"""


from pytex.token import CATCODE
from pytex import integer
from pytex.module import Module
from pytex.integer import readDigits, readSigns
from pytex.accessor import Array, ArrayAccessor, ParameterAccessor


def readUnsignedNumber(parser):
    """
    read an unsigned number from the input
    @param parser: the parser
    @return: the unsigned number
    """
    # an unsigned number 
    v = readDigits(parser, 10)
    t = parser.token_expand()
    # a decimal point
    if t is None:
        return float(v)
    if t.catcode != CATCODE.OTHER or (t.name!= "." and t.name != ","):
        parser.input.unread(t)
        return float(v)
    v += "."
    # a decimal part
    v += readDigits(parser, 10, optional=True)
    return float(v)


def readDimen(parser, mu=False):
    """
    read a dimension from the input
    @param parser: the parser
    @param mu: True if the dimension is a mu dimension
    @return: the dimension
    """
    return readSigns(parser) * readUnsignedDimen(parser, mu)



UNITS = {
    "pt" : 1,
    "pc" : 12,
    "in" : 72.27,
    "dd" : 1238.0 / 1157,
    "sp" : 1.0 / 65536,
    "cm" : 7227.0 / 2540,
    "mm" : 7227.0 / 254,
}

def readUnsignedDimen(parser, mu):
    """
    read an unsigned dimension from the input
    @param parser: the parser
    @param mu: True if the dimension is a mu dimension
    @return: the unsigned dimension
    """
    # an unsigned dimension
    t = parser.token_expand()
    if t is None:
        raise Exception("dimension expected")
    # an internal dimension or a glue (both have a dimenValue method)
    try:
        return t.dimenValue(parser)
    except AttributeError:
        pass
    # a number
    parser.input.unread(t)
    f = readUnsignedNumber(parser)
    parser.skipSpaces()
    # a unit
    t = parser.token_expand()
    if t is None:
        raise Exception("dimension unit expected")
    try:
        return f * t.dimenValue(parser)
    except AttributeError:
        pass
    parser.input.unread(t)
    # skip an optional true
    if mu:
        units = {"mu"}
    else:
        true = parser.readKeyword({"true"})
        if true:
            units = {"pt", "pc", "in", "bp", "cm", "mm", "dd", "cc", "sp"}
        else:
            units = {"pt", "pc", "in", "bp", "cm", "mm", "dd", "cc", "sp", "em", "ex"}
    unit = parser.readKeyword(units)
    if unit is None:
        if mu:
            raise Exception("mu dimension expected")
        else:
            raise Exception("dimension unit expected")
    if mu:
        return f
    if unit == "em":
        raise Exception("em dimension not implemented")
    if unit == "ex":
        raise Exception("ex dimension not implemented")
    return f * UNITS[unit]


class DimenParameter(ParameterAccessor):
    """
    An dimension parameter accessor
    """
    def intValue(self, parser):
        """
        return the integer value of the character code
        """
        return round(self.getValue(parser) * 65536)

    def dimenValue(self, parser):
        """
        return the integer value of the character code
        """
        return self.getValue(parser)


class DimenArrayAccessor(ArrayAccessor):
    """
    accessor for the dimen domain
    """
    def readValue(self, parser):
        return parser.readDimen()

    def intValue(self, parser):
        """
        return the integer value of the character code
        """
        return round(self.getValue(parser) * 65536)

    def dimenValue(self, parser):
        """
        return the integer value of the character code
        """
        return self.getValue(parser)


mod = Module("dimen",
    attributes = {
        "readDimen": readDimen,
    },
    domains={
        "dimen": {"generator": lambda: Array(0), "accessor": DimenArrayAccessor},
    },
    parameters={
        "hfuzz": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "vfuzz": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "overfullrule": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "emergencystretch": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "hsize": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "vsize": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "maxdepth": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "splitmaxdepth": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "boxmaxdepth": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "lineskiplimit": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "delimitershortfall": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "nulldelimiterspace": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "scriptspace": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "mathsurround": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "predisplaysize": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "displaywidth": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "displayindent": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "parindent": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "hangindent": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "hoffset": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
        "voffset": {"value": 0, "accessor": DimenParameter, "domain": "layout"},
    },
)