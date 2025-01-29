"""
This module implements glue parsing and handling.
"""


from pytex.dimen import readDimen, readUnsignedDimen, Dimen, DimenValueAccessor
from pytex.integer import readSigns
from pytex.state import Array
from pytex.accessor import ValuePointer, ArrayAccessor, ParameterAccessor, GlobalParameterAccessor
from pytex.module import Module
import typing


class Stretchness:
    """
    the stretchness of a glue
    
    defined by the stretch factor and the stretch order. Order 0 is finite stretch, 
    orders 1--3 is fil, fill, and filll.    
    """
    mu = False
    def __init__(self, factor=Dimen(), order: int=0):
        self.factor = factor
        self.order = order
    
    def copy(self):
        """
        return a copy of the stretchness
        """
        return Stretchness(self.factor, self.order) 

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
    
    def __eq__(self, value):
        if not isinstance(value, Stretchness):
            return False
        return self.factor == value.factor and self.order == value.order


class Glue:
    """
    a glue is a dimension with stretch and shrink
    """
    mu = False
    def __init__(self, dimen=Dimen(), stretch=Stretchness(), shrink=Stretchness()):
        self.dimen = dimen
        self.stretch = stretch
        self.shrink = shrink
    
    def copy(self):
        """
        return a copy of the glue
        """
        return Glue(self.dimen, self.stretch.copy(), self.shrink.copy())

    def scale(self, factor):
        """
        scale the glue
        factor: the scaling factor
        """
        return Glue(self.dimen, self.stretch * factor, self.shrink / factor)

    def __str__(self):
        return f"{self.dimen}pt plus {self.stretch} minus {self.shrink}"
    
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
    
    def __eq__(self, value):
        if not isinstance(value, Glue):
            return False
        return self.dimen == value.dimen and self.stretch == value.stretch and self.shrink == value.shrink


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
    
    def __eq__(self, value):
        if not isinstance(value, MuStretchness):
            return False
        return self.factor == value.factor and self.order == value.order


class MuGlue(Glue):
    """
    a mu glue is a dimension with stretch and shrink in mu units
    """
    def __init__(self, dimen = 0, stretch=MuStretchness(), shrink=MuStretchness()):
        super().__init__(dimen, stretch, shrink)

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
    
    def __eq__(self, value):
        if not isinstance(value, MuGlue):
            return False
        return self.dimen == value.dimen and self.stretch == value.stretch and self.shrink == value.shrink


def readStretchness(parser, mu: bool=False):
    """
    read a stretchness
    """
    sign = readSigns(parser)
    factor, order = readUnsignedDimen(parser, mu, True)
    if mu:
        return MuStretchness(sign*factor, order)
    return Stretchness(sign*factor, order)


def readGlue(parser, mu: bool=False):
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
    elif mu:
        stretch = MuStretchness(0, 0)
    else:
        stretch = Stretchness(0, 0)
    if parser.readKeyword({"minus"}):
        shrink = readStretchness(parser, mu)
    elif mu:
        shrink = MuStretchness(0, 0)
    else:
        shrink = Stretchness(0, 0)
    if mu:
        return MuGlue(dimen, stretch, shrink)
    return Glue(dimen, stretch, shrink)


class GlueValueAccessor(DimenValueAccessor):
    """
    an accessor for glue values
    """
    def glueValue(self, parser):
        """
        return the glue value
        """
        return self.pointer(parser).getValue(parser)

    def dimenValue(self, parser):
        """
        return the dimen value
        """
        return self.glueValue(parser).dimen


class GlueValuePointer(GlueValueAccessor, ValuePointer):
    """
    A glue value pointer
    """
    def readValue(self, parser):
        return parser.readGlue()


class GlueCommand(GlueValueAccessor):
    """
    access the glue of the command
    """
    def getValue(self, parser):
        return self.pointer(parser).getValue(parser)
    

class GlueArrayAccessor(ArrayAccessor, GlueCommand):
    """
    access an item of a glue array
    """
    def __init__(self, domain):
        ArrayAccessor.__init__(self, domain, GlueValuePointer)


class GlueParameterAccessor(ParameterAccessor, GlueValueAccessor):
    """
    access the value of a glue parameter
    """
    def __init__(self, domain, name):
        ParameterAccessor.__init__(self, domain, name, GlueValuePointer)


class MuGlueValueAccessor:
    """
    accessor for mu glue values
    """
    def muglueValue(self, parser):
        """
        return the glue value
        """
        return self.getValue(parser)


class MuGlueValuePointer(ValuePointer, MuGlueValueAccessor):
    """
    pointing to a mu glue value
    """
    def readValue(self, parser):
        return parser.readGlue(mu=True)


class MuGlueCommand(MuGlueValueAccessor):
    """
    access the mu glue value of a command
    """
    def getValue(self, parser):
        return self.pointer(parser).muglueValue(parser)


class MuGlueArrayAccessor(ArrayAccessor, MuGlueCommand):
    """
    access an item of a mu glue array
    """
    def __init__(self, domain):
        ArrayAccessor.__init__(self, domain, MuGlueValuePointer)


class MuGlueParameterAccessor(ParameterAccessor, MuGlueCommand):
    """
    access the value of a mu glue parameter
    """
    def __init__(self, domain, name):
        ParameterAccessor.__init__(self, domain, name, MuGlueValuePointer)


mod = Module("glue",
    attributes={
        "readGlue": readGlue,
    },
    domains={
        "skip": {"generator": lambda: Array(Glue()), "accessor": GlueArrayAccessor},
        "muskip": {"generator": lambda: Array(MuGlue()), "accessor": MuGlueArrayAccessor},
    },
    parameters={
        # glue parameters
        "baselineskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "lineskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "parskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "parameters"},
        "abovedisplayskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "abovedisplayshortskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "belowdisplayskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "belowdisplayshortskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "leftskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "rightskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "topskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "splittopskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "tabskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "parfillskip": {"value": Glue(0, Stretchness(1,1)), "accessor": GlueParameterAccessor, "domain": "parameters"},
        "thinmuskip": {"value": MuGlue(), "accessor": MuGlueParameterAccessor, "domain": "layout"},
        "medmuskip": {"value": MuGlue(), "accessor": MuGlueParameterAccessor, "domain": "layout"},
        "thickmuskip": {"value": MuGlue(), "accessor": MuGlueParameterAccessor, "domain": "layout"},
        "spaceskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "parameters"},
        "xspaceskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "parameters"},
    }
)
