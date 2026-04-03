"""
This module implements glue parsing and handling.
"""


from pytex import serialization
from pytex.dimen import readUnsignedDimen, Dimen
from pytex.integer import readSigns
from pytex.state import Array
from pytex.accessor import VALUE_TYPE, Accessor
from pytex.module import Module
from pytex.define import registerdef


class Stretchness(serialization.Serializable):
    """
    the stretchness of a glue
    
    defined by the stretch factor and the stretch order. Order 0 is finite stretch, 
    orders 1--3 is fil, fill, and filll.    
    """
    mu = False
    def __init__(self, factor=Dimen(), order: int=0):
        self.factor = Dimen(factor)
        self.order = order
    
    def saveInfo(self):
        return {"factor": float(self.factor), "order": self.order}, None

    def copy(self):
        """
        return a copy of the stretchness
        """
        return Stretchness(self.factor, self.order) 

    def __str__(self):
        if self.order == 0:
            return f"{self.factor}pt"
        return f"{self.factor}fi{'l'*self.order}"

    def __repr__(self):
        factor = repr(self.factor) if isinstance(self.factor, Dimen) else repr(Dimen(self.factor))
        if self.order == 0:
            return factor
        return f"{factor}fi{'l'*self.order}"
    
    def __add__(self, other):
        if self.order == other.order:
            return self.__class__(self.factor + other.factor, self.order)
        return other if self.order < other.order else self

    def __sub__(self, other):
        if self.order == other.order:
            return self.__class__(self.factor - other.factor, self.order)
        return -other if self.order < other.order else self
    
    def __neg__(self):
        return self.__class__(-self.factor, self.order)
    
    def __mul__(self, factor):
        return self.__class__(self.factor * factor, self.order)
    
    def __rmul__(self, factor):
        return self.__class__(self.factor * factor, self.order)

    def __truediv__(self, factor):
        return self.__class__(self.factor / factor, self.order)
    
    def __eq__(self, value):
        if not isinstance(value, Stretchness):
            return False
        return self.factor == value.factor and self.order == value.order


class Glue(serialization.Serializable):
    """
    a glue is a dimension with stretch and shrink
    """
    mu = False
    def __init__(self, dimen=Dimen(), stretch=Stretchness(), shrink=Stretchness()):
        self.dimen = Dimen(dimen)
        self.stretch = stretch
        self.shrink = shrink
    
    def saveInfo(self):
        return {
            "dimen": float(self.dimen), 
            "stretch": self.stretch,
            "shrink": self.shrink,
        }, None
    
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
        return self.__class__(self.dimen, self.stretch * factor, self.shrink / factor)

    def __str__(self):
        return f"{self.dimen}pt plus {self.stretch} minus {self.shrink}"

    def __repr__(self):
        result = repr(self.dimen)
        if self.stretch is not None and (self.stretch.order != 0 or self.stretch.factor != 0):
            result += " plus " + repr(self.stretch)
        if self.shrink is not None and (self.shrink.order != 0 or self.shrink.factor != 0):
            result += " minus " + repr(self.shrink)
        return result
    
    def __add__(self, other):
        return self.__class__(self.dimen + other.dimen, self.stretch + other.stretch, self.shrink + other.shrink)
    
    def __sub__(self, other):
        return self.__class__(self.dimen - other.dimen, self.stretch - other.stretch, self.shrink - other.shrink)
    
    def __neg__(self):
        return self.__class__(-self.dimen, -self.stretch, -self.shrink)
    
    def __mul__(self, factor):
        return self.__class__(self.dimen * factor, self.stretch * factor, self.shrink * factor)
    
    def __rmul__(self, factor):
        return self.__class__(self.dimen * factor, self.stretch * factor, self.shrink * factor)
    
    def __truediv__(self, factor):
        return self.__class__(self.dimen / factor, self.stretch / factor, self.shrink / factor)
    
    def __eq__(self, value):
        if not isinstance(value, Glue) or self.mu != value.mu:
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

    def __repr__(self):
        factor = repr(self.factor) if isinstance(self.factor, Dimen) else repr(Dimen(self.factor))
        if self.order == 0:
            return f"{factor}mu"
        return f"{factor}fi{'l'*self.order}"
    
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

    def __repr__(self):
        result = f"{self.dimen}mu"
        if self.stretch is not None and (self.stretch.order != 0 or self.stretch.factor != 0):
            result += " plus " + repr(self.stretch)
        if self.shrink is not None and (self.shrink.order != 0 or self.shrink.factor != 0):
            result += " minus " + repr(self.shrink)
        return result

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
    value = parser.readInternalValue(
        VALUE_TYPE.MUGLUE if mu else VALUE_TYPE.GLUE,
    )
    if value is not None:
        return value * sign
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


GlueArrayItemAccessor = lambda domain=None, key=None, builtin=True: Accessor(
    domain,
    key,
    builtin=builtin,
    value_type=VALUE_TYPE.GLUE,
    read_key=lambda parser: parser.readInteger(),
)


class SkipArray(Array):
    """
    the skip array
    """
    def __init__(self, state):
        super().__init__("skip", state, Glue)
        self.mu = False


MuGlueArrayItemAccessor = lambda domain=None, key=None, builtin=True: Accessor(
    domain,
    key,
    builtin=builtin,
    value_type=VALUE_TYPE.MUGLUE,
    read_key=lambda parser: parser.readInteger(),
)
mod = Module("glue",
    attributes={
        "readGlue": readGlue,
    },
    domains={
        "skip": {"generator": SkipArray, "accessor": GlueArrayItemAccessor},
        "muskip": {"generator": lambda state: Array("muskip", state, MuGlue), "accessor": MuGlueArrayItemAccessor},
    },
    parameters={
        # glue parameters
        "baselineskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "lineskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "abovedisplayskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "abovedisplayshortskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "belowdisplayskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "belowdisplayshortskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "leftskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "rightskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "topskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "splittopskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "layout"},
        "thinmuskip": {"value": MuGlue(), "accessor": MuGlueArrayItemAccessor, "domain": "layout"},
        "medmuskip": {"value": MuGlue(), "accessor": MuGlueArrayItemAccessor, "domain": "layout"},
        "thickmuskip": {"value": MuGlue(), "accessor": MuGlueArrayItemAccessor, "domain": "layout"},
        # the following glues are not used in typesetting snapshots, i.e., lazy typesetting. Instead, tehy are
        # used in list building time. So they are in parameters not layout.
        "parskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "parameters"},
        "parfillskip": {"value": Glue(0, Stretchness(1,1)), "accessor": GlueArrayItemAccessor, "domain": "parameters"},
        "spaceskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "parameters"},
        "xspaceskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "parameters"},
        "tabskip": {"value": Glue(), "accessor": GlueArrayItemAccessor, "domain": "parameters"},
    },
    commands={
        "skipdef": registerdef("skip", GlueArrayItemAccessor),
        "muskipdef": registerdef("muskip", MuGlueArrayItemAccessor),
    },
)
