"""
Implement vertical mode commands and vlist handling.
"""


from pytex import node as nd
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.module import Module


class VList(lists.List):
    """
    A vertical list.
    """
    def __init__(self, inner=True):
        super().__init__(lists.LISTTYPE.VERTICAL, inner=inner)

    def pack(self):
        """
        prepare the list for typesetting.

        @return a new list and the glues

        This will migrate the \\marks and \\vadjusts in an hbox to the list.
        """
        nodes = []
        glues = []
        for node in self:
            if isinstance(node, nd.Glue):
                glues.append(node)
            elif node.node_type == nd.NODE_TYPE.HLIST:
                if not node.list.inner:
                    # this is a paragraph. We have not implemented it yet
                    raise NotImplementedError("paragraphs are not implemented yet")
                else:
                    # this is a \hbox.
                    node.typeset()
                    nodes.append(node)
                for n in node.migrate:
                    if n.node_type == nd.NODE_TYPE.VADJUST:
                        nodes.extend(n.list)
                    else:
                        # n.node_type == nd.NODE_TYPE.MARK or n.node_type == nd.NODE_TYPE.INS:
                        nodes.append(n)
                continue
            elif node.node_type == nd.NODE_TYPE.VLIST:
                node.typeset()
            nodes.append(node)
        return nodes, glues


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
        super().__init__(Glue(0, Stretchness(1, 1)))


class VFill(VSkip):
    """
    Add a vertical glue of 0pt plus 1fill.
    """
    def __init__(self):
        super().__init__(Glue(0,  Stretchness(1, 2)))


class Vss(VSkip):
    """
    Add a vertical glue of 0pt plus 1fil minus 1fil.
    """
    def __init__(self):
        super().__init__(Glue(0, Stretchness(1, 1), Stretchness(1, 1)))


class VNegFil(VSkip):
    """
    Add a vertical glue of 0pt minus -1fil.
    """
    def __init__(self):
        super().__init__(Glue(0, Stretchness(-1, 1)))


def readVList(parser, reason):
    """
    Read a vertical list.
    @param parser: the parser
    @param reason: the reason for reading the list
    """
    vlist = VList()
    return parser.readList(vlist, reason)


mod = Module("vmode",
    commands={
        "vskip": VSkip(),
        "vfil": VFil(),
        "vfill": VFill(),
        "vss": Vss(),
        "vnegfil": VNegFil(),
    },
    attributes={
        "readVList": readVList
    },
)
