"""
implements the math mode
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


class MList(lists.List):
    def __init__(self, inner=True):
        super().__init__(lists.LISTTYPE.MATH, inner)
    
    node_type = nd.NODE_TYPE.MATH

    def pack(self):
        raise NotImplementedError


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
    def __init__(self, mathcode, fam=-1):
        type = (mathcode >> 12)
        self.fam = (mathcode >> 8) & 0xf
        self.char = mathcode & 0xff
        if type == 7:
            type = ATOM_TYPE.ORD
            if fam != -1:
                self.fam = fam
        super().__init__(ATOM_TYPE(type))

    def nucleus(self):
        return self.char


class Subformula(Atom):
    def __init__(self, mlist):
        super().__init__(ATOM_TYPE.ORD)
        self.list = mlist

    def nucleus(self):
        return self.list


class Box(Atom):
    def __init__(self, box):
        super().__init__(ATOM_TYPE.ORD)
        self.box = box

    def nucleus(self):
        return self.box


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
    parser.beginGroup(pos, GROUP_TYPE.MATH)
    parser.lists.append(MList(inner=inner))


def readField(parser):
    """
    read a field in a math list
    @param parser: the parser
    @return: the field
    """
    parser.skipFiller()
    t = parser.token()
    if t is None:
        raise ValueError("missing field")
    if t.catcode == CATCODE.LETTER or t.catcode == CATCODE.OTHER:
        code = parser.state.mathcode[ord(t.name)]
        char = parser.mathChar(code)
        return char
    if t.catcode == CATCODE.BEGIN_GROUP:
        parser.input.unread(t)
        parser.readList(None, GROUP_TYPE.SIMPLE)
        top = parser.lists[-1]
        assert top.type == lists.LISTTYPE.MATH and isinstance(top[-1], Subformula)
        return top.pop()
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


class MATH_STYLE(enum.Enum):
    DISPLAY = 0
    TEXT = 1
    SCRIPT = 2
    SCRIPTSCRIPT = 3


class Style(nd.Node):
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
        mlist.append(Style(self.style))


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
        "displaystyle": MathStyle(MATH_STYLE.DISPLAY),
        "textstyle": MathStyle(MATH_STYLE.TEXT),
        "scriptstyle": MathStyle(MATH_STYLE.SCRIPT),
        "scriptscriptstyle": MathStyle(MATH_STYLE.SCRIPTSCRIPT),
    },
)
