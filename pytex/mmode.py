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
from pytex.accessor import Accessor, VALUE_TYPE, AttrTarget
from pytex.define import EquitableAccessor
from pytex.lexer import TokenListScanner
from pytex.glue import Glue, Stretchness
from pytex.dimen import Dimen, NEG_MAX_DIMEN, DimenCommand
from pytex import box
from pytex.hmode import Ligature
from pytex.ligature import ligature_step, run_ligature_program
from pytex.serialization import Serializable
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
        return {"style": self.style.value, "cramped": self.cramped}, None
    
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


def mathfont(parser, style, family):
    textfont = parser.textfont
    scriptfont = parser.scriptfont
    scriptscriptfont = parser.scriptscriptfont
    if style.style < MATH_STYLE.S:
        return textfont[family]
    if style.style == MATH_STYLE.S:
        return scriptfont[family]
    return scriptscriptfont[family]


def mathsigma(parser, style: Style):
    return mathfont(parser, style, 2).param


def mathxi(parser, style: Style):
    return mathfont(parser, style, 3).param


def mathmuskips(parser):
    layout = parser.layout
    return [layout[x] for x in ["thinmuskip", "medmuskip", "thickmuskip"]]


def mathlayout(parser, name):
    return parser.layout[name]


class AtomState:
    def __init__(self, parser, prev_atom_type=None, atom_type=None, text_symbol=False):
        self.parser = parser
        self.prev_atom_type = prev_atom_type
        self.atom_type = atom_type
        self.text_symbol = text_symbol


def _coerceAtomState(parser, context):
    if isinstance(context, AtomState):
        return context
    return AtomState(
        parser,
        prev_atom_type=getattr(context, "prev_atom_type", None),
        atom_type=getattr(context, "atom_type", None),
        text_symbol=getattr(context, "text_symbol", False),
    )


class _AtomWrapper:
    """
    Temporary math-atom record produced in MList.typesetNodes pass 1.

    It proxies to the wrapped atom for regular atom fields/methods while
    carrying pass-1 metadata:
    - node_type: normalized effective atom class for spacing
    - style: style snapshot for pass-2 emission
    - text_symbol: Rule 14 text-symbol mark for Rule 17 italic handling
    """
    def __init__(self, atom, node_type, style, text_symbol=False):
        self._atom = atom
        self.node_type = node_type
        self.style = style
        self.text_symbol = text_symbol

    @property
    def atom(self):
        return self._atom

    def __getattr__(self, name):
        return getattr(self._atom, name)


def _drop_redundant_wrapper(box_node, allow_char):
    """
    Drop one outer hbox/vbox layer if it only wraps a single box child.

    This mirrors TeX's "don't keep useless wrappers" behavior while allowing
    callers to retain wrappers around char/ligature nodes when needed.
    """
    if box_node.node_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
        return box_node
    if len(box_node.list) != 1:
        return box_node
    child = box_node.list[0]
    if not isinstance(child, nd.Box):
        return box_node
    if (not allow_char) and child.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
        return box_node
    return child


class MList(lists.List):
    """
    a math list
    @param parser: the parser that created the list
    @
    """
    def __init__(self, parser, list=None, inner=True):
        super().__init__(parser, [] if list is None else list, inner=inner)
        self.building_atom = None
        self.type = lists.LISTTYPE.MATH
        self.isalign = False
    
    node_type = nd.NODE_TYPE.MATH

    list_type_name = "MLIST"

    def clear(self):
        super().clear()
        self.building_atom = None

    def buildAtom(self, field, atom=None):
        if atom is None:
            atom = self[-1] if len(self) > 0 else None
            if not isinstance(atom, Atom):
                atom = Atom(ATOM_TYPE.ORD)
                atom.nucleus = Subformula()
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

    @staticmethod
    def _normalizeNode(node):
        if isinstance(node, MList):
            subformula = Subformula()
            subformula.list = node.list
            node = subformula
        if isinstance(node, box.Box):
            return Box(node)
        if isinstance(node, Subformula):
            atom = Atom(ATOM_TYPE.ORD)
            atom.nucleus = node
            return atom
        if isinstance(node, MathSymbol):
            atom = Op() if node.type == ATOM_TYPE.OP else Atom(node.type)
            atom.nucleus = node
            return atom
        return node

    def append(self, node):
        if self.isalign:
            raise ValueError("improper \\halign inside math mode", self.parser.input.position())
        if self.building_atom is not None:
            atom, field = self.building_atom
            if isinstance(node, MList):
                subformula = Subformula()
                subformula.list = node.list
                node = subformula
            setattr(atom, field, node)
            self.building_atom = None
            return
        node = self._normalizeNode(node)
        super().append(node)


class MathListHolder:
    def __init__(self, list=None, paragraph_math=False):
        self.list = [] if list is None else list
        self.paragraph_math = paragraph_math
    
    node_type = None # not a standard node. Needs to be expanded into boxes

    def saveInfo(self):
        return {}, {"list": self.list}

    def _pass1Collect(self, parser, context, style):
        """
        Pass 1 of math typesetting.

        This pass follows Appendix G Rules 1-4 and builds a normalized temporary
        stream. Atom wrappers are emitted with an effective node_type field that
        can be adjusted without mutating original parse nodes.
        """
        if not isinstance(style, Style):
            style = Style(style)
        pass_through = {
            nd.NODE_TYPE.RULE,
            nd.NODE_TYPE.DISC,
            nd.NODE_TYPE.PENALTY,
            nd.NODE_TYPE.WHATSIT,
            nd.NODE_TYPE.ADJUST,
            nd.NODE_TYPE.MARK,
            nd.NODE_TYPE.INS,
        }
        collected = []
        current = iter(self.list)
        stack = []
        while current is not None:
            node = next(current, None)
            if node is None:
                if not stack:
                    break
                current, style = stack.pop()
                continue
            if node.node_type in pass_through:
                # Rule 1 pass-through nodes.
                collected.append(node)
                continue
            if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
                # Rule 2.
                if getattr(node, "nonscript", False):
                    # \nonscript marker itself disappears after processing.
                    if style.style <= MATH_STYLE.S:
                        nxt = next(current, None)
                        while nxt is None and stack:
                            current, style = stack.pop()
                            nxt = next(current, None)
                        if nxt is None:
                            # we are at the end of the list
                            break
                        if nxt.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
                            # skip the next glue or kern
                            continue
                        # no, the next node is not a glue or kern, handle that node next
                        node = nxt
                    else:
                        # if we are in text or display mode, do nothing
                        continue
                elif getattr(node, "mu", False):
                    expanded = []
                    node.typeset(parser, expanded, context, style)
                    for n in expanded:
                        if n is node:
                            continue
                        if getattr(n, "source", None) is None:
                            n.source = node
                    collected.extend(expanded)
                    continue
                else:
                    collected.append(node)
                    continue
            # Rule 3: style changes update C and disappear.
            if isinstance(node, StyleNode):
                style = node.style
                continue
            # Rule 4: choose branch, then continue from first node of that branch.
            if isinstance(node, ChoiceNode):
                branch = node.branch(style)
                if branch is not None:
                    stack.append((current, style))
                    current = iter(branch)
                continue
            if isinstance(node, Atom):
                s = Style(style.style, style.cramped)
                collected.append(_AtomWrapper(node, node.atom_type, s))
                continue
            typeset = node.typeset
            if typeset is None:
                collected.append(node)
                continue
            expanded = []
            typeset(parser, expanded, context, style)
            if not expanded:
                collected.append(node)
                continue
            for n in expanded:
                if n is node:
                    continue
                if getattr(n, "source", None) is None:
                    n.source = node
            collected.extend(expanded)
        return collected

    def _pass1AdjustAtoms(self, parser, context, collected):
        """
        Pass 1 atom adjustments.

        This applies Rule 5/6 and Rule 14 in a single forward scan:
        - Rule 5 may convert current Bin to Ord, then current continues to Rule 14
        - Rule 6 may retroactively convert previous Bin to Ord, but that previous
          item is not revisited for Rule 14
        - Rule 14 then handles kern/ligature for the current item when applicable
        Finally, trailing Bin becomes Ord.
        """
        prev_types_for_rule5 = (ATOM_TYPE.BIN, ATOM_TYPE.OP, ATOM_TYPE.REL, ATOM_TYPE.OPEN, ATOM_TYPE.PUNCT)
        rule6_types = (ATOM_TYPE.REL, ATOM_TYPE.CLOSE, ATOM_TYPE.PUNCT)

        def previous_atom(index):
            j = index - 1
            while j >= 0:
                item = collected[j]
                if isinstance(item, _AtomWrapper):
                    return item
                j -= 1
            return None

        i = 0
        prev = None
        while i < len(collected):
            cur = collected[i]
            if not isinstance(cur, _AtomWrapper):
                i += 1
                continue
            # Appendix G rules 8-13 classes are emitted as Ord for spacing.
            if cur.node_type in (ATOM_TYPE.VCENT, ATOM_TYPE.OVER, ATOM_TYPE.UNDER, ATOM_TYPE.ACC, ATOM_TYPE.RAD):
                cur.node_type = ATOM_TYPE.ORD
            try_rule14 = False
            if cur.node_type == ATOM_TYPE.BIN:
                if prev is None or prev.node_type in prev_types_for_rule5:
                    # Rule 5.
                    cur.node_type = ATOM_TYPE.ORD
                    try_rule14 = True
            else:
                if cur.node_type in rule6_types and prev is not None and prev.node_type == ATOM_TYPE.BIN:
                    # Rule 6.
                    prev.node_type = ATOM_TYPE.ORD
                try_rule14 = cur.node_type == ATOM_TYPE.ORD
            if try_rule14 and i < len(collected) - 1:
                nxt = collected[i + 1]
                if isinstance(nxt, _AtomWrapper) and cur.node_type == ATOM_TYPE.ORD and nxt.node_type in (
                    ATOM_TYPE.ORD,
                    ATOM_TYPE.OP,
                    ATOM_TYPE.BIN,
                    ATOM_TYPE.REL,
                    ATOM_TYPE.OPEN,
                    ATOM_TYPE.CLOSE,
                    ATOM_TYPE.PUNCT,
                ):
                    if getattr(cur, "sub", None) is None and getattr(cur, "sup", None) is None:
                        n1 = getattr(cur, "nucleus", None)
                        n2 = getattr(nxt, "nucleus", None)
                        if isinstance(n1, MathSymbol) and isinstance(n2, MathSymbol) and n1.fam == n2.fam:
                            # Rule 14: current symbol is marked as a text symbol.
                            cur.text_symbol = True
                            font = mathfont(parser, cur.style, n1.fam)
                            c1 = font[n1.char]
                            c2 = font[n2.char]
                            working = run_ligature_program(
                                [c1, c2],
                                make_ligature=lambda insert_char, replaced, step, base, after: Ligature(insert_char, replaced),
                                make_kern=lambda step, base, after: nd.Kern(step.kern * base.font.at, automatic=True),
                                source_nodes=lambda n: list(n.source) if isinstance(n, Ligature) else [n],
                            )
                            if len(working) == 1 and isinstance(working[0], Ligature):
                                lig = Atom(ATOM_TYPE.ORD)
                                lig.nucleus = MathSymbol(
                                    (ATOM_TYPE.ORD.value << 12) | (n1.fam << 8) | ord(working[0].char),
                                    -1,
                                )
                                lig.source = [cur.atom, nxt.atom]
                                collected[i:i + 2] = [
                                    _AtomWrapper(
                                        lig,
                                        ATOM_TYPE.ORD,
                                        Style(cur.style.style, cur.style.cramped),
                                        text_symbol=True,
                                    )
                                ]
                                # Reconsider with preceding symbol for recursive ligatures.
                                i = max(i - 1, 0)
                                prev = previous_atom(i)
                                continue
                            if len(working) == 3 and isinstance(working[1], nd.Kern):
                                k = nd.Kern(working[1].kern, automatic=True)
                                k.source = [cur.atom, nxt.atom]
                                collected.insert(i + 1, k)
                                prev = cur
                                i += 2
                                continue
            prev = cur
            i += 1
        # Appendix G: trailing Bin becomes Ord.
        if prev is not None and prev.node_type == ATOM_TYPE.BIN:
            prev.node_type = ATOM_TYPE.ORD

    def _rule21Penalty(self, parser, paragraph_math, current_item, next_item):
        """
        Appendix G Rule 21 inter-atom penalties.
        """
        if not paragraph_math:
            return None
        if next_item is None:
            return None
        if not isinstance(current_item, _AtomWrapper):
            return None
        atom_type = current_item.node_type
        if atom_type not in (ATOM_TYPE.BIN, ATOM_TYPE.REL):
            return None
        if isinstance(next_item, nd.Penalty):
            return None
        if atom_type == ATOM_TYPE.REL and isinstance(next_item, _AtomWrapper) and next_item.node_type == ATOM_TYPE.REL:
            return None
        layout = parser.layout
        penalty = layout["binoppenalty"] if atom_type == ATOM_TYPE.BIN else layout["relpenalty"]
        if penalty >= 10000:
            return None
        p = nd.Penalty(penalty)
        p.source = current_item.atom
        return p

    def _pass2Emit(self, parser, packed, context, collected):
        """
        Pass 2 of math typesetting.

        Emit normalized wrappers/nodes into packed output. Spacing decisions use
        wrapper.node_type, i.e., the effective class computed in pass 1.
        """
        if packed is None:
            packed = []
        previous = {}
        for name in ("prev_atom_type", "atom_type", "text_symbol"):
            if hasattr(context, name):
                previous[name] = (True, getattr(context, name))
            else:
                previous[name] = (False, None)
        prev_atom_type = None
        items = iter(collected)
        item = next(items, None)
        try:
            while item is not None:
                nxt = next(items, None)
                if isinstance(item, _AtomWrapper):
                    context.prev_atom_type = prev_atom_type
                    context.atom_type = item.node_type
                    context.text_symbol = item.text_symbol
                    item.typeset(parser, packed, context, item.style)
                    prev_atom_type = context.prev_atom_type
                else:
                    packed.append(item)
                p = self._rule21Penalty(parser, self.paragraph_math, item, nxt)
                if p is not None:
                    packed.append(p)
                item = nxt
        finally:
            for name, (had_attr, value) in previous.items():
                if had_attr:
                    setattr(context, name, value)
                elif hasattr(context, name):
                    delattr(context, name)
        return packed

    def typesetNodes(self, parser, packed, context, style):
        collected = self._pass1Collect(parser, context, style)
        self._pass1AdjustAtoms(parser, context, collected)
        atom_state = _coerceAtomState(parser, context)
        return self._pass2Emit(parser, packed, atom_state, collected)

    def typeset(self, parser, packed, context, style):
        # Typeset into an hbox first; if it only wraps one box-like node,
        # drop that outer wrapper (TeX optimization for translated sub-mlists).
        hbox = box.HBox(parser, None, None)
        self.typesetNodes(parser, hbox.list, context, style)
        packed.append(_drop_redundant_wrapper(hbox.typeset(parser), allow_char=True))


class Subformula(MathListHolder):
    def __init__(self):
        super().__init__(list=[], paragraph_math=False)
        self.left_delim = None
        self.right_delim = None

    def saveInfo(self):
        return {}, {
            "list": self.list,
            "left_delim": self.left_delim,
            "right_delim": self.right_delim,
        }

    def typeset(self, parser, packed, context, style):
        temp = []
        super().typeset(parser, temp, context, style)
        if len(temp) == 1:
            packed.append(temp[0])
        else:
            hbox = box.HBox(parser, None, 0)
            hbox.list = temp
            hbox.typeset(parser, packed)


class InlineMathNode(MathListHolder):
    pretypeset_in_hlist = True

    def __init__(self, parser=None, nodes=None):
        super().__init__(list=nodes, paragraph_math=True)
        self.parser = parser
        self.inner = True
        self._typeset_cache = None

    node_type = nd.NODE_TYPE.MATH

    def pretypeset(self, parser):
        self.parser = parser
        if self._typeset_cache is not None:
            return
        cache = []
        # Appendix G Rule 22: inline math translation is enclosed by
        # math-on/math-off nodes, each carrying the current \mathsurround.
        math_shift = nd.MathShift(True)
        math_shift.source = self
        math_shift.kern = Dimen(parser.layout["mathsurround"])
        cache.append(math_shift)
        self.typesetNodes(parser, cache, self, Style(MATH_STYLE.T))
        math_shift = nd.MathShift(False)
        math_shift.kern = Dimen(parser.layout["mathsurround"])
        cache.append(math_shift)
        self._typeset_cache = cache

    def typeset(self, parser, packed):
        self.pretypeset(parser)
        packed.extend(self._typeset_cache)


class DisplayMathNode(nd.Node, MathListHolder):
    typeset_to_vlist = True
    
    node_type = nd.NODE_TYPE.MATH

    def __init__(self):
        super().__init__(list=[], paragraph_math=True)
        self.inner = False
        # the equation number. If there is one, this holds a tuple (MList, bool)
        # where the MList points to the equation number material, and the bool indicates
        # whether the equation number is on the left
        self.eqno = None

    def saveInfo(self):
        init, extra = super().saveInfo()
        return init, extra | {"eqno": self.eqno}

    def typeset(self, parser, packed):
        cache = []
        volatile = parser.volatile
        displaywidth = volatile["displaywidth"]
        displayindent = volatile["displayindent"]
        predisplaysize = volatile["predisplaysize"]
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
            eqno.typesetNodes(parser, a.list, self, Style(MATH_STYLE.T))
            a = a.typeset(parser)
            e = a.width
            q = e + mathfont(parser, Style(MATH_STYLE.T), 2).param[5] # quad (fontdimen6)
        else:
            q = Dimen()
            e = Dimen()
            eqno = None
            left = None
        h = self.typesetNodes(parser, None, self, Style(MATH_STYLE.D))
        b = box.HBox(parser, None, 0)
        b.list[:] = h
        b = b.typeset(parser)
        w0 = b.width
        z = displaywidth
        s = displayindent
        p = predisplaysize
        if w0 + q > z:
            # look at all the stretchness of a
            if e != 0:
                b = box.HBox(parser, to=z-q, spread=None)
                b.list[:] = h
                b = b.typeset(parser)
                ratio = b.glue_ratio
                if isinstance(ratio, tuple):
                    sign, num, den = ratio
                    over_shrink_ratio = int(sign) < 0 and int(num) > int(den)
                else:
                    over_shrink_ratio = ratio < -1
                not_enough_shrink = (
                    b.spread < 0
                    and (
                        int(b.natural.shrink.factor) == 0
                        or over_shrink_ratio
                    )
                )
                if not_enough_shrink:
                    e = Dimen()
            if e == 0:
                b = box.HBox(parser, to=min(w0, z), spread=None)
                b.list[:] = h
                b = b.typeset(parser)
        # TEX tries now to center the display without regard to the
        # equation number. But if such centering would make it too close to that number
        # (where “too close” means that the space between them is less than the width e), the
        # equation is either centered in the remaining space or placed as far from the equation
        # number as possible. The latter alternative is chosen only if the first item on list h is
        # glue, since T EX assumes that such glue was placed there in order to control the spacing
        # precisely. But let’s state the rules more formally: Let w be the width of box b. TEX
        # computes a displacement d, to be used later when positioning box b, by first setting
        # d=1/2 (z−w). If e>0 and if d<2e, then d is reset to 1/2 (z−w−e) or to zero, where
        # zero is chosen if list h begins with a glue item
        w = b.width
        d = (z - w) / 2
        if e > 0 and d < 2*e:
            begins_with_glue = len(h) > 0 and h[0].node_type == nd.NODE_TYPE.GLUE
            d = Dimen() if begins_with_glue else (z - w - e) / 2
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
        cache.append(nd.Penalty(parser.layout["predisplaypenalty"]))
        if d + s <= p or left is True:
            ga = nd.Glue(parser.layout["abovedisplayskip"], "\\abovedisplayskip")
            gb = nd.Glue(parser.layout["belowdisplayskip"], "\\belowdisplayskip")
        else:
            ga = nd.Glue(parser.layout["abovedisplayshortskip"], "\\abovedisplayshortskip")
            gb = nd.Glue(parser.layout["belowdisplayshortskip"], "\\belowdisplayshortskip")
        if e == 0 and left is True:
            a.shifted = Dimen(s)
            cache.append(a)
            cache.append(nd.Penalty(10000))
        else:
            cache.append(ga)
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
            b = b.typeset(parser)
        b.shifted = Dimen(s+d)
        b.display = True
        cache.append(b)
        # The final task is to append the glue or the equation number
        # that follows the display. If there was an \eqno and if e = 0, an infinite
        # penalty is placed on the vertical list, followed by the equation number box a shifted
        # right by s+ z minus its width, followed by a penalty item whose cost is the value
        # of \postdisplaypenalty. Otherwise a penalty item for the \postdisplaypenalty is
        # appended first, followed by a glue item for gb as specified above.
        if e == 0 and left is False:
            cache.append(nd.Penalty(10000))
            a.shifted = Dimen(s + z) - a.width
            a.interline_glue = nd.Glue(None, None)
            cache.append(a)
            cache.append(nd.Penalty(parser.layout["postdisplaypenalty"]))
        else:
            cache.append(nd.Penalty(parser.layout["postdisplaypenalty"]))
            cache.append(gb)
        for n in cache:
            n.source = self
        packed.extend(cache)


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
        return {"style": self.style}, None

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
        return {"atom_type": self.atom_type},  {
                "sub": self.sub, 
                "sup": self.sup,
                "left": self.left,
                "right": self.right
            }

    node_type = nd.NODE_TYPE.MATHNODE

    def __repr__(self):
        sub = f"_{self.sub}" if self.sub is not None else ""
        sup = f"^{self.sup}" if self.sup is not None else ""
        left = f"{self.left}" if self.left is not None else ""
        right = f"{self.right}" if self.right is not None else ""
        return f"{left}{self.__class__.__name__}({self.nucleus}{sub}{sup}){right}"

    def _boundaryInfo(self):
        nucleus = getattr(self, "nucleus", None)
        if self.atom_type != ATOM_TYPE.INNER or not isinstance(nucleus, Subformula):
            return None
        if nucleus.left_delim is None or nucleus.right_delim is None:
            return None
        return nucleus.left_delim, nucleus.right_delim, nucleus.list

    def _typesetBoundaryInner(self, parser, context, style, left_delim, right_delim, body_items):
        body_holder = MathListHolder(body_items, paragraph_math=False)
        body_nodes = []
        body_context = AtomState(parser)
        body_holder.typesetNodes(parser, body_nodes, body_context, style)
        body = box.HBox(parser, None, None)
        body.list[:] = body_nodes
        body = body.typeset(parser)
        sigma = mathsigma(parser, style)
        axis = Dimen(sigma[21])
        delta_up = body.height - axis
        delta_down = body.depth + axis
        delta = delta_up if delta_up >= delta_down else delta_down
        f = mathlayout(parser, "delimiterfactor")
        l = mathlayout(parser, "delimitershortfall")
        rule19 = Dimen(integer=(int(delta) // 500) * f)
        short = 2 * delta - l
        total = rule19 if rule19 >= short else short
        left_box = left_delim.typeset(parser, total, context, style, axis)
        right_box = right_delim.typeset(parser, total, context, style, axis)
        out = box.HBox(parser, None, None)
        out.list[:] = [left_box, body, right_box]
        out = out.typeset(parser)
        out.source = self
        return out
    
    def typeset(self, parser, packed, context=None, style=None):
        atom_type = self.atom_type if context is None else getattr(context, "atom_type", self.atom_type)
        if context is None:
            # Fallback for generic list/box expansion paths.
            packed.append(self)
            return
        # Rule 5/6/14 class normalization is handled in MList.typesetNodes pass 1.
        # At this stage we only emit with the supplied effective atom_type.
        context.atom_type = atom_type
        boundary_info = self._boundaryInfo()
        if boundary_info is not None:
            self.typsetSpace(parser, packed, context, style, atom_type)
            left_delim, right_delim, body_items = boundary_info
            packed.append(self._typesetBoundaryInner(parser, context, style, left_delim, right_delim, body_items))
            context.prev_atom_type = atom_type
            return
        b = self.assemble(parser, context, style)
        sigma = mathsigma(parser, style)
        axis = Dimen(sigma[21])
        total = b.height + b.depth
        if self.left is not None and self.right is not None:
            # TeXbook Appendix G, Rule 19: size boundary delimiters from
            # formula extent around the axis, not simply h+d.
            delta_up = b.height - axis
            delta_down = b.depth + axis
            delta = delta_up if delta_up >= delta_down else delta_down
            f = mathlayout(parser, "delimiterfactor")
            l = mathlayout(parser, "delimitershortfall")
            rule19 = Dimen(integer=(int(delta) // 500) * f)
            short = 2 * delta - l
            total = rule19 if rule19 >= short else short
        if self.left:
            left = self.left.typeset(parser, total, context, style, axis)
            self.typsetSpace(parser, packed, context, style, ATOM_TYPE.OPEN)
            packed.append(left)
            context.prev_atom_type = ATOM_TYPE.OPEN
            self.typsetSpace(parser, packed, context, style, atom_type)
        else:
            self.typsetSpace(parser, packed, context, style, atom_type)
        if self.left is not None or self.right is not None:
            if getattr(b, "source", None) is None:
                b.source = self
            packed.append(b)
        else:
            for n in b.list:
                # packed needs to handle ligatures automatically. So we cannot use extend, but to add them invididually
                packed.append(n)
        context.prev_atom_type = atom_type
        if self.right:
            right = self.right.typeset(parser, total, context, style, axis)
            self.typsetSpace(parser, packed, context, style, ATOM_TYPE.CLOSE)
            packed.append(right)
            context.prev_atom_type = ATOM_TYPE.CLOSE

    """
    An array holding the spaces between the previous atom (rows) and the current item (columns)
    0 means no space, 1 or -1 means a thinmuskip, 2 or -2 means a medmuskip, and 3 or -3 means 
    a thickmuskip. None means the situation is impossible, and negative numbers mean that the
    space is not put in script or scriptscript styles (like prpeceeded by a \\nonscript)
    """
    spaces = [
        [0, 1, -2, -3, 0, 0, 0, -1],
        [1, 1, None, -3, 0, 0, 0, -1],
        [-2, -2, None, None, -2, None, None, -2],
        [-3, -3, None, 0, -3, 0, 0, -3],
        [0, 0, None, 0, 0, 0, 0, 0],
        [0, 1, -2, -3, 0, 0, 0, -1],
        [-1, -1, None, -1, -1, -1, -1, -1],
        [-1, 1, -2, -3, -1, 0, -1, -1]
    ]

    def typsetSpace(self, parser, packed, context, style, atom_type):
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
        packed.append(
            nd.Glue(
                muglue(parser, style, mathmuskips(parser)[space - 1]),
                ["\\thinmuskip", "\\medmuskip", "\\thickmuskip"][space - 1],
            )
        )
        pass

    def typesetNucleus(self, parser, packed, context, style):
        """
        Typeset the nucleus (Appendix G Rule 17) and return delta.

        Delta is the italic correction reserved for script positioning. When no
        subscript is present, Rule 17 may realize it immediately as a kern and
        return zero.
        """
        delta = Dimen()
        if self.nucleus is None:
            # return an emptybox
            b = box.HBox(parser, 0, 0)
            b = b.typeset(parser)
            packed.append(b)
            return delta

        if isinstance(self.nucleus, MathSymbol):
            self.nucleus.typeset(parser, packed, context, style, include_italic=False)
            # Rule 17 (common symbol case).
            node = packed[-1]
            font = node.font
            fontdimen2 = font.param[1] if len(font.param) > 1 else 0
            text_symbol = getattr(context, "text_symbol", False)
            if (not text_symbol) or int(fontdimen2) == 0:
                delta = Dimen(node.italic)
            if int(delta) != 0 and self.sub is None:
                packed.append(nd.Kern(delta, automatic=True))
                delta = Dimen()
        else:
            self.nucleus.typeset(parser, packed, context, style)
        return delta

    def _rule18aIsCharTranslation(self, translated):
        """
        Rule 18a character-nucleus test:
        translated nucleus is a character box, optionally followed by one kern.
        """
        if not translated:
            return False
        first = translated[0]
        if first.node_type not in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
            return False
        if len(translated) == 1:
            return True
        return len(translated) == 2 and translated[1].node_type == nd.NODE_TYPE.KERN

    def _translatedHeightDepth(self, parser, translated):
        """
        Measure height/depth of translated nucleus material as one horizontal box.
        """
        if len(translated) == 1 and isinstance(translated[0], nd.Box):
            n = translated[0]
            shifted = getattr(n, "shifted", 0)
            return n.height - shifted, n.depth + shifted
        b = box.HBox(parser, None, 0)
        b.list.extend(translated)
        b = b.typeset(parser)
        return b.height, b.depth

    def rule18a(self, parser, translated, context, style):
        """
        Appendix G Rule 18a: preliminary superscript/subscript shifts u,v.
        """
        if self._rule18aIsCharTranslation(translated):
            return Dimen(), Dimen()
        h, d = self._translatedHeightDepth(parser, translated)
        q = Dimen(mathsigma(parser, style.superscript())[17])  # sigma18 at C^
        r = Dimen(mathsigma(parser, style.subscript())[18])    # sigma19 at C_
        return h - q, d + r

    def _typesetScriptField(self, parser, field, context, style):
        """
        Typeset a script field in style and return it as a box.
        """
        if isinstance(field, MathSymbol):
            x = box.HBox(parser, None, 0)
            field.typeset(parser, x.list, context, style, include_italic=True)
            x = x.typeset(parser)
            x.width += mathlayout(parser, "scriptspace")
            if hasattr(x, "to"):
                x.to = x.width
            return x
        local = AtomState(parser)
        if isinstance(field, Atom):
            x = field.assemble(parser, local, style)
            x.width += mathlayout(parser, "scriptspace")
            if hasattr(x, "to"):
                x.to = x.width
            return x
        x = box.HBox(parser, None, 0)
        if field is not None:
            typeset = field.typeset
            if typeset is None:
                x.list.append(field)
            else:
                typeset(parser, x.list, local, style)
        x = _drop_redundant_wrapper(x.typeset(parser), allow_char=False)
        x.width += mathlayout(parser, "scriptspace")
        if hasattr(x, "to"):
            x.to = x.width
        return x

    def rule18c(self, parser, x, context, style, u):
        """
        Appendix G Rule 18c: tentative superscript shift-up.
        """
        sigma = mathsigma(parser, style)
        sigma5 = Dimen(sigma[4])  # sigma5, x-height
        if style.style == MATH_STYLE.D and not style.cramped:
            p = Dimen(sigma[12])   # sigma13
        elif style.cramped:
            p = Dimen(sigma[14])   # sigma15
        else:
            p = Dimen(sigma[13])   # sigma14
        lift_limit = x.depth + abs(sigma5) / 4
        if p > u:
            u = p
        if lift_limit > u:
            u = lift_limit
        return u

    def rule18d(self, parser, context, style, v):
        """
        Appendix G Rule 18d (both scripts case):
        build subscript box y in C_ and enforce v >= sigma17.
        """
        y = self._typesetScriptField(parser, self.sub, context, style.subscript())
        sigma17 = Dimen(mathsigma(parser, style)[16])  # sigma17
        if sigma17 > v:
            v = sigma17
        return y, v

    def rule18e(self, parser, x, y, context, style, u, v):
        """
        Appendix G Rule 18e: joint superscript/subscript clearance adjustment.
        """
        theta = Dimen(mathxi(parser, style)[7])  # xi8
        min_clear = 4 * theta
        clearance = (u - x.depth) - (y.height - v)
        if clearance < min_clear:
            v += (min_clear - clearance)
        sigma5 = Dimen(mathsigma(parser, style)[4])  # sigma5 x-height
        psi = (abs(sigma5) * 4) / 5 - (u - x.depth)
        if psi > 0:
            u += psi
            v -= psi
        return u, v

    def rule18f(self, parser, packed, x, y, u, v, delta):
        """
        Appendix G Rule 18f: build and append joint sup/sub vbox.
        """
        delta = Dimen() if delta is None else Dimen(delta)
        top = x
        if int(delta) != 0:
            shifted = box.HBox(parser, None, 0)
            shifted.list.append(nd.Kern(delta))
            shifted.list.append(x)
            top = shifted.typeset(parser)
        k = u + v - x.depth - y.height
        out = box.VBox(parser, top.height + u, 0)
        # Math-internal vertical stacks should not run VList interline glue logic.
        out.list[:] = [top, nd.Kern(k), y]
        out = out.typeset(parser)
        out.depth = y.depth + v
        packed.append(out)
        return out
    
    def typesetScripts(self, parser, packed, context, style, delta):
        """
        typeset the nucleus, the superscript and the subscript
        """
        if self.sub is None and self.sup is None:
            return
        # Rule 18a: compute preliminary shifts; later subrules 18b-f will use
        # these values together with delta from Rule 17.
        u, v = self.rule18a(parser, packed, context, style)
        if self.sup is None:
            # Rule 18b: subscript only.
            x = self._typesetScriptField(parser, self.sub, context, style.subscript())
            sigma = mathsigma(parser, style)
            sigma16 = Dimen(sigma[15])  # sigma16
            sigma5 = Dimen(sigma[4])    # sigma5 (x-height)
            lift_limit = x.height - (abs(sigma5) * 4) / 5
            shift = v
            if sigma16 > shift:
                shift = sigma16
            if lift_limit > shift:
                shift = lift_limit
            x.shifted = shift
            packed.append(x)
            return
        # Rule 18c: superscript exists.
        x = self._typesetScriptField(parser, self.sup, context, style.superscript())
        u = self.rule18c(parser, x, context, style, u)
        if self.sub is None:
            # Rule 18d.
            x.shifted = -u
            packed.append(x)
            return
        # Rule 18d (both scripts): build subscript and apply v floor.
        y, v = self.rule18d(parser, context, style, v)
        # Rule 18e.
        u, v = self.rule18e(parser, x, y, context, style, u, v)
        # Rule 18f.
        self.rule18f(parser, packed, x, y, u, v, delta)

    def assemble(self, parser, context, style):
        """
        return a box that contains the nucleus, superscritp and subscript.
        """
        # Use natural-width packing: rule-12/13 constructions read this width.
        b = box.HBox(parser, None, 0)
        # typesetNucleus may disable Rule 18 script attachment (Rule 12 single-char accent case).
        self._attach_scripts = True
        delta = self.typesetNucleus(parser, b.list, context, style)
        if self._attach_scripts:
            self.typesetScripts(parser, b.list, context, style, delta)
        self._attach_scripts = True
        return b.typeset(parser)

    @staticmethod
    def overbar(parser, b, k, t):
        """
        Build TeX's overbar box: kern(t), rule(t), kern(k), then box b.
        """
        out = box.VBox(parser, None, 0)
        out.list[:] = [
            nd.Kern(t),
            nd.Rule(NEG_MAX_DIMEN, t, 0),
            nd.Kern(k),
            b,
        ]
        return out.typeset(parser)

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
            b = b.typeset(parser)
        if b.width == width:
            return b
        out = box.HBox(parser, width, None)
        hss = Glue(0, Stretchness(1, 1), Stretchness(1, 1))
        out.list.append(nd.Glue(hss, None))
        italic = None
        out.list.extend(b.list)
        if b.list:
            right = b.list[-1]
            if right.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                italic = getattr(right, "italic", None)
        if italic is not None and int(italic) != 0:
            out.list.append(nd.Kern(italic, automatic=True))
        out.list.append(nd.Glue(hss, None))
        result = out.typeset(parser)
        if hasattr(b, "math_axis_shift"):
            result.math_axis_shift = b.math_axis_shift
        return result
    

class Op(Atom):
    """
    Operator atom (Appendix G Rule 13/13a).
    """
    def __init__(self):
        super().__init__(ATOM_TYPE.OP)
        self.limits = MATH_LIMITS.DISPLAY

    def _rule13UseLimits(self, style):
        # \\limits => always, \\nolimits => never, \\displaylimits => display only.
        if self.limits == MATH_LIMITS.NONE:
            return False
        if self.limits == MATH_LIMITS.NORMAL:
            return True
        return style.style == MATH_STYLE.D

    def _typesetLimitField(self, parser, field, context, style):
        if isinstance(field, MathSymbol):
            out = box.HBox(parser, None, 0)
            field.typeset(parser, out.list, context, style, include_italic=True)
            out = out.typeset(parser)
        else:
            local = AtomState(parser)
            if isinstance(field, Atom):
                out = field.assemble(parser, local, style)
            else:
                out = box.HBox(parser, None, 0)
                if field is not None:
                    typeset = getattr(field, "typeset", None)
                    if typeset is None:
                        out.list.append(field)
                    else:
                        typeset(parser, out.list, local, style)
                out = out.typeset(parser)
        if field is not None:
            out.width += mathlayout(parser, "scriptspace")
            out.to = out.width
        return out

    def _rule13Nucleus(self, parser, context, style, use_limits):
        y = box.HBox(parser, None, 0)
        delta = Dimen()
        symbol = self.nucleus if isinstance(self.nucleus, MathSymbol) else None
        if symbol is None:
            typeset = getattr(self.nucleus, "typeset", None)
            if typeset is None:
                if self.nucleus is not None:
                    y.list.append(self.nucleus)
            else:
                typeset(parser, y.list, context, style)
            return y.typeset(parser), delta
        # C > T means display style in this implementation.
        font = mathfont(parser, style, symbol.fam)
        node = font[symbol.char]
        if style.style == MATH_STYLE.D and node.char_info.next_larger is not None:
            node = font[node.char_info.next_larger]
        delta = Dimen(node.italic)
        y.list.append(node)
        # Include italic correction in width iff limits are used or there is no subscript.
        if int(delta) != 0 and (use_limits or self.sub is None):
            y.list.append(nd.Kern(delta, automatic=True))
        y = y.typeset(parser)
        axis = Dimen(mathsigma(parser, style)[21])  # sigma22
        axis_shift = (y.height - y.depth) / 2 - axis
        if use_limits:
            y.math_axis_shift = axis_shift
        else:
            y.shifted = axis_shift
        return y, delta

    def _rule13aAttachLimits(self, parser, context, style, y, delta):
        x_nonempty = self.sup is not None
        z_nonempty = self.sub is not None
        x = self._typesetLimitField(parser, self.sup, context, style.superscript())
        z = self._typesetLimitField(parser, self.sub, context, style.subscript())
        target = x.width if x.width >= y.width else y.width
        if z.width > target:
            target = z.width
        x = Atom.rebox(parser, x, target)
        y = Atom.rebox(parser, y, target)
        z = Atom.rebox(parser, z, target)

        xi = mathxi(parser, style)
        xi9 = Dimen(xi[8])
        xi10 = Dimen(xi[9])
        xi11 = Dimen(xi[10])
        xi12 = Dimen(xi[11])
        xi13 = Dimen(xi[12])
        half_delta = delta / 2

        pieces = []
        if x_nonempty:
            pieces.append(nd.Kern(xi13))
            x.shifted = half_delta
            pieces.append(x)
            k = xi11 - x.depth
            if xi9 > k:
                k = xi9
            pieces.append(nd.Kern(k))
        y_index = len(pieces)
        pieces.append(y)
        if z_nonempty:
            k = xi12 - z.height
            if xi10 > k:
                k = xi10
            pieces.append(nd.Kern(k))
            z.shifted = -half_delta
            pieces.append(z)
            pieces.append(nd.Kern(xi13))
        out = box.VBox(parser, None, 0)
        out.list[:] = pieces
        out = out.typeset(parser)
        # Rule 13a baseline: the resulting vbox baseline aligns with the centered
        # operator nucleus baseline (box y), not with the bottom of the stack.
        below = self._rule13aDepthFromY(out, pieces, y_index)
        total = out.height + out.depth
        out.depth = below
        out.height = total - below
        return out

    def _rule13aDepthFromY(self, out, pieces, y_index):
        def _effective_box_dims(item):
            shifted = getattr(item, "math_axis_shift", 0)
            return item.height - shifted, item.depth + shifted

        y = pieces[y_index]
        _, prevdepth = _effective_box_dims(y)
        below = Dimen()
        for item in pieces[y_index + 1:]:
            node_type = item.node_type
            if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                h, d = _effective_box_dims(item)
                below += prevdepth + h
                prevdepth = d
            elif node_type == nd.NODE_TYPE.KERN:
                below += prevdepth + item.kern
                prevdepth = Dimen()
            elif node_type == nd.NODE_TYPE.GLUE:
                below += prevdepth + item.glue.dimen
                prevdepth = Dimen()
            else:
                below += prevdepth
                prevdepth = Dimen()
        below += prevdepth
        # Keep split sane if future node kinds alter packing assumptions.
        if below < 0:
            return Dimen()
        total = out.height + out.depth
        if below > total:
            return total
        return below

    def assemble(self, parser, context, style):
        b = box.HBox(parser, 0, 0)
        use_limits = self._rule13UseLimits(style)
        y, delta = self._rule13Nucleus(parser, context, style, use_limits)
        if use_limits:
            b.list.append(self._rule13aAttachLimits(parser, context, style, y, delta))
        else:
            b.list.append(y)
            self.typesetScripts(parser, b.list, context, style, delta)
        return b.typeset(parser)


class MathSymbol(serialization.Serializable):
    """
    A math symbol
    @param mathcode: the math code
    @param fam: the \\fam value
    """
    def __init__(self, mathcode, fam):
        self.type, self.fam, self.char = self.decode(mathcode, fam)

    def saveInfo(self):
        return {"mathcode": self.encode(), "fam": -1}, None

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

    def typeset(self, parser, packed, context, style, include_italic=True):
        font = mathfont(parser, style, self.fam)
        node = font[self.char]
        packed.append(node)
        if include_italic and int(node.italic) != 0:
            packed.append(nd.Kern(node.italic, automatic=True))


class Box(Atom):
    """
    a box
    @param box: the box
    """
    def __init__(self, box):
        super().__init__(ATOM_TYPE.ORD)
        self.nucleus = box
    
    def saveInfo(self):
        init, extra = super().saveInfo()
        return init | {"box": self.nucleus}, extra

    def typesetNucleus(self, parser, packed, context, style):
        # Box atoms carry a prebuilt box nucleus.
        typeset = getattr(self.nucleus, "typeset", None)
        packed.append(self.nucleus if typeset is None else typeset(parser))
        return Dimen()


class MathEndGroupCallback:
    def __init__(self, node):
        self.node = node

    def finalize(self, parser, top, mlist):
        if isinstance(self.node, Subformula) and len(mlist.list) == 1:
            node = mlist.list[0]
            if isinstance(node, Atom) and node.atom_type == ATOM_TYPE.ACC:
                top.append(node)
                return
        top.append(self.node)

    def __call__(self, parser):
        mlist = parser.lists.pop()
        assert mlist.type == lists.LISTTYPE.MATH
        # we need to check if we are building a general fraction
        if getattr(mlist, "building_atom", None) is not None:
            raise ValueError("missing field", parser.input.position())
        if getattr(mlist, "is_denominator", False):
            mlist= parser.lists.pop()
        top = parser.lists[-1]
        self.finalize(parser, top, mlist)


class MathShiftEndGroupCallback(MathEndGroupCallback):    
    def prepare(self, parser):
        mlist = parser.lists[-1]
        if mlist.type != lists.LISTTYPE.MATH:
            return
        if mlist.inner:
            self.node.pretypeset(parser)
            return
        if not mlist.isalign:
            return
        self.node = mlist[0]

    def finalize(self, parser, top, mlist):
        # here top points to the enclosing horizontal list
        # if mlist is inline math, then we simply add it to the enclosing list
        eqno = getattr(mlist, "eqno", None)
        if eqno is not None:
            self.node.eqno = eqno
        if mlist.inner:
            top.append(self.node)
            return
        if mlist.isalign:
            self.node = mlist[0]
        top.append(self.node)
        parser.globals["prevgraf"] += 3
        # TeX is back in horizontal mode after a display, but the follow-on
        # paragraph is only added if it later receives content.
        parser.newParagraph(
            indent=False,
            parskip=False,
        )


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
        # are we in display math or inline math?
        if not top.inner:
            t = parser.token()
            if t is None or t.catcode != CATCODE.MATH_SHIFT:
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
    started_in_vmode = False
    if top.type == lists.LISTTYPE.VERTICAL:
        parser.input.unread(parser.current_token)
        parser.newParagraph()
        return
    # if we are in restricted horizontal mode, only inline math is allowed. So we do not 
    # need to check for a second $ token
    prev_par = None
    if top.type == lists.LISTTYPE.VERTICAL:
        pass
    elif top.inner:
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
    node = InlineMathNode() if inner else DisplayMathNode()
    if not inner:
        volatile = parser.volatile
        if not started_in_vmode:
            prev_par = parser.endParagraph()
            if prev_par is None:
                volatile["displaywidth"] = parser.layout["hsize"]
                volatile["displayindent"] = Dimen()
                volatile["predisplaysize"] = NEG_MAX_DIMEN
                parser.globals["prevgraf"] = 0
        else:
            volatile["displaywidth"] = parser.layout["hsize"]
            volatile["displayindent"] = Dimen()
            volatile["predisplaysize"] = NEG_MAX_DIMEN
            parser.globals["prevgraf"] = 0
        parser.paragraph_before_last_display_math = prev_par
    parser.lists.append(MList(parser, node.list, inner=inner))
    # \fam=-1 when entering math mode
    parser.parameters["fam"] = -1
    callback = MathShiftEndGroupCallback(node)
    parser.beginGroup(
        parser.input.position(),
        GROUP_TYPE.MATH_SHIFT,
        to_end=callback.prepare,
        ended=callback,
    )
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

    def className(self):
        return Serializable.className(self)
    
    def saveInfo(self):
        return {"mathcode": self.mathcode}, None

    @classmethod
    def new(cls, parser, **kargs):
        return cls(**kargs)

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
    
    def __eq__(self, other):
        return isinstance(other, MathCharValue) and self.mathcode == other.mathcode



class MathCharDefAccesor(EquitableAccessor):
    def readValue(self, parser):
        return MathCharValue(parser.readInteger())


mathchardef = MathCharDefAccesor()


def mudimen(source, style, dimen):
    """
    calculate the actual dimension of a mu dimen
    @param parser: the parser
    @param dimen: the mu dimen
    @return: the true dimension

    The mu unit is 1/18 of the em unit of \\textfont[2]
    """
    sigma6 = mathfont(source, style, 2).param[5]  # fontdimen 6 is em

    def trunc_div(value, divisor):
        if value >= 0:
            return value // divisor
        return -((-value) // divisor)

    # TeX computes mu units with integer arithmetic: first 1mu = sigma6/18,
    # then the scaled-mu amount is multiplied by that truncated unit.
    mu = trunc_div(int(sigma6), 18)
    return Dimen(integer=trunc_div(int(dimen) * mu, Dimen.scale))


def muglue(source, style, glue):
    """
    calculate the actual dimension of a mu glue
    @param parser: the parser
    @param glue: the mu glue
    @return: the true dimension
    """
    dimen = mudimen(source, style, glue.dimen)
    stretch = mustretchness(source, style, glue.stretch)
    shrink = mustretchness(source, style, glue.shrink)
    return Glue(dimen, stretch, shrink)


def mustretchness(source, style, stretch):
    """
    calculate the actual stretchness of a mu glue
    @param parser: the parser
    @param stretch: the stretchness
    @return: the true stretchness
    """
    factor = mudimen(source, style, stretch.factor) if stretch.order == 0 else stretch.factor
    return Stretchness(factor, stretch.order)


class MuKern(nd.Kern):
    def __init__(self, dimen):
        super().__init__(Dimen(dimen))
        self.mu = True

    def saveInfo(self):
        return {"dimen": float(self.dimen)}, None

    def typeset(self, parser, packed, context, style):
        if packed is None:
            raise ValueError("typeset requires a packed list")
        if parser is None:
            raise ValueError("typeset requires a parser for mu units")
        dimen = mudimen(parser, style, self.kern)
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
        super().__init__(glue, None)
        self.mu = True

    def saveInfo(self):
        return {"glue": self.glue, "name": self.name}, None

    def typeset(self, parser, packed, context, style):
        if packed is None:
            raise ValueError("typeset requires a packed list")
        packed.append(nd.Glue(muglue(parser, style, self.glue), getattr(self, "name", None)))
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
                "display": self.display,
                "text": self.text,
                "script": self.script,
                "scriptscript": self.scriptscript
            }, None
 
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
    def __init__(self, node):
        super().__init__(node)
        self.state = 0
        self.attr = ["display", "text", "script", "scriptscript"]

    def beginGroup(self, parser):
        t = parser.token_expand()
        t = parser.token_meaning(t)
        pos = parser.input.position()
        if t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a \"{\"", pos)
        parser.lists.append(MList(parser))
        parser.beginGroup(pos, GROUP_TYPE.MATH_CHOICE, ended=self)

    def finalize(self, parser, top, mlist):
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
        callback = MathChoiceEndGroupCallback(choice)
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
                "type": self.type.value,
                "small": self.small,
                "large": self.large
            }, None

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

    def _fontSearchOrder(self, parser, style, family):
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
        textfont = parser.textfont
        scriptfont = parser.scriptfont
        scriptscriptfont = parser.scriptscriptfont
        if level >= MATH_STYLE.SS:
            add(scriptscriptfont[family])
        if level >= MATH_STYLE.S:
            add(scriptfont[family])
        add(textfont[family])
        return fonts

    def _lookupChar(self, font, code):
        if font is None:
            return None, None
        try:
            char = chr(code)
        except ValueError:
            return None, None
        info = font.glyphInfo(char)
        if info is None:
            return None, None
        return info, font[char]

    def _scanSymbol(self, parser, symbol, style, minimum, best):
        if self._symbolIsNull(symbol):
            return None, best
        code0 = ord(symbol.char)
        for font in self._fontSearchOrder(parser, style, symbol.fam):
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
                        "extensible": info.assembly is not None,
                    }
                if total >= minimum or info.assembly is not None:
                    return {
                        "node": node,
                        "info": info,
                        "font": font,
                        "total": total,
                        "extensible": info.assembly is not None,
                    }, best
                if info.next_larger is None:
                    break
                code = ord(info.next_larger)
        return None, best

    def _boxWithItalic(self, parser, node):
        b = box.HBox(parser, None, 0)
        b.list.append(node)
        italic = getattr(node, "italic", None)
        if italic is not None and int(italic) != 0:
            b.list.append(nd.Kern(italic, automatic=True))
        return b.typeset(parser)

    def _buildExtensible(self, parser, chosen, minimum):
        info = chosen["info"]
        ext = info.assembly
        if ext is None:
            return self._boxWithItalic(parser, chosen["node"])

        def piece(code):
            if code == 0:
                return None
            _, n = self._lookupChar(chosen["font"], code)
            b = box.HBox(parser, None, 0)
            b.list.append(n)
            return b.typeset(parser)

        top = piece(ext.top)
        mid = piece(ext.middle)
        bot = piece(ext.bottom)
        rep = piece(ext.repeat)
        if rep is None:
            return self._boxWithItalic(parser, chosen["node"])

        def total(n):
            return n.height + n.depth if n is not None else Dimen()

        top_total = total(top)
        mid_total = total(mid)
        bot_total = total(bot)
        rep_total = total(rep)
        if int(rep_total) <= 0:
            return self._boxWithItalic(parser, chosen["node"])

        base = top_total + mid_total + bot_total
        need = minimum - base
        if mid is not None:
            unit = 2 * rep_total
            repeat = 0 if need <= 0 else max(0, (int(need) + int(unit) - 1) // int(unit))
        else:
            unit = rep_total
            repeat = 0 if need <= 0 else max(0, (int(need) + int(unit) - 1) // int(unit))
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
        v.expanded = list(parts)
        v = v.typeset(parser)
        # TeX uses the repeatable piece width for extensible delimiters.
        v.width = rep.width
        return v

    def typeset(self, parser, total, context, style, axis=None):
        """
        return a box containing the delimiter that fits a requested total
        height+depth.
        """
        if axis is None:
            axis = Dimen(mathsigma(parser, style)[21])
        if self._isNull():
            b = box.HBox(parser, mathlayout(parser, "nulldelimiterspace"), None)
            b = b.typeset(parser)
            # Rule 15e/19 centering applies to null delimiters as well.
            b.shifted = (b.height - b.depth) / 2 - axis
            return b
        minimum = Dimen(total)
        best = None
        chosen, best = self._scanSymbol(parser, self.small, style, minimum, best)
        if chosen is None:
            chosen, best = self._scanSymbol(parser, self.large, style, minimum, best)
        if chosen is None:
            chosen = best
        if chosen is None:
            b = box.HBox(parser, mathlayout(parser, "nulldelimiterspace"), None)
            return b.typeset(parser)
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
        return {"delim": self.delim, "oprand": self.oprand}, None

    def _typesetField(self, parser, field, context, style):
        out = box.HBox(parser, None, 0)
        if field is not None:
            typeset = getattr(field, "typeset", None)
            if typeset is None:
                out.list.append(field)
            else:
                typeset(parser, out.list, context, style)
        return _drop_redundant_wrapper(out.typeset(parser), allow_char=False)

    def typesetNucleus(self, parser, packed, context, style: Style):
        """
        Appendix G, Rule 11: typeset radical nucleus and delimiter.
        """
        x = self._typesetField(parser, self.oprand, context, Style(style.style, cramped=True))
        theta = Dimen(mathxi(parser, style)[7])  # xi8 default rule thickness
        # Rule 11: in display style, use sigma5; otherwise use theta.
        if style.style < MATH_STYLE.T:
            phi = Dimen(mathsigma(parser, style)[4])  # sigma5
        else:
            phi = theta
        clr = theta + abs(phi) / 4
        y = self.delim.typeset(parser, x.height + x.depth + clr + theta, context, style)
        if y.height <= 0:
            y.height = theta
        delta = y.depth - (x.height + x.depth + clr)
        if delta > 0:
            clr += delta / 2
        y.shifted = -(x.height + clr)
        out = box.HBox(parser, None, 0)
        out.list[:] = [y, Atom.overbar(parser, x, clr, y.height)]
        packed.append(out.typeset(parser))
        return Dimen()

    node_type = nd.NODE_TYPE.MATHNODE


class Delimiter(lists.ModeDependentCommand):
    """
    the \\delimiter command
    """
    def math(self, parser, mlist):
        # when used independently in a math list, its right most 3 hex digits are
        # dropped, and the remaining 15 bits are used as the a mathchar
        delcode = parser.readInteger() >> 12
        fam = parser.parameters["fam"]
        mlist.append(MathSymbol(delcode, fam))

    def delimiter(self, parser):
        delcode = parser.readInteger()
        fam = parser.parameters["fam"]
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
        code = parser.delcode[ord(t.name)]
    else:
        try:
            code = t.delimiter(parser)
        except AttributeError:
            raise ValueError("expecting a delimiter")
    return Delim(code, parser.parameters["fam"])


class Radical(lists.ModeDependentCommand):
    """
    the \\radical command
    """
    def math(self, parser, mlist):
        delim = Delim(parser.readInteger(), parser.parameters["fam"])
        mlist.buildAtom("oprand", Rad(delim, None))


class MathLeftEndGroupCallBack(MathEndGroupCallback):
    def __init__(self, node, atom):
        super().__init__(node)
        self.atom = atom

    def finalize(self, parser, top, mlist):
        self.node.right_delim = readDelimiter(parser)
        self.atom.nucleus = self.node

class Left(lists.ModeDependentCommand):
    """
    the \\left command
    """
    def math(self, parser, mlist):
        delim = readDelimiter(parser)
        atom = Atom(ATOM_TYPE.INNER)
        mlist.append(atom)
        subformula = Subformula()
        subformula.left_delim = delim
        parser.lists.append(MList(parser, subformula.list))
        parser.beginGroup(
            parser.input.position(),
            GROUP_TYPE.MATH_LEFT,
            ended=MathLeftEndGroupCallBack(subformula, atom),
        )


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
        self.delims = None

    def saveInfo(self):
        return {
                "num": self.nucleus[0],
                "den": self.nucleus[1],
                "bar": self.nucleus[2],
                "thickness": self.nucleus[3],
            }, {
                "delims": self.delims,
            }
    
    def rule15(self, parser, style: Style):
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
            theta = Dimen(mathxi(parser, style)[7]) if bar else Dimen()
        else:
            theta = Dimen(thickness)
        return num, den, theta

    def rule15b(self, parser, style: Style, theta: Dimen):
        """
        Appendix G, Rule 15b: base numerator/denominator shifts.
        """
        sigma = mathsigma(parser, style)
        if style.style < MATH_STYLE.T:
            # C > T
            u = Dimen(sigma[7])   # sigma8
            v = Dimen(sigma[10])  # sigma11
        else:
            # C <= T
            u = Dimen(sigma[8] if int(theta) != 0 else sigma[9])  # sigma9/sigma10
            v = Dimen(sigma[11])  # sigma12
        return u, v

    def rule15c(self, parser, x, z, style: Style, u: Dimen, v: Dimen):
        """
        Appendix G, Rule 15c: atop-style clearance adjustment (theta = 0).

        Returns adjusted (u, v, clearance_kern).
        """
        xi8 = Dimen(mathxi(parser, style)[7])
        phi = (7 * xi8) if style.style < MATH_STYLE.T else (3 * xi8)
        psi = (u - x.depth) - (z.height - v)
        if psi < phi:
            delta = (phi - psi) / 2
            u = u + delta
            v = v + delta
            psi = (u - x.depth) - (z.height - v)
        return u, v, psi

    def rule15d(self, parser, x, z, style: Style, theta: Dimen, u: Dimen, v: Dimen):
        """
        Appendix G, Rule 15d: over-style bar placement/clearance adjustment.

        Returns adjusted (u, v, kern_above_rule, kern_below_rule).
        """
        phi = (3 * theta) if style.style < MATH_STYLE.T else theta
        a = Dimen(mathsigma(parser, style)[21])  # axis height, sigma22
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

    def typesetNucleus(self, parser, packed, context, style: Style):
        # TeXbook Appendix G, Rule 15(a-e)
        num, den, theta = self.rule15(parser, style)
        x = box.HBox(parser, None, 0)
        z = box.HBox(parser, None, 0)
        num.typesetNodes(parser, x.list, context, style.numerator())
        den.typesetNodes(parser, z.list, context, style.denominator())
        x = x.typeset(parser)
        z = z.typeset(parser)
        target = x.width if x.width >= z.width else z.width
        x = Atom.rebox(parser, x, target)
        z = Atom.rebox(parser, z, target)
        u, v = self.rule15b(parser, style, theta)
        if int(theta) == 0:
            # Rule 15c (\atop): enforce minimum clearance with adjusted shifts.
            u, v, k = self.rule15c(parser, x, z, style, u, v)
            out = box.VBox(parser, x.height + u, 0)
            out.list[:] = [x, nd.Kern(k), z]
            out = out.typeset(parser)
            out.depth = z.depth + v
        else:
            # Rule 15d (\over): enforce clearances from numerator/denominator to bar.
            u, v, k1, k2 = self.rule15d(parser, x, z, style, theta, u, v)
            out = box.VBox(parser, x.height + u, 0)
            out.list[:] = [
                x,
                nd.Kern(k1),
                nd.Rule(target, theta, 0),
                nd.Kern(k2),
                z,
            ]
            out = out.typeset(parser)
            out.depth = z.depth + v
        # Rule 15e: delimiters around the fraction vbox.
        # For plain \over/\atop/\above, TeX uses null delimiters whose width is
        # \nulldelimiterspace.
        if self.delims is None:
            left_delim = Delim(0, 0)
            right_delim = Delim(0, 0)
        else:
            left_delim, right_delim = self.delims
        sigma = mathsigma(parser, style)
        min_total = Dimen(sigma[19] if style.style < MATH_STYLE.T else sigma[20])
        total = out.height + out.depth
        if total < min_total:
            total = min_total
        axis = Dimen(sigma[21])
        left_box = left_delim.typeset(parser, total, context, style, axis)
        right_box = right_delim.typeset(parser, total, context, style, axis)
        wrapped = box.HBox(parser, None, 0)
        wrapped.list[:] = [left_box, out, right_box]
        packed.append(wrapped.typeset(parser))
        return Dimen()

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
        numerator = Subformula()
        numerator.list = mlist.list.copy()
        mlist.list.clear()
        # mlist becomes the numerator
        denominator = Subformula()
        fraction = Over(numerator, denominator, self.bar, thickness)
        if self.delim:
            fraction.delims = (left, right)
        if self.thickness:
            fraction.thickness = thickness
        mlist.append(fraction)
        den_builder = MList(parser, denominator.list, mlist.inner)
        den_builder.is_denominator = True
        parser.lists.append(den_builder)


class Accent(Atom):
    """
    a node representing an accent
    @param accent: the accent
    @param base: a math field
    """
    def __init__(self, accent, base):
        super().__init__(ATOM_TYPE.ACC)
        self.accent = accent
        self.nucleus = base

    @property
    def base(self):
        return self.nucleus

    @base.setter
    def base(self, value):
        self.nucleus = value

    def saveInfo(self):
        return {"accent": self.accent, "base": self.base}, None

    def _typesetField(self, parser, field, context, style):
        out = box.HBox(parser, None, 0)
        if field is not None:
            typeset = getattr(field, "typeset", None)
            if typeset is None:
                out.list.append(field)
            else:
                typeset(parser, out.list, context, style)
        return _drop_redundant_wrapper(out.typeset(parser), allow_char=False)

    def _fontCharIfExists(self, font, char):
        info = font.glyphInfo(char)
        if info is None:
            return None
        return font[char]

    def _rule12Skew(self, parser, nucleus_symbol, context, style):
        # Kern amount for nucleus followed by skewchar in its font.
        if not isinstance(nucleus_symbol, MathSymbol):
            return Dimen()
        base_style = Style(style.style, cramped=True)
        font = mathfont(parser, base_style, nucleus_symbol.fam)
        base = self._fontCharIfExists(font, nucleus_symbol.char)
        if base is None:
            return Dimen()
        skew = font.fontchar.get("skewchar", 0)
        if not font.hasCharCode(skew):
            return Dimen()
        nxt = self._fontCharIfExists(font, chr(skew))
        if nxt is None:
            return Dimen()
        step = ligature_step(base, nxt)
        if step is None or not step.isKern:
            return Dimen()
        return Dimen(step.kern * font.at)

    def _rule12SingleBaseSymbol(self, field):
        """
        Return the underlying symbol when the accent base is just one symbol,
        possibly wrapped by a one-item subformula/group.
        """
        while True:
            if isinstance(field, MathSymbol):
                return field
            if isinstance(field, Atom):
                if field.sub is not None or field.sup is not None:
                    return None
                field = field.nucleus
                continue
            if isinstance(field, Subformula):
                if len(field.list) != 1:
                    return None
                field = field.list[0]
                continue
            return None

    def _rule12AccentNode(self, parser, context, style, u):
        # Pick accent in current size, following successor chain while width <= u.
        font = mathfont(parser, style, self.accent.fam)
        node = self._fontCharIfExists(font, self.accent.char)
        if node is None:
            return None, None
        while True:
            chain = getattr(node.char_info, "chain", None)
            if chain is None:
                break
            nxt = self._fontCharIfExists(font, chain)
            if nxt is None or nxt.width > u:
                break
            node = nxt
        return node, font

    def typesetNucleus(self, parser, packed, context, style: Style):
        # Rule 12 starts from nucleus in style C'.
        self._attach_scripts = True
        base_symbol = self._rule12SingleBaseSymbol(self.nucleus)
        x = self._typesetField(parser, self.nucleus, context, Style(style.style, cramped=True))
        u = x.width
        y_char, accent_font = self._rule12AccentNode(parser, context, style, u)
        # If accent doesn't exist in current size, continue at Rule 16.
        if y_char is None:
            return super().typesetNucleus(parser, packed, context, style)
        s = self._rule12Skew(parser, base_symbol, context, style) if base_symbol is not None else Dimen()
        delta = x.height
        xh = Dimen(accent_font.param[4])  # fontdimen5 (x-height)
        if delta > xh:
            delta = xh
        if base_symbol is not None:
            old_h = x.height
            base_atom = Atom(ATOM_TYPE.ORD)
            base_atom.nucleus = base_symbol
            base_atom.sub = self.sub
            base_atom.sup = self.sup
            x = base_atom.assemble(parser, context, style)
            delta += x.height - old_h
            # Rule 12 single-character branch absorbs scripts into x.
            self._attach_scripts = False
        # y is accent character including italic correction.
        y = box.HBox(parser, None, 0)
        y.list.append(y_char)
        if int(y_char.italic) != 0:
            y.list.append(nd.Kern(y_char.italic, automatic=True))
        y = y.typeset(parser)
        y.shifted = s + (u - y.width) / 2
        # z stacks y, kern(-delta), x.
        z = box.VBox(parser, None, 0)
        z.list[:] = [y, nd.Kern(-delta), x]
        z = z.typeset(parser)
        if z.height < x.height:
            k = x.height - z.height
            z.list.insert(0, nd.Kern(k))
            z.natural.dimen += k
        z.width = x.width
        packed.append(z)
        return Dimen()
    
    node_type = nd.NODE_TYPE.MATHNODE


class MathAccent(lists.ModeDependentCommand):
    """
    the \\accent command
    """
    def math(self, parser, mlist):
        accent = MathSymbol(parser.readInteger(), parser.parameters["fam"])
        mlist.buildAtom("base", Accent(accent, None))


class Eqno(lists.ModeDependentCommand):
    """
    the \\eqno command
    @param left: whether the equation number is on the left
    """
    def __init__(self, left: bool):
        self.left = left

    def math(self, parser, mlist):
        def callback(parser):
            eq_state = parser.lists.pop()
            eqno = getattr(parser.lists[-1], "eqno", [None, None])[0]
            assert eq_state is eqno_builder
            parser.input.unread(MathShiftToken("$", CATCODE.MATH_SHIFT))
        # we must be at the bottom of the math lists
        enclosing = parser.lists[-2]
        if enclosing.type == lists.LISTTYPE.MATH:
            raise ValueError("misplaced equation number", parser.input.position())
        if mlist.inner:
            raise ValueError("only display math can have an equation number", parser.input.position())
        # equation numbers are invalid in $$\halign$$
        if mlist.isalign:
            raise ValueError("equation numbers cannot be used with \\halign in math mode", parser.input.position())
        # We start a new group, parsing the equation number, then we pop it off during the 
        # mathShift function before ending the math mode.
        eqno = Subformula()
        eqno_builder = MList(parser, eqno.list)
        parser.lists.append(eqno_builder)
        mlist.eqno = (eqno, self.left)
        parser.beginGroup(
            parser.input.position(),
            GROUP_TYPE.MATH_SHIFT,
            ended=callback,
        )


class VCent(Box):
    """
    a vcent box
    """
    def __init__(self, box):
        super().__init__(box)
        self.atom_type = ATOM_TYPE.VCENT
    
    def saveInfo(self):
        init, extra = super().saveInfo() 
        return init | {"box": self.nucleus}, extra

    def typesetNucleus(self, parser, packed, context, style):
        # \vcenter is built as a raw vbox; ensure dimensions are realized
        # before centering around the math axis.
        box = self.nucleus.typeset(parser)
        height = box.height if box.height is not None else Dimen()
        depth = box.depth if box.depth is not None else Dimen()
        v = height + depth
        a = Dimen(mathsigma(parser, style)[21])
        half = v / 2
        box.height = half + a
        box.depth = half - a
        packed.append(box)
        return Dimen()


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
        super().__init__(Glue(), None)
        self.nonscript = True

    def saveInfo(self):
        return {}, None


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

    def typesetNucleus(self, parser, packed, context, style: Style):
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
            x = x.typeset(parser)
        theta = Dimen(mathxi(parser, style)[7])
        if self.atom_type == ATOM_TYPE.OVER:
            vbox = Atom.overbar(parser, x, 3 * theta, theta)
        else:
            vbox = box.VBox(parser, None, 0)
            kern1 = nd.Kern(theta)
            rule = nd.Rule(NEG_MAX_DIMEN, theta, 0)
            kern2 = nd.Kern(3*theta)
            vbox.list[:] = [x, kern2, rule, kern1]
            vbox = vbox.typeset(parser)
        packed.append(vbox)
        return Dimen()


class VolatileParameterAccessor(Accessor, DimenCommand):
    target_type = VALUE_TYPE.DIMEN

    def __init__(self, index):
        super().__init__(None, index)
        self.index = index

    def saveInfo(self):
        return {"name": self.name}, None

    def readValue(self, parser):
        return parser.readDimen()

    def getTarget(self, parser):
        pos = parser.input.position()
        return AttrTarget(VolatileParameterSlot(parser, self.index, pos), "value", self.target_type)
    
    def set(self, parser, value):
        self.getTarget(parser).set(value, global_scope=False)
    
    def setGlobal(self, parser, value):
        self.getTarget(parser).set(value, global_scope=True)
    
    def dimenValue(self, parser):
        value = parser.volatile[self.index]
        if value is not None:
            return value
        # when this is accessed here, we are in building a list. So we use parser.paragraph_before_last_display_math
        # if this paragraph does not exist, then the value has not been changed. we should have returned early
        para = parser.paragraph_before_last_display_math
        assert para is not None
        para.typeset(parser, [])
        return parser.volatile[self.index]


class VolatileParameterSlot:
    def __init__(self, parser, index, pos):
        self.parser = parser
        self.index = index
        self.pos = pos

    @property
    def value(self):
        value = self.parser.volatile[self.index]
        if value is not None:
            return value
        para = self.parser.paragraph_before_last_display_math
        assert para is not None
        para.typeset(self.parser, [])
        value = self.parser.volatile[self.index]
        if value is None:
            raise ValueError(f"volatile parameter {self.index} is undefined", self.pos)
        return value

    @value.setter
    def value(self, new_value):
        self.parser.volatile[self.index] = new_value

    
mod = Module("mmode",
    attributes= {
        "mathShift": mathShift,
        "subscript": subscript,
        "superscript": superscript,
        "paragraph_before_last_display_math": None,
    },
    commands= {
        "mathchar": MathChar(),
        "mathchardef": mathchardef,
        "mkern": MKern(),
        "mskip": MSkip(),
        "mathord": MathAtom(ATOM_TYPE.ORD),
        "mathop": MathAtom(generator=Op),
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
        "predisplaysize": VolatileParameterAccessor("predisplaysize"),
        "displaywidth": VolatileParameterAccessor("displaywidth"),
        "displayindent": VolatileParameterAccessor("displayindent"),
    },
    parameters={
        # these values are automatically set by the parser, and are volatile. But they are subject to
        # grouping. So they are in the volatile domain, and will not be dumped in a format.
        "predisplaysize": {"value": Dimen(), "accessor": None, "domain": "volatile"},
        "displaywidth": {"value": Dimen(), "accessor": None, "domain": "volatile"},
        "displayindent": {"value": Dimen(), "accessor": None, "domain": "volatile"},
    },
)
