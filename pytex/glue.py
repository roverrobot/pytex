"""
This module implements glue parsing and handling.
"""


from pytex.dimen import readDimen, readUnsignedDimen
from pytex.integer import readSigns
from pytex.state import Array
from pytex.accessor import ValuePointer, ArrayAccessor, ParameterAccessor
from pytex.module import Module
import typing


class Stretchness:
    """
    the stretchness of a glue
    
    defined by the stretch factor and the stretch order. Order 0 is finite stretch, 
    orders 1--3 is fil, fill, and filll.    
    """
    mu = False
    def __init__(self, factor: float, order: int):
        self.factor = factor
        self.order = order
    
    def __str__(self):
        if self.order == 0:
            return f"{self.factor}pt"
        return f"{self.factor}fi{'l'*self.order}"
    
    def __add__(self, other):
        if self.order == other.order:
            return Stretchness(self.factor + other.factor, self.order)
        return other if self.order < other.order else self

    def __sub__(self, other):
        if self.order == other.order:
            return Stretchness(self.factor - other.factor, self.order)
        return -other if self.order < other.order else self
    
    def __neg__(self):
        return Stretchness(-self.factor, self.order)
    
    def __mul__(self, factor):
        return Stretchness(self.factor * factor, self.order)
    
    def __rmul__(self, factor):
        return Stretchness(self.factor * factor, self.order)

    def __truediv__(self, factor):
        return Stretchness(self.factor / factor, self.order)


class Glue:
    """
    a glue is a dimension with stretch and shrink
    """
    mu = False
    def __init__(self, dimen: float=0, stretch: Stretchness = None, shrink: Stretchness = None):
        self.dimen = dimen
        self.stretch = stretch
        self.shrink = shrink
    
    def __str__(self):
        result = f"{self.dimen}pt"
        if self.stretch is not None:
            result += " plus " + str(self.stretch)
        if self.shrink is not None:
            result += " minus " + str(self.shrink)
        return result
    
    def __add__(self, other):
        return Glue(self.dimen + other.dimen, self.stretch + other.stretch, self.shrink + other.shrink)
    
    def __sub__(self, other):
        return Glue(self.dimen - other.dimen, self.stretch - other.stretch, self.shrink - other.shrink)
    
    def __neg__(self):
        return Glue(-self.dimen, -self.stretch, -self.shrink)
    
    def __mul__(self, factor):
        return Glue(self.dimen * factor, self.stretch * factor, self.shrink * factor)
    
    def __rmul__(self, factor):
        return Glue(self.dimen * factor, self.stretch * factor, self.shrink * factor)
    
    def __truediv__(self, factor):
        return Glue(self.dimen / factor, self.stretch / factor, self.shrink / factor)


class MuStretchness(Stretchness):
    """
    the stretchness of a mu glue
    """
    mu = True
    def __str__(self):
        if self.order == 0:
            return f"{self.factor}mu"
        return f"{self.factor}fi{'l'*self.order}"
    
    def stretchness(self, parser):
        """
        return the stretchness value
        """
        raise NotImplementedError()


class MuGlue(Glue):
    """
    a mu glue is a dimension with stretch and shrink in mu units
    """
    mu = True
    def __str__(self):
        result = f"{self.dimen}mu"
        if self.stretch is not None:
            result += " plus " + str(self.stretch)
        if self.shrink is not None:
            result += " minus " + str(self.shrink)
        return result

    def glue(self, parser):
        """
        return the glue value
        """
        raise NotImplementedError()


def readStretchness(parser, mu: bool=False) -> Stretchness:
    """
    read a stretchness
    """
    sign = readSigns(parser)
    factor, order = readUnsignedDimen(parser, mu, True)
    if mu:
        return MuStretchness(sign*factor, order)
    return Stretchness(sign*factor, order)


def readGlue(parser, mu: bool=False) -> Glue:
    """
    read a glue
    """
    sign = readSigns(parser)
    # check for internal glue
    t = parser.token_expand()
    if t is None:
        raise Exception("glue expected")
    try:
        value = t.muglueValue(parser) if mu else t.glueValue(parser)
        return value * sign
    except AttributeError:
        parser.input.unread(t)
    dimen = readUnsignedDimen(parser, mu, False) * sign
    shrink = None
    if parser.readKeyword({"plus"}):
        stretch = readStretchness(parser, mu)
    else:
        stretch = Stretchness(0, 0)
    if parser.readKeyword({"minus"}):
        shrink = readStretchness(parser, mu)
    else:
        shrink = Stretchness(0, 0)
    if mu:
        return MuGlue(dimen, stretch, shrink)
    return Glue(dimen, stretch, shrink)


class GlueValuePointer(ValuePointer):
    """
    An dimension parameter accessor
    """
    def readValue(self, parser):
        return parser.readGlue()

    def intValue(self, parser):
        """
        return the integer value (dimension in sp unit, i.e., dimension * 65536) 
        """
        return round(self.dimenValue(parser) * 65536)

    def dimenValue(self, parser):
        """
        return the dimen value
        """
        return self.getValue(parser).dimen
    
    def glueValue(self, parser):
        """
        return the glue value
        """
        return self.getValue(parser)


class MuGlueValuePointer(ValuePointer):
    """
    An mu dimension parameter accessor
    """
    def readValue(self, parser):
        return parser.readGlue(mu=True)

    def muglueValue(self, parser):
        """
        return the glue value
        """
        return self.getValue(parser)


mod = Module("glue",
    attributes={
        "readGlue": readGlue,
    },
    domains={
        "skip": {"generator": lambda: Array(Glue()), "accessor": ArrayAccessor, "type": GlueValuePointer},
        "muskip": {"generator": lambda: Array(MuGlue()), "accessor": ArrayAccessor, "type": MuGlueValuePointer},
    },
    parameters={
        # glue parameters
        "baselineskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "lineskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "parskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "abovedisplayskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "abovedisplayshortskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "belowdisplayskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "belowdisplayshortskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "leftskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "rightskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "topskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "splittopskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "tabskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "parfillskip": {"value": Glue(0, Stretchness(1,1)), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "layout"},
        "thinmuskip": {"value": MuGlue(), "accessor": ParameterAccessor, "type": MuGlueValuePointer, "domain": "layout"},
        "medmuskip": {"value": MuGlue(), "accessor": ParameterAccessor, "type": MuGlueValuePointer, "domain": "layout"},
        "thickmuskip": {"value": MuGlue(), "accessor": ParameterAccessor, "type": MuGlueValuePointer, "domain": "layout"},
        "spaceskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "parameters"},
        "xspaceskip": {"value": Glue(), "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "parameters"},
        "lastskip": {"value": 0, "accessor": ParameterAccessor, "type": GlueValuePointer, "domain": "globals"},
    }
)