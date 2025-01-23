"""
parse and wrap up an hbox
"""

from pytex import node as nd
from pytex import hmode
from pytex.glue import Stretchness
from pytex.module import Module
from pytex.accessor import ArrayAccessor, ValuePointer
from pytex.state import Array
from pytex.token import Command, CATCODE
from pytex.dimen import Dimen
from pytex import conditional
from pytex.state import GROUP_TYPE


class WrapInfo:
    """
    The natural dimension,  stretchness and migratable nodes of an hlist
    @param nodes: the nodes
    """
    def __init__(self, nodes):
        self.natural_width = Dimen()
        self.height = Dimen()
        self.depth = Dimen()
        self.stretch = Stretchness(0,0)
        self.shrink = Stretchness(0,0)
        self.migrate = []
        for n in nodes:
            if isinstance(n, nd.Glue):
                self.stretch += n.glue.stretch
                self.shrink += n.glue.shrink
                self.natural_width += n.glue.dimen
            elif isinstance(n, nd.Box):
                self.natural_width += n.width
                self.height = max(self.height, n.height)
                self.depth = max(self.depth, n.depth)
            elif isinstance(n, nd.Kern):
                self.natural_width += n.kern
            elif isinstance(n, nd.VAdjust):
                self.migrate.append(n)
            elif isinstance(n, nd.Mark):
                self.migrate.append(n)


class HBox(nd.Box):
    """
    A horizontal box.
    @param hlist: an hlist to be wrapped
    @param to: the target width
    @param spread: the spread
    @param packed: optionally the packed hlist.
    """
    def __init__(self, to, spread):
        self.hlist = None
        self.content = None
        self.to = to
        self.spread = spread
        super().__init__(0, 0, 0)

    node_type = nd.NODE_TYPE.HLIST

    def pack(self, hlist, packed=None):
        self.content, self.glues = packed if packed is not None else hlist.pack()
        info = WrapInfo(self.content)
        self.migrate = info.migrate
        if self.to is None:
            self.width = info.natural_width + self.spread
        else:
            self.width = self.to
        self.height = info.height
        self.depth = info.depth
        diff = self.width - info.natural_width
        if diff == 0: # natural
            for g in self.glues:
                g.kern = g.glue.dimen
        elif diff > 0: # stretch
            ratio = 1 if info.stretch.factor == 0 else diff / info.stretch.factor
            order = info.stretch.order
            for g in self.glues:
                stretch = g.glue.stretch
                s = stretch.factor * ratio if stretch.order == order else 0
                g.kern = g.glue.dimen + s
        else: # shrink
            ratio = min(1, -diff / info.shrink.factor)
            order = info.shrink.order
            for g in self.glues:
                shrink = g.glue.shrink
                s = shrink.factor * ratio if shrink.order == order else 0
                g.kern = g.glue.dimen - s

    def copy(self):
        """
        return a copy of the box
        """
        box = HBox(0, 0)
        box.width = self.width
        box.height = self.height
        box.depth = self.depth
        box.hlist = self.hlist
        box.content = self.content
        box.glues = self.glues
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
    

class BoxValuePointer(ValuePointer):
    """
    a value pointer for the \\hbox array
    """
    def __init__(self, domain, index, wipe):
        super().__init__(domain, index, eq=True)
        self.wipe = wipe

    def readValue(self, parser):
        return parser.readBox()

    def boxValue(self, parser):
        box = self.getValue(parser)
        if self.wipe:
            self.domain[self.index] = VoidBox()
            return box
        return box.copy()


class Box(Command):
    """
    the \\box or \\copy command
    @param wipe whether to wipe the box register after use
    """
    def __init__(self, wipe: bool=False):
        self.wipe = wipe
    
    def execute(self, parser):
        p = self.pointer(parser)
        box = p.boxValue(parser)
        parser.lists[-1].append(box)
    
    def pointer(self, parser):
        pos = parser.input.position()
        index = parser.readInteger()
        if 0 <= index < len(parser.state.box.values):
            return BoxValuePointer(parser.state.box, index, self.wipe)
        raise ValueError("box index out of range", pos)


class BoxSpecPointer:
    """
    a pointer that read a box specification (not including the list)

    @param command: the command that starts the box spec reading
    Note that the box is only partially constructed by this pointer, i.e.,
    the list is not read. According to the TeX Book, the \\afterassignment
    token is put into the input stack after the openning { token. This means 
    that the assignment is done after the { token.
    """
    def __init__(self, command):
        self.command = command
        self.list = command.list()
        self.box = None
  
    def boxValue(self, parser):
        def callback():
            parser.run = False
            assert parser.lists.pop() == self.list
            self.box.pack(self.list)
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
        self.box = self.command.box(to, spread)
        parser.skipFiller()
        pos = parser.input.position()
        t = parser.token_expand()
        if t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a {", pos)
        parser.lists.append(self.list)
        parser.beginGroup(pos, self.command.reason(), callback)
        return self.box

class ReadBox(Command):
    """
    the base class for \\hbox, \\vbox and \\vtop commands
    """
    def list(self):
        """
        create a new list
        """
        raise NotImplementedError
    
    def box(self):
        """
        create a new box
        """
        raise NotImplementedError
    
    def reason(self):
        """
        return the reason for reading the box
        """
        raise NotImplementedError
    
    def pointer(self, parser):
        """
        return a pointer that read a box specification (not including the list)
        """
        return BoxSpecPointer(self)
    
    def execute(self, parser):
        p = self.pointer(parser)
        box = p.boxValue(parser)
        parser.loop()
        parser.lists[-1].append(box)


class HBoxCommand(ReadBox):
    """
    the \\hbox command
    """
    def list(self):
        return hmode.HList()
    
    def box(self, to, spread):
        return HBox(to, spread)
    
    def reason(self):
        return GROUP_TYPE.HBOX
    

def readBox(parser):
    """
    read a box from the input stack
    """
    pos = parser.input.position()
    command = parser.token_expand()
    if command is None:
        raise ValueError("expecting a box", pos)
    try:
        p = command.pointer(parser)
        return p.boxValue(parser)
    except AttributeError:
        raise ValueError("expecting a box", pos)
    

class SetBox(ArrayAccessor):
    """
    the \\setbox command
    """
    def __init__(self):
        super().__init__("box", BoxValuePointer)


class IfVoid(conditional.Conditional):
    """
    The \\ifinner command.
    """
    def __init__(self):
        super().__init__("\\ifinner")
    
    def condition(self, parser):
        pos = parser.input.position()
        index = parser.readInteger()
        if 0 <= index < len(parser.state.box.values):
            return 0 if parser.state.box[index].content is None else 1
        raise ValueError("box index out of range", pos)


mod = Module("hbox", 
    domains={
        "box": {"generator": lambda: Array(VoidBox), "accessor": None},
    },
    attributes={
        "readBox": readBox,
    },
    commands={
        "box": Box(True),
        "copy": Box(False),
        "setbox": SetBox(),
        "ifvoid": IfVoid(),
        "hbox": HBoxCommand(),
    }
)