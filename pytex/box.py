"""
parse and wrap up an hbox
"""

from pytex import node as nd
from pytex import hmode
from pytex import vmode
from pytex.glue import Glue
from pytex.module import Module
from pytex.accessor import Accessor, ArrayAccessor, VALUE_TYPE
from pytex.state import Array
from pytex.token import Command, CATCODE
from pytex.dimen import Dimen, DimenCommand
from pytex.integer import IntegerArrayItemAccessor
from pytex import conditional
from pytex.state import GROUP_TYPE
from pytex.lists import LISTTYPE, ModeDependentCommand, GlueCommand
from pytex.lexer import TokenListScanner
import enum
import types


class GlueRatio(tuple):
    """
    Tuple-compatible glue ratio with legacy numeric conversion support.
    """
    __slots__ = ()

    def __new__(cls, sign=0, num=0, den=1):
        sign = int(sign)
        num = int(num)
        den = int(den) if int(den) != 0 else 1
        if sign == 0 or num == 0:
            sign, num, den = 0, 0, 1
        return super().__new__(cls, (sign, num, den))

    def __float__(self):
        sign, num, den = self
        if sign == 0 or num == 0 or den == 0:
            return 0.0
        return (sign * num) / den


class Box(nd.Box):
    """
    the base class for \\hbox, \\vbox, and \\vtop
    @param to: the target width or height
    @param spread: the spread
    """
    def __init__(self, parser, to, spread):
        super().__init__(None, None, None)
        self.parser = parser
        self.to = None if to is None else Dimen(to)
        self.spread = None if spread is None else Dimen(spread)
        self.list = []
        self.shifted = 0
        self.natural = None
        # (sign, num, den), representing sign * num / den.
        # sign is -1, 0, or 1; num >= 0; den >= 1.
        self.glue_ratio = GlueRatio(0, 0, 1)
        self._packed = None

    def saveInfo(self):
        packed = None if self._packed == self else self._packed
        return {
                "to": self.to, 
                "spread": self.spread, 
            }, {
                "list": self.list,
                "width": self.width,
                "height": self.height,
                "depth": self.depth,
                "shifted": self.shifted,
                "_packed": packed,
            }
    
    @classmethod
    def new(cls, parser, **kargs):
        box = cls(parser, **kargs)
        if box._packed is None and getattr(box, "width") is not None:
            box._packed = box
        return box
    
    @staticmethod
    def _ratioParts(glue_ratio):
        if isinstance(glue_ratio, tuple):
            sign, num, den = glue_ratio
            sign = int(sign)
            num = int(num)
            den = int(den)
            if sign == 0 or num == 0:
                return 0, 0, 1
            if den == 0:
                return 0, 0, 1
            return (1 if sign > 0 else -1), abs(num), abs(den)
        if glue_ratio is None:
            return 0, 0, 1
        value = int(glue_ratio)
        if value == 0:
            return 0, 0, 1
        return (1 if value > 0 else -1), abs(value), Dimen.scale

    @classmethod
    def ratioDimen(cls, glue_ratio):
        sign, num, den = cls._ratioParts(glue_ratio)
        if sign == 0:
            return Dimen()
        return Dimen(integer=Dimen._trunc_div(sign * num * Dimen.scale, den))

    def _setGlueRatio(self, spread, natural):
        if spread is None:
            self.glue_ratio = GlueRatio(0, 0, 1)
            return
        if spread > 0:
            den = int(natural.stretch.factor)
            if den != 0:
                self.glue_ratio = GlueRatio(1, int(spread), den)
                return
        elif spread < 0:
            den = int(natural.shrink.factor)
            if den != 0:
                self.glue_ratio = GlueRatio(-1, -int(spread), den)
                return
        self.glue_ratio = GlueRatio(0, 0, 1)

    def typeset(self, parser, packed=None):
        """
        typeset the box
        @param parser: the parser
        @param packed: if provided, append this node and skip in-place typesetting.
        """
        if self._packed is None:
            self._typesetSelf(parser)
        if packed is None:
            return self._packed
        packed.append(self._packed)

    def _typesetSelf(self, parser):
        raise NotImplementedError("this method should be implemented in subclasses")

    @staticmethod
    def _set_badness(parser, spread, natural):
        state = parser.globals
        if spread == 0:
            state["badness"] = 0
            return
        if spread > 0:
            stretch = natural.stretch
            if stretch.factor == 0:
                state["badness"] = 10000
                return
            if stretch.order > 0:
                state["badness"] = 0
                return
            num = int(spread)
            den = int(stretch.factor)
        else:
            shrink = natural.shrink
            if shrink.factor == 0:
                state["badness"] = 1000000
                return
            if shrink.order > 0:
                state["badness"] = 0
                return
            num = -int(spread)
            den = int(shrink.factor)
            if num > den:
                state["badness"] = 1000000
                return
        bad = (100 * num * num * num + (den * den * den) // 2) // (den * den * den)
        state["badness"] = min(10000, bad)

    def _expand(self, parser, content, node):
        """
        Expand the current list and collect nodes/glues/migratory nodes.
        """
        typeset = node.typeset
        if typeset is None:
            content.append(node)
            return
        start = len(content)
        typeset(parser, content)
        if len(content) == start:
            content.append(node)
            return
        for n in content[start:]:
            if n is node:
                continue
            if getattr(n, "source", None) is None:
                n.source = node

    def copy(self, content=None):
        """
        return a copy of the box
        """
        BoxType = type(self)
        box = BoxType(self.parser, self.to, self.spread)
        box.width = self.width
        box.height = self.height
        box.depth = self.depth
        box.shifted = self.shifted
        if content is None:
            box.list = self.list
        else:
            normalized = []
            for node in content:
                packed = getattr(node, "_packed", None)
                if packed is not None and packed is not node:
                    node = packed
                normalized.append(node)
            box.list[:] = normalized
        box.source = self.source
        box.natural = self.natural
        box.glue_ratio = self.glue_ratio
        if content is not None:
            box._packed = box
        return box


class BadnessAccessor(IntegerArrayItemAccessor):
    """
    Lazily realize the most recent box pack when \\badness is inspected.
    """
    def intValue(self, parser):
        box = parser.lastbox
        if box is not None:
            parser.lastbox = None
            if box._packed is None:
                box.typeset(parser)
        return super().intValue(parser)

    def set(self, parser, value):
        parser.lastbox = None
        super().set(parser, value)

    def setGlobal(self, parser, value):
        parser.lastbox = None
        super().setGlobal(parser, value)


class HBox(Box, hmode.HListHolder):
    """
    A horizontal box.
    @param to: the target width
    @param spread: the spread
    """
    def __init__(self, parser, to, spread):
        super().__init__(parser, to, spread)
        hmode.HListHolder.__init__(self, self.list)
        self.migratory = []

    init_needs_parser = True

    node_type = nd.NODE_TYPE.HLIST

    def _typesetSelf(self, parser):
        if self._packed is not None:
            # it has been typeset. do nothing
            return
        self.raw = self.list
        content = []
        typeset_nodes = getattr(self.list, "typesetNodes", None)
        if typeset_nodes is None:
            self.typesetNodes(parser, content)
        else:
            typeset_nodes(parser, content)
        glues = []
        natural = Glue()
        self.width = Dimen()
        self.height = Dimen()
        self.depth = Dimen()
        for n in content:
            node_type = n.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                glues.append(n)
                natural += n.glue
            elif node_type == nd.NODE_TYPE.KERN:
                natural.dimen += n.kern
            elif isinstance(n, nd.Box):
                shifted = getattr(n, "shifted", 0)
                w = n.width
                h = n.height - shifted
                d = n.depth + shifted
                natural = self.calculate(n, natural, (w, h, d))
            elif n.node_type in (nd.NODE_TYPE.ADJUST, nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS):
                self.migratory.append(n)
            else:
                natural = self.calculate(n, natural, None)
        # calculate the ratio
        if self.spread is None:
            if self.to is None:
                self.to = natural.dimen
            self.spread = self.to - natural.dimen
        elif self.to is None:
            self.to = self.spread + natural.dimen
        spread = self.spread
        if self.to is None:
            self.to = natural.dimen + self.spread
        self._setGlueRatio(spread, natural)
        self.natural = natural
        self._set_badness(parser, spread, natural)
        self.width = self.to
        self.list = content
        self._packed = self
    
    def calculate(self, node, natural, dim):
        if dim is None:
            # node is something else.
            if node.node_type == nd.NODE_TYPE.DISC:
                w = node.replace_width
                h = Dimen()
                d = Dimen()
                for sub in node.replace:
                    if sub.node_type == nd.NODE_TYPE.KERN:
                        continue
                    sh = getattr(sub, "height", None)
                    sd = getattr(sub, "depth", None)
                    if sh is not None and sh > h:
                        h = sh
                    if sd is not None and sd > d:
                        d = sd
                dim = (w, h, d)
            elif node.node_type == nd.NODE_TYPE.MATH:
                natural.dimen += node.kern # .kern has been set by MList.typeset
                return natural
            else:
                return natural
        w, h, d = dim
        natural.dimen += w
        if self.height is None or h > float(self.height):
            self.height = h
        if self.depth is None or d > float(self.depth):
            self.depth = d
        return natural
    
    def typeset(self, parser, packed=None):
        x = super().typeset(parser, packed)
        self.width = self.to
        return x

    def rightmost(self):
        # finf the right edge of the rightmost box
        w = self.width
        sign, num, den = self._ratioParts(self.glue_ratio)
        use_stretch = False
        order = 0
        if self.spread > 0:
            use_stretch = True
            order = self.natural.stretch.order
        else:
            order = self.natural.shrink.order
        if self.spread > 0 and sign <= 0:
            num = 0
            den = 1
        elif self.spread < 0 and sign >= 0:
            num = 0
            den = 1
        for node in reversed(self.list):
            node_type = node.node_type
            if node_type == nd.NODE_TYPE.KERN:
                w -= node.kern
            elif node_type == nd.NODE_TYPE.GLUE:
                glue = node.glue
                ss = glue.stretch if use_stretch else glue.shrink
                if ss.order < order:
                    continue
                extra = Dimen()
                if num != 0:
                    extra = Dimen(integer=Dimen._trunc_div(int(ss.factor) * num, den))
                w -= glue.dimen + extra
            else:
                nw = getattr(node, "width", None)
                if nw is not None:
                    break
        return w

    def __repr__(self):
        return f"HBox({self.width}, {self.height}, {self.depth}, {self.list})"


class BoxCommand(Command):
    """
    the \\box or \\copy command
    @param wipe whether to wipe the box register after use
    """
    def __init__(self, wipe: bool=False):
        self.wipe = wipe
    
    def execute(self, parser):
        box = self.boxValue(parser, False)
        if box is None:
            return
        parser.lists[-1].append(box)
    
    def boxValue(self, parser, setbox):
        index = parser.readInteger()
        box = parser.box[index]
        if self.wipe:
            parser.box[index] = None
            return box
        return box.copy()    


def readBoxSpec(parser, keywords=["to", "spread"]):
    """
    read the to/spread spec from the input stack
    @param parser: the parser
    @return: a tuple (to, spread)
    """
    spec = parser.readKeyword(keywords)
    if spec is None:
        return None, Dimen()
    dim = parser.readDimen()
    return spec, dim


class ListEndCallback:
    def __call__(self, parser):
        state = parser.lists.pop()
        if getattr(state, "type", None) == LISTTYPE.VERTICAL:
            parser.globals["prevdepth"] = state.saved_prevdepth


class ReadBoxEndCallback(ListEndCallback):
    def __init__(self, box):
        self.box = box
        self.finished = False

    def __call__(self, parser):
        super().__call__(parser)
        parser.lastbox = self.box
        self.finished = True
        parser.run = False


class BoxPretypesetCallback:
    def __init__(self, box):
        self.box = box

    def __call__(self, parser):
        if self.box.node_type == nd.NODE_TYPE.VLIST:
            top = parser.lists[-1]
            if top.type == LISTTYPE.HORIZONTAL and not top.inner:
                parser.endParagraph()
        self.box = self.box.typeset(parser)


class BuildBox(Command):
    """
    the base class for \\hbox, \\vbox and \\vtop commands
    """
    def box(self):
        """
        create a new box
        """
        raise NotImplementedError
    
    group_type = None # howto start the group
    vertical = None
    
    def execute(self, parser):
        top = parser.lists[-1]
        box = self.boxValue(parser, False)
        top.append(box)

    def boxValue(self, parser, setbox):
        spec, d = readBoxSpec(parser)
        box = self.box(parser, d, None) if spec == "to" else self.box(parser, None, d)
        to_end = BoxPretypesetCallback(box)
        parser.skipFiller()
        t = parser.token_expand()
        t = parser.token_meaning(t)
        if t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a {", parser.input.position())
        if self.vertical:
            state = vmode.VList(parser, box.list, inner=True)
        else:
            state = hmode.HList(parser, box.list, inner=True)
        parser.lists.append(state)
        state.group_type = self.group_type
        every = parser.everyvbox.value if self.vertical else parser.everyhbox.value
        if every:
            parser.input.push(TokenListScanner(every))
            if parser.tracingcommands > 0 and parser.checkRange():
                parser.message(f"every{'v' if self.vertical else 'h'}box: {parser.toksToString(every)}")
        if not setbox:
            callback = ReadBoxEndCallback(box)
            parser.beginGroup(parser.input.position(), self.group_type, to_end=to_end, ended=callback)
            parser.loop()
            if callback.finished:
                parser.run = True
        return box


class HBoxCommand(BuildBox):
    """
    the \\hbox command
    """
    def box(self, parser, to, spread):
        return HBox(parser, to, spread)
    
    group_type = GROUP_TYPE.HBOX
    vertical = False
    

def readBox(parser, setbox=False): 
    """
    read a box from the input stack
    @param parser: the parser
    @param setbox: whether the this function is called from setbox
    """
    box_value = getattr(parser.token_expand().definition, "boxValue", None)
    if box_value is None:
        raise ValueError("expecting a box", parser.input.position())
    return box_value(parser, setbox)
    

class SetBoxEndCallback:
    def __init__(self, accessor, box):
        self.accessor = accessor
        self.box = box

    def __call__(self, parser):
        state = parser.lists.pop()
        if getattr(state, "type", None) == LISTTYPE.VERTICAL:
            parser.globals["prevdepth"] = state.saved_prevdepth
        self.box = self.box.typeset(parser)
        parser.lastbox = self.box
        self.accessor._set(parser)


class BoxArrayItemAccessor(Accessor):
    target_type = VALUE_TYPE.BOX

    def readKey(self, parser):
        return parser.readInteger()

    def readValue(self, parser):
        return readBox(parser, setbox=True)
    
    def set(self, parser, value):
        # the actualy value setting is done in assign
        self.value = (self.currentKey(parser), value, False)

    def setGlobal(self, parser, value):
        # the actualy value setting is done in assign
        self.value = (self.currentKey(parser), value, True)

    def _set(self, parser):
        key, value, globally = self.value
        if globally:
            parser.set(self.domain.name, key, global_scope=True, value=value)
        else:
            parser.set(self.domain.name, key, value=value)

    def assign(self, parser, prefixes):
        if self.key is None and self.needsKey():
            return self.bindKey(self.readKey(parser)).assign(parser, prefixes)
        top = parser.lists[-1]
        super().assign(parser, prefixes)
        new = parser.lists[-1]
        if new is not top:
            # we are reading a list, but the group has not started yet to accommodate \afterassignment
            value = self.value[1]
            to_end = BoxPretypesetCallback(value)
            parser.beginGroup(
                parser.input.position(),
                new.group_type,
                to_end=to_end,
                ended=SetBoxEndCallback(self, self.value[1]),
            )
        else:
            self._set(parser)

class IfBox(conditional.Conditional):
    """
    The \\ifinner command.
    """
    def __init__(self, type):
        self.type = type

    def condition(self, parser):
        index = parser.readInteger()
        box = parser.box[index]
        if self.type is None:
            return 0 if box is None else 1
        return 0 if isinstance(box, self.type) else 1


class VBox(Box, vmode.VListHolder):
    """
    A vertical box.
    @param to: the target height
    @param spread: the spread
    @param vtop: whether the box is a vtop
    """
    def __init__(self, parser, to, spread):
        super().__init__(parser, to, spread)
        vmode.VListHolder.__init__(self, self.list)
        self.expanded = []
        self.boxmaxdepth = parser.layout["boxmaxdepth"]

    init_needs_parser = True

    node_type = nd.NODE_TYPE.VLIST  

    def calculate(self, node, natural, dim):
        if dim is None:
            return natural
        w, h, d = dim
        shifted = getattr(node, "shifted", 0)
        w = max(Dimen(), w + shifted)
        if self.width is None or w > float(self.width):
            self.width = w
        return natural

    def typeset(self, parser, packed=None, maxdepth=None):
        if self._packed is not None:
            if packed is not None:
                packed.append(self._packed)
            return self._packed
        content = self.list
        natural = Glue()
        self.width = Dimen()
        self.height = Dimen()
        self.depth = Dimen()
        last_depth = Dimen()
        for n in content:
            node_type = n.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                natural += n.glue
                natural.dimen += last_depth
                last_depth = Dimen()
                continue
            if node_type == nd.NODE_TYPE.KERN:
                natural.dimen += n.kern + last_depth
                last_depth = Dimen()
                continue
            if isinstance(n, nd.Box):
                w = n.width
                h = n.height
                d = n.depth
                natural = self.calculate(n, natural, (w, h, d))
                natural.dimen += h + last_depth
                last_depth = d
                continue
            self.calculate(n, natural, None)
        self.depth = last_depth
        if maxdepth is None:
            maxdepth = parser.layout["boxmaxdepth"]
        if self.depth > maxdepth:
            natural.dimen += self.depth - maxdepth
            self.depth = maxdepth
        if self.spread is None:
            if self.to is None:
                self.to = natural.dimen
            self.spread = self.to - natural.dimen
        elif self.to is None:
            self.to = self.spread + natural.dimen
        spread = self.spread
        self._setGlueRatio(spread, natural)
        self.natural = natural
        self._set_badness(parser, spread, natural)
        self.height = self.to
        self._packed = self
        if packed is not None:
            packed.append(self._packed)
        return self._packed


    def copy(self, content=None):
        box = super().copy(content)
        if content is None and self._packed is self:
            box._packed = box
        return box

    def __repr__(self):
        return f"VBox({self.width}, {self.height}, {self.depth}, {self.list})"


class VTop(VBox):
    def typeset(self, parser, packed=None):
        box = super().typeset(parser, packed)
        total = self.height + self.depth
        first = self._packed.list[0] if self._packed.list else None
        box.height = self.height = getattr(first, "height", 0)
        box.depth = self.depth = total - self.height
        return box


class VBoxCommand(BuildBox):
    """
    the \\vbox command
    """
    def box(self, parser, to, spread):
        return VBox(parser, to, spread)
    
    vertical = True
    group_type = GROUP_TYPE.VBOX
    

class VTopCommand(VBoxCommand):
    """
    the \\vtop command
    """
    def box(self, parser, to, spread):
        return VTop(parser, to, spread)
    
    group_type = GROUP_TYPE.VTOP


class BoxDimenAccessor(Accessor, DimenCommand):
    target_type = VALUE_TYPE.DIMEN

    def readValue(self, parser):
        return parser.readDimen()

    def set(self, parser, value):
        assert self.domain is not None
        setattr(self.domain, self.key, value)

    def setGlobal(self, parser, value):
        assert self.domain is not None
        setattr(self.domain, self.key, value)

    def dimenValue(self, parser):
        box = self.domain
        if box is None:
            return Dimen()
        d = getattr(box, self.key, None)
        if d is None:
            box = box.typeset(parser)
            d = getattr(box, self.key)
        return d


class BoxDimenCommand(ArrayAccessor, DimenCommand):
    """
    a command that accesses a dimension for a box
    @param domain the attribute of the box dimension
    """
    def __init__(self, domain):
        super().__init__(domain)

    def getItemAccessor(self, parser):
        return BoxDimenAccessor(parser.box[parser.readInteger()], self.domain)
    
    def dimenValue(self, parser):
        return self.getItemAccessor(parser).dimenValue(parser)


class UnBox(Command):
    """
    the \\un[hv]box and \\un[hv]copy commands
    @param vertical whether the command is vertical
    @param wipe whether to wipe the box register after use
    """
    def __init__(self, vertical: bool, wipe: bool):
        self.vertical = vertical
        self.wipe = wipe

    def execute(self, parser):
        top = parser.lists[-1]
        if (not self.vertical) and top.type == LISTTYPE.VERTICAL:
            # Horizontal unboxing commands in vertical mode start a paragraph.
            # This is required for \leavevmode, which LaTeX defines as
            # \unhbox\voidb@x.
            if parser.current_token is not None:
                parser.input.unread(parser.current_token)
            parser.newParagraph(indent=False)
            return
        index = parser.readInteger()
        if index < 0:
            raise ValueError("box index out of range", parser.input.position())
        box = parser.box[index]
        if self.wipe:
            parser.box[index] = None
        if box is None:
            return
        top = parser.lists[-1]
        if top.type == LISTTYPE.MATH and not self.vertical:
            raise ValueError("the box must be void in math mode", parser.input.position())
        if (self.vertical and top.type != LISTTYPE.VERTICAL) or (
            not self.vertical and top.type != LISTTYPE.HORIZONTAL):
            raise ValueError("wrong mode", parser.input.position())
        if self.vertical and box.node_type != nd.NODE_TYPE.VLIST:
            raise ValueError("expecting a vbox", parser.input.position())
        if not self.vertical and box.node_type != nd.NODE_TYPE.HLIST:
            raise ValueError("expecting an hbox", parser.input.position())
        nodes = box.list
        for node in nodes:
            node.source = box
        if top.type == LISTTYPE.VERTICAL:
            top.extend(nodes, add_interline=False)
        else:
            top.extend(nodes)


class Shift(ModeDependentCommand):
    """
    The \\raise, \\lower, \\moveleft, \\moveright command.
    @param vertical whether the command is vertical (\\moveleft, \\moveright) or
    horizontal (\\raise, \\lower)
    @param direction: the direction of the shift (-1, or 1). Here +1 means right or down,
    and -1 means left or up.
    """
    def __init__(self, vertical: bool, direction: int):
        self.is_vertical = vertical
        self.direction = direction
    
    def horizontal(self, parser, hlist):
        if self.is_vertical:
            super().horizontal(parser, hlist)
        hlist.append(self.shift(parser))
    
    def vertical(self, parser, vlist):
        if not self.is_vertical:
            super().vertical(parser, vlist)
        vlist.append(self.shift(parser))
    
    def math(self, parser, mlist):
        if self.is_vertical:
            super().math(parser, mlist)
        box = self.shift(parser)
        mlist.append(box)
    
    def shift(self, parser):
        """
        read the shift value and box, then return the shifted box
        """
        shift = parser.readDimen()
        box = parser.readBox()
        shifted = shift * self.direction
        box.shifted = shifted
        packed = getattr(box, "_packed", None)
        if packed is not None:
            packed.shifted = shifted
        return box


class AccentBox(Box):
    """
    An accent box.
    """
    def __init__(self, accent):
        super().__init__(None, None, None)
        self.list.append(accent)
        self.accent = accent
        self.width = accent.width
        self.height = accent.height
        self.depth = accent.depth
        self.typeset = None

    node_type = nd.NODE_TYPE.HLIST

    def saveInfo(self):
        return {"accent": self.accent}, None


class AccentNode(nd.Node):
    """
    An accent node.
    """
    def __init__(self, accent, base):
        self.accent = accent
        self.base = base

    def saveInfo(self):
        return {"accent": self.accent, "base": self.base}, None
    
    node_type = nd.NODE_TYPE.ACCENT

    def typeset(self, parser, packed):
        if packed is None:
            raise ValueError("typeset requires a packed list")
        nodes = packed
        char, accent = self.base, self.accent
        if char is None:
            nodes.append(accent)
            return
        # TeX \accent positioning in horizontal mode:
        # dx = 1/2 (w(base) - w(accent)) + slant * (h(base) - xheight).
        # The accent glyph is raised/lowered by xheight - h(base), if negative.
        font = char.font
        slant = Dimen(font.param[0])   # \fontdimen1
        ex = Dimen(font.param[4])      # \fontdimen5 (x-height)
        dx = (char.width - accent.width) / 2 + slant * (char.height - ex)
        if dx != 0:
            nodes.append(nd.Kern(dx))
        accentbox = AccentBox(accent)
        dy = ex - char.height
        if dy < 0:
            accentbox.shifted = dy
        nodes.append(accentbox)
        # Backspace by the accent advance, preserving total width as w(base).
        nodes.append(nd.Kern(-dx - accent.width))
        nodes.append(char)
        return


class IndentBox(Box):
    """
    An indent box.
    """
    def __init__(self, parser):
        super().__init__(parser, None, None)
        self.width = parser.parameters["parindent"]
        self.height = Dimen()
        self.depth = Dimen()
        self.typeset = None

    def saveInfo(self):
        return {}, None
    
    init_needs_parser = True

    node_type = nd.NODE_TYPE.HLIST


class LEADERS_TYPE(enum.Enum):
    LEADERS = 0
    CLEADERS = 1
    XLEADERS = 2


def _appendLeader(parser, type, box):
    t = parser.token_expand().definition
    if t is None or not isinstance(t, GlueCommand):
        raise ValueError("expecting a glue", parser.input.position())
    top = parser.lists[-1]
    if (t.vert and top.type == LISTTYPE.VERTICAL) or (not t.vert and top.type != LISTTYPE.VERTICAL):
        glue = t.glueValue(parser)
    else:
        raise ValueError("glue in the wrong mode", parser.input.position())
    node = nd.Glue(glue, t.name)
    node.leaders = (type, box)
    parser.lists[-1].append(node)


class LeaderBoxCallback:
    def __init__(self, type, box):
        self.type = type
        self.box = box

    def __call__(self, parser):
        state = parser.lists.pop()
        if getattr(state, "type", None) == LISTTYPE.VERTICAL:
            parser.globals["prevdepth"] = state.saved_prevdepth
        parser.lastbox = self.box
        _appendLeader(parser, self.type, self.box)


class Leaders(Command):
    """
    The \\leaders, \\cleaders and \\xleaders command.
    """
    def __init__(self, type: LEADERS_TYPE):
        self.type = type

    def execute(self, parser):
        top = parser.lists[-1]
        # read a rule
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting a rule or a box", parser.input.position())
        if isinstance(t, nd.Rule):
            if (t.vert and top.type == LISTTYPE.VERTICAL) or (not t.vert and top.type != LISTTYPE.VERTICAL):
                box = t.readRule(parser)
            else:
                raise ValueError("rule in the wrong mode", parser.input.position())
            _appendLeader(parser, self.type, box)
            return
        # box
        top = parser.lists[-1]
        box_value = getattr(t.definition, "boxValue", None)
        if box_value is None:
            raise ValueError("expecting a rule or a box", parser.input.position())
        box = box_value(parser, setbox=True)
        if (box.node_type == nd.NODE_TYPE.HLIST and top.type == LISTTYPE.VERTICAL) or (box.node_type == nd.NODE_TYPE.VLIST and top.type != LISTTYPE.VERTICAL):
            raise ValueError("box in the wrong mode", parser.input.position())
        new = parser.lists[-1]
        if new is not top:
            # we are reading a list, but the group has not started yet to accommodate \afterassignment
            parser.beginGroup(
                parser.input.position(),
                new.group_type,
                ended=LeaderBoxCallback(self.type, box),
            )
        else:
            _appendLeader(parser, self.type, box)
 

class LastBox(Command):
    """
    The \\lastbox command.
    """
    def boxValue(self, parser, setbox):
        top = parser.lists[-1]
        # this command can only be unsed in horizontal mode or in ner vertical mode
        if top.type == LISTTYPE.VERTICAL and not top.inner:
            if len(top.list) == 0:
                raise ValueError("\\lastbox cannot be used in the main vertical list", parser.input.position())
        if top.type == LISTTYPE.MATH:
            raise ValueError("\\lastbox cannot be used in math mode", parser.input.position())
        return top.pop() if top and isinstance(top[-1], Box) else None
    
    def execute(self, parser):
        self.boxValue(parser, False)


mod = Module("hbox", 
    domains={
        "box": {"generator": lambda state: Array("box", state), "accessor": BoxArrayItemAccessor},
    },
    parameters={
        "badness": {"value": 0, "accessor": BadnessAccessor, "domain": "globals"},
    },
    attributes={
        "readBox": readBox,
        "readBoxSpec": readBoxSpec,
    },
    commands={
        "box": BoxCommand(True),
        "copy": BoxCommand(False),
        "ifvoid": IfBox(None),
        "ifhbox": IfBox(HBox),
        "ifvbox": IfBox(VBox),
        "hbox": HBoxCommand(),
        "vbox": VBoxCommand(),
        "vtop": VTopCommand(),
        "wd": BoxDimenCommand("width"),
        "ht": BoxDimenCommand("height"),
        "dp": BoxDimenCommand("depth"),
        "unhbox": UnBox(False, True),
        "unvbox": UnBox(True, True),
        "unhcopy": UnBox(False, False),
        "unvcopy": UnBox(True, False),
        "raise": Shift(False, -1),
        "lower": Shift(False, 1),
        "moveleft": Shift(True, -1),
        "moveright": Shift(True, 1),
        "leaders": Leaders(LEADERS_TYPE.LEADERS),
        "cleaders": Leaders(LEADERS_TYPE.CLEADERS),
        "xleaders": Leaders(LEADERS_TYPE.XLEADERS),
        "lastbox": LastBox(),
    }
)
