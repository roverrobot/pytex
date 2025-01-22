"""
This module implements dimension parsing and handling.
"""


from pytex.token import CATCODE
from pytex import integer
from pytex.module import Module
from pytex.integer import readDigits, readSigns
from pytex.state import Array
from pytex.accessor import ValuePointer, ArrayAccessor, ParameterAccessor


class Dimen:
    scale = 65536
    def __init__(self, dimen=None, integer=0):
        if dimen is None:
            self.value = 0 if integer is None else integer
        else:
            self.value = int(float(dimen) * self.scale)

    def __repr__(self):
        return f"{self.value/self.scale:.5f}"
    
    def __float__(self):
        return self.value / self.scale
    
    def __int__(self):
        return self.value
    
    def __sub__(self, other):
        return Dimen(float(self) - float(other))
    
    def __rsub__(self, other):
        return Dimen(float(other)-float(self))
    
    def __abs__(self):
        return Dimen(integer=abs(self.value))
    
    def __eq__(self, other):
        return self.value == round(float(other)*self.scale)
    
    def __lt__(self, other):
        return self.value < round(float(other)*self.scale)

    def __gt__(self, other):
        return self.value > round(float(other)*self.scale)

    def __add__(self, other):
        return Dimen(float(self) + float(other))
    
    def __radd__(self, other):
        return Dimen(float(self.value) + float(other))
    
    def __mul__(self, other):
        return Dimen(float(self) * float(other))
    
    def __rmul__(self, other):
        return Dimen(float(self) * float(other))
    
    def __truediv__(self, other):
        return Dimen(float(self) / float(other))
    
    def __rtruediv__(self, other):
        return Dimen(float(other) / float(self))
    
    def __round__(self, n):
        return Dimen(round(float(self), n))


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
    return  Dimen(sign * dimen)


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
        return t.pointer(parser).dimenValue(parser)
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
        value = t.pointer(parser)
        return f * value.dimenValue(parser)
    except AttributeError:
        parser.input.unread(t)
    true = False
    if mu:
        units = {"mu"}
    else:
        # skip an optional true
        true = parser.readKeyword({"true"})
        if true:
            units = {"pt", "pc", "in", "bp", "cm", "mm", "dd", "cc", "sp"}
        else:
            units = {"pt", "pc", "in", "bp", "cm", "mm", "dd", "cc", "sp", "em", "ex"}
    if stretchness and not true:
        units.add("fil")
    unit = parser.readKeyword(units)
    # skip a space
    parser.skipSpaces(n=1)
    if unit is None:
        if mu:
            raise Exception("mu dimension expected")
        else:
            raise Exception("dimension unit expected")
    infinity = 0
    if unit == "mu":
        dimen = f
    elif unit == "em":
        dimen = f * parser.state.parameters["currentfont"].param[5] #parameter #6 is quad width
    elif unit == "ex":
        dimen = f * parser.state.parameters["currentfont"].param[4] #parameter #6 is x height
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
        dimen = f * UNITS[unit] * parser.state.layout["mag"] / 1000
    if stretchness:
        return Dimen(dimen), infinity
    return Dimen(dimen)


class DimenValuePointer(ValuePointer):
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


mod = Module("dimen",
    attributes = {
        "readDimen": readDimen,
    },
    domains={
        "dimen": {"generator": lambda: Array(0), "accessor": ArrayAccessor, "type": DimenValuePointer},
    },
    parameters={
        "hfuzz": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "vfuzz": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "overfullrule": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "emergencystretch": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "hsize": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "vsize": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "maxdepth": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "splitmaxdepth": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "boxmaxdepth": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "lineskiplimit": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "delimitershortfall": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "nulldelimiterspace": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "scriptspace": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "mathsurround": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "predisplaysize": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "displaywidth": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "displayindent": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "parindent": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "parameters"},
        "hangindent": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "hoffset": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
        "voffset": {"value": Dimen(), "accessor": ParameterAccessor, "type": DimenValuePointer, "domain": "layout"},
    },
)