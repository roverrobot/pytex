"""
This module implements glue parsing and handling.
"""


from pytex import serialization
from pytex.dimen import readUnsignedDimen, Dimen, DimenCommand
from pytex.integer import readSigns
from pytex.state import Array
from pytex.accessor import ParameterAccessor, ArrayAccessor, ArrayItemAccessor
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
        self.factor = factor
        self.order = order
    
    def saveInfo(self):
        return {"init": {"factor": self.factor, "order": self.order}}

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
        self.dimen = dimen
        self.stretch = stretch
        self.shrink = shrink
    
    def saveInfo(self):
        return {"init": {
            "dimen": self.dimen, 
            "stretch": self.stretch,
            "shrink": self.shrink,
        }}
    
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
        value = t.definition.muglueValue(parser) if mu else t.definition.glueValue(parser)
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


class GlueCommand(DimenCommand):
    """
    the base class that converts a glue to a dimen
    """
    def dimenValue(self, parser):
        """
        return the dimension value of the glue
        """
        return self.glueValue(parser).dimen
    

class GlueArrayItemAccessor(ArrayItemAccessor, GlueCommand):
    """
    access the value of a glue parameter
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return readGlue(parser, mu=False)

    def glueValue(self, parser):
        """
        return the glue value
        """
        return self.domain[self.index]


class GlueArrayAccessor(ArrayAccessor, GlueCommand):
    """
    access an item of a glue array
    """
    def getItemAccessor(self, parser):
        return GlueArrayItemAccessor(self.domain, parser.readInteger())

    def glueValue(self, parser):
        """
        return the glue value of an item of the array
        @param parser: the parser
        @return: the glue value of the item of the array
        """
        return self.domain[parser.readInteger()]


class SkipArray(Array):
    """
    the skip array
    """
    def __init__(self, state):
        super().__init__("skip", state, Glue)
        self.mu = False


class MuGlueCommand(DimenCommand):
    """
    the base class that converts a mu glue to a dimen
    """
    def dimenValue(self, parser):
        """
        return the glue value
        """
        return self.muglueValue(parser).dimen


class MuGlueArrayItemAccessor(ArrayItemAccessor, MuGlueCommand):
    """
    access the value of a glue parameter
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return readGlue(parser, mu=True)

    def muglueValue(self, parser):
        """
        return the glue value
        """
        return self.domain[self.index]


class MuGlueArrayAccessor(ArrayAccessor, MuGlueCommand):
    """
    access an item of a mu glue array
    """
    def getItemAccessor(self, parser):
        return MuGlueArrayItemAccessor(self.domain, parser.readInteger())

    def muglueValue(self, parser):
        """
        return the mu glue value of an item of the array
        @param parser: the parser
        @return: the mu glue value of the item of the array
        """
        return self.domain[parser.readInteger()]


class GlueParameterAccessor(ParameterAccessor, GlueCommand):
    """
    access a glue parameter
    """
    def readValue(self, parser):
        return readGlue(parser, mu=False)

    def glueValue(self, parser):
        """
        return the glue value of the parameter
        @param parser: the parser
        @return: the glue value of the parameter
        """
        return self.entry.value


class MuGlueParameterAccessor(ParameterAccessor, MuGlueCommand):
    """
    access a mu glue parameter
    """
    def readValue(self, parser):
        return readGlue(parser, mu=True)
    
    def muglueValue(self, parser):
        """
        return the mu glue value of the parameter
        @param parser: the parser
        @return: the mu glue value of the parameter
        """
        return self.entry.value


mod = Module("glue",
    attributes={
        "readGlue": readGlue,
    },
    domains={
        "skip": {"generator": SkipArray, "accessor": GlueArrayAccessor},
        "muskip": {"generator": lambda state: Array("muskip", state, MuGlue), "accessor": MuGlueArrayAccessor},
    },
    parameters={
        # glue parameters
        "baselineskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "lineskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "abovedisplayskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "abovedisplayshortskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "belowdisplayskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "belowdisplayshortskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "leftskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "rightskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "topskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "splittopskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "layout"},
        "thinmuskip": {"value": MuGlue(), "accessor": MuGlueParameterAccessor, "domain": "layout"},
        "medmuskip": {"value": MuGlue(), "accessor": MuGlueParameterAccessor, "domain": "layout"},
        "thickmuskip": {"value": MuGlue(), "accessor": MuGlueParameterAccessor, "domain": "layout"},
        # the following glues are not used in typesetting snapshots, i.e., lazy typesetting. Instead, tehy are
        # used in list building time. So they are in parameters not layout.
        "parskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "parameters"},
        "parfillskip": {"value": Glue(0, Stretchness(1,1)), "accessor": GlueParameterAccessor, "domain": "parameters"},
        "spaceskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "parameters"},
        "xspaceskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "parameters"},
        "tabskip": {"value": Glue(), "accessor": GlueParameterAccessor, "domain": "parameters"},
    },
    commands={
        "skipdef": registerdef("skip", GlueArrayItemAccessor),
        "muskipdef": registerdef("muskip", MuGlueArrayItemAccessor),
    },
)
