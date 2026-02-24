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
from pytex.token import CATCODE, MathShiftToken
from pytex.module import Module
from pytex.state import GROUP_TYPE
from pytex.accessor import ParameterAccessor
from pytex.define import Define
from pytex.lexer import TokenListScanner
from pytex.glue import Glue, Stretchness
from pytex.dimen import Dimen, NEG_MAX_DIMEN
from pytex import box
from pytex.hmode import HList
from pytex.vmode import VNodeContext, init_prevdepth
import enum
from math import inf, ceil


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
        get the style for a generalized fraction numerator (Rule 15a)
        @return: the style
        """
        if self.style == MATH_STYLE.D:
            return Style(MATH_STYLE.T, cramped=self.cramped)
        return self.superscript()
    
    def denominator(self):
        """
        get the style for a generalized fraction denominator (Rule 15a)
        @return: the style
        """
        if self.style == MATH_STYLE.D:
            return Style(MATH_STYLE.T, cramped=True)
        return self.subscript()

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
        # TeX requires symbols/extensible families to expose enough fontdimen values.
        # family 2 (symbols): at least 22 params; family 3 (extension): at least 13 params.
        for name, fonts in (
            ("textfont", self.textfont),
            ("scriptfont", self.scriptfont),
            ("scriptscriptfont", self.scriptscriptfont),
        ):
            symbol_params = getattr(fonts[2], "param", ())
            ext_params = getattr(fonts[3], "param", ())
            if len(symbol_params) < 22:
                raise ValueError(f"{name}[2] has {len(symbol_params)} fontdimen params; need at least 22 for math typesetting")
            if len(ext_params) < 13:
                raise ValueError(f"{name}[3] has {len(ext_params)} fontdimen params; need at least 13 for math typesetting")
        # inter-atom spaces
        self.muskips = [parser.state.layout[x] for x in ["thinmuskip", "medmuskip", "thickmuskip"]]
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
    
    def font(self, style, family):
        """
        get the font of a family in the current style
        @param settings: the settings for typesetting the math list
        @param family: the family
        @return: the font
        """
        if style.style < MATH_STYLE.S:
            return self.textfont[family]
        if style.style == MATH_STYLE.S:
            return self.scriptfont[family]
        return self.scriptscriptfont[family]

    def sigma(self, style: Style):
        return self.font(style, 2).param

    def xi(self, style: Style):
        return self.font(style, 3).param

class AtomTypesetContext:
    """
    Transient context for typesetting one atom.

    Carries list-level context plus the previous/effective atom type used by
    Appendix G rule 5.
    """
    def __init__(self, context, prev_atom_type):
        self.context = context
        self.prev_atom_type = prev_atom_type
        self.atom_type = None

    def __getitem__(self, index):
        return getattr(self.context, index, None)

    def __getattr__(self, name):
        return getattr(self.context, name)


class MList(lists.List):
    """
    a math list
    @param parser: the parser that created the list
    @param inner: whether the list is in internal mode (inline or subformula)
    """
    def __init__(self, parser, inner=True, nodes=None):
        super().__init__(parser, lists.LISTTYPE.MATH, inner, nodes)
        self.building_atom = None
    
    node_type = nd.NODE_TYPE.MATH

    def clear(self):
        super().clear()
        self.building_atom = None

    def buildAtom(self, field, atom=None):
        if atom is None:
            atom = self[-1] if len(self) > 0 else None
            if not isinstance(atom, Atom):
                atom = Subformula(MList(self.parser))
                self.append(atom)
        else:
            self.append(atom)
        if getattr(atom, field, None) is not None:
            if field == "sub":
                raise ValueError("double subscript", self.parser.input.position())
            if field == "sup":
                raise ValueError("double superscript", self.parser.input.position())
            raise ValueError("double field", self.parser.input.position())
        self.building_atom = (atom, field)

    def append(self, node):
        if self.building_atom is not None:
            atom, field = self.building_atom
            setattr(atom, field, node)
            self.building_atom = None
            return
        if isinstance(node, box.Box):
            node = Box(node)
        elif isinstance(node, MList):
            n = Atom(ATOM_TYPE.ORD)
            n.nucleus = node
            node = n
        elif isinstance(node, MathSymbol):
            n = Atom(node.type)
            n.nucleus = node
            node = n
        super().append(node)

    def typesetNodes(self, parser, packed, context, style):
        # typeset the nodes n the list into an hlist
        if not isinstance(style, Style):
            style = Style(style)
        pass_through = {
            nd.NODE_TYPE.RULE,
            nd.NODE_TYPE.DISC,
            nd.NODE_TYPE.PENALTY,
            nd.NODE_TYPE.WHATSIT,
        }
        if packed is None:
            packed = HList(parser)
        current = self
        i = 0
        stack = []
        prev_atom_type = None
        while current is not None:
            if i >= len(current):
                if not stack:
                    break
                current, i = stack.pop()
                continue
            node = current[i]
            i += 1
            # TeXBook Appdex G, Rule 3: If the current item is a style change, set C to the specified style. Delete the
            # current item from the list and move on to the next.
            if isinstance(node, StyleNode):
                style = node.style
                continue
            # TeXbook Appendix G, rule 4.
            if isinstance(node, ChoiceNode):
                branch = node.branch(style)
                if isinstance(branch, Subformula):
                    branch = branch.nucleus
                if branch is not None:
                    stack.append((current, i))
                    current = branch
                    i = 0
                continue
            if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
                # TeXbook Appendix G, rule 2.
                if getattr(node, "nonscript", False):
                    packed.append(node)
                    if style.style <= MATH_STYLE.S and i < len(current):
                        # remove the immediately following glue/kern item.
                        nxt = current[i]
                        if nxt.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
                            i += 1
                    continue
                if getattr(node, "mu", False):
                    start = len(packed)
                    node.typeset(parser, packed, context, style)
                    for n in packed[start:]:
                        if n is node:
                            continue
                        if getattr(n, "source", None) is None:
                            n.source = node
                    continue
                packed.append(node)
                continue
            # TeXbook Appendix G, rule 1: these nodes stay unchanged.
            if node.node_type in pass_through:
                packed.append(node)
                continue
            if isinstance(node, Atom):
                atom_context = AtomTypesetContext(context, prev_atom_type)
                node.typeset(parser, packed, atom_context, style)
                prev_atom_type = node.atom_type if atom_context.atom_type is None else atom_context.atom_type
                continue
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
    def __init__(self, style, cramped=False):
        if isinstance(style, Style):
            self.style = style
        else:
            self.style = Style(style, cramped)

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
        self.left: Delim= None 
        self.right: Delim = None

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
    
    def typeset(self, parser, packed, context=None, style=None, atom_type=None):
        if atom_type is None:
            atom_type = self.atom_type
        if context is None:
            # Fallback for generic list/box expansion paths.
            packed.append(self)
            return
        prev_atom_type = context.prev_atom_type
        sigma = context.sigma(style)
        xi = context.xi(style)
        # TeXbook Appendix G, rule 5.
        if atom_type == ATOM_TYPE.BIN and (
            prev_atom_type is None
            or prev_atom_type in (ATOM_TYPE.BIN, ATOM_TYPE.OP, ATOM_TYPE.REL, ATOM_TYPE.OPEN, ATOM_TYPE.PUNCT)
        ):
            atom_type = ATOM_TYPE.ORD
        # TeXbook Appendix G, rule 6. If the current item is a Rel or Close or Punct atom, and if the most recent 
        # previous atom was Bin, change that previous Bin to Ord.
        elif atom_type in (ATOM_TYPE.REL, ATOM_TYPE.CLOSE, ATOM_TYPE.PUNCT) and prev_atom_type == ATOM_TYPE.BIN:
            prev_atom_type = ATOM_TYPE.ORD
        # TeXbook Appendix G, rule 8. If the current item is a Vcent atom (from \vcenter), let its nucleus be a vbox
        # of height-plus-depth v. Change the height to 1/2 v+ a and the depth to 1/2 v−a, where
        # a is the axis height, σ22. Change this atom to type Ord 
        # TeXbook Appendix G: After the entire math list has been processed by Rules 1–18, T EX looks at the last 
        # atom (if there was one), and changes its type from Bin to Ord (if it was of type Bin). 
        context.atom_type = atom_type
        b = self.assemble(parser, context, style)
        if context.prev_atom_type == ATOM_TYPE.BIN:
            context.prev_atom_type = ATOM_TYPE.ORD
        axis = Dimen(context.sigma(style)[21])
        total = b.height + b.depth
        if self.left:
            left = self.left.typeset(parser, total, context, style, axis)
            self.typsetSpace(packed, context, style, ATOM_TYPE.OPEN)
            packed.append(left)
            context.prev_atom_type = ATOM_TYPE.OPEN
            self.typsetSpace(packed, context, style, atom_type)
        else:
            self.typsetSpace(packed, context, style, atom_type)
        for n in b.list:
            # packed needs to handle ligatures automatically. So we cannot use extend, but to add them invididually
            packed.append(n)
        context.prev_atom_type = atom_type
        if self.right:
            right = self.right.typeset(parser, total, context, style, axis)
            self.typsetSpace(packed, context, style, ATOM_TYPE.OPEN)
            packed.append(right)
            context.prev_atom_type = ATOM_TYPE.CLOSE

    """
    An array holding the spaces between the previous atom (rows) and the current item (columns)
    0 means no space, 1 or -1 means a thinmuskip, 2 or -2 means a medmuskip, and 3 or -3 means 
    a thickmuskip. None means the situation is impossible, and negative numbers mean that the
    space is not put in script or scriptscript styles (like prpeceeded by a \\nonscript)
    """
    spaces = [
        [0, 1, -2, -3, 0, 0, -1],
        [1, 1, None, -3, 0, 0, 0, -1],
        [-2, -2, None, None, -2, None, None, -2],
        [-3, -3, None, 0, -3, 0, 0, -3],
        [0, 0, None, 0, 0, 0, 0, 0],
        [0, 1, -2, -3, 0, 0, 0, -1],
        [-1, -1, None, -1, -1, -1, -1, -1],
        [-1, 1, -2, -3, -1, 0, -1, -1]
    ]

    def typsetSpace(self, packed, context:MathTypesetContext, style, atom_type):
        """
        Typeset the psace between this atom and the previous one
        """
        prev_type = context.prev_atom_type
        if prev_type is None:
            # the first Atom needs no space
            return
        space = self.spaces[prev_type.value][atom_type.value]
        assert space is not None, f"Impossible situation: an atom {prev_type} followed by {atom_type}"
        if space == 0:
            return
        if space < 0:
            if style.style > MATH_STYLE.T:
                return
            space = -space
        packed.append(nd.Glue(muglue(context, style, context.muskips[space - 1])))
        pass

    def typesetNucleus(self, parser, packed, context, style):
        """
        Typeset the nucleus into a box and return it
        """
        if self.nucleus is None:
            # return an emptybox
            b = box.HBox(parser, 0, 0)
            b.typeset(parser, [])
            packed.append(b)
        else:
            self.nucleus.typeset(parser, packed, context, style)
    
    def typesetScripts(self, parser, packed, context, style):
        """
        typeset the nucleus, the superscript and the subscript
        """
        pass

    def assemble(self, parser, context, style):
        """
        return a box that contains the nucleus, superscritp and subscript.
        """
        b = box.HBox(parser, 0, 0)
        self.typesetNucleus(parser, b.list, context, style)
        b.typeset(parser, [])
        return b

    @staticmethod
    def rebox(parser, b, width):
        """
        Rebox an hbox to the desired width.

        If width already matches, return the original box. Otherwise, center content
        with \\hss glue at both sides. The source box is unpackaged, and a trailing
        italic correction kern is preserved when implied by the unboxed rightmost char.
        """
        if b.node_type != nd.NODE_TYPE.HLIST:
            raise ValueError("rebox expects an hbox")
        width = Dimen(width)
        if b.width is None:
            b.typeset(parser, [])
        if b.width == width:
            return b
        out = box.HBox(parser, width, None)
        hss = Glue(0, Stretchness(1, 1), Stretchness(1, 1))
        out.list.append(nd.Glue(hss))
        italic = None
        out.list.extend(b.list)
        if b.list:
            right = b.list[-1]
            if right.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                italic = getattr(right, "italic", None)
        if italic is not None and float(italic) != 0:
            out.list.append(nd.Kern(italic, automatic=True))
        out.list.append(nd.Glue(hss))
        out.typeset(parser, [])
        return out
    

class MathSymbol(serialization.Serializable):
    """
    A math symbol
    @param mathcode: the math code
    @param fam: the \\fam value
    """
    def __init__(self, mathcode, fam):
        self.type, self.fam, self.char = self.decode(mathcode, fam)

    def saveInfo(self):
        return {"init": {"mathcode": self.encode(), "fam": -1}}

    def encode(self):
        return (self.type.value << 12) | (self.fam << 8) | ord(self.char)

    @classmethod
    def decode(cls, mathcode, fam=-1):
        type = (mathcode >> 12)
        family = (mathcode >> 8) & 0xf
        char = mathcode & 0xff
        if type == 7:
            type = ATOM_TYPE.ORD
            if fam != -1:
                family = fam
        return ATOM_TYPE(type), family, chr(char)

    def typeset(self, parser, packed, context, style):
        font = context.font(style, self.fam)
        packed.append(font[self.char])


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


class MathEndGroupCallback:
    def __init__(self, parser):
        self.parser = parser

    def endgroup(self, parser, top, mlist):
        raise NotImplementedError("subclasses should implement it")

    def __call__(self):
        # first we need to check if we are building a general fraction
        parser = self.parser

        def _ensure_atom_complete(mlist):
            if mlist.building_atom is not None:
                raise ValueError("missing field", parser.input.position())

        mlist = parser.lists.pop()
        assert mlist.type == lists.LISTTYPE.MATH
        _ensure_atom_complete(mlist)
        if getattr(mlist, "is_denominator", False):
            mlist = parser.lists.pop()
            _ensure_atom_complete(mlist)
        top = parser.lists[-1]
        self.endgroup(parser, top, mlist)


class MathShitfEndGroupCallback(MathEndGroupCallback):
    def endgroup(self, parser, top, mlist):
        mlist.typeset_context = MathTypesetContext(parser, mlist.inner)
        # here top points to the enclosing horizontal list
        # if mlist is inline math, then we simply add it to the enclosing list
        if mlist.inner:
            top.append(mlist)
            return
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

class SubformulaEndGroupCallBack(MathEndGroupCallback):
    def endgroup(self, parser, top, mlist):
        top.append(mlist)

def mathShift(parser):
    """
    begin or end math mode
    @param parser: the parser
    @param position: the position of the token
    """
    # check if we are starting or terminating the math mode
    top = parser.lists[-1]
    # are we current in math mode or not?
    # if so, we are terminating the math mode
    if top.type == lists.LISTTYPE.MATH:
        # Now we are in math mode. We are terminating the math mode.
        t = parser.token()
        # are we in display math or inline math?
        if top.inner:
            if t:
                parser.input.unread(t)
        elif t is None or t.catcode != CATCODE.MATH_SHIFT:
            # we are in display math mode. We should match $$, i.e., an additional $
            raise ValueError("missing $", parser.input.position())
        pos = parser.input.position()
        # We first terminates the current group.
        # if the current math list is not the base math list started by a math shift,
        # nor is it an equation number, doing so will raise an error for mismatched groups.
        parser.endGroup(pos, GROUP_TYPE.MATH_SHIFT)
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
    parser.beginGroup(parser.input.position(), GROUP_TYPE.MATH_SHIFT, MathShitfEndGroupCallback(parser))
    mlist = InlineMathList(parser) if inner else DisplayMathList(parser)
    parser.lists.append(mlist)
    every = parser.everymath.value if inner else parser.everydisplay.value
    if every:
        parser.input.push(TokenListScanner(every))
        if parser.tracingcommands > 0 and parser.checkRange():
            parser.message(f"everymath: {parser.toksToString(every)}")


def subscript(parser):
    """
    set the subscript of an atom
    @param parser: the parser
    """
    parser.lists[-1].buildAtom("sub")


def superscript(parser):
    """
    set the superscript of an atom
    @param parser: the parser
    """
    parser.lists[-1].buildAtom("sup")


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


def mudimen(context, style, dimen):
    """
    calculate the actual dimension of a mu dimen
    @param parser: the parser
    @param dimen: the mu dimen
    @return: the true dimension

    The mu unit is 1/18 of the em unit of \\textfont[2]
    """
    return dimen * context.font(style, 2).param[5] / 18 # fontdimen 6 is em


def muglue(context, style, glue):
    """
    calculate the actual dimension of a mu glue
    @param parser: the parser
    @param glue: the mu glue
    @return: the true dimension
    """
    dimen = mudimen(context, style, glue.dimen)
    stretch = mustretchness(context, style, glue.stretch)
    shrink = mustretchness(context, style, glue.shrink)
    return Glue(dimen, stretch, shrink)


def mustretchness(context, style, stretch):
    """
    calculate the actual stretchness of a mu glue
    @param parser: the parser
    @param stretch: the stretchness
    @return: the true stretchness
    """
    factor = mudimen(context, style, stretch.factor) if stretch.order == 0 else stretch.factor
    return Stretchness(factor, stretch.order)


class MuKern(nd.Kern):
    def __init__(self, dimen):
        super().__init__(dimen)
        self.mu = True

    def saveInfo(self):
        return {"init": {"dimen": self.dimen}}

    def typeset(self, parser, packed, context, style):
        if packed is None:
            raise ValueError("typeset requires a packed list")
        if parser is None:
            raise ValueError("typeset requires a parser for mu units")
        dimen = mudimen(context, style, self.kern)
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

    def typeset(self, parser, packed, context, style):
        if packed is None:
            raise ValueError("typeset requires a packed list")
        packed.append(nd.Glue(muglue(context, style, self.glue)))
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
    the general class to implement commands such as \\mathord, \\vcent etc
    """
    def __init__(self, atom_type=None, generator=None):
        self.generator = generator if generator is not None else lambda: Atom(atom_type)

    def math(self, parser, mlist):
        atom = self.generator()
        mlist.buildAtom("nucleus", atom)


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

    def branch(self, style):
        current = style.style if isinstance(style, Style) else style
        if current == MATH_STYLE.D:
            return self.display
        if current == MATH_STYLE.T:
            return self.text
        if current == MATH_STYLE.S:
            return self.script
        return self.scriptscript

    node_type = nd.NODE_TYPE.MATHNODE


class MathChoiceEndGroupCallback(MathEndGroupCallback):
    def __init__(self, parser, node):
        super().__init__(parser)
        self.node = node
        self.state = 0
        self.attr = ["display", "text", "script", "scriptscript"]

    def beginGroup(self, parser):
        t = parser.token_expand()
        pos = parser.input.position()
        if t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a \"{\"", pos)
        parser.lists.append(MList(parser))
        parser.beginGroup(pos, GROUP_TYPE.MATH_CHOICE, self)

    def endgroup(self, parser, top, mlist):
        setattr(self.node, self.attr[self.state], mlist)
        self.state += 1
        if self.state < 4:
            self.beginGroup(parser)


class MathChoice(lists.ModeDependentCommand):
    """
    the \\mathchoice command
    """
    def math(self, parser, mlist):
        choice = ChoiceNode(None, None, None, None)
        mlist.append(choice)
        callback = MathChoiceEndGroupCallback(parser, choice)
        callback.beginGroup(parser)


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
    
    def _isNull(self):
        return self.small.encode() == 0 and self.large.encode() == 0

    @staticmethod
    def _symbolIsNull(symbol):
        return symbol.encode() == 0 and symbol.fam == 0

    @staticmethod
    def _styleLevel(style):
        return style.style if isinstance(style, Style) else style

    def _fontSearchOrder(self, context, style, family):
        """
        Build delimiter search order for one family:
        - scriptscriptfont if C is scriptscript
        - scriptfont if C is script/scriptscript
        - textfont always
        """
        level = self._styleLevel(style)
        fonts = []
        seen = set()

        def add(f):
            if f is None:
                return
            key = id(f)
            if key in seen:
                return
            seen.add(key)
            fonts.append(f)

        if family < 0 or family >= 16:
            return fonts
        if level >= MATH_STYLE.SS:
            add(context.scriptscriptfont[family])
        if level >= MATH_STYLE.S:
            add(context.scriptfont[family])
        add(context.textfont[family])
        return fonts

    def _lookupChar(self, font, code):
        if font is None:
            return None, None
        if code < font.bc or code > font.ec:
            return None, None
        i = code - font.bc
        info = font.tfm.char_info[i]
        if not getattr(info, "exists", True):
            return None, None
        return info, font.charnode[i]

    def _scanSymbol(self, symbol, context, style, minimum, best):
        if self._symbolIsNull(symbol):
            return None, best
        code0 = ord(symbol.char)
        for font in self._fontSearchOrder(context, style, symbol.fam):
            code = code0
            visited = set()
            while code not in visited:
                visited.add(code)
                info, node = self._lookupChar(font, code)
                if info is None:
                    break
                total = node.height + node.depth
                if best is None or total > best["total"]:
                    best = {
                        "node": node,
                        "info": info,
                        "font": font,
                        "total": total,
                        "extensible": info.extend is not None,
                    }
                if total >= minimum or info.extend is not None:
                    return {
                        "node": node,
                        "info": info,
                        "font": font,
                        "total": total,
                        "extensible": info.extend is not None,
                    }, best
                if info.chain is None:
                    break
                code = ord(info.chain)
        return None, best

    def _boxWithItalic(self, parser, node):
        b = box.HBox(parser, None, 0)
        b.list.append(node)
        italic = getattr(node, "italic", None)
        if italic is not None and float(italic) != 0:
            b.list.append(nd.Kern(italic, automatic=True))
        b.typeset(parser, [])
        return b

    def _buildExtensible(self, parser, chosen, minimum):
        info = chosen["info"]
        ext = info.extend
        if ext is None:
            return self._boxWithItalic(parser, chosen["node"])

        def piece(code):
            if code == 0:
                return None
            _, n = self._lookupChar(chosen["font"], code)
            return n

        top = piece(ext.top)
        mid = piece(ext.mod)
        bot = piece(ext.bot)
        rep = piece(ext.rep)
        if rep is None:
            return self._boxWithItalic(parser, chosen["node"])

        def total(n):
            return n.height + n.depth if n is not None else Dimen()

        top_total = total(top)
        mid_total = total(mid)
        bot_total = total(bot)
        rep_total = total(rep)
        if float(rep_total) <= 0:
            return self._boxWithItalic(parser, chosen["node"])

        base = top_total + mid_total + bot_total
        need = minimum - base
        if mid is not None:
            unit = 2 * rep_total
            repeat = 0 if need <= 0 else max(0, ceil(float(need) / float(unit)))
        else:
            unit = rep_total
            repeat = 0 if need <= 0 else max(0, ceil(float(need) / float(unit)))
        # Ensure at least one repeatable piece is present in the stack.
        repeat = max(repeat, 1)

        parts = []
        if top is not None:
            parts.append(top)
        if mid is not None:
            for _ in range(repeat):
                parts.append(rep)
            parts.append(mid)
            for _ in range(repeat):
                parts.append(rep)
        else:
            for _ in range(repeat):
                parts.append(rep)
        if bot is not None:
            parts.append(bot)
        if not parts:
            parts.append(rep)

        v = box.VTop(parser, None, 0)
        v.list.extend(parts)
        v.typeset(parser, [])
        # TeX uses the repeatable piece width for extensible delimiters.
        v.width = rep.width
        return v

    def typeset(self, parser, total, context=None, style=None, axis=None):
        """
        return a box containing the delimiter that fits a requested total
        height+depth.
        """
        if self._isNull():
            b = box.HBox(parser, parser.state.layout["nulldelimiterspace"], None)
            b.typeset(parser, [])
            return b
        if context is None:
            context = MathTypesetContext(parser, True)
        if style is None:
            style = Style(MATH_STYLE.T)
        if axis is None:
            axis = Dimen(context.sigma(style)[21])
        minimum = Dimen(total)
        best = None
        chosen, best = self._scanSymbol(self.small, context, style, minimum, best)
        if chosen is None:
            chosen, best = self._scanSymbol(self.large, context, style, minimum, best)
        if chosen is None:
            chosen = best
        if chosen is None:
            b = box.HBox(parser, parser.state.layout["nulldelimiterspace"], None)
            b.typeset(parser, [])
            return b
        if chosen["extensible"]:
            out = self._buildExtensible(parser, chosen, minimum)
        else:
            out = self._boxWithItalic(parser, chosen["node"])
        # Center delimiter around the math axis.
        out.shifted = (out.height - out.depth) / 2 - axis
        return out


class Rad(Atom):
    """
    a node representing a radical
    @param delim: the delimiter
    @param oprand: a math field
    """
    def __init__(self, delim, oprand):
        super().__init__(ATOM_TYPE.RAD)
        self.delim = delim
        self.oprand = oprand

    def saveInfo(self):
        return {"init": {"delim": self.delim, "oprand": self.oprand}}

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
        mlist.buildAtom("oprand", Rad(delim, None))


class MathLeftEndGroupCallBack(MathEndGroupCallback):
    def __init__(self, parser, atom):
        super().__init__(parser)
        self.atom = atom

    def endgroup(self, parser, top, mlist):
        self.atom.nucleus = mlist
        self.atom.right = readDelimiter(parser)

class Left(lists.ModeDependentCommand):
    """
    the \\left command
    """
    def math(self, parser, mlist):
        delim = readDelimiter(parser)
        atom = Atom(ATOM_TYPE.ORD)
        atom.left = delim
        mlist.append(atom)
        parser.lists.append(MList(parser))
        parser.beginGroup(parser.input.position(), GROUP_TYPE.MATH_LEFT, MathLeftEndGroupCallBack(parser, atom))


class Right(lists.ModeDependentCommand):
    """
    the \\right command
    """
    def math(self, parser, mlist):
        parser.endGroup(parser.input.position(), GROUP_TYPE.MATH_LEFT)


class Over(Atom):
    """
    a node representing a general fraction
    @param num: the numerator
    @param den: the denominator
    @param bar: whether it has a bar
    @param thickness: the thickness of the bar
    """
    def __init__(self, num, den, bar, thickness):
        super().__init__(ATOM_TYPE.INNER)
        self.nucleus = (num, den, bar, thickness)

    def saveInfo(self):
        return {"init": {"num": self.nucleus[0], "den": self.nucleus[1], "bar": self.nucleus[2], "thickness": self.nucleus[3]}}
    
    def rule15(self, context: MathTypesetContext, style: Style):
        """
        Appendix G, Rule 15 preamble for generalized fractions.

        Returns:
        - numerator mlist
        - denominator mlist
        - bar thickness theta
        - left delimiter (or None)
        - right delimiter (or None)
        """
        num, den, bar, thickness = self.nucleus
        if thickness is None:
            theta = Dimen(context.xi(style)[7]) if bar else Dimen()
        else:
            theta = Dimen(thickness)
        left, right = getattr(self, "_rule15_delims", (self.left, self.right))
        return num, den, theta, left, right

    def rule15b(self, context: MathTypesetContext, style: Style, theta: Dimen):
        """
        Appendix G, Rule 15b: base numerator/denominator shifts.
        """
        sigma = context.sigma(style)
        if style.style > MATH_STYLE.T:
            # C > T
            u = Dimen(sigma[7])   # sigma8
            v = Dimen(sigma[10])  # sigma11
        else:
            # C <= T
            u = Dimen(sigma[8] if float(theta) != 0 else sigma[9])  # sigma9/sigma10
            v = Dimen(sigma[11])  # sigma12
        return u, v

    def rule15c(self, x, z, context: MathTypesetContext, style: Style, u: Dimen, v: Dimen):
        """
        Appendix G, Rule 15c: atop-style clearance adjustment (theta = 0).

        Returns adjusted (u, v, clearance_kern).
        """
        xi8 = Dimen(context.xi(style)[7])
        phi = (7 * xi8) if style.style > MATH_STYLE.T else (3 * xi8)
        psi = (u - x.depth) - (z.height - v)
        if psi < phi:
            delta = (phi - psi) / 2
            u = u + delta
            v = v + delta
            psi = (u - x.depth) - (z.height - v)
        return u, v, psi

    def rule15d(self, x, z, context: MathTypesetContext, style: Style, theta: Dimen, u: Dimen, v: Dimen):
        """
        Appendix G, Rule 15d: over-style bar placement/clearance adjustment.

        Returns adjusted (u, v, kern_above_rule, kern_below_rule).
        """
        phi = (3 * theta) if style.style > MATH_STYLE.T else theta
        a = Dimen(context.sigma(style)[21])  # axis height, sigma22
        half_theta = theta / 2
        k1 = (u - x.depth) - (a + half_theta)
        if k1 < phi:
            u = u + (phi - k1)
            k1 = (u - x.depth) - (a + half_theta)
        k2 = (a - half_theta) - (z.height - v)
        if k2 < phi:
            v = v + (phi - k2)
            k2 = (a - half_theta) - (z.height - v)
        return u, v, k1, k2

    def typesetNucleus(self, parser, packed, context: MathTypesetContext, style: Style):
        # TeXbook Appendix G, Rule 15(a-e)
        num, den, theta, left, right = self.rule15(context, style)
        x = box.HBox(parser, None, 0)
        z = box.HBox(parser, None, 0)
        num.typesetNodes(parser, x.list, context, style.numerator())
        den.typesetNodes(parser, z.list, context, style.denominator())
        x.typeset(parser, [])
        z.typeset(parser, [])
        target = x.width if x.width >= z.width else z.width
        x = Atom.rebox(parser, x, target)
        z = Atom.rebox(parser, z, target)
        # Fraction internals are stacked explicitly by Rule 15; disable
        # normal vertical interline glue between x and z.
        x.typeset_context = VNodeContext(parser.state.layout, init_prevdepth)
        z.typeset_context = VNodeContext(parser.state.layout, init_prevdepth)
        u, v = self.rule15b(context, style, theta)
        if float(theta) == 0:
            # Rule 15c (\atop): enforce minimum clearance with adjusted shifts.
            u, v, k = self.rule15c(x, z, context, style, u, v)
            out = box.VBox(parser, x.height + u, 0)
            out.list.clear()
            out.list.append(x)
            out.list.append(nd.Kern(k))
            out.list.append(z)
            out.typeset(parser, [])
            out.depth = z.depth + v
        else:
            # Rule 15d (\over): enforce clearances from numerator/denominator to bar.
            u, v, k1, k2 = self.rule15d(x, z, context, style, theta, u, v)
            out = box.VBox(parser, x.height + u, 0)
            out.list.clear()
            out.list.append(x)
            out.list.append(nd.Kern(k1))
            out.list.append(nd.Rule(target, theta, 0))
            out.list.append(nd.Kern(k2))
            out.list.append(z)
            out.typeset(parser, [])
            out.depth = z.depth + v
        # Rule 15e: optional delimiters around the fraction vbox.
        if left is None and right is None:
            packed.append(out)
            return
        min_total = Dimen(context.sigma(style)[19] if style.style > MATH_STYLE.T else context.sigma(style)[20])
        total = out.height + out.depth
        if total < min_total:
            total = min_total
        axis = Dimen(context.sigma(style)[21])
        left_box = left.typeset(parser, total, context, style, axis) if left is not None else box.HBox(parser, 0, None)
        if left is None:
            left_box.typeset(parser, [])
        right_box = right.typeset(parser, total, context, style, axis) if right is not None else box.HBox(parser, 0, None)
        if right is None:
            right_box.typeset(parser, [])
        packed.append(left_box)
        packed.append(out)
        packed.append(right_box)
        return

    def typeset(self, parser, packed, context, style):
        # Rule 15e integrates optional delimiters into the nucleus, so suppress
        # Atom.typeset's generic left/right wrapper handling.
        self._rule15_delims = (self.left, self.right)
        self.left = None
        self.right = None
        try:
            # Generalized fractions are treated as Inner atoms for spacing.
            super().typeset(parser, packed, context, style, atom_type=ATOM_TYPE.INNER)
        finally:
            self.left, self.right = self._rule15_delims
            del self._rule15_delims

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
        if getattr(mlist, "is_denominator", False):
            raise ValueError("double fraction", parser.input.position())
        if self.delim:
            left = readDelimiter(parser)
            right = readDelimiter(parser)
        thickness = parser.readDimen() if self.thickness else None
        # replace the current MList with a new one
        numerator = MList(mlist.parser, mlist.inner)
        numerator[:] = mlist
        numerator.inner = True
        mlist.clear()
        # mlist becomes the numerator
        denominator = MList(mlist.parser, mlist.inner)
        fraction = Over(numerator, denominator, self.bar, thickness)
        if self.delim:
            fraction.left = left
            fraction.right = right
        if self.thickness:
            fraction.thickness = thickness
        mlist.append(fraction)
        parser.lists.append(denominator)
        denominator.is_denominator = True


class Accent(Atom):
    """
    a node representing an accent
    @param accent: the accent
    @param base: a math field
    """
    def __init__(self, accent, base):
        super().__init__(ATOM_TYPE.ACC)
        self.accent = accent
        self.base = base

    def saveInfo(self):
        return {"init": {"accent": self.accent, "base": self.base}}
    
    node_type = nd.NODE_TYPE.MATHNODE


class MathAccent(lists.ModeDependentCommand):
    """
    the \\accent command
    """
    def math(self, parser, mlist):
        accent = MathSymbol(parser.readInteger(), parser.state.parameters["fam"])
        mlist.buildAtom("base", Accent(accent, None))


class Eqno(lists.ModeDependentCommand):
    """
    the \\eqno command
    @param left: whether the equation number is on the left
    """
    def __init__(self, left: bool):
        self.left = left

    def math(self, parser, mlist):
        def callback():
            assert parser.lists.pop() is getattr(parser.lists[-1], "eqno", [None, None])[0]
            parser.input.unread(MathShiftToken("$", CATCODE.MATH_SHIFT))
        # we must be at the bottom of the math lists
        enclosing = parser.lists[-2]
        if enclosing.type == lists.LISTTYPE.MATH:
            raise ValueError("misplaced equation number", parser.input.position())
        if mlist.inner:
            raise ValueError("only display math can have an equation number", parser.input.position())
        # We start a new group, parsing the equation number, then we pop it off during the 
        # mathShift function before ending the math mode.
        eqno = MList(parser)
        parser.lists.append(eqno)
        mlist.eqno = (eqno, self.left)
        parser.beginGroup(parser.input.position(), GROUP_TYPE.MATH_SHIFT, callback)


class VCent(Box):
    """
    a vcent box
    """
    def __init__(self, box):
        super().__init__(box)
        self.atom_type = ATOM_TYPE.VCENT
    
    def saveInfo(self):
        return super().saveInfo() | {"init": {"box": self.nucleus}}

    def typeset(self, parser, packed, context, style):
        super().typeset(parser, packed, context, style, atom_type=ATOM_TYPE.ORD)

    def typesetNucleus(self, parser, packed, context: MathTypesetContext, style):
        box = self.nucleus.copy()
        v = box.height + box.depth
        a = context.sigma(style)[21]
        box.height = Dimen(float(v)/2 + a)
        box.depth = Dimen(float(v)/2 - a)
        packed.append(box)


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


class Line(Atom):
    def __init__(self, over):
        atom_type = ATOM_TYPE.OVER if over else ATOM_TYPE.UNDER
        super().__init__(atom_type)

    def typesetNucleus(self, parser, packed, context: MathTypesetContext, style: Style):
        # Texbook Append G, rule 9: If the current item is an Over atom (from \overline), set box x to the nucleus
        # in style C′. Then replace the nucleus by a vbox containing kern θ, hrule of height θ,
        # kern 3θ, and box x, from top to bottom, where θ= ξ8 is the default rule thickness.
        # (This puts a rule over the nucleus, with 3θ clearance, and with θ units of extra white
        # space assumed to be present above the rule.)
        # Texbook Append G, rule 10: If the current item is an Under atom (from \underline), set box x to the
        # nucleus in style C. Then replace the nucleus by a vtop made from box x, kern 3θ, and
        # hrule of height θ, where θ= ξ8 is the default rule thickness; and add θ to the depth of
        # the box. (This puts a rule under the nucleus, with 3θ clearance, and with θ units of
        # extra white space assumed to be present below the rule.)
        x = box.HBox(parser, None, 0)
        self.nucleus.typeset(parser, x.list, context, Style(style.style, cramped=True))
        if len(x.list) == 1:
            x = x.list[0]
        else:
            x.typeset(parser, [])
        theta = Dimen(context.xi(style)[7])
        vbox = box.VBox(parser, None, 0)
        kern1 = nd.Kern(theta)
        rule = nd.Rule(NEG_MAX_DIMEN, theta, 0)
        kern2 = nd.Kern(3*theta)
        if self.atom_type == ATOM_TYPE.OVER:
            vbox.list[:] = [kern1, rule, kern2, x]
        else:
            vbox.list[:] = [x, kern2, rule, kern1]
        vbox.typeset(parser, [])
        packed.append(vbox)

    
    def typeset(self, parser, packed, context, style):
        super().typeset(parser, packed, context, style, atom_type=ATOM_TYPE.ORD)


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
        "overline": MathAtom(generator = lambda: Line(True)),
        "underline": MathAtom(generator = lambda: Line(False)),
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
