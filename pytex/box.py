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
from pytex.dimen import Dimen, DimenCommand, DimenArrayItemAccessor
from pytex import conditional
from pytex.state import GROUP_TYPE
from pytex.lists import LISTTYPE, ModeDependentCommand, GlueCommand
from pytex.lexer import TokenListScanner
from math import inf
import enum
import types


class Box(nd.Box):
    """
    the base class for \\hbox, \\vbox, and \\vtop
    @param to: the target width or height
    @param spread: the spread
    @param list: the list of nodes in the box
    """
    def __init__(self, to, spread, list):
        super().__init__(None, None, None)
        self.to = to
        self.spread = spread
        self.list = list
        self.shifted = 0
        self.glue_ratio = 0

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

    def typeset(self, parser, packed):
        """
        typeset the box
        @param packed: if provided, append this node and skip in-place typesetting.
        """
        if self.width is not None: 
            # we have been typeset. do nothing
            packed.append(self)
            return
        content = []
        for n in self.list:
            self._expand(parser, content, n)
        self.list[:] = content
        glues = []
        natural = Glue()
        self.width = Dimen()
        self.height = Dimen()
        self.depth = Dimen()
        for n in self.list:
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
        spread = self.spread if self.to is None else self.to - natural.dimen
        if spread is None:
            self.glue_ratio = 0
        if self.to is None:
            self.to = natural.dimen + self.spread
        elif spread > 0 and natural.stretch.factor != 0:
            self.glue_ratio = spread / natural.stretch.factor
        elif spread < 0 and natural.shrink.factor != 0:
            self.glue_ratio = spread / natural.shrink.factor
        else:
            self.glue_ratio = 0
        packed.append(self)

    def _expand(self, parser, content, node):
        """
        Expand the current list and collect nodes/glues/migratory nodes.
        """
        typeset = node.typeset
        if typeset is not None:
            start = len(content)
            typeset(parser, content)
            if len(content) > start:
                for n in content[start:]:
                    if n is node:
                        continue
                    if getattr(n, "source", None) is None:
                        n.source = node
                return
        content.append(node)


    def copy(self):
        """
        return a copy of the box
        """
        BoxType = type(self)
        box = BoxType(self.list.parser, self.to, self.spread)
        box.width = self.width
        box.height = self.height
        box.depth = self.depth
        box.shifted = self.shifted
        box.list = self.list
        box.source = self.source
        box.glue_ratio = self.glue_ratio
        return box


class HBox(Box):
    """
    A horizontal box.
    @param to: the target width
    @param spread: the spread
    """
    def __init__(self, parser, to, spread):
        super().__init__(to, spread, hmode.HList(parser, True))
        self.migrate = []

    @classmethod
    def new(cls, parser, **kwargs):
        return cls(parser, kwargs["to"], kwargs["spread"])

    node_type = nd.NODE_TYPE.HLIST

    def _expand(self, parser, content, node):
        if node.node_type in (nd.NODE_TYPE.ADJUST, nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS):
            # these nodes are not expanded, but their content is migrated to the current list.
            self.migrate.append(node)
            content.append(node)
            return
        super()._expand(parser, content, node)
    
    def calculate(self, node, natural, dim):
        if dim is None:
            # node is something else.
            if node.node_type == nd.NODE_TYPE.DISC:
                parser = self.list.parser
                box = HBox(parser, None, None)
                box.list = node.replace
                box.typeset(parser, [])
                w = box.width
                h = box.height
                d = box.depth
            elif node.node_type == nd.NODE_TYPE.MATH:
                natural.dimen += self.list.parser.state.layout["mathsurround"]
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
    
    def typeset(self, parser, packed):
        super().typeset(parser, packed)
        self.width = self.to

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


def readToSpread(parser):
    """
    read the to/spread spec from the input stack
    @param parser: the parser
    @return: a tuple (to, spread)
    """
    spec = parser.readKeyword(["to", "spread"])
    if spec is None:
        return None, Dimen()
    dim = parser.readDimen()
    if spec == "to":
        return dim, Dimen()
    return None, dim


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
        box = self.boxValue(parser, False)
        top = parser.lists[-1]
        top.append(box)
        # if we are in vertical model, then migrate
        if top.type == LISTTYPE.VERTICAL:
            migrate = getattr(box, "migrate", None)
            if migrate:
                for n in migrate:
                    if n.node_type == nd.NODE_TYPE.ADJUST:
                        for m in n.vlist:
                            top.append(m)
                    else:
                        top.append(n)

    def boxValue(self, parser, setbox):
        to, spread = readToSpread(parser)
        box = self.box(parser, to, spread)
        parser.skipFiller()
        t = parser.token_expand()
        if t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a {", parser.input.position())
        if setbox:
            # \afterassignment is put after the { token.
            afterassignment = parser.state.globals["afterassignment"]
            if afterassignment is not None:
                parser.state.globals["afterassignment"] = None
                parser.input.unread(afterassignment)
                if parser.tracingcommands > 0 and parser.checkRange():
                    parser.message(f"afterassignment: {parser.tokenToString(afterassignment)}")
        every = parser.everyvbox.value if self.vertical else parser.everyhbox.value
        if every:
            parser.input.push(TokenListScanner(every))
            if parser.tracingcommands > 0 and parser.checkRange():
                parser.message(f"every{'v' if self.vertical else 'h'}box: {parser.toksToString(every)}")
        parser.input.unread(t)
        parser.readList(box.list, self.group_type)
        box.typeset(parser, [])
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
    command = parser.token_expand().definition
    if command is None:
        raise ValueError("expecting a box", parser.input.position())
    try:
        return command.boxValue(parser, setbox)
    except AttributeError:
        raise ValueError("expecting a box", parser.input.position())
    

class BoxArrayItemAccessor(ArrayItemAccessor):
    def readValue(self, parser):
        if self.index == 1:
            x=0
        return readBox(parser, setbox=True)
    
    def boxValue(self, parser):
        """
        read the box value from the input stack
        @param parser: the parser
        """
        return self.domain[self.index]
    

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
        super().__init__(to, spread, vmode.VList(parser))

    @classmethod
    def new(cls, parser, **kwargs):
        return cls(parser, kwargs["to"], kwargs["spread"])

    node_type = nd.NODE_TYPE.VLIST  

    def calculate(self, node, natural, dim):
        if dim is None:
            natural.dimen += self.depth
            self.depth = 0
            return natural
        w, h, d = dim
        if self.width is None or w > float(self.width):
            self.width = w
        natural.dimen += h + self.depth
        self.depth = d
        return natural

    def typeset(self, parser, packed):
        """
        typeset the box
        @param packed: if provided, append this node and skip in-place typesetting.
        """
        super().typeset(parser, packed)
        self.height = self.to

    def __repr__(self):
        return f"VBox({self.width}, {self.height}, {self.depth}, {self.list})"


class VTop(VBox):
    def typeset(self, parser, packed):
        super().typeset(parser, packed)
        total = self.height + self.depth
        if self.list:
            self.height = getattr(self.list[0], "height", 0)
            self.depth = total - self.height


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
        setattr(self.domain, self.index, value)

    def setGlobal(self, parser, value):
        setattr(self.domain, self.index, value)

    def dimenValue(self, parser):
        d = getattr(self.domain, self.index)
        return 0 if d is None else d


class BoxDimenCommand(ArrayAccessor, DimenCommand):
    """
    a command that accesses a dimension for a box
    @param domain the attribute of the box dimension
    """
    def getItemAccessor(self, parser):
        return BoxDimenAccessor(parser.state.box[parser.readInteger()], self.domain)
    
    def dimenValue(self, parser):
        box = parser.state.box[parser.readInteger()]
        if box is None:
            return 0
        d = getattr(box, self.domain)
        if d is None:
            # not typeset yet
            box.typeset(parser, [])
            d = getattr(box, self.domain)
        return d


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
        top.extend(box.list)


class Shift(ModeDependentCommand):
    """
    The \\raise, \\lower, \\moveleft, \\moveright command.
    @param vertical whether the command is vertical (\\moveleft, \\moveright) or
    horizontal (\\raise, \\lower)
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
        super().__init__(None, None, [accent])
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
        # build the accent
        # append a kern to shift the accent so that it aligns with the char
        w = char.width + char.italic
        dx = (w - accent.width) / 2
        if dx != 0:
            nodes.append(nd.Kern(dx))
        accentbox = AccentBox(accent)
        ex = char.font.param[4] # font dimen 5 is ex
        dy = ex - char.height
        if dy < 0:
            accentbox.shifted = dy
        nodes.append(accentbox)
        # move the char back by the width of the accent box
        nodes.append(nd.Kern(-(float(char.width) + float(accent.width)) / 2))
        nodes.append(char)
        return


class IndentBox(Box):
    """
    An indent box.
    """
    def __init__(self, parser):
        super().__init__(None, None, None)
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
        else: # box
            parser.input.unread(t)
            box = parser.readBox()
            if (box.node_type == nd.NODE_TYPE.HLIST and top.type == LISTTYPE.VERTICAL) or (box.node_type == nd.NODE_TYPE.VLIST and top.type != LISTTYPE.VERTICAL):
                raise ValueError("box in the wrong mode", parser.input.position())
        t = parser.token_expand().definition
        if t is None:
            raise ValueError("expecting a glue", parser.input.position())
        if isinstance(t, GlueCommand):
            if (t.vert and top.type == LISTTYPE.VERTICAL) or (not t.vert and top.type != LISTTYPE.VERTICAL):
                glue = t.glueValue(parser)
            else:
                raise ValueError("glue in the wrong mode", parser.input.position())
        else:
            raise ValueError("expecting a glue", parser.input.position())
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
        # this command can only be unsed in horizontal mode or in ner vertical mode
        if top.type == LISTTYPE.VERTICAL and not top.inner:
            raise ValueError("\\lastbox cannot be used in the main vertical list", parser.input.position())
        if top.type == LISTTYPE.MATH:
            raise ValueError("\\lastbox cannot be used in math mode", parser.input.position())
        return top.pop() if top and isinstance(top[-1], Box) else None
    
    def execute(self, parser):
        self.boxValue(parser, False)


mod = Module("hbox", 
    domains={
        "box": {"generator": BoxArray, "accessor": SetBox},
    },
    attributes={
        "readBox": readBox,
        "readToSpread": readToSpread,
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
        "moveleft": Shift(True, 1),
        "moveright": Shift(True, -1),
        "leaders": Leaders(LEADERS_TYPE.LEADERS),
        "cleaders": Leaders(LEADERS_TYPE.CLEADERS),
        "xleaders": Leaders(LEADERS_TYPE.XLEADERS),
        "lastbox": LastBox(),
    }
)
