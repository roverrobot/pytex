"""
This module implement paragraph handling (unrestricted hlist).
"""

from pytex import hmode
from pytex import node as nd
from pytex import box as bx
from pytex.module import Module


class Language(nd.WhatsIt):
    """
    a language node
    """
    def __init__(self, language):
        self.language = language


class Paragraph(hmode.HList):
    """
    A paragraph.
    @param parser: the parser
    @param indent: whether to indent the paragraph
    """
    def __init__(self, parser, indent: bool):
        super().__init__(parser, inner = False)
        self.current_language = parser.state.parameters["language"]
        self.disc = False
        if indent:
            self.append(bx.IndentBox(parser))

    # not a proper node
    node_type = None
    
    def saveInfo(self):
        d = super().saveInfo()
        d["init"]["indent"] = self.inner
        del d["init"]["inner"]
        return d | {"extra": {"disc": self.disc}}
    
    def discretionary(self):
        self.disc = False
        disc = nd.Disc(hmode.DiscHList(), hmode.DiscHList(), hmode.DiscHList())
        self.append(disc)
    
    def append(self, node):
        disc = False
        if isinstance(node, nd.CharNode):
            language = self.parser.state.parameters["language"]
            if self.current_language != language:
                self.current_language = language
                super().append(Language(language))
            if ord(node.char) == self.parser.hyphenChar():
                disc = True
        super().append(node)
        if disc:
            self.disc = True
        elif self.disc:
            self.discretionary()


def lineBreak(parser):
    """
    break a line into paragraphs
    @param parser: the parser
    """
    top = parser.lists[-1]
    if not isinstance(top, Paragraph):
        return
    raise NotImplementedError("lineBreak")


mod = Module("paragraph",
    attributes={
        "lineBreak": lineBreak,
    },
)
