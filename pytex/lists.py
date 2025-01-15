"""
The horizontal and vertical lists of TeX.
"""


from pytex import node as nd
from pytex.token import Command
import enum
from pytex.module import Module


class LISTTYE(enum.Enum):
    VERTICAL = 0
    HORIZONTAL = 1
    MATH = 2


class List(list):
    """
    A list of nodes.
    @type: The type of list.
    @inner: Whether the list is in internal mode.

    The internal mode means an internal vlist, or restricted hlist, or nondisplay mlist.
    """
    def __init__(self, type: LISTTYE, inner: bool=True):
        super().__init__()
        self.type = type

    def __repr__(self):
        if self.type == LISTTYE.VERTICAL:
            type = "VList"
        elif self.type == LISTTYE.HORIZONTAL:
            type = "HList"
        else:
            type = "MList"
        inner = "inner" if self.inner else ""
        return f'{type}({inner}, {", ".join(repr(node) for node in self)})'
    

class ModeDependentCommand(Command):
    """
    A command that behaves differently in different modes.
    """
    def execute(self, parser):
        top = parser.lists[-1]
        mode = top.type
        if mode == LISTTYE.HORIZONTAL:
            self.horizontal(parser, top)
        elif mode == LISTTYE.VERTICAL:
            self.vertical(parser, top)
        elif mode == LISTTYE.MATH:
            self.math(parser, top)
    
    def modeError(self, parser, mode):
        pos = parser.input.pos
        raise ValueError(f"this command cannot be used in {mode} mode", pos)
    
    def horizontal(self, parser, hlist):
        self.modeError(parser, "horizontal")
    
    def vertical(self, parser, vlist):
        self.modeError(parser, "vertical")
    
    def math(self, parser, mlist):
        self.modeError(parser, "math")


class Kern(Command):
    """
    Add a kern node.

    This command is mode-independent.
    """
    def execute(self, parser):
        dimen = parser.readDimen()
        node = nd.Kern(dimen)
        parser.lists[-1].append(node)


class Penalty(Command):
    """
    Add a penalty node.

    This command is mode-independent.
    """
    def execute(self, parser):
        penalty = parser.readInteger()
        node = nd.Penalty(penalty)
        parser.lists[-1].append(node)


mod = Module("lists",
    commands={
        "kern": Kern(),
        "penalty": Penalty(),
    },
)
