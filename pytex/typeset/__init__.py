"""Parser-owned typesetting services and module installer."""

from pytex.module import Module
from pytex.typeset.math import MathTypesetter
from pytex.typeset.paragraph import ParagraphTypesetter


class TypesetOps:
    """Facade for parser-owned typesetting services."""

    def __init__(self, parser):
        self.parser = parser
        self.paragraph = ParagraphTypesetter(parser)
        self.math = MathTypesetter(parser)


def init(parser):
    parser.typeset = TypesetOps(parser)
    parser.line_breaker = parser.typeset.paragraph
    parser.math_typesetter = parser.typeset.math


mod = Module("typeset", init=init)
