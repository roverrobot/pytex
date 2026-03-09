"""
Implement vertical mode commands and vlist handling.
"""


from pytex import node as nd
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.module import Module
from pytex.token import Command
from pytex.dimen import Dimen, DimenCommand
from pytex.accessor import Accessor


# initializer for prevdepth as -1000pt
init_prevdepth = Dimen(-1000.0)


class VNodeContext:
    """
    The context for a node in vertical mode. This is used to store the parameters that affect the typesetting of the node, such as baselineskip, lineskip, etc.
    """
    def __init__(self, layout, prevdepth):
        self.baselineskip = layout["baselineskip"]
        self.lineskip = layout["lineskip"]
        self.lineskiplimit = layout["lineskiplimit"]
        self.interlinepenalty = layout["interlinepenalty"]
        self.prevdepth = prevdepth


def expandVerticalNode(parser, node):
    """
    Expand one vertical-list item into concrete nodes without mutating the
    containing list.
    """
    materialize = getattr(node, "materialize_box_nodes", None)
    if materialize is not None:
        packed = materialize(parser)
        if packed is None:
            return []
        if not isinstance(packed, list):
            try:
                packed = list(packed)
            except TypeError:
                packed = [packed]
        for n in packed:
            if n is node:
                continue
            if getattr(n, "source", None) is None:
                n.source = node
        return packed
    typeset = getattr(node, "typeset", None)
    if typeset is None:
        return [node]
    packed = []
    node.typeset(parser, packed)
    if not packed:
        return [node]
    for n in packed:
        if n is node:
            continue
        if getattr(n, "source", None) is None:
            n.source = node
    return packed


def typesetVerticalNodes(parser, nodes, packed):
    """
    Typeset a raw vertical node list into packed output.
    """
    prevdepth = init_prevdepth
    firstbox = True
    for node in nodes:
        expanded = expandVerticalNode(parser, node)
        node_context = getattr(node, "typeset_context", None)
        for item in expanded:
            if item.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                # if the prevdepth is explicitly set, we use it. Otherwise, we use the current prevdepth
                context = getattr(item, "typeset_context", None)
                if context is None:
                    context = node_context
                    node_context = None
                else:
                    item.typeset_context = None
                if context is None:
                    if not firstbox:
                        prev = packed[-1] if packed else None
                        if prev is not None and prev.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.RULE):
                            interlinepenalty = parser.state.layout["interlinepenalty"]
                            if interlinepenalty != 0:
                                packed.append(nd.Penalty(interlinepenalty))
                            if float(prevdepth) > float(init_prevdepth):
                                baselineskip = parser.state.layout["baselineskip"]
                                diff = baselineskip.dimen - prevdepth - item.height
                                if diff < parser.state.layout["lineskiplimit"]:
                                    packed.append(nd.Glue(parser.state.layout["lineskip"], "\\lineskip"))
                                else:
                                    packed.append(nd.Glue(Glue(diff, baselineskip.stretch, baselineskip.shrink), "\\baselineskip"))
                else:
                    # add interline penalty if needed
                    if context.interlinepenalty != 0 and not firstbox:
                        packed.append(nd.Penalty(context.interlinepenalty))
                    d = getattr(context, "prevdepth", None)
                    if d is not None:
                        prevdepth = d
                    # if prevdepth <= -10000, do not add interline glue
                    if float(prevdepth) > float(init_prevdepth) and not firstbox:
                        baselineskip = context.baselineskip
                        diff = baselineskip.dimen - prevdepth - item.height
                        if diff < context.lineskiplimit:
                            packed.append(nd.Glue(context.lineskip, "\\lineskip"))
                        else:
                            packed.append(nd.Glue(Glue(diff, baselineskip.stretch, baselineskip.shrink), "\\baselineskip"))
                # update prevdepth for the next item
                prevdepth = item.depth
                if firstbox:
                    firstbox = False
            # reset prevdepth for rules
            elif item.node_type == nd.NODE_TYPE.RULE:
                prevdepth = init_prevdepth
            # other nodes do not change the prevdepth
            packed.append(item)
    return packed


class VListHolder:
    """
    Common holder for vertical node lists.

    This helper stays in vmode because it provides vertical list
    typesetting behavior.
    """
    def __init__(self, nodes=None):
        self.list = [] if nodes is None else nodes

    def __len__(self):
        return len(self.list)

    def __iter__(self):
        return iter(self.list)

    def __getitem__(self, index):
        return self.list[index]

    def __setitem__(self, index, value):
        self.list[index] = value

    def __delitem__(self, key):
        del self.list[key]

    def append(self, node):
        self.list.append(node)

    def extend(self, nodes):
        self.list.extend(nodes)

    def pop(self, *args):
        return self.list.pop(*args)

    def clear(self):
        self.list.clear()

    def typesetNodes(self, parser, packed):
        return typesetVerticalNodes(parser, self.list, packed)


class VList(lists.List):
    """
    Vertical list build-state wrapper.

    This is what lives on parser.lists while vertical material is scanned.
    It serves a concrete vertical list node and tracks \\prevdepth/\\lastbox
    build-time state.
    """

    def __init__(self, parser, nodes, inner=True):
        self.parser = parser
        self.list = nodes
        self.inner = inner
        self.prevdepth = init_prevdepth
        self.can_lastbox = False
        self.type = lists.LISTTYPE.VERTICAL

    list_type_name = "VList"
    
    def append(self, node):
        self.can_lastbox = False
        context = getattr(node, "typeset_context", None)
        if context is None and getattr(node, "needs_vcontext", False):
            node.typeset_context = VNodeContext(self.parser.state.layout, self.prevdepth)
            context = node.typeset_context
        is_box = node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST)
        if context is None and is_box:
            node.typeset_context = VNodeContext(self.parser.state.layout, self.prevdepth)
            context = node.typeset_context
        if is_box:
            self.prevdepth = getattr(node, "depth", None)
        elif node.node_type == nd.NODE_TYPE.RULE:
            self.prevdepth = init_prevdepth
        elif context is not None:
            self.prevdepth = None
        self.list.append(node)

    def resolvePrevDepth(self):
        if self.prevdepth is not None:
            return self.prevdepth
        for i in range(len(self) - 1, -1, -1):
            node = self[i]
            context = getattr(node, "typeset_context", None)
            if context is not None:
                depth = getattr(node, "depth", None)
                if depth is None:
                    nodes = expandVerticalNode(self.parser, node)
                    for n in nodes:
                        if n.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                            if getattr(n, "typeset_context", None) is None:
                                n.typeset_context = context
                            break
                    self[i:i + 1] = nodes
                    for n in reversed(nodes):
                        depth = getattr(n, "depth", None)
                        if depth is not None:
                            return depth
                    continue
                return depth
            elif node.node_type == nd.NODE_TYPE.RULE:
                break
        return init_prevdepth


class VAdjust(nd.Node, VListHolder):
    """
    A \\vadjust node.
    """

    def __init__(self, vlist):
        VListHolder.__init__(self, vlist)

    @property
    def vlist(self):
        return self.list

    @vlist.setter
    def vlist(self, value):
        self.list = value

    def saveInfo(self):
        return {"init": {"vlist": self.vlist}}

    node_type = nd.NODE_TYPE.ADJUST


class Mark(nd.Node):
    """
    A \\mark node.
    """

    def __init__(self, tokens):
        self.tokens = tokens

    def saveInfo(self):
        return {"init": {"tokens": self.tokens}}

    node_type = nd.NODE_TYPE.MARK


class Insert(nd.Node, VListHolder):
    """
    An insert node.
    """

    def __init__(self, index, vlist):
        self.index = index
        VListHolder.__init__(self, vlist)

    @property
    def vlist(self):
        return self.list

    @vlist.setter
    def vlist(self, value):
        self.list = value

    def saveInfo(self):
        return {"init": {"index": self.index, "vlist": self.vlist}}

    node_type = nd.NODE_TYPE.INS


# Backward-compatibility aliases for code that still references pytex.node.*.
nd.VAdjust = VAdjust
nd.Mark = Mark
nd.Insert = Insert


class PrevDepth(Accessor, DimenCommand):
    """
    The \\prevdepth command. This is vertical-list-local state.
    """
    def readValue(self, parser):
        return parser.readDimen()

    def setGlobal(self, parser, value):
        return self.set(parser, value)

    def set(self, parser, value):
        top = parser.lists[-1]
        if top.type != lists.LISTTYPE.VERTICAL:
            raise ValueError("\\prevdepth can only be used in vertical mode")
        top.prevdepth = value

    def dimenValue(self, parser):
        top = parser.lists[-1]
        if top.type != lists.LISTTYPE.VERTICAL:
            raise ValueError("\\prevdepth can only be used in vertical mode")
        return top.resolvePrevDepth()


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


def readVList(parser, reason, ended=None):
    """
    Read a vertical list.
    @param parser: the parser
    @param reason: the reason for reading the list
    @param ended: called after the list group closes
    """
    vstate = VList(parser, [])
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
        "prevdepth": PrevDepth(),
        "end": End(),
    },
    attributes={
        "readVList": readVList
    }
)
