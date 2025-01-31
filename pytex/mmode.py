"""
implements the math mode

Math style may change after an atom is parsed, which happens when parsing a general 
fraction: the math material were in the current style, but when \\over is met, the 
current list became the numerator and change its style. So, the style cannot be fixed
when parsing the math list, but after the list is parsed.
"""

from pytex import lists
from pytex import node as nd
from pytex.token import CATCODE
from pytex.module import Module
from pytex.state import GROUP_TYPE
from pytex.accessor import Accessor
from pytex.define import Define
from pytex.integer import IntegerCommand
from pytex.glue import Glue, Stretchness
import enum


class MATH_STYLE(enum.IntEnum):
    D = 0 # display style
    T = 1 # text style
    S = 2 # script style
    SS = 3 # script script style


class Style:
    def __init__(self, style: MATH_STYLE, cramped: bool = False):
        self.style = style
        self.cramped = cramped
    
    def font(self, settings, family):
        """
        get the font of a family in the current style
        @param settings: the settings for typesetting the math list
        @param family: the family
        @return: the font
        """
        if self.style < MATH_STYLE.S:
            return settings.textfont[family]
        if self.style == MATH_STYLE.S:
            return settings.scriptfont[family]
        return settings.scriptscriptfont[family]
    
    def superscript(self):
        """
        get the style for a superscript
        @param parser: the parser
        @return: the style
        """
        style = MATH_STYLE.S if self.style < MATH_STYLE.S else MATH_STYLE.SS
        return Style(style, cramped=self.cramped)

    def subscript(self):
        """
        get the style for a subscript
        @return: the style
        """
        style = MATH_STYLE.S if self.style < MATH_STYLE.S else MATH_STYLE.SS
        return Style(style, cramped=True)

    def numerator(self):
        """
        get the style for a numerator
        @return: the style
        """
        style = self.style - 1 if self.style > MATH_STYLE.SS else MATH_STYLE.SS
        return Style(style, cramped=self.cramped)
    
    def denominator(self):
        """
        get the style for a denominator
        @return: the style
        """
        style = self.style - 1 if self.style > MATH_STYLE.SS else MATH_STYLE.SS
        return Style(style, cramped=True)

    def __repr__(self):
        cramped = '\"' if self.cramped else ''
        return f"Style({self.style}{cramped})"


class MList(lists.List):
    def __init__(self, inner=True):
        super().__init__(lists.LISTTYPE.MATH, inner)
    
    node_type = nd.NODE_TYPE.MATH

    def pack(self):
        raise NotImplementedError


class StyleNode(nd.Node):
    """
    a node representing a math style change
    """
    def __init__(self, style):
        self.style = style

    node_type = nd.NODE_TYPE.MATHNODE


class MathStyle(lists.ModeDependentCommand):
    """
    set the math style: \\displaystyle, \\textstyle, \\scriptstyle, \\scriptscriptstyle
    """
    def __init__(self, style):
        self.style = style

    def math(self, parser, mlist):
        mlist.append(StyleNode(self.style))


class ATOM_TYPE(enum.Enum):
    ORD = 0
    OP = 1
    BIN = 2
    REL = 3
    OPEN = 4
    CLOSE = 5
    PUNCT = 6
    INNER = 7
    OVER = 8
    UNDER = 9
    ACC = 10
    RAD = 11
    VCENT = 12


class Atom(nd.Node):
    """
    Base class for all atoms.
    """
    def __init__(self, atom_type: ATOM_TYPE):
        self.sub = None
        self.sup = None
        self.atom_type = atom_type

    node_type = nd.NODE_TYPE.MATHNODE

    def __repr__(self):
        sub = f"_{self.sub}" if self.sub is not None else ""
        sup = f"^{self.sup}" if self.sup is not None else ""
        return f"{self.nucleus()}{sub}{sup}"
    

class MathSymbol(Atom):
    """
    A math symbol
    @param mathcode: the math code
    @param fam: the \\fam value
    """
    def __init__(self, mathcode, fam):
        type, fam, char = self.decode(mathcode, fam)
        super().__init__(ATOM_TYPE(type))
        self.nucleus = (fam, char)

    @classmethod
    def decode(cls, mathcode, fam=-1):
        type = (mathcode >> 12)
        family = (mathcode >> 8) & 0xf
        char = mathcode & 0xff
        if type == 7:
            type = ATOM_TYPE.ORD
            if fam != -1:
                family = fam
        return type, family, chr(char)

    def typesetNucleus(self, settings, hlist):
        char, fam = self.nucleus
        font = settings.style.font(settings, fam)
        hlist.append(font[char])


class Subformula(Atom):
    """
    a subformula
    @param mlist: the list
    """
    def __init__(self, mlist):
        super().__init__(ATOM_TYPE.ORD)
        self.nucleus = mlist


class Box(Atom):
    """
    a box
    @param box: the box
    """
    def __init__(self, box):
        super().__init__(ATOM_TYPE.ORD)
        self.nucleus = box


def mathShift(parser):
    """
    begin or end math mode
    @param parser: the parser
    @param position: the position of the token
    """
    pos = parser.input.position()
    top = parser.lists[-1]
    if top.type == lists.LISTTYPE.MATH:
        if not top.inner:
            pos = parser.input.position()
            t = parser.token()
            if t is None or t.catcode != CATCODE.MATH_SHIFT:
                raise ValueError("missing $", pos)
        parser.endGroup(pos, GROUP_TYPE.MATH)
        parser.lists.pop()
        parser.lists[-1].append(top)
        return
    if top.type == lists.LISTTYPE.VERTICAL:
        parser.newParagraph()
    t = parser.token()
    if t is None:
        inner = True
    elif t.catcode == CATCODE.MATH_SHIFT:
        inner = False
    else:
        inner = True
        parser.input.unread(t)
    # \fam=-1 when entering math mode
    parser.state.parameters["fam"] = -1
    parser.beginGroup(pos, GROUP_TYPE.MATH)
    parser.lists.append(MList(inner=inner))


def readSubformula(parser, lbrace=None):
    """
    read a subformula
    @param parser: the parser
    @param style: the current math style
    @return: the subformula
    """
    if lbrace is None:
        parser.skipFiller()
        lbrace = parser.token_expand()
        if lbrace.catcode != CATCODE.BEGIN_GROUP:
            return None
    parser.input.unread(lbrace)
    list = MList(True)
    parser.readList(list, GROUP_TYPE.SIMPLE)
    assert len(list)== 1 and isinstance(list[-1], Subformula)
    return list[-1]

def readField(parser):
    """
    read a field in a math list
    @param parser: the parser
    @return: the field
    """
    parser.skipFiller()
    t = parser.token_expand()
    if t is None:
        raise ValueError("missing field")
    if t.catcode == CATCODE.LETTER or t.catcode == CATCODE.OTHER:
        code = parser.state.mathcode[ord(t.name)]
        char = parser.mathChar(code)
        return char
    if t.catcode == CATCODE.BEGIN_GROUP:
        field = readSubformula(parser, lbrace=t)
        if field is not None:
            return field
    try:
        return t.mathCharValue(parser)
    except AttributeError:
        raise ValueError("expecting a math field")


def lastAtom(mlist):
    """
    get the last atom in a list
    @param mlist: the list
    """
    if mlist.type != lists.LISTTYPE.MATH:
        raise ValueError("not a math list")
    if len(mlist) == 0:
        atom = None
    else:
        atom = mlist[-1]
        if not isinstance(atom, Atom):
            atom = None
    if atom is None:
        atom = Subformula(MList())
        mlist.append(atom)
    return atom


def subscript(parser):
    """
    set the subscript of an atom
    @param parser: the parser
    """
    top = parser.lists[-1]
    atom = lastAtom(top)
    if atom.sub is not None:
        raise ValueError("double subscript", parser.input.position())
    field = readField(parser)
    atom.sub = field


def superscript(parser):
    """
    set the superscript of an atom
    @param parser: the parser
    """
    top = parser.lists[-1]
    atom = lastAtom(top)
    if atom.sup is not None:
        raise ValueError("double superscript", parser.input.position())
    field = readField(parser)
    atom.sup = field


class MathChar(lists.ModeDependentCommand):
    """
    the \\mathchar command
    """
    def math(self, parser, mlist):
        mlist.append(self.mathCharValue(parser))

    def mathCharValue(self, parser):
        code = parser.readInteger()
        return parser.mathChar(code)
    
    def __repr__(self):
        c = self.mathcode >> 12
        f = (self.mathcode >> 8) & 0xf
        p = self.mathcode & 0xff
        return f"\\mathchar{{{c}, {f}, {p}}}"


class MathCharValue(lists.ModeDependentCommand):
    """
    the \\mathchardef value
    @param mathcode: the math code
    """
    def __init__(self, mathcode):
        super().__init__()
        self.mathcode = mathcode

    def math(self, parser, mlist):
        mlist.append(self.mathCharValue(parser))

    def intValue(self, parser):
        return self.mathcode

    def mathCharValue(self, parser):
        return parser.mathChar(self.mathcode)
    

class MathCharDefAccesor(Accessor):
    def readValue(self, parser):
        return MathCharValue(parser.readInteger())


class MathCharDef(IntegerCommand, Define):
    """
    the \\mathchardef command
    """
    def newItemAccessor(self, index):
        return MathCharDefAccesor(self.domain, index)


def mudimen(parser, dimen):
    """
    calculate the actual dimension of a mu dimen
    @param parser: the parser
    @param dimen: the mu dimen
    @return: the true dimension

    The mu unit is 1/18 of the em unit of \\textfont[2]
    """
    return dimen * parser.state.textfont[2].param[5] / 18 # fontdimen 6 is em


def muglue(parser, glue):
    """
    calculate the actual dimension of a mu glue
    @param parser: the parser
    @param glue: the mu glue
    @return: the true dimension
    """
    dimen = mudimen(parser, glue.dimen)
    stretch = nustretchness(parser, glue.stretch)
    shrink = nustretchness(parser, glue.shrink)
    return Glue(dimen, stretch, shrink)


def nustretchness(parser, stretch):
    """
    calculate the actual stretchness of a mu glue
    @param parser: the parser
    @param stretch: the stretchness
    @return: the true stretchness
    """
    factor = mudimen(parser, stretch.factor) if stretch.order == 0 else stretch.factor
    return Stretchness(factor, stretch.order)


class MuKern(nd.Kern):
    def __init__(self, dimen):
        super().__init__(dimen)
        self.mu = True

    def typeset(self, parser, hlist):
        dimen = mudimen(self.kern, parser)
        hlist.append(nd.Kern(dimen))


class MKern(lists.ModeDependentCommand):
    """
    the \\mkern command
    """
    def math(self, parser, mlist):
        dimen = parser.readDimen(mu=True)
        mlist.append(MuKern(dimen))


class MuGlue(nd.Glue):
    def __init__(self, glue):
        super().__init__(glue)
        self.mu = True

    def typeset(self, parser, hlist):
        hlist.append(nd.Glue(self.glue))


class MSkip(lists.ModeDependentCommand):
    """
    the \\mskip command
    """
    def math(self, parser, mlist):
        glue = parser.readGlue(mu=True)
        mlist.append(MuGlue(glue))


class MathAtom(lists.ModeDependentCommand):
    """
    specify the atom type of the field following the command
    """
    def __init__(self, atom_type):
        self.atom_type = atom_type

    def math(self, parser, mlist):
        field = readField(parser)
        field.atom_type = self.atom_type
        mlist.append(field)


class MATH_LIMITS(enum.Enum):
    DISPLAY = 0
    NORMAL = 1
    NONE = 2


class Limits(lists.ModeDependentCommand):
    """
    set the limits of a math operator if the last item is an OP atom
    """
    def __init__(self, limits):
        self.limits = limits

    def math(self, parser, mlist):
        if len(mlist) > 0:
            node = mlist[-1]
            if isinstance(node, Atom) and node.atom_type == ATOM_TYPE.OP:
                node.limits = self.limits


class ChoiceNode(nd.Node):
    """
    a node representing \\mathchoice
    """
    def __init__(self, display, text, script, scriptscript):
        self.display = display
        self.text = text
        self.script = script
        self.scriptscript = scriptscript

    node_type = nd.NODE_TYPE.MATHNODE


class MathChoice(lists.ModeDependentCommand):
    """
    the \\mathchoice command
    """
    def math(self, parser, mlist):
        display = readSubformula(parser)
        if display is None:
            raise ValueError("missing the display choice")
        text = readSubformula(parser)
        if text is None:
            raise ValueError("missing the text choice")
        script = readSubformula(parser)
        if script is None:
            raise ValueError("missing the script choice")
        scriptscript = readSubformula(parser)
        if scriptscript is None:
            raise ValueError("missing the scriptscript choice")
        mlist.append(ChoiceNode(display, text, script, scriptscript))


class Delim:
    """
    a class represent a delimiter
    @param delcode: the delimiter code
    @param fam: the \\fam value
    """
    def __init__(self, delcode: int, fam: int):
        self.small = MathSymbol((delcode >> 12) & 0x7ff, fam)
        self.large = MathSymbol(delcode & 0x7ff, fam)
        self.type = ATOM_TYPE(delcode >> 24 & 7)


class Rad(Atom):
    """
    a node representing a radical
    @param delim: the delimiter
    @param oprand: a math field
    """
    def __init__(self, delim, oprand):
        super().__init__(ATOM_TYPE.RAD)
        self.nucleus = (delim, oprand)

    node_type = nd.NODE_TYPE.MATHNODE


class Delimiter(lists.ModeDependentCommand):
    """
    the \\delimiter command
    """
    def math(self, parser, mlist):
        # when used independently in a math list, its right most 3 hex digits are
        # dropped, and the remaining 15 bits are used as the a mathchar
        delcode = parser.readInteger() >> 12
        fam = parser.state.parameters["fam"]
        mlist.append(MathSymbol(delcode, fam))

    def delimiter(self, parser):
        delcode = parser.readInteger()
        fam = parser.state.parameters["fam"]
        return Delim(delcode, fam)


def readDelimiter(parser):
    """
    read a delimiter
    @param parser: the parser
    @return: the delimiter
    """
    t = parser.token_expand()
    if t is None:
        raise ValueError("missing delimiter")
    if t.catcode == CATCODE.LETTER or t.catcode == CATCODE.OTHER:
        code = parser.state.delcode[ord(t.name)]
    else:
        try:
            code = t.delimiter(parser)
        except AttributeError:
            raise ValueError("expecting a delimiter")
    return Delim(code, parser.state.parameters["fam"])


class Radical(lists.ModeDependentCommand):
    """
    the \\radical command
    """
    def math(self, parser, mlist):
        delim = Delim(parser.readInteger(), parser.state.parameters["fam"])
        oprand = readField(parser)
        mlist.append(Radical(delim, oprand))


class Left(lists.ModeDependentCommand):
    """
    the \\left command
    """
    def math(self, parser, mlist):
        delim = readDelimiter(parser)
        parser.beginGroup(parser.input.position(), GROUP_TYPE.MATH_LEFT)
        parser.lists[-1].left = delim


class Right(lists.ModeDependentCommand):
    """
    the \\right command
    """
    def math(self, parser, mlist):
        delim = readDelimiter(parser)
        parser.lists[-1].right = delim
        parser.endGroup(parser.input.position(), GROUP_TYPE.MATH_LEFT)
        atom = lastAtom(parser.lists[-1])
        atom.left = atom.nucleus.left
        atom.right = atom.nucleus.right


class Accent(Atom):
    """
    a node representing an accent
    @param accent: the accent
    @param base: a math field
    """
    def __init__(self, accent, base):
        super().__init__(ATOM_TYPE.ACC)
        self.nucleus = (accent, base)

    node_type = nd.NODE_TYPE.MATHNODE


class MathAccent(lists.ModeDependentCommand):
    """
    the \\accent command
    """
    def math(self, parser, mlist):
        accent = MathSymbol(parser.readInteger(), parser.state.parameters["fam"])
        base = readField(parser)
        mlist.append(Accent(accent, base))


mod = Module("mmode",
    attributes= {
        "mathShift": mathShift,
        "subscript": subscript,
        "superscript": superscript,
    },
    commands= {
        "mathchar": MathChar(),
        "mathchardef": MathCharDef(),
        "mkern": MKern(),
        "mskip": MSkip(),
        "mathord": MathAtom(ATOM_TYPE.ORD),
        "mathop": MathAtom(ATOM_TYPE.OP),
        "mathbin": MathAtom(ATOM_TYPE.BIN),
        "mathrel": MathAtom(ATOM_TYPE.REL),
        "mathopen": MathAtom(ATOM_TYPE.OPEN),
        "mathclose": MathAtom(ATOM_TYPE.CLOSE),
        "mathpunct": MathAtom(ATOM_TYPE.PUNCT),
        "mathinner": MathAtom(ATOM_TYPE.INNER),
        "overline": MathAtom(ATOM_TYPE.OVER),
        "underline": MathAtom(ATOM_TYPE.UNDER),
        "displaystyle": MathStyle(MATH_STYLE.D),
        "textstyle": MathStyle(MATH_STYLE.T),
        "scriptstyle": MathStyle(MATH_STYLE.S),
        "scriptscriptstyle": MathStyle(MATH_STYLE.SS),
        "displaylimits": Limits(MATH_LIMITS.DISPLAY),
        "limits": Limits(MATH_LIMITS.NORMAL),
        "nolimits": Limits(MATH_LIMITS.NONE),
        "mathchoice": MathChoice(),
        "delimiter": Delimiter(),
        "radical": Radical(),
        "mathaccent": MathAccent(),
        "left": Left(),
        "right": Right(),
    },
)
