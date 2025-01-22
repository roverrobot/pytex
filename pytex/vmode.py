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


class VSkip(VerticalCommand):
    """
    Add a vertical skip.
    """
    def __init__(self, glue=None):
        self.glue = glue

    def vertical(self, parser, vlist):
        if self.glue is None:
            glue = parser.readGlue()
        else:
            glue = self.glue
        node = nd.Glue(glue)
        vlist.append(node)


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


mod = Module("vmode",
    commands={
        "vskip": VSkip(),
        "vfil": VFil(),
        "vfill": VFill(),
        "vss": Vss(),
        "vnegfil": VNegFil(),
    },
)