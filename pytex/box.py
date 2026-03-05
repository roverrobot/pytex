"""
parse and wrap up an hbox
"""

from pytex import node as nd
from pytex import hmode
from pytex import vmode
from pytex.glue import Glue
from pytex.module import Module
from pytex.accessor import Accessor, ArrayAccessor, ArrayItemAccessor
from pytex.state import Array
from pytex.token import Command, CATCODE
from pytex.dimen import Dimen, DimenCommand, DimenArrayAccessor
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


class VBoxTypesetContext:
    """
    Snapshot of vbox-local layout parameters needed for lazy typesetting.
    """
    def __init__(self, layout):
        self.boxmaxdepth = layout["boxmaxdepth"]


class Box(nd.Box):
    """
    the base class for \\hbox, \\vbox, and \\vtop
    @param to: the target width or height
    @param spread: the spread
    """
    def __init__(self, parser, to, spread, list=None):
        super().__init__(None, None, None)
        self.parser = parser
        self.to = None if to is None else Dimen(to)
        self.spread = None if spread is None else Dimen(spread)
        self.list = list
        self.shifted = 0
        self.natural = None
        # (sign, num, den), representing sign * num / den.
        # sign is -1, 0, or 1; num >= 0; den >= 1.
        self.glue_ratio = GlueRatio(0, 0, 1)
        self._typeset_cache = None

    def saveInfo(self):
        return {
            "init": {
                "to": self.to, 
                "spread": self.spread, 
            },
            "extra": {
                "shifted": self.shifted,
                "list": self.list,
                "glue_ratio": self.glue_ratio,
            }
        }

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
        self.pretypeset(parser)
        if packed is None:
            return self._typeset_cache
        packed.append(self._typeset_cache)

    def pretypeset(self, parser):
        raise NotImplementedError("this method should be implemented in subclasses")

    @staticmethod
    def _set_badness(parser, spread, natural):
        state = parser.state.globals
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
            box.list[:] = content
        box.source = self.source
        box.natural = self.natural
        box.glue_ratio = self.glue_ratio
        if content is not None:
            if hasattr(box, "typeset_context"):
                box.typeset_context = None
            box._typeset_cache = box
        return box


class BadnessAccessor(IntegerArrayItemAccessor):
    """
    Lazily realize the most recent box pack when \\badness is inspected.
    """
    def intValue(self, parser):
        box = parser.lastbox
        if box is not None:
            parser.lastbox = None
            if box._typeset_cache is None:
                box.pretypeset(parser)
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
        super().__init__(parser, to, spread, [])
        hmode.HListHolder.__init__(self, self.list)

    @classmethod
    def new(cls, parser, **kwargs):
        return cls(parser, kwargs["to"], kwargs["spread"])

    node_type = nd.NODE_TYPE.HLIST

    def pretypeset(self, parser):
        if self._typeset_cache is not None:
            # it has been typeset. do nothing
            return
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
                shifted = n.shifted if n.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST) else 0
                w = n.width
                h = n.height - shifted
                d = n.depth + shifted
                natural = self.calculate(n, natural, (w, h, d))
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
        self._typeset_cache = self.copy(content)
    
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
        if packed is not None:
            for n in self.list:
                if n.node_type in (nd.NODE_TYPE.ADJUST, nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS):
                    packed.append(n)
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
        box = parser.state.box[index]
        if self.wipe:
            parser.state.box[index] = None
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
    def __init__(self, parser):
        self.parser = parser
    
    def __call__(self):
        self.parser.lists.pop()


class ReadBoxEndCallback(ListEndCallback):
    def __init__(self, parser, box):
        super().__init__(parser)
        self.box = box
        self.finished = False

    def __call__(self):
        super().__call__()
        self.parser.lastbox = self.box
        self.finished = True
        self.parser.run = False


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
        parser.skipFiller()
        t = parser.token_expand()
        t = parser.token_meaning(t)
        if t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a {", parser.input.position())
        if self.vertical:
            state = parser.wrapBuildState(box.list)
        else:
            state = hmode.HList(parser, inner=True, node=box.list)
        parser.lists.append(state)
        state.group_type = self.group_type
        every = parser.everyvbox.value if self.vertical else parser.everyhbox.value
        if every:
            parser.input.push(TokenListScanner(every))
            if parser.tracingcommands > 0 and parser.checkRange():
                parser.message(f"every{'v' if self.vertical else 'h'}box: {parser.toksToString(every)}")
        if not setbox:
            callback = ReadBoxEndCallback(parser, box)
            parser.beginGroup(parser.input.position(), self.group_type, ended=callback)
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
    def __init__(self, parser, accessor, box):
        self.parser = parser
        self.accessor = accessor
        self.box = box

    def __call__(self):
        self.parser.lists.pop()
        self.parser.lastbox = self.box
        self.accessor._set(self.parser)



class BoxArrayItemAccessor(ArrayItemAccessor):
    def readValue(self, parser):
        return readBox(parser, setbox=True)
    
    def set(self, parser, value):
        # the actualy value setting is done in assign
        self.value = (value, False)

    def setGlobal(self, parser, value):
        # the actualy value setting is done in assign
        self.value = (value, True)

    def _set(self, parser):
        value, globally = self.value
        if globally:
            super().setGlobal(parser, value)
        else:
            super().set(parser, value)

    def assign(self, parser, prefixes):
        top = parser.lists[-1]
        super().assign(parser, prefixes)
        new = parser.lists[-1]
        if new is not top:
            # we are reading a list, but the group has not started yet to accommodate \afterassignment
            parser.beginGroup(
                parser.input.position(),
                new.group_type,
                ended=SetBoxEndCallback(parser, self, self.value[0]),
            )
        else:
            self._set(parser)
    

class BoxArray(Array):
    """
    an array of boxes
    """
    def __init__(self, state):
        super().__init__("box", state, None)
    
    def dump(self):
        """
        dump the array
        @return: a dict that contains the array values
        """
        values = {}
        for i, v in enumerate(self):
            if v is not None:
                values[i] = v
        return values


class SetBox(ArrayAccessor):
    """
    the \\setbox command
    """
    def getItemAccessor(self, parser):
        return BoxArrayItemAccessor(self.domain, parser.readInteger())


class IfBox(conditional.Conditional):
    """
    The \\ifinner command.
    """
    def __init__(self, type):
        self.type = type

    def condition(self, parser):
        index = parser.readInteger()
        box = parser.state.box[index]
        if self.type is None:
            return 0 if box is None else 1
        return 0 if isinstance(box, self.type) else 1


class VBox(Box):
    """
    A vertical box.
    @param to: the target height
    @param spread: the spread
    @param vtop: whether the box is a vtop
    """
    def __init__(self, parser, to, spread):
        super().__init__(parser, to, spread, vmode.VList(parser))
        self.box_typeset_context = VBoxTypesetContext(parser.state.layout)

    @classmethod
    def new(cls, parser, **kwargs):
        return cls(parser, kwargs["to"], kwargs["spread"])

    node_type = nd.NODE_TYPE.VLIST  

    def calculate(self, node, natural, dim):
        if dim is None:
            return natural
        w, h, d = dim
        if self.width is None or w > float(self.width):
            self.width = w
        return natural

    def pretypeset(self, parser):
        if self._typeset_cache is not None:
            return
        content = []
        typeset_nodes = getattr(self.list, "typesetNodes", None)
        if typeset_nodes is None:
            for n in self.list:
                self._expand(parser, content, n)
        else:
            typeset_nodes(parser, content)
        natural = Glue()
        self.width = Dimen()
        self.height = Dimen()
        self.depth = Dimen()
        last_depth = Dimen()
        have_box = False
        trailing_glue = False
        for n in content:
            node_type = n.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                natural += n.glue
                if have_box:
                    trailing_glue = True
                continue
            if node_type == nd.NODE_TYPE.KERN:
                natural.dimen += n.kern
                if have_box:
                    trailing_glue = True
                continue
            if isinstance(n, nd.Box):
                shifted = n.shifted if n.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST) else 0
                w = n.width
                h = n.height - shifted
                d = n.depth + shifted
                natural = self.calculate(n, natural, (w, h, d))
                natural.dimen += h + last_depth
                last_depth = d
                have_box = True
                trailing_glue = False
                continue
            self.calculate(n, natural, None)
        if have_box and not trailing_glue:
            self.depth = last_depth
        else:
            self.depth = Dimen()
        maxdepth = self.box_typeset_context.boxmaxdepth
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
        self._typeset_cache = self.copy(content)

    def __repr__(self):
        return f"VBox({self.width}, {self.height}, {self.depth}, {self.list})"


class VTop(VBox):
    def pretypeset(self, parser):
        super().pretypeset(parser)
        total = self.height + self.depth
        self._typeset_cache.height = self.height = getattr(self.list[0], "height", 0)
        self._typeset_cache.depth = self.depth = total - self.height


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


class BoxDimenAccessor(ArrayItemAccessor, DimenCommand):
    def readValue(self, parser):
        return parser.readDimen()

    def set(self, parser, value):
        assert self.domain is not None
        setattr(self.domain, self.index, value)

    def setGlobal(self, parser, value):
        assert self.domain is not None
        setattr(self.domain, self.index, value)

    def dimenValue(self, parser):
        box = self.domain
        if box is None:
            return Dimen()
        d = getattr(box, self.index, None)
        if d is None:
            box = box.typeset(parser)
            d = getattr(box, self.index)
        return d


class BoxDimenCommand(DimenArrayAccessor):
    """
    a command that accesses a dimension for a box
    @param domain the attribute of the box dimension
    """
    def getItemAccessor(self, parser):
        return BoxDimenAccessor(parser.state.box[parser.readInteger()], self.domain)
    
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
        index = parser.readInteger()
        if not (0 <= index < parser.state.box.size):
            raise ValueError("box index out of range", parser.input.position())
        box = parser.state.box[index]
        if self.wipe:
            parser.state.box[index] = None
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
        materialized, changed = _materializeBoxListNodes(parser, box.list)
        top.extend(materialized if changed else box.list)
        if self.vertical and top.type == LISTTYPE.VERTICAL:
            top.can_lastbox = True


def _materializeBoxNodes(parser, node):
    materialize = getattr(node, "materialize_box_nodes", None)
    if materialize is None:
        return None
    nodes = materialize(parser)
    if nodes is None:
        return []
    if isinstance(nodes, list):
        return nodes
    try:
        return list(nodes)
    except TypeError:
        return [nodes]


def _materializeBoxListNodes(parser, nodes):
    expanded = []
    changed = False
    for node in nodes:
        materialized = _materializeBoxNodes(parser, node)
        if materialized is None:
            expanded.append(node)
            continue
        changed = True
        for n in materialized:
            if n is node:
                expanded.append(n)
                continue
            if getattr(n, "source", None) is None:
                n.source = node
            expanded.append(n)
    return expanded, changed


def _materializeTailForLastBox(parser, top):
    while top:
        tail = top[-1]
        if isinstance(tail, Box):
            return True
        nodes = _materializeBoxNodes(parser, tail)
        if nodes is None:
            return False
        if len(nodes) == 1 and nodes[0] is tail:
            return False
        can_lastbox = getattr(top, "can_lastbox", None)
        top[-1:] = nodes
        if hasattr(top, "prevdepth"):
            top.prevdepth = None
        if can_lastbox is not None:
            top.can_lastbox = can_lastbox
    return False


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
        box.shifted = shift * self.direction
        return box


class AccentBox(Box):
    """
    An accent box.
    """
    def __init__(self, accent):
        super().__init__(None, None, None, [accent])
        self.accent = accent
        self.width = accent.width
        self.height = accent.height
        self.depth = accent.depth
        self.typeset = None

    node_type = nd.NODE_TYPE.HLIST

    def saveInfo(self):
        return {"init": {"accent": self.accent}}


class AccentNode(nd.Node):
    """
    An accent node.
    """
    def __init__(self, accent, base):
        self.accent = accent
        self.base = base

    def saveInfo(self):
        return {"init": {"accent": self.accent, "base": self.base}}
    
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
        super().__init__(parser, None, None, None)
        self.width = parser.state.parameters["parindent"]
        self.height = Dimen()
        self.depth = Dimen()
        self.typeset = None

    def saveInfo(self):
        return {}
    
    @classmethod
    def new(cls, parser, **kwargs):
        return cls(parser)

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
    def __init__(self, parser, type, box):
        self.parser = parser
        self.type = type
        self.box = box

    def __call__(self):
        self.parser.lists.pop()
        self.parser.lastbox = self.box
        _appendLeader(self.parser, self.type, self.box)


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
                ended=LeaderBoxCallback(parser, self.type, box),
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
        if top.type == LISTTYPE.VERTICAL and not top.inner and not getattr(top, "can_lastbox", False):
            raise ValueError("\\lastbox cannot be used in the main vertical list", parser.input.position())
        if top.type == LISTTYPE.MATH:
            raise ValueError("\\lastbox cannot be used in math mode", parser.input.position())
        if not _materializeTailForLastBox(parser, top):
            return None
        return top.pop()
    
    def execute(self, parser):
        self.boxValue(parser, False)


mod = Module("hbox", 
    domains={
        "box": {"generator": BoxArray, "accessor": SetBox},
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
