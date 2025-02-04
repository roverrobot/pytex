"""
parse and wrap up an hbox
"""

from pytex import node as nd
from pytex import vmode
from pytex.glue import Stretchness
from pytex.module import Module
from pytex.accessor import Accessor, ArrayAccessor
from pytex.state import Array
from pytex.token import Command, CATCODE, relax
from pytex.dimen import Dimen, DimenCommand
from pytex import conditional
from pytex.state import GROUP_TYPE
from pytex.lists import LISTTYPE, ModeDependentCommand, GlueCommand
from math import inf
import enum
import types


class Box(nd.Box):
    """
    the base class for \\hbox, \\vbox, and \\vtop
    @param to: the target width or height
    @param spread: the spread
    """
    def __init__(self, to, spread):
        super().__init__(None, None, None)
        # the hlist or vlist that this box wraps
        self.list = None
        # the packed list with glues and rule dimensions set correctly
        self.content = None
        self.to = to
        self.spread = spread
        self.shifted = 0

    inner = True

    def typeset(self, packed=None):
        """
        typeset the box
        @param packed: optionally the packed hlist.
        """
        raise NotImplementedError("this method should be implemented by subclasses")

    def copy(self):
        """
        return a copy of the box
        """
        BoxType = type(self)
        box = BoxType(self.to, self.spread)
        box.width = self.width
        box.height = self.height
        box.depth = self.depth
        box.shifted = self.shifted
        box.list = self.list
        box.content = self.content
        box.migrate = self.migrate
        return box


class HBoxWrapInfo:
    """
    The natural dimension,  stretchness and migratable nodes of an hlist
    @param nodes: the nodes
    """
    def __init__(self, nodes):
        self.natural_width = Dimen()
        self.height = None
        self.depth = None
        self.stretch = Stretchness(0,0)
        self.shrink = Stretchness(0,0)
        self.rules = [] # the rules which depth or height is not set (i.e., is None)
        for n in nodes:
            if isinstance(n, nd.Glue):
                self.stretch += n.glue.stretch
                self.shrink += n.glue.shrink
                self.natural_width += n.glue.dimen
            elif isinstance(n, nd.Box):
                w, h, d = self.boxDimen(n)
                self.natural_width += w
                if self.height is None or h > float(self.height):
                    self.height = h
                if self.depth is None or d > float(self.depth):
                    self.depth = d
                if isinstance(n, nd.Rule) and (n.height is None or n.depth is None):
                    self.rules.append(n)
            elif isinstance(n, nd.Kern):
                self.natural_width += n.kern

    def boxDimen(self, n):
        if isinstance(n, nd.Rule):
            w = 0 if n.width is None else n.width
            h = -inf if n.height is None else n.height
            d = -inf if n.depth is None else n.depth
        else:
            if n.node_type == nd.NODE_TYPE.HLIST or n.node_type == nd.NODE_TYPE.VLIST:
                shifted = n.shifted
            else:
                shifted = 0
            w = n.width
            h = n.height - shifted
            d = n.depth + shifted
        return w, h, d


class HBox(Box):
    """
    A horizontal box.
    @param to: the target width
    @param spread: the spread
    """
    def __init__(self, to, spread):
        super().__init__(to, spread)
        self.migrate = []

    node_type = nd.NODE_TYPE.HLIST

    def typeset(self, packed=None):
        """
        typeset the box
        @param packed: optionally the packed hlist.
        """
        self.content, glues, self.migrate = packed if packed is not None else self.list.pack()
        info = HBoxWrapInfo(self.content)
        if self.to is None:
            self.width = info.natural_width + self.spread
        else:
            self.width = self.to
        self.height = info.height
        self.depth = info.depth
        for r in info.rules:
            if r.height is None:
                r.height = self.height
            if r.depth is None:
                r.depth = self.depth
        diff = self.width - info.natural_width
        if diff == 0: # natural
            for g in glues:
                g.kern = g.glue.dimen
        elif diff > 0: # stretch
            ratio = 1 if info.stretch.factor == 0 else diff / info.stretch.factor
            order = info.stretch.order
            for g in glues:
                stretch = g.glue.stretch
                s = stretch.factor * ratio if stretch.order == order else 0
                g.kern = g.glue.dimen + s
        else: # shrink
            ratio = min(1, -diff / info.shrink.factor)
            order = info.shrink.order
            for g in glues:
                shrink = g.glue.shrink
                s = shrink.factor * ratio if shrink.order == order else 0
                g.kern = g.glue.dimen - s

    def copy(self):
        """
        return a copy of the box
        """
        box = super().copy()
        box.migrate = self.migrate
        return box
    
    def __repr__(self):
        return f"HBox({self.width}, {self.height}, {self.depth}, {self.content})"


class VoidBox(nd.Box):
    """
    An empty box.
    """
    def __init__(self):
        super().__init__(0, 0, 0)
        self.content = None

    def __repr__(self):
        return "Box()"


class BoxCommand(Command):
    """
    the \\box or \\copy command
    @param wipe whether to wipe the box register after use
    """
    def __init__(self, wipe: bool=False):
        self.wipe = wipe
    
    def execute(self, parser):
        box = self.boxValue(parser, False)
        if isinstance(box, VoidBox):
            return
        parser.lists[-1].append(box)
    
    def boxValue(self, parser, setbox):
        index = parser.readInteger()
        box = parser.state.box[index]
        if self.wipe:
            parser.state.box[index] = VoidBox()
            return box
        return box.copy()    

class BuildBox(Command):
    """
    the base class for \\hbox, \\vbox and \\vtop commands
    """
    def list(self, parser):
        """
        create a new list
        """
        raise NotImplementedError
    
    def box(self):
        """
        create a new box
        """
        raise NotImplementedError
    
    def groupType(self):
        """
        return the reason for reading the box
        """
        raise NotImplementedError
    
    def execute(self, parser):
        box = self.boxValue(parser, False)
        parser.lists[-1].append(box)

    def boxValue(self, parser, setbox):
        spec = parser.readKeyword(["to", "spread"])
        if spec is None:
            to = None
            spread = 0
        else:
            dim = parser.readDimen()
            if spec == "to":
                to = dim
                spread = 0
            else:
                to = None
                spread = dim
        box = self.box(to, spread)
        box.list = self.list(parser)
        parser.skipFiller()
        pos = parser.input.position()
        t = parser.token_expand()
        if t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a {", self.pos)
        if setbox:
            # \afterassignment is put after the { token.
            afterassignment = parser.state.globals["afterassignment"]
            if afterassignment is not None:
                parser.state.globals["afterassignment"] = None
                parser.input.unread(afterassignment)
        parser.input.unread(t)
        parser.readList(box.list, self.groupType())
        return box


class HBoxCommand(BuildBox):
    """
    the \\hbox command
    """
    def list(self, parser):
        return parser.newHList()
    
    def box(self, to, spread):
        return HBox(to, spread)
    
    def groupType(self):
        return GROUP_TYPE.HBOX
    

def readBox(parser, setbox=False): 
    """
    read a box from the input stack
    @param parser: the parser
    @param setbox: whether the this function is called from setbox
    """
    pos = parser.input.position()
    command = parser.token_expand().meaning
    if command is None:
        raise ValueError("expecting a box", pos)
    try:
        return command.boxValue(parser, setbox)
    except AttributeError:
        raise ValueError("expecting a box", pos)
    

class BoxAccessor(Accessor):
    def readValue(self, parser):
        return readBox(parser, setbox=True)
    

class SetBox(ArrayAccessor):
    """
    the \\setbox command
    """
    def __init__(self):
        super().__init__("box")
    
    def getValue(self, parser):
        raise ValueError("\\setbox does not return a box")

    def newItemAccessor(self, index):
        return BoxAccessor("box", index, eq=True)

class IfVoid(conditional.Conditional):
    """
    The \\ifinner command.
    """
    def __init__(self):
        super().__init__("\\ifinner")
    
    def condition(self, parser):
        index = parser.readInteger()
        box = parser.state.box[index]
        return 0 if isinstance(box, VoidBox) else 1


class VBoxWrapInfo:
    """
    The natural dimension,  stretchness and migratable nodes of an hlist
    @param nodes: the nodes
    @param vtop: whether the box is a vtop
    """
    def __init__(self, nodes, vtop):
        self.natural_height = Dimen()
        self.width = None
        self.depth = Dimen()
        self.stretch = Stretchness(0,0)
        self.shrink = Stretchness(0,0)
        self.rules = []
        d = 0
        h = 0
        for n in nodes:
            if isinstance(n, nd.Glue):
                self.stretch += n.glue.stretch
                self.shrink += n.glue.shrink
                self.natural_height += n.glue.dimen
            elif isinstance(n, nd.Box):
                w, h, d = self.boxDimen(n)
                if self.width is None or w > float(self.width):
                    self.width = w
                self.natural_height += h + d
                if isinstance(n, nd.Rule) and n.width is None:
                    self.rules.append(n)
            elif isinstance(n, nd.Kern):
                self.natural_height += n.kern
        if len(nodes) > 0:
            last = nodes[-1]
            if isinstance(last, nd.Box):
                self.natural_height -= d
                self.depth = d
            if vtop:
                first = nodes[0]
                w, h, d = self.boxDimen(first)
                self.depth = self.natural_height - h + d
                self.natural_height = h

    def boxDimen(self, n):
        if isinstance(n, nd.Rule):
            w = -inf if n.width is None else n.width
            h = 0 if n.height is None else n.height
            d = 0 if n.depth is None else n.depth
        else:
            h = n.height
            d = n.depth
            if n.node_type == nd.NODE_TYPE.HLIST or n.node_type == nd.NODE_TYPE.VLIST:
                shifted = n.shifted
            else:
                shifted = 0
            w = n.width - shifted
        return w, h, d


class VBox(Box):
    """
    A vertical box.
    @param to: the target height
    @param spread: the spread
    @param vtop: whether the box is a vtop
    """
    def __init__(self, to, spread, vtop):
        super().__init__(to, spread)
        self.vtop = vtop

    node_type = nd.NODE_TYPE.VLIST

    def typeset(self, packed=None):
        """
        typeset the box
        @param packed: optionally the packed vlist.
        """
        self.content, glues = packed if packed is not None else self.list.pack()
        info = VBoxWrapInfo(self.content, self.vtop)
        if self.to is None:
            self.height = info.natural_height + self.spread
        else:
            self.height = self.to
        self.width = info.width
        self.depth = info.depth
        for r in info.rules:
            if r.width is None:
                r.width = self.width
        diff = self.height - info.natural_height
        if diff == 0:
            for g in glues:
                g.kern = g.glue.dimen
        elif diff > 0:
            ratio = 1 if info.stretch.factor == 0 else diff / info.stretch.factor
            order = info.stretch.order
            for g in glues:
                stretch = g.glue.stretch
                s = stretch.factor * ratio if stretch.order == order else 0
                g.kern = g.glue.dimen + s
        else:
            ratio = min(1, -diff / info.shrink.factor)
            order = info.shrink.order
            for g in glues:
                shrink = g.glue.shrink
                s = shrink.factor * ratio if shrink.order == order else 0
                g.kern = g.glue.dimen - s

    def __repr__(self):
        return f"VBox({self.width}, {self.height}, {self.depth}, {self.content})"


class VBoxCommand(BuildBox):
    """
    the \\hbox command
    @param vtop: whether the box is a vtop
    """
    def __init__(self, vtop):
        self.vtop = vtop

    def list(self, parser):
        return vmode.VList(parser)
    
    def box(self, to, spread):
        return VBox(to, spread, self.vtop)
    
    def groupType(self):
        return GROUP_TYPE.VTOP if self.vtop else GROUP_TYPE.VBOX
    

class BoxDimenAccessor(Accessor):
    def readValue(self, parser):
        return parser.readDimen()

    def setValue(self, parser, value, globally):
        box = parser.state.box[self.index]
        setattr(box, self.dimen, value)

    def getValue(self, parser):
        box = parser.state.box[self.index]
        return getattr(box, self.dimen)

class BoxDimenCommand(DimenCommand, ArrayAccessor):
    """
    a command that accesses a dimension for a box
    """
    def __init__(self, dimen):
        self.dimen = dimen
        super().__init__("box")

    def getItemAccessor(self, parser, index):
        if index is None:
            index = self.getIndex(parser)
        p = BoxDimenAccessor("box", index)
        p.dimen = self.dimen
        return p


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
        pos = parser.input.position()
        index = parser.readInteger()
        if not (0 <= index < len(parser.state.box.values)):
            raise ValueError("box index out of range", pos)
        box = parser.state.box[index]
        if self.wipe:
            parser.state.box[index] = VoidBox()
        if isinstance(box, VoidBox):
            return
        top = parser.lists[-1]
        if top.type == LISTTYPE.MATH and not self.vertical:
            raise ValueError("the box must be void in math mode", pos)
        if (self.vertical and top.type != LISTTYPE.VERTICAL) or (
            not self.vertical and top.type != LISTTYPE.HORIZONTAL):
            raise ValueError("wrong mode", pos)
        if self.vertical and box.node_type != nd.NODE_TYPE.VLIST:
            raise ValueError("expecting a vbox", pos)
        if not self.vertical and box.node_type != nd.NODE_TYPE.HLIST:
            raise ValueError("expecting an hbox", pos)
        top.extend(box.list)


class Shift(ModeDependentCommand):
    """
    The \\raise, \\lower, \\moveleft, \\moveright command.
    @param vertical whether the command is vertical (\moveleft, \moveright) or
    horizontal (\raise, \lower)
    @param direction: the direction of the shift (-1, or 1). Here -1 means right or up,
    and 1 means left or down.
    """
    def __init__(self, vertical: bool, direction: int):
        self.vertical = vertical
        self.direction = direction

    def horizontal(self, parser, hlist):
        if self.vertical:
            super().horizontal(parser, hlist)
        hlist.append(self.shift(parser))

    def vertical(self, parser, vlist):
        if not self.vertical:
            super().vertical(parser, vlist)
        vlist.append(self.shift(parser))

    def math(self, parser, mlist):
        if self.vertical:
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
        super().__init__(None, None)
        self.accent = accent
        self.width = accent.width
        self.height = accent.height
        self.depth = accent.depth
        self.content = [accent]

    node_type = nd.NODE_TYPE.HLIST

    def typeset(self, hlist):
        # there is not need to typeset the box
        pass


class AccentNode(nd.Node):
    """
    An accent node.
    """
    def __init__(self, accent, base):
        self.accent = accent
        self.base = base

    node_type = nd.NODE_TYPE.ACCENT

    def typeset(self, hlist):
        char, accent = self.base, self.accent
        if char is None:
            hlist.append(accent)
            return
        # build the accent
        # append a kern to shift the accent so that it aligns with the char
        w = char.width + char.italic
        dx = (w - accent.width) / 2
        if dx != 0:
            hlist.append(nd.Kern(dx))
        accentbox = AccentBox(accent)
        ex = char.font.param[4] # font dimen 5 is ex
        dy = ex - char.height
        if dy < 0:
            accentbox.shifted = dy
        hlist.append(accentbox)
        # move the char back by the width of the accent box
        hlist.append(nd.Kern(-(float(char.width) + float(accent.width)) / 2))
        hlist.append(char)


class IndentBox(Box):
    """
    An indent box.
    """
    def __init__(self, parser):
        super().__init__(None, None)
        self.width = parser.state.parameters["parindent"]
        self.height = Dimen()
        self.depth = Dimen()
        self.content = None

    node_type = nd.NODE_TYPE.HLIST

    def typeset(self, hlist):
        # there is not need to typeset the box
        pass


class LEADERS_TYPE(enum.Enum):
    LEADERS = 0
    CLEADERS = 1
    XLEADERS = 2


class Leaders(Command):
    """
    The \\leaders, \\cleaders and \\xleaders command.
    """
    def __init__(self, type: LEADERS_TYPE):
        self.type = type

    def execute(self, parser):
        top = parser.lists[-1]
        # read a rule
        pos = parser.input.position()
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting a rule or a box", pos)
        if isinstance(t, nd.Rule):
            if (t.vert and top.type == LISTTYPE.VERTICAL) or (not t.vert and top.type != LISTTYPE.VERTICAL):
                box = t.readRule(parser)
            else:
                raise ValueError("rule in the wrong mode", pos)
        else: # box
            parser.input.unread(t)
            box = parser.readBox()
            if (box.node_type == nd.NODE_TYPE.HLIST and top.type == LISTTYPE.VERTICAL) or (box.node_type == nd.NODE_TYPE.VLIST and top.type != LISTTYPE.VERTICAL):
                raise ValueError("box in the wrong mode", pos)
        pos = parser.input.position()
        t = parser.token_expand().meaning
        if t is None:
            raise ValueError("expecting a glue", pos)
        if isinstance(t, GlueCommand):
            if (t.vert and top.type == LISTTYPE.VERTICAL) or (not t.vert and top.type != LISTTYPE.VERTICAL):
                glue = t.glueValue(parser)
            else:
                raise ValueError("glue in the wrong mode", pos)
        else:
            raise ValueError("expecting a glue", pos)
        node = nd.Glue(glue)
        node.leaders = (self.type, box)
        top = parser.lists[-1]
        parser.lists[-1].append(node)


class LastBox(Command):
    """
    The \\lastbox command.
    """
    def boxValue(self, parser, setbox):
        top = parser.lists[-1]
        if top.type == LISTTYPE.VERTICAL and not top.inner:
            raise ValueError("\\lastbox cannot be used in vertical mode")
        box = top.pop() if len(top) > 0 and isinstance(top[-1], Box) else VoidBox()
        return box
    
    def execute(self, parser):
        self.boxValue(parser, False)


mod = Module("hbox", 
    domains={
        "box": {"generator": lambda: Array(VoidBox), "accessor": None},
    },
    attributes={
        "readBox": readBox,
    },
    commands={
        "box": BoxCommand(True),
        "copy": BoxCommand(False),
        "setbox": SetBox(),
        "ifvoid": IfVoid(),
        "hbox": HBoxCommand(),
        "vbox": VBoxCommand(False),
        "vtop": VBoxCommand(True),
        "wd": BoxDimenCommand("width"),
        "ht": BoxDimenCommand("height"),
        "dp": BoxDimenCommand("depth"),
        "unhbox": UnBox(False, True),
        "unvbox": UnBox(True, True),
        "unhcopy": UnBox(False, False),
        "unvcopy": UnBox(True, False),
        "raise": Shift(False, -1),
        "lower": Shift(False, 1),
        "moveleft": Shift(True, 1),
        "moveright": Shift(True, -1),
        "leaders": Leaders(LEADERS_TYPE.LEADERS),
        "cleaders": Leaders(LEADERS_TYPE.CLEADERS),
        "xleaders": Leaders(LEADERS_TYPE.XLEADERS),
        "lastbox": LastBox(),
    }
)