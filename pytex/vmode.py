"""
Implement vertical mode commands and vlist handling.
"""


from pytex import node as nd
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.module import Module
from pytex.token import Command, CommandToken
from pytex.dimen import Dimen, DimenArrayItemAccessor
from pytex.state import GROUP_TYPE


# initializer for prevdepth as -1000pt
init_prevdepth = Dimen(-1000.0)


class VList(lists.List):
    """
    Vertical list build-state wrapper.

    This is what lives on parser.lists while vertical material is scanned.
    It builds a concrete vertical list node and tracks \\prevdepth/\\lastbox
    build-time state.
    """
    def __init__(self, parser, nodes, inner=True, add_interline=True):
        super().__init__(parser, nodes, inner)
        self.raw = []
        self.lastitem = None
        self.add_interline = add_interline

    list_type_name = "VList"
    type = lists.LISTTYPE.VERTICAL

    def open(self):
        super().open()
        self.saved_prevdepth = self.parser.globals.get("prevdepth", init_prevdepth)
        self.parser.globals["prevdepth"] = init_prevdepth

    def close(self):
        self.parser.globals["prevdepth"] = self.saved_prevdepth
        super().close()

    def extend(self, nodes, add_interline=True):
        for node in nodes:
            self.append(node, add_interline)

    def _pageBuilder(self):
        if self.inner:
            return None
        return getattr(self.parser, "page_builder", None)

    def concreteNodes(self):
        page_builder = self._pageBuilder()
        if page_builder is not None:
            return page_builder.concreteNodes(self)
        return list(self.list)

    def rawNodes(self):
        page_builder = self._pageBuilder()
        if page_builder is not None:
            return page_builder.rawNodes(self)
        return list(self.raw)

    def _notePageBuilder(self, node):
        page_builder = self._pageBuilder()
        if page_builder is not None:
            page_builder.noteAppend(self, node)

    def appendParagraph(self, para):
        self.raw.append(para)
        self.parser.typeset.paragraph.typeset(para, self)
        self._notePageBuilder(para)

    def appendDisplayMath(self, node):
        self.raw.append(node)
        self.parser.typeset.math.typesetDisplayMath(node, self)
        self._notePageBuilder(node)
    
    def append(self, node, add_interline=None):
        if add_interline is None:
            add_interline = self.add_interline
        if node.source is None:
            self.raw.append(node)
        align_typesetter = getattr(getattr(self.parser, "typeset", None), "align", None)
        if align_typesetter is not None and align_typesetter.appendToVList(node, self):
            self._notePageBuilder(node)
            return
        if getattr(node, "typeset_to_vlist", False):
            node.typeset(self.parser, self)
            self._notePageBuilder(node)
            return
        # appending a built node
        if node.node_type == nd.NODE_TYPE.RULE:
            self.parser.globals["prevdepth"] = init_prevdepth
            self.list.append(node)
            self._notePageBuilder(node)
            return
        if node.node_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            self.list.append(node)
            self._notePageBuilder(node)
            return
        prevdepth = self.parser.globals["prevdepth"]
        interline_penalty = getattr(node, "interline_penalty", None)
        if add_interline and interline_penalty is not None:
            penalty = nd.Penalty(interline_penalty)
            penalty.source = node
            self.list.append(penalty)
        glue_node = getattr(node, "interline_glue", None)
        if add_interline and (prevdepth > init_prevdepth or glue_node is not None):
            if glue_node is None:
                glue = self.parser.layout["baselineskip"].copy()
                glue.dimen -= prevdepth + node.height
                limit = self.parser.layout["lineskiplimit"]
                if glue.dimen >= limit:
                    glue_node = nd.Glue(glue, "\\baselineskip")
                else:
                    glue_node = nd.Glue(self.parser.layout["lineskip"], "\\lineskip")
            if glue_node.glue is not None:
                glue_node.source = node
                self.list.append(glue_node)
        self.list.append(node)
        self.parser.globals["prevdepth"] = node.depth
        if node.node_type == nd.NODE_TYPE.HLIST:
            for n in getattr(node, "migratory", []):
                self.append(n, add_interline=False)
        self._notePageBuilder(node)
    
    @staticmethod
    def isOwner(node, owner):
        if node is owner:
            return True
        while node:
            if node.source == owner:
                return True
            node = node.source
        return False
    
    def pop(self):
        node = self.list.pop()
        # resbuild prevdepth
        if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.RULE):
            self.calculatePrevDepth()
        return node

    def calculatePrevDepth(self):
        prevdepth = init_prevdepth
        for n in reversed(self.list):
            if n.node_type == nd.NODE_TYPE.RULE:
                break
            if n.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                prevdepth = n.depth
                break
        self.parser.globals["prevdepth"] = prevdepth

class VAdjust(nd.Node):
    """
    A \\vadjust node carrying already-built vertical material.
    """

    def __init__(self, list):
        self.list = list
        for n in list:
            n.source = list

    def saveInfo(self):
        return {"list": self.list}, None

    node_type = nd.NODE_TYPE.ADJUST
    typeset_to_vlist = True

    def typeset(self, parser, packed):
        packed.extend(self.list, add_interline=False)


class Mark(nd.Node):
    """
    A \\mark node.
    """

    def __init__(self, tokens):
        self.tokens = tokens

    def saveInfo(self):
        return {"tokens": self.tokens}, None

    node_type = nd.NODE_TYPE.MARK


class Insert(nd.Node):
    """
    An insert node carrying already-built vertical material.
    """

    def __init__(self, index, list):
        self.index = index
        self.list = list

    def saveInfo(self):
        return {"index": self.index, "list": self.list}, None

    node_type = nd.NODE_TYPE.INS


# Backward-compatibility aliases for code that still references pytex.node.*.
nd.VAdjust = VAdjust
nd.Mark = Mark
nd.Insert = Insert


class VerticalCommand(lists.ModeDependentCommand):
    """
    A command that behaves differently in different modes.
    """
    def horizontal(self, parser, hlist):
        """
        In unrestricterd horizontal mode, a vertical command should terminate the 
        current list by inserting a \\par token, then re-read the vertical
        command after that paragraph ends.
        @param parser: the parser
        @param hlist: the current list
        """
        if hlist.inner:
            # raise an error
            super().horizontal(parser, hlist)
        par = CommandToken("\\par")
        par.entry = parser.equitable.entry("\\par")
        parser.input.unread(parser.current_token)
        parser.input.unread(par)


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


def readVList(parser, reason, ended=None):
    """
    Read a vertical list.
    @param parser: the parser
    @param reason: the reason for reading the list
    @param ended: called after the list group closes
    """
    add_interline = reason not in (GROUP_TYPE.ADJUSTED_HBOX, GROUP_TYPE.NO_ALIGN)
    vstate = VList(parser, [], add_interline=add_interline)
    parser.clearParagraphSettings()
    return parser.readList(vstate, reason, ended)


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
        "prevdepth": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "globals"},
    },
)
