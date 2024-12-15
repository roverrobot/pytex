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


def readDimen(parser, mu: bool=False):
    """
    read a dimension from the input

    Note that, this function is is used to read either a dimension or a 
    stretchness of a glue.

    @param parser: the parser
    @param mu: True if the dimension is a mu dimension
    @return: the dimension if fil is False, otherwise the dimension and the infinity level

    """
    sign = readSigns(parser)
    dimen = readUnsignedDimen(parser, mu, False)
    return  sign * dimen


UNITS = {
    "pt" : 1,
    "pc" : 12,
    "in" : 72.27,
    "dd" : 1238.0 / 1157,
    "sp" : 1.0 / 65536,
    "cm" : 7227.0 / 2540,
    "mm" : 7227.0 / 254,
}

def readUnsignedDimen(parser, mu: bool, stretchness: bool):
    """
    read an unsigned dimension from the input
    @param parser: the parser
    @param mu: True if the dimension is a mu dimension
    @param stretchness: True if the dimension is a stretchness
    @return: the unsigned dimension if stretchness is False, otherwise the 
    dimension and the infinity level
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
    if stretchness:
        units.add("fil")
    unit = parser.readKeyword(units)
    if unit is None:
        if mu:
            raise Exception("mu dimension expected")
        else:
            raise Exception("dimension unit expected")
    infinity = 0
    if mu:
        dimen = f
    elif unit == "em":
        raise Exception("em dimension not implemented")
    elif unit == "ex":
        raise Exception("ex dimension not implemented")
    elif unit == "fil":
        infinity = 1
        # read additional "l"
        l = {"l"}
        while parser.readKeyword(l):
            infinity += 1
        # maximum infinity is 3 (fil, fill, filll)
        if infinity > 3:
            infinity = 3
        dimen = f
    else:
        dimen = f * UNITS[unit]
    if stretchness:
        return dimen, infinity
    return dimen


class DimenValue:
    """
    An dimension parameter accessor
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return parser.readDimen()

    def intValue(self, parser):
        """
        return the dimension in sp unit, i.e., dimension * 65536
        @param parser: the parser
        """
        return round(self.getValue(parser) * 65536)

    def dimenValue(self, parser):
        """
        return the dimension value
        @param parser: the parser
        """
        return self.getValue(parser)


class DimenParameter(DimenValue, ParameterAccessor):
    """
    An dimension parameter accessor
    """
    pass

class DimenArrayAccessor(DimenValue, ArrayAccessor):
    """
    accessor for the dimen domain
    """
    pass


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