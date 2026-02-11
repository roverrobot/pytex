"""
Implement vertical mode commands and vlist handling.
"""


from pytex import node as nd
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.module import Module
from pytex.token import Command
from pytex.dimen import Dimen, DimenParameterAccessor


# initializer for prevdepth as -1000pt
init_prevdepth = Dimen(-1000.0)


class VList(lists.List):
    """
    A vertical list.
    @param parser: the parser that created the list
    @param inner: whether the list is in internal mode
    """
    def __init__(self, parser, inner=True):
        super().__init__(parser, lists.LISTTYPE.VERTICAL, inner=inner)
        parser.state.volatile["prevdepth"] = init_prevdepth

    def append(self, node):
        """
        Append a node to the list.
        @param node: the node to append
        """
        self.parser.state.volatile["prevdepth"] = node.depth if isinstance(node, nd.Box) else init_prevdepth
        super().append(node)


class VerticalCommand(lists.ModeDependentCommand):
    """
    A command that behaves differently in different modes.
    """
    def horizontal(self, parser, hlist):
        """
        In unrestricterd horizontal mode, a vertical command should terminate the 
        current list and return to the enclosing vertical list.
        @param parser: the parser
        @param hlist: the current list
        """
        if hlist.inner:
            # raise an error
            super().horizontal(parser, hlist)
        parser.endParagraph()
        self.execute(parser)


class VSkip(lists.GlueCommand, VerticalCommand):
    """
    Add a vertical skip.
    """
    def __init__(self, glue=None):
        lists.GlueCommand.__init__(self, True, glue)

    def vertical(self, parser, vlist):
        vlist.append(self.glueNode(parser))


class VFil(VSkip):
    """
    Add a vertical glue of 0pt plus 1fil.
    """
    def __init__(self):
        super().__init__()


def readVList(parser, reason):
    """
    Read a vertical list.
    @param parser: the parser
    @param reason: the reason for reading the list
    """
    vlist = VList(parser)
    return parser.readList(vlist, reason)


class End(Command):
    """
    End the current vertical list.
    """
    def execute(self, parser):
        parser.end()


mod = Module("vmode",
    commands={
        "vskip": VSkip(),
        "vfil": VSkip(Glue(0, Stretchness(1, 1))),
        "vfill": VSkip(Glue(0, Stretchness(1, 2))),
        "vss": VSkip(Glue(0, Stretchness(1, 1), Stretchness(1, 1))),
        "vnegfil": VSkip(Glue(0, Stretchness(-1, 1))),
        "end": End(),
    },
    attributes={
        "readVList": readVList
    },
    parameters={
        # prevdepth is the previosu box's depth. It is reset to -1000pt in each vertical list.
        # so it is not a layout parameter
        "prevdepth": {"value": init_prevdepth, "accessor": DimenParameterAccessor, "domain": "volatile"},
    }
)
