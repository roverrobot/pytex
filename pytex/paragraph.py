"""
This module implement paragraph handling (unrestricted hlist).
"""

from pytex import hmode
from pytex import node as nd
from pytex import box as bx
from pytex.module import Module
from pytex.accessor import Accessor, VALUE_TYPE
from pytex.dimen import Dimen
from pytex.glue import Glue
from pytex.hmode import HorizontalCommand


class Language(nd.WhatsIt):
    """
    a language node
    """
    def __init__(self, language):
        self.language = language


class Paragraph(nd.Node):
    """
    A paragraph.
    @param parser: the parser
    @param indent: whether to indent the paragraph
    """
    def __init__(self, parser, indent: bool):
        self.list = []
        self.raw = []
        self.indent = indent
        # \prevgraf for this paragraph (set by display-math machinery when needed).
        self.prevgraf = 0
        self.line_count = 0
        self.actual_looseness = 0
        # Display math opens a synthetic following paragraph that may remain empty.
        if indent:
            indent_box = bx.IndentBox(parser)
            self.raw.append(indent_box)
            self.list.append(indent_box)
        self._line_boxes = None

    # not a proper node
    node_type = None
    _migratory_node_types = (nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS, nd.NODE_TYPE.ADJUST)

    def saveInfo(self):
        return {
                "indent": self.indent,
            }, {
                "disc": getattr(self, "disc", None),
                "list": self.list,
            }

    init_needs_parser = True
    
    def __repr__(self):
        return f'HList([{", ".join(repr(node) for node in self.list)}])'

    def meaning(self, parser):
        return "HList"

    def lineShape(self, parser, line_no):
        parshape = parser.volatile["parshape"]
        hsize = parser.layout["hsize"]
        hangindent = parser.volatile["hangindent"]
        hangafter = parser.volatile["hangafter"]
        if parshape:
            i = line_no - 1
            if i >= len(parshape):
                i = len(parshape) - 1
            return parshape[i]
        hang = hangindent
        if hang == 0:
            return Dimen(), hsize
        after = hangafter
        if after >= 0:
            hanging = line_no > after
        else:
            hanging = line_no <= -after
        if not hanging:
            return Dimen(), hsize
        if hang > 0:
            return hang, hsize - abs(hang)
        return Dimen(), hsize - abs(hang)

    @staticmethod
    def _lineDisc(parser, disc, broken):
        rendered = disc.pre if broken else disc.replace
        out = hmode.Disc(disc.pre, disc.post, list(rendered))
        out.source = getattr(disc, "source", None)
        return out

    def _scanBreaks(self, parser, nodes):
        """
        Scan an already-typeset horizontal node list for legal breakpoints.
        """
        return parser.typeset.paragraph.scanBreaks(self, nodes)

    def lineBreak(self, parser, hlist, breaks=None):
        return parser.typeset.paragraph.lineBreak(self, hlist, breaks)

    def _hyphenate(self, parser, hlist=None, scan=None):
        return parser.typeset.paragraph.hyphenate(self, hlist, scan)

class SetLanguage(HorizontalCommand):
    def horizontal(self, parser, hlist):
        language = parser.readInteger()
        hlist.append(Language(language))


class PrevGraf(Accessor):
    target_type = VALUE_TYPE.INT
    value_type = VALUE_TYPE.INT


mod = Module("paragraph",
    commands={
        "setlanguage": SetLanguage(),
    },
    parameters={
        "prevgraf": {"value": 0, "accessor": PrevGraf, "domain": "globals"},
    },
)
