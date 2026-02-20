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
from pytex.token import CATCODE
from pytex.module import Module
from pytex.state import GROUP_TYPE
from pytex.accessor import ParameterAccessor
from pytex.define import Define
from pytex.lexer import TokenListScanner
from pytex.glue import Glue, Stretchness
from pytex.dimen import Dimen
from pytex import box
from pytex.hmode import HList
from pytex.vmode import VNodeContext, init_prevdepth
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


class MathTypesetContext:
    """
    the typesetting context for math mode, which is used to determine the interline penalty and baselineskip for display math
    """
    def __init__(self, parser, inner):
        # the interline settings
        # fonts
        def copy(array):
            return [array[i] for i in range(16)]
        self.textfont = copy(parser.state.textfont)
        self.scriptfont = copy(parser.state.scriptfont)
        self.scriptscriptfont = copy(parser.state.scriptscriptfont)
        if not inner:
            self.prevgraf = None
            layout = parser.state.layout
            # display math parameters
            self.displaywidth = layout["displaywidth"]
            self.displayindent = layout["displayindent"]
            self.predisplaysize = None
            self.prevdepth = None
            self.postdisplaypenalty = layout["postdisplaypenalty"]
            self.abovedisplayskip = layout["abovedisplayskip"]
            self.belowdisplayskip = layout["belowdisplayskip"]
            self.abovedisplayshortskip = layout["abovedisplayshortskip"]
            self.belowdisplayshortskip = layout["belowdisplayshortskip"]
            # interline parameters
            self.baselineskip = layout["baselineskip"]
            self.lineskip = layout["lineskip"]
            self.lineskiplimit = layout["lineskiplimit"]
            self.predisplaypenalty = layout["predisplaypenalty"]
            self.interlinepenalty = 0 # do not emit interline penalty

    def __getitem__(self, index):
        return getattr(self, index, None)


class MList(lists.List):
    """
    a math list
    @param parser: the parser that created the list
    @param inner: whether the list is in internal mode (inline or subformula)
    """
    def __init__(self, parser, inner=True, nodes=None):
        super().__init__(parser, lists.LISTTYPE.MATH, inner, nodes)
        # is this list a denominator? if so, this points to the fraction node
        self.fraction = None 
    
    node_type = nd.NODE_TYPE.MATH

    def append(self, node):
        if isinstance(node, box.Box):
            node = Box(node)
        super().append(node)

    def typesetNodes(self, parser, packed, context, style):
        # typeset the nodes n the list into an hlist
        if not isinstance(style, Style):
            style = Style(style)
        if packed is None:
            packed = HList(parser)
        for node in self:
            typeset = node.typeset
            if typeset is None:
                packed.append(node)
                continue
            start = len(packed)
            typeset(parser, packed, context, style)
            if len(packed) == start:
                packed.append(node)
                continue
            for n in packed[start:]:
                if n is node:
                    continue
                if getattr(n, "source", None) is None:
                    n.source = node
        return packed

    def typeset(self, parser, packed, context, style):
        # typeset into an hbox
        box = box.HBox(parser, None, None)
        self.typesetNodes(parser, box.list, context, style)
        box.typeset(parser, packed)


class InlineMathList(MList):
    def __init__(self, parser, nodes=None):
        super().__init__(parser, True, nodes)

    def saveInfo(self):
        return {"init": [x for x in self], "extra": { "fraction": self.fraction}}

    def typeset(self, parser, packed):
        math_shift = nd.MathShift(True)
        math_shift.source = self
        math_shift.kern = Dimen(parser.state.layout["mathsurround"])
        packed.append(math_shift)
        self.typesetNodes(parser, packed, self.typeset_context, Style(MATH_STYLE.T))
        math_shift = nd.MathShift(False)
        math_shift.kern = Dimen(parser.state.layout["mathsurround"])
        packed.append(math_shift)


class DisplayMathList(MList):
    def __init__(self, parser, nodes=None):
        super().__init__(parser, False, nodes)
        # the equation number. If there is one, this holds a tuple (MList, bool)
        # where the MList points to the equation number material, and the bool indicates
        # whether the equation number is on the left
        self.eqno = None
        self.typeset_context: MathTypesetContext = None
        # these point to the unrestricted hlists before and after the display math
        self.prev_paragraph = None
        self.next_paragraph = None

    def saveInfo(self):
        return {
            "init": [x for x in self], 
            "extra": {
                "eqno": self.eqno,
            }
        }

    def typeset(self, parser, packed):
        # display math
        assert self.typeset_context.prevgraf is not None
        # check the \predisplaysize
        assert self.typeset_context.predisplaysize is not None
        # After a display has been read, TEX converts it from a math list to a horizontal
        # list h in display style, as explained in Appendix G. An equation number, if
        # present, is processed in text style and put into an hbox a with its natural width. Now
        # the fussy processing begins: Let z, s, and p be the current values of \displaywidth,
        # \displayindent, and \predisplaysize. Let q and e be zero if there is no equation
        # number; otherwise let e be the width of the equation number, and let q be equal to
        # eplus one quad in the symbols font (i.e., in \textfont2). Let w0 be the natural width
        # of the displayed formula h. If w0 + q ≤z, list h is packaged in an hbox b having its
        # natural width w0. But if w0 + q>z (i.e., if the display is too wide to fit at its natural
        # width), TEX performs the following “squeeze routine”: If e!= 0 and if there is enough
        # shrinkability in the displayed formula h to reduce its width to z−q, then list h is
        # packaged in an hbox b of width z−q. Otherwise e is set to zero, and list h is packaged
        # in a (possibly overfull) hbox b of width min(w0,z).
        if self.eqno is not None:
            eqno, left = self.eqno
            a = box.HBox(parser, None, 0)
            eqno.typesetNodes(parser, a.list, self.typeset_context, Style(MATH_STYLE.T))
            a.typeset(parser, [])
            e = float(a.width)
            q = e + self.typeset_context.textfont[2].param[1] # quad
        else:
            q = 0
            e = 0
            eqno = None
            left = None
        h = self.typesetNodes(parser, None, self.typeset_context, Style(MATH_STYLE.D))
        b = box.HBox(parser, None, 0)
        b.list = h
        b.typeset(parser, [])
        w0 = float(b.width)
        z = self.typeset_context.displaywidth
        s = self.typeset_context.displayindent
        p = self.typeset_context.predisplaysize
        if w0 + q > z:
            # look at all the stretchness of a
            if e != 0:
                b = box.HBox(parser, to=z-q, spread=None)
                b.list = h
                b.typeset(parser, [])
                if b.glue_ratio > 1:
                    e = 0
            if e == 0:
                b = box.HBox(parser, to=min(w0, z), spread=None)
                b.list = h
                b.typeset(parser, [])
        # TEX tries now to center the display without regard to the
        # equation number. But if such centering would make it too close to that number
        # (where “too close” means that the space between them is less than the width e), the
        # equation is either centered in the remaining space or placed as far from the equation
        # number as possible. The latter alternative is chosen only if the first item on list h is
        # glue, since T EX assumes that such glue was placed there in order to control the spacing
        # precisely. But let’s state the rules more formally: Let w be the width of box b. TEX
        # computes a displacement d, to be used later when positioning box b, by first setting
        # d=(z−w). If e>0 and if d<2e, then d is reset to (z−w−e) or to zero, where
        # zero is chosen if list h begins with a glue item
        w = b.width
        d = z - w
        if e > 0 and d < 2*e:
            d = 0 if h[0].node_type == nd.NODE_TYPE.GLUE else z - w - e
        # TEX is now ready to put things onto the current vertical list,
        # just after the material previously constructed for the paragraph-so-far. First
        # comes a penalty item, whose cost is an integer parameter called \predisplaypenalty.
        # Then comes glue. If d+ s ≤ p, or if there was a left equation number (\leqno),
        # TEX sets ga and gb to glue items specified by the parameters \abovedisplayskip and
        # \belowdisplayskip, respectively; otherwise ga and gb become glue items correspond-
        # ing to \abovedisplayshortskip and \belowdisplayshortskip. [Translation: If the
        # predisplaysize is short enough so that it doesn’t overlap the displayed formula, the glue
        # above and below the display will be “short” by comparison with the glue that is used
        # when there is an overlap.] If e= 0 and if there is an \leqno, the equation number is
        # appended as an hbox by itself, shifted right s and preceded by interline glue as usual;
        # an infinite penalty is also appended, to prevent a page break between this number and
        # the display. Otherwise a glue item ga is placed on the vertical list.
        packed.append(nd.Penalty(self.typeset_context.predisplaypenalty))
        if d + s <= p or left is True:
            ga = self.typeset_context.abovedisplayskip
            gb = self.typeset_context.belowdisplayskip
        else:
            ga = self.typeset_context.abovedisplayshortskip
            gb = self.typeset_context.belowdisplayshortskip
        if e == 0 and left is True:
            a.typeset_context = VNodeContext(self.typeset_context, None)
            a.shifted = Dimen(s)
            packed.append(a)
            packed.append(nd.Penalty(10000))
        else:
            packed.append(nd.Glue(ga))
        if e != 0:
            # Now comes the displayed equation itself. If e!= 0, the
            # equation number box a is combined with the formula box b as follows: Let k
            # be a kern of width z−w−e−d. In the \eqno case, box b is replaced by an hbox
            # containing (b,k,a); in the \leqno case, box b is replaced by an hbox containing (a,k,b),
            # and d is set to zero. In all cases, box b is then appended to the vertical list, shifted
            # right by s+ d.
            line = box.HBox(parser, None, None)
            if e != 0:
                k = nd.Kern(z-w-e-d)
                if left:
                    line.list.append(a)
                    line.list.append(k)
                    line.list.append(b)
                    d = 0
                else:
                    line.list.append(b)
                    line.list.append(k)
                    line.list.append(a)
            b = line
        b.typeset(parser, [])
        b.shifted = Dimen(s+d)
        b.typeset_context = VNodeContext(self.typeset_context, None)
        b.typeset_context.prevdepth = init_prevdepth # prevent interline glue
        packed.append(b)
        # The final task is to append the glue or the equation number
        # that follows the display. If there was an \eqno and if e = 0, an infinite
        # penalty is placed on the vertical list, followed by the equation number box a shifted
        # right by s+ z minus its width, followed by a penalty item whose cost is the value
        # of \postdisplaypenalty. Otherwise a penalty item for the \postdisplaypenalty is
        # appended first, followed by a glue item for gb as specified above.
        if e == 0 and left is False:
            packed.append(nd.Penalty(10000))
            a.shifted = Dimen(s + z) - a.width
            a.typeset_context = VNodeContext(self.typeset_context, None)
            a.typeset_context.prevdepth = init_prevdepth
            packed.append(a)
            packed.append(nd.Penalty(self.typeset_context.postdisplaypenalty))
        else:
            packed.append(nd.Penalty(self.typeset_context.postdisplaypenalty))
            packed.append(nd.Glue(gb))
        # TEX now adds 3 to \prevgraf and returns to horizontal mode, ready to resume the paragraph.
        self.next_paragraph.typeset_context.prevgraf = self.typeset_context.prevgraf + 3


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
        # we must first read a token to check for a second $. We should do it before
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
        mlist = parser.lists.pop()
        mlist.typeset_context = MathTypesetContext(parser, mlist.inner)
        # here top points to the enclosing horizontal list
        top = parser.lists[-1]
        # if mlist is inline math, then we simply add it to the enclosing list
        if mlist.inner:
            top.append(mlist)
        else:
            # top is a paragraph. We need to end first
            parser.endParagraph()
            vlist = parser.lists[-1] # the enclosing vertical list
            vlist.append(mlist)
            parser.newParagraph(indent=False, parskip=False)
            new_par = parser.lists[-1] # the new paragraph after the display math
            top.next_paragraph = mlist
            mlist.prev_paragraph = top
            mlist.next_paragraph = new_par
            new_par.prev_paragraph = mlist
        return
    # otherwise, we are starting a new math mode
    # if we are current in a vertical mode, unread the token, enter the horizontal mode,
    # and then the $ token is encountered again
    if top.type == lists.LISTTYPE.VERTICAL:
        parser.input.unread(parser.current_token)
        parser.newParagraph()
        return
    # if we are in restricted horizontal mode, only inlien math is allowed. So we do not 
    # need to check for a second $ token
    if top.inner:
        inner = True
    else:
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
    mlist = InlineMathList(parser) if inner else DisplayMathList(parser)
    parser.lists.append(mlist)
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

    def typeset(self, parser, packed):
        if packed is None:
            raise ValueError("typeset requires a packed list")
        if parser is None:
            raise ValueError("typeset requires a parser for mu units")
        dimen = mudimen(parser, self.kern)
        packed.append(nd.Kern(dimen))
        return


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

    def typeset(self, parser, packed):
        if packed is None:
            raise ValueError("typeset requires a packed list")
        packed.append(nd.Glue(muglue(parser, self.glue)))
        return


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
