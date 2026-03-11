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


def _mark_source(node, source):
    if getattr(node, "source", None) is None:
        node.source = source
    return node


def _append_concrete_vertical(packed, state, node):
    packed.append(node)
    if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
        state["prevdepth"] = node.depth
        state["seen_box"] = True
    elif node.node_type == nd.NODE_TYPE.RULE:
        state["prevdepth"] = init_prevdepth


def _append_expanded_item(parser, packed, state, item, source, node_context=None):
    if item.node_type == nd.NODE_TYPE.ADJUST:
        for sub in expandVerticalNode(parser, item):
            sub_source = getattr(sub, "source", None)
            if sub_source is None:
                sub_source = source
            _append_expanded_item(parser, packed, state, sub, sub_source)
        return
    if item.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
        context = getattr(item, "typeset_context", None)
        if context is None:
            context = node_context
        else:
            item.typeset_context = None
        if context is None:
            if state["seen_box"]:
                prev = packed[-1] if packed else None
                if prev is not None and prev.node_type in (
                    nd.NODE_TYPE.HLIST,
                    nd.NODE_TYPE.VLIST,
                    nd.NODE_TYPE.RULE,
                ):
                    interlinepenalty = parser.state.layout["interlinepenalty"]
                    if interlinepenalty != 0:
                        penalty = nd.Penalty(interlinepenalty)
                        penalty.source = source
                        _append_concrete_vertical(packed, state, penalty)
                    if float(state["prevdepth"]) > float(init_prevdepth):
                        baselineskip = parser.state.layout["baselineskip"]
                        diff = baselineskip.dimen - state["prevdepth"] - item.height
                        if diff < parser.state.layout["lineskiplimit"]:
                            glue = nd.Glue(parser.state.layout["lineskip"], "\\lineskip")
                        else:
                            glue = nd.Glue(
                                Glue(diff, baselineskip.stretch, baselineskip.shrink),
                                "\\baselineskip",
                            )
                        glue.source = source
                        _append_concrete_vertical(packed, state, glue)
        else:
            if context.interlinepenalty != 0 and state["seen_box"]:
                penalty = nd.Penalty(context.interlinepenalty)
                penalty.source = source
                _append_concrete_vertical(packed, state, penalty)
            prevdepth = getattr(context, "prevdepth", None)
            if prevdepth is None:
                prevdepth = state["prevdepth"]
            if float(prevdepth) > float(init_prevdepth) and state["seen_box"]:
                baselineskip = context.baselineskip
                diff = baselineskip.dimen - prevdepth - item.height
                if diff < context.lineskiplimit:
                    glue = nd.Glue(context.lineskip, "\\lineskip")
                else:
                    glue = nd.Glue(
                        Glue(diff, baselineskip.stretch, baselineskip.shrink),
                        "\\baselineskip",
                    )
                glue.source = source
                _append_concrete_vertical(packed, state, glue)
        _append_concrete_vertical(packed, state, _mark_source(item, source))
        return
    _append_concrete_vertical(packed, state, _mark_source(item, source))


def _append_expanded_node(parser, packed, state, node):
    node_context = getattr(node, "typeset_context", None)
    for item in expandVerticalNode(parser, node):
        source = getattr(item, "source", None)
        if source is None:
            source = node
        _append_expanded_item(parser, packed, state, item, source, node_context)
        if item.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            node_context = None


def _rebuild_expanded_state(nodes):
    state = {"prevdepth": init_prevdepth, "seen_box": False}
    for node in nodes:
        if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            state["prevdepth"] = node.depth
            state["seen_box"] = True
        elif node.node_type == nd.NODE_TYPE.RULE:
            state["prevdepth"] = init_prevdepth
    return state


def _expanded_tail_depth(parser, node):
    for item in reversed(expandVerticalNode(parser, node)):
        if item.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            return item.depth
        if item.node_type == nd.NODE_TYPE.RULE:
            return init_prevdepth
    return init_prevdepth


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
            _mark_source(n, node)
        return packed
    typeset = getattr(node, "typeset", None)
    if typeset is None:
        _mark_source(node, node)
        return [node]
    packed = []
    node.typeset(parser, packed)
    if not packed:
        _mark_source(node, node)
        return [node]
    for n in packed:
        _mark_source(n, node)
    return packed


def typesetVerticalNodes(parser, nodes, packed):
    """
    Typeset a raw vertical node list into packed output.
    """
    realize_ready = getattr(nodes, "_realizeReadyTailNodes", None)
    if realize_ready is not None:
        realize_ready()
        expanded_raw_count = getattr(nodes, "_expanded_raw_count", None)
        raw_nodes = getattr(nodes, "list", None)
        if expanded_raw_count is not None and raw_nodes is not None and expanded_raw_count == len(raw_nodes):
            packed.extend(nodes.expanded)
            return packed
    state = {"prevdepth": init_prevdepth, "seen_box": False}
    for node in nodes:
        _append_expanded_node(parser, packed, state, node)
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
        self.expanded = []
        self._expanded_raw_count = 0
        self._expanded_prevdepth = init_prevdepth
        self._expanded_seen_box = False
        self._local_prevdepth = init_prevdepth
        self._parser_prevdepth_active = False
        self.inner = inner
        self.prevdepth = init_prevdepth
        self.can_lastbox = False
        self.type = lists.LISTTYPE.VERTICAL

    list_type_name = "VList"

    @property
    def prevdepth(self):
        if self._parser_prevdepth_active and self.parser.lists and self.parser.lists[-1] is self:
            return self.parser.state.volatile["prevdepth"]
        return self._local_prevdepth

    @prevdepth.setter
    def prevdepth(self, value):
        self._local_prevdepth = value
        if self._parser_prevdepth_active and self.parser.lists and self.parser.lists[-1] is self:
            self.parser.state.volatile["prevdepth"] = value

    def _activateParserState(self):
        if self._parser_prevdepth_active:
            return
        if self.parser.lists and self.parser.lists[-1] is self:
            self.parser.state.volatile["prevdepth"] = self._local_prevdepth
            self._parser_prevdepth_active = True

    @staticmethod
    def _entryReadyForExpansion(node):
        if getattr(node, "page_builder_ready", True) is False:
            return False
        if getattr(node, "box_materializable", False) and node.node_type is None:
            return getattr(node, "_typeset_cache", None) is not None
        next_paragraph = getattr(node, "next_paragraph", None)
        if (
            next_paragraph is not None
            and hasattr(next_paragraph, "typeset_context")
            and getattr(next_paragraph, "typeset_context", None) is None
        ):
            return False
        return True

    def _materializeExpandedNode(self, node):
        start = len(self.expanded)
        state = {
            "prevdepth": self._expanded_prevdepth,
            "seen_box": self._expanded_seen_box,
        }
        _append_expanded_node(self.parser, self.expanded, state, node)
        self._expanded_prevdepth = state["prevdepth"]
        self._expanded_seen_box = state["seen_box"]
        return self.expanded[start:]

    def _didRealizeExpandedNode(self, node, material):
        pass

    def _realizeReadyTailNodes(self):
        while self._expanded_raw_count < len(self.list):
            node = self.list[self._expanded_raw_count]
            if not self._entryReadyForExpansion(node):
                break
            material = self._materializeExpandedNode(node)
            self._expanded_raw_count += 1
            self._didRealizeExpandedNode(node, material)

    def finalizeExpandedNode(self, node):
        if getattr(node, "box_materializable", False) and node.node_type is None:
            if getattr(node, "_typeset_cache", None) is None:
                node.pretypeset(self.parser)
        self._realizeReadyTailNodes()
        if node in self.list[:self._expanded_raw_count]:
            self.prevdepth = self._expanded_prevdepth if self.expanded else init_prevdepth
            return
        raise ValueError("cannot finalize missing vlist node")
    
    def append(self, node):
        self.can_lastbox = False
        self._realizeReadyTailNodes()
        base_prevdepth = self.resolvePrevDepth()
        context = getattr(node, "typeset_context", None)
        if context is None and getattr(node, "needs_vcontext", False):
            node.typeset_context = VNodeContext(self.parser.state.layout, base_prevdepth)
            context = node.typeset_context
        is_box = node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST)
        if context is None and is_box:
            node.typeset_context = VNodeContext(self.parser.state.layout, base_prevdepth)
            context = node.typeset_context
        if is_box:
            self.prevdepth = getattr(node, "depth", None)
        elif node.node_type == nd.NODE_TYPE.RULE:
            self.prevdepth = init_prevdepth
        elif context is not None or getattr(node, "box_materializable", False):
            self.prevdepth = None
        self.list.append(node)
        self._realizeReadyTailNodes()
        if self._expanded_raw_count == len(self.list):
            self.prevdepth = self._expanded_prevdepth if self.expanded else init_prevdepth

    def resolvePrevDepth(self):
        if self.prevdepth is not None:
            return self.prevdepth
        self._realizeReadyTailNodes()
        if self.prevdepth is not None:
            return self.prevdepth
        for i in range(len(self) - 1, -1, -1):
            node = self[i]
            context = getattr(node, "typeset_context", None)
            if context is not None:
                depth = getattr(node, "depth", None)
                if depth is None:
                    return _expanded_tail_depth(self.parser, node)
                return depth
            elif node.node_type == nd.NODE_TYPE.RULE:
                break
        return init_prevdepth

    def pop(self, *args):
        index = args[0] if args else -1
        if index not in (-1, len(self.list) - 1):
            raise NotImplementedError("VList.pop only supports removing the tail")
        node = self.list.pop(*args)
        if self._expanded_raw_count > len(self.list):
            self._expanded_raw_count = len(self.list)
        while self.expanded and getattr(self.expanded[-1], "source", None) is node:
            self.expanded.pop()
        state = _rebuild_expanded_state(self.expanded)
        self._expanded_prevdepth = state["prevdepth"]
        self._expanded_seen_box = state["seen_box"]
        if self._expanded_raw_count < len(self.list):
            self.prevdepth = None
        else:
            self.prevdepth = self._expanded_prevdepth if self.expanded else init_prevdepth
        return node


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

    def materialize_box_nodes(self, parser):
        packed = []
        typesetVerticalNodes(parser, self.vlist, packed)
        return packed

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
    The \\prevdepth command. This is current vertical-builder state.
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
