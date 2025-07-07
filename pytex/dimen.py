"""
This module implements dimension parsing and handling.
"""

from pytex import serialization
from pytex.token import CATCODE
from pytex.module import Module
from pytex.integer import readDigits, readSigns
from pytex.state import Array
from pytex.accessor import Accessor, ArrayAccessor


class Dimen(serialization.Serializable):
    scale = 65536
    def __init__(self, dimen=None, integer=0):
        if dimen is None:
            self.value = 0 if integer is None else integer
        else:
            self.value = int(float(dimen) * self.scale)

    def saveInfo(self):
        return {"init": {"integer": self.value}}

    def negate(self):
        self.value = -self.value
        return self

    def __repr__(self):
        f = float(self)
        s = str(int(f)) + "."
        f -= int(f)
        if f == 0:
            return s + "0"
        for i in range(4):
            f *= 10
            d = int(f)
            s += str(d)
            f -= d
            if f == 0:
                break
        if f > 0:
            s += str(int(f*10 + 0.5))
        return s
    
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
    t = parser.token_expand()
    if t.catcode != CATCODE.OTHER or t.name != ".":
        if hasattr(t.definition, "intValue"):
            return float(t.definition.intValue(parser))
        parser.input.unread(t)
        v = readDigits(parser, 10)
        t = parser.token_expand()
        # a decimal point
        if t is None:
            return float(v)
        if t.catcode != CATCODE.OTHER or (t.name!= "." and t.name != ","):
            parser.input.unread(t)
            return float(v)
    else:
        v = "0"
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
    if sign < 0:
        return dimen.negate()
    return dimen


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
        if stretchness:
            return t.definition.dimenValue(parser), 0
        return t.definition.dimenValue(parser)
    except AttributeError:
        pass
    # a number
    parser.input.unread(t)
    f = readUnsignedNumber(parser)
    t = parser.skipSpaces()
    # a unit
    if t is None:
        raise ValueError("dimension unit expected", parser.input.position())
    try:
        if stretchness:
            return f * t.definition.dimenValue(parser), 0
        return f * t.definition.dimenValue(parser)
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
    parser.skipSpace()
    if unit is None:
        if mu:
            raise ValueError("mu dimension expected", parser.input.position())
        else:
            raise ValueError("dimension unit expected", parser.input.position())
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
        # note that the everything is multiplied by \mag/1000. Thus, to produce 1 true pt,
        # we need to multiply 1 pt by 1000/\mag to cancel the effect of \mag
        dimen = f * UNITS[unit] * 1000 / parser.state.layout["mag"]
    if stretchness:
        return Dimen(dimen), infinity
    return Dimen(dimen)


class DimenCommand:
    def readValue(self, parser):
        return readDimen(parser)

    def intValue(self, parser):
        """
        return the dimension in sp unit, i.e., dimension * 65536
        @param parser: the parser
        """
        return int(self.dimenValue(parser))

    def dimenValue(self, parser):
        """
        return the dimension value
        @param parser: the parser
        """
        return self.getValue(parser)


class DimenAccessor(DimenCommand, Accessor):
    """
    access the value of a dimen parameter
    """
    pass


class DimenArrayAccessor(DimenCommand, ArrayAccessor):
    """
    access an item of a dimen array
    """
    def newItemAccessor(self, index):
        return DimenAccessor(self.domain, index)


mod = Module("dimen",
    attributes = {
        "readDimen": readDimen,
    },
    domains={
        "dimen": {"generator": lambda state: Array("dimen", state, Dimen), "accessor": DimenArrayAccessor},
    },
    parameters={
        "hfuzz": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "vfuzz": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "overfullrule": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "emergencystretch": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "hsize": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "vsize": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "maxdepth": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "splitmaxdepth": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "boxmaxdepth": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "lineskiplimit": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "delimitershortfall": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "nulldelimiterspace": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "scriptspace": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "mathsurround": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "predisplaysize": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "displaywidth": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "displayindent": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "parindent": {"value": Dimen(), "accessor": DimenAccessor, "domain": "parameters"},
        "hangindent": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "hoffset": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
        "voffset": {"value": Dimen(), "accessor": DimenAccessor, "domain": "layout"},
    },
)