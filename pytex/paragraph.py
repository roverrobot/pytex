"""
This module implement paragraph handling (unrestricted hlist).
"""

from pytex import hmode
from pytex import node as nd
from pytex import box as bx
from pytex import lists
from pytex.module import Module
from pytex.dimen import Dimen


class ParagraphTypesetContext:
    """
    Frozen typesetting context for a paragraph.
    """
    def __init__(self, parser, paragraph, prev_context=None):
        self.paragraph = paragraph
        self.prev_context = prev_context
        self.next_context = None
        self.line_count = None
        if prev_context is not None:
            prev_context.next_context = self
            self.prevgraf = 0 if prev_context.line_count is None else prev_context.line_count
        else:
            self.prevgraf = 0
        self.hsize = Dimen(parser.state.layout["hsize"])
        self.leftskip = parser.state.layout["leftskip"].copy()
        self.rightskip = parser.state.layout["rightskip"].copy()
        self.parfillskip = parser.state.parameters["parfillskip"].copy()
        self.pretolerance = parser.state.layout["pretolerance"]
        self.tolerance = parser.state.layout["tolerance"]
        self.linepenalty = parser.state.layout["linepenalty"]
        self.hyphenpenalty = parser.state.layout["hyphenpenalty"]
        self.exhyphenpenalty = parser.state.layout["exhyphenpenalty"]
        self.adjdemerits = parser.state.layout["adjdemerits"]
        self.doublehyphendemerits = parser.state.layout["doublehyphendemerits"]
        self.finalhyphendemerits = parser.state.layout["finalhyphendemerits"]
        self.looseness = parser.state.layout["looseness"]
        self.hangindent = Dimen(parser.state.layout["hangindent"])
        self.hangafter = parser.state.layout["hangafter"]
        self.parshape = [(Dimen(indent), Dimen(width)) for indent, width in parser.state.globals["parshape"]]
        self.language = parser.state.parameters["language"]

    def setLineCount(self, line_count):
        self.line_count = line_count
        if self.next_context is not None:
            self.next_context.prevgraf = line_count


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
        self.typeset_context = None
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


def _lineBreakRound(parser, para, vlist):
    """
    Run one line-breaking round.
    @param vlist: vertical list to receive the resulting line boxes
    @return: True if a feasible set of breaks is found and emitted

    TeX's algorithm, at a high level:
    1) Build legal breakpoints (glue, penalties, discretionary nodes) and
       evaluate candidate lines from prior active breakpoints.
    2) Compute badness from line shortfall/excess using the paragraph context
       (`hsize`, `parshape`, skips, hanging-indent settings).
    3) Classify each feasible line into fitness classes and accumulate
       demerits (line penalties, hyphen penalties, adjacency penalties, etc.).
    4) Keep best active candidates per fitness class and prune impossible
       ones as scanning proceeds.
    5) At paragraph end, pick best total demerits path, reconstruct breaks,
       then package each line as an hbox.
    6) Record produced line count into `typeset_context.line_count` so
       subsequent paragraphs receive `\\prevgraf`.
    """

    # TODO: implement TeX line-breaking (active list / demerits) for one round.
    raise NotImplementedError("lineBreak round algorithm not implemented")


def _hyphenate(parser, para):
    """
    Insert discretionary nodes for automatic hyphenation before round 2.
    """
    # TODO: implement paragraph hyphenation pass.
    return


def lineBreak(parser, para, vlist):
    """
    Break one paragraph into lines (TeXbook Appendix H line-breaking model).

    This routine is intentionally paragraph-driven, not stack-driven:
    callers must pass the Paragraph node to break, so lazy typesetting can
    process paragraphs in any order.

    TeX runs this in rounds:
    - Round 1: no automatic hyphenation.
    - If no feasible breaks are found, run hyphenation and repeat the same
      algorithm in round 2.
    `_lineBreakRound` assumes discretionary nodes are already present.

    @param parser: parser environment (used for helper routines/output hooks)
    @param para: the Paragraph node to be line-broken
    @param vlist: vertical list that receives the line boxes
    @return: True if feasible breaks are found in round 1 (or round 2 later)
    """
    if not isinstance(para, Paragraph):
        raise ValueError("lineBreak expects a Paragraph node")
    if para.typeset_context is None:
        raise ValueError("paragraph is missing typeset context")
    if getattr(vlist, "type", None) != lists.LISTTYPE.VERTICAL:
        raise ValueError("lineBreak expects a vertical list output")
    if _lineBreakRound(parser, para, vlist):
        return True
    _hyphenate(parser, para)
    # TODO: round 2 after hyphenation:
    # return _lineBreakRound(parser, para, vlist)
    return False


mod = Module("paragraph",
    attributes={
        "lineBreak": lineBreak,
    },
)
