"""
This module implements dimension parsing and handling.
"""

from pytex import serialization
from pytex.token import CATCODE
from pytex.module import Module
from pytex.integer import readDigits, readSigns
from pytex.state import Array
from pytex.accessor import Accessor, VALUE_TYPE
from pytex.define import registerdef


DECIMAL_DIGIT_LIMIT = 17

class Dimen(serialization.Serializable):
    scale = 65536
    def __init__(self, dimen=0.0, integer=None):
        if integer is None:
            self.value = int(float(dimen) * self.scale)
        else:
            self.value = 0 if integer is None else integer

    def saveInfo(self):
        return {"integer": self.value}, None

    def negate(self):
        return Dimen(integer=-self.value)

    def __repr__(self):
        # Mirror TeX's print_scaled routine so dimension-to-string round trips
        # stay stable when macros re-parse values (for example geometry's
        # \strip@pt + \setlength flow).
        s = self.value
        out = ""
        if s < 0:
            out = "-"
            s = -s
        out += str(s // self.scale) + "."
        scaled = 10 * (s % self.scale) + 5
        delta = 10
        while True:
            if delta > self.scale:
                scaled = scaled + 32768 - 50000
            out += str(scaled // self.scale)
            scaled = 10 * (scaled % self.scale)
            delta *= 10
            if scaled <= delta:
                break
        return out
    
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
        return Dimen(integer=self._trunc_div(self.value * den, num))
    
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
    num, den = readUnsignedNumberRatio(parser)
    return num / den


def _round_decimals(digits: str) -> int:
    """
    TeX's round_decimals approximation to 16 binary fractional bits.
    """
    a = 0
    two = 2 * Dimen.scale
    for c in reversed(digits[:DECIMAL_DIGIT_LIMIT]):
        a = (a + (ord(c) - ord("0")) * two) // 10
    return (a + 1) // 2


def readUnsignedNumberRatio(parser):
    """
    Read an unsigned number as an exact-ish rational pair (num, den).

    Decimal literals follow TeX's round_decimals behavior, so a literal
    coefficient is represented as n / 2^16.
    """
    # an unsigned number
    value = parser.readInternalValue(VALUE_TYPE.INT)
    if value is not None:
        return int(value), 1
    t = parser.token_expand()
    if t is None:
        raise ValueError("expecting a number", parser.input.position())
    if t.catcode != CATCODE.OTHER or t.name != ".":
        parser.input.unread(t)
        int_part = int(readDigits(parser, 10), 10)
        t = parser.token_expand()
        # a decimal point
        if t is None:
            return int_part, 1
        if t.catcode != CATCODE.OTHER or (t.name!= "." and t.name != ","):
            parser.input.unread(t)
            return int_part, 1
    else:
        int_part = 0
    frac = readDigits(parser, 10, optional=True)
    return int_part * Dimen.scale + _round_decimals(frac), Dimen.scale


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
    # values are (numerator, denominator) in pt units
    "pt": (1, 1),
    "pc": (12, 1),
    "in": (7227, 100),
    "bp": (7227, 7200),
    "dd": (1238, 1157),
    "cc": (14856, 1157),
    "sp": (1, 65536),
    "cm": (7227, 254),
    "mm": (7227, 2540),
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
    def dimenValue(t):
        parser.input.unread(t)
        value = parser.readInternalValue(VALUE_TYPE.DIMEN)
        if value is not None:
            return value
        definition = getattr(t, "definition", None)
        dimen_value = getattr(definition, "dimenValue", None)
        if dimen_value is None:
            return None
        return dimen_value(parser)
    # an unsigned dimension
    t = parser.token_expand()
    if t is None:
        raise Exception("dimension expected")
    # an internal dimension or a glue (both have a dimenValue method)
    # a number
    value = dimenValue(t)
    if value is not None:
        return (value, 0) if stretchness else value
    num, den = readUnsignedNumberRatio(parser)
    t = parser.skipSpaces()
    # a unit
    if t is None:
        raise ValueError("dimension unit expected", parser.input.position())
    value = dimenValue(t)
    if value is not None:
        dimen = Dimen(integer=Dimen._trunc_div(num * int(value), den))
        return (dimen, 0) if stretchness else dimen
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
        dimen = Dimen(integer=Dimen._trunc_div(num * Dimen.scale, den))
    elif unit == "em":
        # parameter #6 is quad width
        em = parser.parameters["currentfont"].param[5]
        dimen = Dimen(integer=Dimen._trunc_div(num * int(em), den))
    elif unit == "ex":
        # parameter #5 is x-height
        ex = parser.parameters["currentfont"].param[4]
        dimen = Dimen(integer=Dimen._trunc_div(num * int(ex), den))
    elif unit == "fil":
        infinity = 1
        # read additional "l"
        l = {"l"}
        while parser.readKeyword(l):
            infinity += 1
        # maximum infinity is 3 (fil, fill, filll)
        if infinity > 3:
            infinity = 3
        dimen = Dimen(integer=Dimen._trunc_div(num * Dimen.scale, den))
    else:
        # note that the everything is multiplied by \mag/1000. Thus, to produce 1 true pt,
        # we need to multiply 1 pt by 1000/\mag to cancel the effect of \mag
        unit_num, unit_den = UNITS[unit]
        mag = parser.parameters["mag"]
        dimen = Dimen(integer=Dimen._trunc_div(
            num * unit_num * Dimen.scale * 1000,
            den * unit_den * mag,
        ))
    if stretchness:
        return dimen, infinity
    return dimen


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


class DimenArrayItemAccessor(Accessor, DimenCommand):
    """
    access the value of a dimen parameter
    """
    target_type = VALUE_TYPE.DIMEN

    def readKey(self, parser):
        return parser.readInteger()

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
        return self.domain[self.currentKey(parser)]


class DimenArray(Array):
    """
    an array of dimensions
    """
    def __init__(self, state):
        super().__init__("dimen", state, Dimen)


mod = Module("dimen",
    attributes = {
        "readDimen": readDimen,
    },
    domains={
        "dimen": {"generator": DimenArray, "accessor": DimenArrayItemAccessor},
    },
    parameters={
        "hfuzz": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "vfuzz": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "overfullrule": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "emergencystretch": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "hsize": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "vsize": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "maxdepth": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "splitmaxdepth": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "boxmaxdepth": {"value": MAX_DIMEN, "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "lineskiplimit": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "delimitershortfall": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "nulldelimiterspace": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "scriptspace": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "mathsurround": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "hoffset": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        "voffset": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "layout"},
        # this value is nit in layout, because it is not used in a snapshot for typesetting
        "parindent": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "parameters"},
        "hangindent": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "volatile"},
    },
    commands={
        "dimendef": registerdef("dimen", DimenArrayItemAccessor),
    },
)
