"""Parser-owned typesetting services and module installer."""

from pytex.module import Module
from pytex.typeset.paragraph import ParagraphTypesetter
from pytex.typeset.math import MathTypesetter
from pytex.typeset.align import AlignmentTypesetter
from pytex.typeset.page import PageBuilder
from pytex.typeset.shipout import Shipout


class TypesetOps:
    """Facade for parser-owned typesetting services."""

    def __init__(self, parser):
        self.parser = parser
        self.paragraph = ParagraphTypesetter(parser)
        self.math = MathTypesetter(parser)
        self.align = AlignmentTypesetter(parser)
        self.page = PageBuilder(parser)
        self.shipout = Shipout(parser)


def init(parser):
    parser.typeset = TypesetOps(parser)
    parser.line_breaker = parser.typeset.paragraph
    parser.math_typesetter = parser.typeset.math
    parser.alignment_typesetter = parser.typeset.align
    parser.page_builder = parser.typeset.page
    parser.shipout = parser.typeset.shipout


mod = Module("typeset", init=init)
