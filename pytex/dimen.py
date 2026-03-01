"""
This module implements dimension parsing and handling.
"""

from pytex import serialization
from pytex.token import CATCODE
from pytex.module import Module
from pytex.integer import readDigits, readSigns
from pytex.state import Array
from pytex.accessor import ParameterAccessor, ArrayAccessor, ArrayItemAccessor
from pytex.define import registerdef

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
        s = "" if self.value >=0 else "-"
        f = abs(float(self))
        s += str(int(f)) + "."
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
        if f >= 0.05:
            s += str(int(f*10 + 0.5))
        return s
    
    def __float__(self):
        return self.value / self.scale
    
    def __int__(self):
        return self.value
    
    def __neg__(self):
        return Dimen(integer=-self.value)

    @staticmethod
    def _ratio(value):
        if isinstance(value, Dimen):
            return value.value, Dimen.scale
        if isinstance(value, int):
            return value, 1
        try:
            return value.as_integer_ratio()
        except AttributeError:
            return float(value).as_integer_ratio()

    @classmethod
    def _pt_value(cls, value):
        if isinstance(value, Dimen):
            return value.value
        num, den = cls._ratio(value)
        return cls._trunc_div(num * cls.scale, den)

    def __sub__(self, other):
        return Dimen(integer=self.value - self._pt_value(other))
    
    def __rsub__(self, other):
        return Dimen(integer=self._pt_value(other) - self.value)
    
    def __abs__(self):
        return Dimen(integer=abs(self.value))
    
    def __eq__(self, other):
        return self.value == round(float(other)*self.scale)
    
    def __lt__(self, other):
        return self.value < round(float(other)*self.scale)

    def __gt__(self, other):
        return self.value > round(float(other)*self.scale)

    def __ge__(self, other):
        return self.value >= int(float(other) * self.scale)
    
    def __le__(self, other):
        return self.value <= int(float(other) * self.scale)

    def __add__(self, other):
        return Dimen(integer=self.value + self._pt_value(other))
    
    def __radd__(self, other):
        return Dimen(integer=self._pt_value(other) + self.value)

    @staticmethod
    def _trunc_div(numerator, denominator):
        if denominator == 0:
            raise ZeroDivisionError("division by zero")
        sign = 1
        if numerator < 0:
            numerator = -numerator
            sign = -sign
        if denominator < 0:
            denominator = -denominator
            sign = -sign
        return sign * (numerator // denominator)

    @staticmethod
    def _round_div(numerator, denominator):
        if denominator == 0:
            raise ZeroDivisionError("division by zero")
        sign = 1
        if numerator < 0:
            numerator = -numerator
            sign = -sign
        if denominator < 0:
            denominator = -denominator
            sign = -sign
        quotient, remainder = divmod(numerator, denominator)
        if remainder * 2 >= denominator:
            quotient += 1
        return sign * quotient
    
    def __mul__(self, other):
        num, den = self._ratio(other)
        return Dimen(integer=self._trunc_div(self.value * num, den))
    
    def __rmul__(self, other):
        num, den = self._ratio(other)
        return Dimen(integer=self._trunc_div(num * self.value, den))
    
    def __truediv__(self, other):
        num, den = self._ratio(other)
        return Dimen(integer=self._round_div(self.value * den, num))
    
    def __rtruediv__(self, other):
        return Dimen(integer=self._round_div(self._pt_value(other) * self.scale, self.value))
    
    def __round__(self, n):
        return Dimen(round(float(self), n))
    

MAX_DIMEN = Dimen(integer=0xffffffff)
NEG_MAX_DIMEN = Dimen(integer=-0xffffffff)


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
    "bp" : 7227.0 / 7200,
    "dd" : 1238.0 / 1157,
    "cc" : 14856.0 / 1157,
    "sp" : 1.0 / 65536,
    "cm" : 7227.0 / 254,
    "mm" : 7227.0 / 2540,
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
    """
    base class that converts a dimension to an integer
    """
    def intValue(self, parser):
        """
        get the integer value of the dimension
        @param parser: the parser
        @return: the integer value of the dimension
        """
        return int(self.dimenValue(parser))  # convert to int for consistency with other parameters


class DimenArrayItemAccessor(ArrayItemAccessor, DimenCommand):
    """
    access the value of a dimen parameter
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return readDimen(parser, mu=False)
    
    def dimenValue(self, parser):
        """
        get the dimension value from the input stack
        @param parser: the parser
        @return: the dimension value
        """
        return self.domain[self.index]


class DimenArrayAccessor(ArrayAccessor, DimenCommand):
    """
    access an item of a dimen array
    """
    def getItemAccessor(self, parser):
        return DimenArrayItemAccessor(self.domain, parser.readInteger())
    
    def dimenValue(self, parser):
        """
        get the dimension value of an item of the array
        @param parser: the parser
        @return: the dimension value of the item of the array
        """
        return self.domain[parser.readInteger()]


class DimenArray(Array):
    """
    an array of dimensions
    """
    def __init__(self, state):
        super().__init__("dimen", state, Dimen)


class DimenParameterAccessor(ParameterAccessor, DimenCommand):
    """
    access a dimen parameter
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return readDimen(parser, mu=False)

    def dimenValue(self, parser):
        """
        get the dimension value of the parameter
        @param parser: the parser
        @return: the dimension value of the parameter
        """
        return self.entry.value


mod = Module("dimen",
    attributes = {
        "readDimen": readDimen,
    },
    domains={
        "dimen": {"generator": DimenArray, "accessor": DimenArrayAccessor},
    },
    parameters={
        "hfuzz": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "vfuzz": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "overfullrule": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "emergencystretch": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "hsize": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "vsize": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "maxdepth": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "splitmaxdepth": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "boxmaxdepth": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "lineskiplimit": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "delimitershortfall": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "nulldelimiterspace": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "scriptspace": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "mathsurround": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "hoffset": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        "voffset": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "layout"},
        # this value is nit in layout, because it is not used in a snapshot for typesetting
        "parindent": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "parameters"},
        "hangindent": {"value": Dimen(), "accessor": DimenParameterAccessor, "domain": "volatile"},
    },
    commands={
        "dimendef": registerdef("dimen", DimenArrayItemAccessor),
    },
)
