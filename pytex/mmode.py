"""
implements the math mode

Math style may change after an atom is parsed, which happens when parsing a general 
fraction: the math material were in the current style, but when \\over is met, the 
current list became the numerator and change its style. So, the style cannot be fixed
when parsing the math list, but after the list is parsed.
"""

from pytex import serialization
from pytex import lists
from pytex import node as nd
from pytex.token import CATCODE, CommandToken
from pytex.module import Module
from pytex.state import GROUP_TYPE
from pytex.accessor import ParameterAccessor
from pytex.define import Define
from pytex.lexer import TokenListScanner
from pytex.glue import Glue, Stretchness
from pytex import box
import enum


class MATH_STYLE(enum.IntEnum):
    D = 0 # display style
    T = 1 # text style
    S = 2 # script style
    SS = 3 # script script style


class Style(serialization.Serializable):
    def __init__(self, style: MATH_STYLE, cramped: bool = False):
        self.style = style
        self.cramped = cramped

    def saveInfo(self):
        return {"init": {"style": self.style.value, "cramped": self.cramped}}
    
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
    """
    a math list
    @param parser: the parser that created the list
    @param inner: whether the list is in internal mode (inline or subformula)
    """
    def __init__(self, parser, inner=True):
        super().__init__(parser, lists.LISTTYPE.MATH, inner)
        # is this list a denominator? if so, this points to the fraction node
        self.fraction = None 
        # the equation number. If there is one, this holds a tuple (MList, bool)
        # where the MList points to the equation number material, and the bool indicates
        # whether the equation number is on the left
        self.eqno = None
    
    def saveInfo(self):
        return super().saveInfo() | {"extra": { "eqno": self.eqno}}

    node_type = nd.NODE_TYPE.MATH

    def append(self, node):
        if isinstance(node, box.Box):
            node = Box(node)
        super().append(node)

    def typeset(self, parser):
        nodes = []
        nodes.append(nd.MathShift(True))
        for node in self:
            typeset = node.typeset
            if typeset is None:
                nodes.append(node)
                continue
            content = typeset(parser)
            if content is None:
                nodes.append(node)
                continue
            if not isinstance(content, list):
                content = list(content) if isinstance(content, lists.List) else [content]
            for n in content:
                if n is node:
                    continue
                if getattr(n, "source", None) is None:
                    n.source = node
            nodes.extend(content)
        nodes.append(nd.MathShift(False))
        for n in (nodes[0], nodes[-1]):
            n.source = self
        return nodes

    def pack(self):
        raise NotImplementedError


class StyleNode(nd.Node):
    """
    a node representing a math style change
    """
    def __init__(self, style):
        self.style = style

    def saveInfo(self):
        return {"init": {"style": self.style}}

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
        # the left and right delimiters, assigned by \left and \right or fractions with delimiters
        self.left = None 
        self.right = None

    def saveInfo(self):
        return {
            "extra": {
                "sub": self.sub, 
                "sup": self.sup,
                "left": self.left,
                "right": self.right
            }
        }

    node_type = nd.NODE_TYPE.MATHNODE

    def __repr__(self):
        sub = f"_{self.sub}" if self.sub is not None else ""
        sup = f"^{self.sup}" if self.sup is not None else ""
        left = f"{self.left}" if self.left is not None else ""
        right = f"{self.right}" if self.right is not None else ""
        return f"{left}{self.__class__.__name__}({self.nucleus}{sub}{sup}){right}"
    

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

    def saveInfo(self):
        return super().saveInfo() | {"init": {"mathcode": self.encode(), "fam": -1}}

    def encode(self):
        type = self.atom_type.value
        fam, char = self.nucleus
        return (type << 12) | (fam << 8) | ord(char)

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

    def saveInfo(self):
        return super().saveInfo() | {"init": {"mlist": self.nucleus}}


class Box(Atom):
    """
    a box
    @param box: the box
    """
    def __init__(self, box):
        super().__init__(ATOM_TYPE.ORD)
        self.nucleus = box
    
    def saveInfo(self):
        return super().saveInfo() | {"init": {"box": self.nucleus}}


def mathShift(parser):
    """
    begin or end math mode
    @param parser: the parser
    @param position: the position of the token
    """
    pos = parser.input.position()
    top = parser.lists[-1]
    # are we current in math mode or not?
    # if so, we are terminating the math mode
    if top.type == lists.LISTTYPE.MATH:
        # Now we are in math mode. We are terminating the math mode.
        # we must first check if the next token is $. We should do it before
        # ending the current group, as \aftergroup may insert tokens
        t = parser.token()
        pos = parser.input.position()
        # We first terminates the current group.
        # if the current math list is not the base math list started by a math shift,
        # nor is it an equation number, doing so will raise an error for mismatched groups.
        parser.endGroup(pos, GROUP_TYPE.MATH_SHIFT)
        # Now, if we are parsing equation numbers, ending the group will pop off
        # the current list, leave us at the base math list. Otherwise, we are in the base list
        # and ending the group will not pop the list off. So by now, we are at the base list.
        top = parser.lists[-1]
        # are we in display math or inline math?
        if top.inner:
            if t:
                parser.input.unread(t)
        elif t is None or t.catcode != CATCODE.MATH_SHIFT:
            # we are in display math mode. We should match $$, i.e., an additional $
            raise ValueError("missing $", pos)
        # now the top list may have changed because of endGroup (during fraction handling)
        top = parser.lists.pop()
        parser.lists[-1].append(top)
        return
    # otherwise, we are starting a new math mode
    # if we are current in a vertical mode, unread the token, enter the horizontal mode,
    # and then the $ token is encountered again
    if top.type == lists.LISTTYPE.VERTICAL:
        parser.input.unread(parser.current_token)
        parser.newParagraph()
        return
    # first, we check for inline or display math
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
    parser.beginGroup(pos, GROUP_TYPE.MATH_SHIFT)
    parser.lists.append(MList(parser, inner=inner))
    every = parser.everymath.value if inner else parser.everydisplay.value
    if every:
        parser.input.push(TokenListScanner(every))
        if parser.tracingcommands > 0 and parser.checkRange():
            parser.message(f"everymath: {parser.toksToString(every)}")


def readSubformula(parser, group_type, lbrace=None):
    """
    read a subformula
    @param parser: the parser
    @param group_type: the type of the new group
    @param style: the current math style
    @return: the subformula
    """
    if lbrace is None:
        parser.skipFiller()
        lbrace = parser.token_expand()
        if lbrace.catcode != CATCODE.BEGIN_GROUP:
            return None
    parser.input.unread(lbrace)
    list = MList(parser)
    parser.readList(list, group_type)
    assert len(list)== 1 and isinstance(list[-1], Subformula)
    return list[-1]

def readField(parser):
    """
    read a field in a math list
    @param parser: the parser
    @param group_type: the type of the new group
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
        field = readSubformula(parser, GROUP_TYPE.SIMPLE, lbrace=t)
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
        atom = Subformula(MList(mlist.parser))
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
    

class MathCharValue(lists.ModeDependentCommand):
    """
    the \\mathchardef value
    @param mathcode: the math code
    """
    def __init__(self, mathcode):
        super().__init__()
        self.mathcode = mathcode

    def saveInfo(self):
        return {"init": {"mathcode": self.mathcode}}

    @classmethod
    def new(cls, parser, **kwargs):
        """
        create a new object from the dictionary
        """
        return cls(**kwargs)

    def math(self, parser, mlist):
        mlist.append(self.mathCharValue(parser))

    def intValue(self, parser):
        return self.mathcode

    def mathCharValue(self, parser):
        return parser.mathChar(self.mathcode)
    
    def meaning(self, parser):
        """
        return the meaning of the command
        """
        s = parser.formatName("\\mathchar")
        return f"{s}\"{self.mathcode:X}"



class MathCharDefAccesor(ParameterAccessor):
    def readValue(self, parser):
        return MathCharValue(parser.readInteger())


mathchardef = Define(MathCharDefAccesor)


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

    def saveInfo(self):
        return {"init": {"dimen": self.dimen}}

    def typeset(self, parser):
        if parser is None:
            raise ValueError("typeset requires a parser for mu units")
        dimen = mudimen(parser, self.kern)
        return [nd.Kern(dimen)]


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

    def saveInfo(self):
        return {"init": {"glue": self.glue}}

    def typeset(self, parser):
        return [nd.Glue(muglue(parser, self.glue))]


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

    def saveInfo(self):
        return {
            "init": {
                "display": self.display,
                "text": self.text,
                "script": self.script,
                "scriptscript": self.scriptscript
            }
        }

    node_type = nd.NODE_TYPE.MATHNODE


class MathChoice(lists.ModeDependentCommand):
    """
    the \\mathchoice command
    """
    def math(self, parser, mlist):
        display = readSubformula(parser, GROUP_TYPE.MATH_CHOICE)
        if display is None:
            raise ValueError("missing the display choice")
        text = readSubformula(parser, GROUP_TYPE.MATH_CHOICE)
        if text is None:
            raise ValueError("missing the text choice")
        script = readSubformula(parser, GROUP_TYPE.MATH_CHOICE)
        if script is None:
            raise ValueError("missing the script choice")
        scriptscript = readSubformula(parser, GROUP_TYPE.MATH_CHOICE)
        if scriptscript is None:
            raise ValueError("missing the scriptscript choice")
        mlist.append(ChoiceNode(display, text, script, scriptscript))


class Delim(serialization.Serializable):
    """
    a class represent a delimiter
    @param delcode: the delimiter code
    @param fam: the \\fam value
    """
    def __init__(self, delcode: int, fam: int):
        self.small = MathSymbol((delcode >> 12) & 0x7ff, fam)
        self.large = MathSymbol(delcode & 0x7ff, fam)
        self.type = ATOM_TYPE(delcode >> 24 & 7)
    
    def saveInfo(self):
        return {
            "init": {
                "type": self.type.value,
                "small": self.small,
                "large": self.large
            }
        }

    def __repr__(self):
        return f"Delim({self.type}, {self.small}, {self.large})"


class Rad(Atom):
    """
    a node representing a radical
    @param delim: the delimiter
    @param oprand: a math field
    """
    def __init__(self, delim, oprand):
        super().__init__(ATOM_TYPE.RAD)
        self.nucleus = (delim, oprand)

    def saveInfo(self):
        return {"init": {"delim": self.nucleus[0], "oprand": self.nucleus[1]}}

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
        mlist.append(Rad(delim, oprand))


class Left(lists.ModeDependentCommand):
    """
    the \\left command
    """
    def math(self, parser, mlist):
        delim = readDelimiter(parser)
        parser.beginGroup(parser.input.position(), GROUP_TYPE.MATH_LEFT)
        parser.lists[-2][-1].left = delim


class Right(lists.ModeDependentCommand):
    """
    the \\right command
    """
    def math(self, parser, mlist):
        delim = readDelimiter(parser)
        parser.endGroup(parser.input.position(), GROUP_TYPE.MATH_LEFT)
        atom = lastAtom(parser.lists[-1])
        atom.right = delim


class Over(Atom):
    """
    a node representing a general fraction
    @param num: the numerator
    @param den: the denominator
    @param bar: whether it has a bar
    @param thickness: the thickness of the bar
    """
    def __init__(self, num, den, bar, thickness):
        super().__init__(ATOM_TYPE.OVER)
        self.nucleus = (num, den, bar, thickness)

    def saveInfo(self):
        return {"init": {"num": self.nucleus[0], "den": self.nucleus[1], "bar": self.nucleus[2], "thickness": self.nucleus[3]}}
    
    node_type = nd.NODE_TYPE.MATHNODE


class GeneralFraction(lists.ModeDependentCommand):
    """
    the \\over command and its variants
    @param bar: whether it has a bar
    @param delim: whether it has a pair delimiter
    @param thickness: the thickness of the ba
    """
    def __init__(self, bar: bool, delim: bool, thickness: bool):
        self.delim = delim
        self.bar = bar
        self.thickness = thickness

    def math(self, parser, mlist):
        # when TeX sees this command, it will change the current list to the numerator
        # Then it will start a new math list, and parse the denominator in the new list.
        if mlist.fraction is not None:
            raise ValueError("double fraction", parser.input.position())
        if self.delim:
            left = readDelimiter(parser)
            right = readDelimiter(parser)
        thickness = parser.readDimen() if self.thickness else None            
        replacement = MList(mlist.parser, mlist.inner)
        mlist.inner = True
        parser.lists[-1] = replacement
        enclosing = parser.lists[-2]
        if enclosing.type == lists.LISTTYPE.MATH:
            # we are parsing a subformula, replace the last atom with the new list
            enclosing[-1].nucleus = replacement
        denominator = MList(mlist.parser, mlist.inner)
        parser.lists.append(denominator)
        fraction = Over(mlist, None, self.bar, thickness)
        replacement.append(fraction)
        if self.delim:
            fraction.left = left
            fraction.right = right
        if self.thickness:
            fraction.thickness = thickness
        denominator.fraction = fraction


class Accent(Atom):
    """
    a node representing an accent
    @param accent: the accent
    @param base: a math field
    """
    def __init__(self, accent, base):
        super().__init__(ATOM_TYPE.ACC)
        self.nucleus = (accent, base)

    def saveInfo(self):
        return {"init": {"accent": self.nucleus[0], "base": self.nucleus[1]}}
    
    node_type = nd.NODE_TYPE.MATHNODE


class MathAccent(lists.ModeDependentCommand):
    """
    the \\accent command
    """
    def math(self, parser, mlist):
        accent = MathSymbol(parser.readInteger(), parser.state.parameters["fam"])
        base = readField(parser)
        mlist.append(Accent(accent, base))


class Eqno(lists.ModeDependentCommand):
    """
    the \\eqno command
    @param left: whether the equation number is on the left
    """
    def __init__(self, left: bool):
        self.left = left

    def math(self, parser, mlist):
        # we must be at the bottom of the math lists
        enclosing = parser.lists[-2]
        if enclosing.type == lists.LISTTYPE.MATH:
            raise ValueError("misplaced equation number", parser.input.position())
        if mlist.inner:
            raise ValueError("only display math can have an equation number", parser.input.position())
        # We start a new group, parsing the equation number, then we pop it off during the 
        # mathShift function before ending the math mode.
        parser.beginGroup(parser.input.position(), GROUP_TYPE.MATH_SHIFT)
        # now we have a new subformula for the equation number
        eqno = parser.lists[-1]
        mlist.eqno = (eqno, self.left)
        # the last entry of mlist should be the subformula. We do not need it
        mlist.pop()


class VCent(Box):
    """
    a vcent box
    """
    def __init__(self, box):
        super().__init__(box)
        self.atom_type = ATOM_TYPE.VCENT
    
    def saveInfo(self):
        return super().saveInfo() | {"init": {"box": self.nucleus}}


class VCenter(box.VBoxCommand):
    """
    the \\vcenter command

    As if it is a \\vbox command, but put the box into a VCent atom. In addition
    this command cannot be used to access the box value.
    """
    def execute(self, parser):
        top = parser.lists[-1]
        if top.type != lists.LISTTYPE.MATH:
            raise ValueError("\\vcenter can only be used in math mode", parser.input.position())
        box = super().boxValue(parser, False)
        top.append(VCent(box))

    def boxValue(self, parser, inner):
        raise ValueError("\\vcenter does not return a be used in math mode")
    
    group_type = GROUP_TYPE.VCENTER


class NonscriptGlue(nd.Glue):
    """
    a class representing a non-script glue
    """
    def __init__(self):
        super().__init__(Glue())
        self.nonscript = True

    def saveInfo(self):
        return {}


class Nonscript(lists.ModeDependentCommand):
    """
    the \\nonscript command
    """
    def math(self, parser, mlist):
        mlist.append(NonscriptGlue())


mod = Module("mmode",
    attributes= {
        "mathShift": mathShift,
        "subscript": subscript,
        "superscript": superscript,
    },
    commands= {
        "mathchar": MathChar(),
        "mathchardef": mathchardef,
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
        "over": GeneralFraction(True, delim=False, thickness=False),
        "atop": GeneralFraction(False, delim=False, thickness=False),
        "above": GeneralFraction(True, delim=False, thickness=True),
        "overwithdelims": GeneralFraction(True, delim=True, thickness=False),
        "atopwithdelims": GeneralFraction(False, delim=True, thickness=False),
        "abovewithdelims": GeneralFraction(True, delim=True, thickness=True),
        "eqno": Eqno(False),
        "leqno": Eqno(True),
        "vcenter": VCenter(),
        "nonscript": Nonscript(),
    },
)
