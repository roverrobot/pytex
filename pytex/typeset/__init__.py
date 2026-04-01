"""Parser-owned typesetting services and module installer."""

from pytex.module import Module
from pytex.typeset.paragraph import ParagraphTypesetter


class TypesetOps:
    """Facade for parser-owned typesetting services."""

    def __init__(self, parser):
        self.parser = parser
        self.paragraph = ParagraphTypesetter(parser)


def init(parser):
    parser.typeset = TypesetOps(parser)
    parser.line_breaker = parser.typeset.paragraph


mod = Module("typeset", init=init)
