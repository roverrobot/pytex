"""
parse and wrap up an hbox
"""

from pytex import node as nd
from pytex import hmode
from pytex.glue import Stretchness
from pytex.module import Module
from pytex.accessor import ArrayAccessor, ValuePointer
from pytex.state import Array
from pytex.token import Command
from pytex.dimen import Dimen


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
    def __init__(self, hlist, to=None, spread=0, packed = None):
        self.hlist = hlist
        self.content, self.glues = packed if packed is not None else hlist.pack()
        info = WrapInfo(self.content)
        self.migrate = info.migrate
        if to is None:
            self.width = info.natural_width + spread
        else:
            self.width = to
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
        box = HBox(self.hlist, self.width, 0)
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
        return "Box()s"
    

class BoxValuePointer(ValuePointer):
    """
    a value pointer for the \\hbox array
    """
    def __init__(self, domain, index, wipe):
        super().__init__(domain, index, eq=True)
        self.wipe = wipe

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
    

class SetBox(Command):
    """
    the \\setbox command
    """
    def execute(self, parser):
        pos = parser.input.position()
        index = parser.readInteger()
        box = readBox(parser)
        if 0 <= index < len(parser.state.box):
            parser.state.box[index] = box
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
    }
)