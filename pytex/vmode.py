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


def _mark_source(node, source):
    if getattr(node, "source", None) is None:
        node.source = source
    return node


def _append_concrete_vertical(packed, state, node):
    packed.append(node)
    if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
        state["prevdepth"] = node.depth
        state["seen_box"] = True
        state["pending_interline"] = False
    elif node.node_type == nd.NODE_TYPE.RULE:
        state["prevdepth"] = init_prevdepth
        state["pending_interline"] = False
    elif getattr(node, "interline_generated", False):
        state["pending_interline"] = True


def _append_interline_glue(packed, state, source, glue_node):
    if glue_node.glue is None:
        return
    node = nd.Glue(glue_node.glue, glue_node.name)
    node.source = source
    node.interline_generated = True
    _append_concrete_vertical(packed, state, node)


def _compute_interline_material(layout, prevdepth, height):
    interline_penalty = layout["interlinepenalty"]
    if float(prevdepth) <= float(init_prevdepth):
        return interline_penalty, nd.Glue(None, "\\baselineskip")
    baselineskip = layout["baselineskip"]
    diff = baselineskip.dimen - prevdepth - height
    if diff < layout["lineskiplimit"]:
        return interline_penalty, nd.Glue(layout["lineskip"], "\\lineskip")
    return interline_penalty, nd.Glue(
        Glue(diff, baselineskip.stretch, baselineskip.shrink),
        "\\baselineskip",
    )


def _append_interline_nodes(parser, packed, state, source, box):
    prevdepth = state["prevdepth"]
    if float(prevdepth) <= float(init_prevdepth):
        return
    interline_penalty = getattr(box, "interline_penalty", None)
    interline_glue = getattr(box, "interline_glue", None)
    default_penalty, default_glue = _compute_interline_material(
        parser.state.layout,
        prevdepth,
        box.height,
    )
    if interline_penalty is None:
        interline_penalty = default_penalty
    if interline_glue is None:
        interline_glue = default_glue
    if interline_penalty != 0:
        penalty = nd.Penalty(interline_penalty)
        penalty.source = source
        penalty.interline_generated = True
        _append_concrete_vertical(packed, state, penalty)
    _append_interline_glue(packed, state, source, interline_glue)


def _should_insert_default_interline(packed, state):
    if state["pending_interline"]:
        return False
    if state["builder_mode"]:
        return True
    prev = packed[-1] if packed else None
    return prev is not None and prev.node_type in (
        nd.NODE_TYPE.HLIST,
        nd.NODE_TYPE.VLIST,
        nd.NODE_TYPE.RULE,
    )


def _append_expanded_item(parser, packed, state, item, source):
    if item.node_type == nd.NODE_TYPE.ADJUST:
        subitems = []
        typesetVerticalNodes(parser, item.vlist, subitems)
        for sub in subitems:
            sub.source = source
            _append_concrete_vertical(packed, state, sub)
        return
    if item.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
        if _should_insert_default_interline(packed, state):
            _append_interline_nodes(parser, packed, state, source, item)
        _append_concrete_vertical(packed, state, _mark_source(item, source))
        return
    _append_concrete_vertical(packed, state, _mark_source(item, source))


def _append_expanded_node(parser, packed, state, node):
    for item in expandVerticalNode(parser, node):
        source = getattr(item, "source", None)
        if source is None:
            source = node
        _append_expanded_item(parser, packed, state, item, source)


def _rebuild_expanded_state(nodes):
    state = {
        "prevdepth": init_prevdepth,
        "seen_box": False,
        "pending_interline": False,
        "builder_mode": True,
    }
    for node in nodes:
        if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            state["prevdepth"] = node.depth
            state["seen_box"] = True
            state["pending_interline"] = False
        elif node.node_type == nd.NODE_TYPE.RULE:
            state["prevdepth"] = init_prevdepth
            state["pending_interline"] = False
        elif getattr(node, "interline_generated", False):
            state["pending_interline"] = True
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
    typeset = getattr(node, "typeset", None)
    if typeset is None:
        _mark_source(node, node)
        return [node]
    packed = []
    node.typeset(parser, packed)
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
    state = {
        "prevdepth": init_prevdepth,
        "seen_box": False,
        "pending_interline": False,
        "builder_mode": False,
    }
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
        self._local_prevdepth = init_prevdepth
        self._parser_prevdepth_active = False
        self.inner = inner
        self.prevdepth = init_prevdepth
        self.lastbox = None
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

    def _appendInterlineMaterial(self, node, prior_prevdepth):
        interline_penalty = getattr(node, "interline_penalty", None)
        interline_glue = getattr(node, "interline_glue", None)
        if interline_glue is None:
            default_penalty, interline_glue = _compute_interline_material(
                self.parser.state.layout,
                prior_prevdepth,
                node.height,
            )
            if interline_penalty is None:
                interline_penalty = default_penalty
        if interline_penalty != 0 and float(prior_prevdepth) > float(init_prevdepth):
            penalty = nd.Penalty(interline_penalty)
            penalty.interline_generated = True
            self.list.append(penalty)
        if float(prior_prevdepth) > float(init_prevdepth) and interline_glue.glue is not None:
            glue_node = nd.Glue(interline_glue.glue, interline_glue.name)
            glue_node.interline_generated = True
            self.list.append(glue_node)

    def _expandedPrevDepth(self):
        for node in reversed(self.expanded):
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                return node.depth
            if node.node_type == nd.NODE_TYPE.RULE:
                return init_prevdepth
        return init_prevdepth

    def _expandedLastBox(self):
        for node in reversed(self.expanded):
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                return node
        return None

    def _syncExpandedTailState(self):
        self.lastbox = self._expandedLastBox()

    def _expandReadyNode(self, node):
        start = len(self.expanded)
        state = _rebuild_expanded_state(self.expanded)
        _append_expanded_node(self.parser, self.expanded, state, node)
        self._syncExpandedTailState()
        return self.expanded[start:]

    def _realizeReadyTailNodes(self):
        while self._expanded_raw_count < len(self.list):
            node = self.list[self._expanded_raw_count]
            self._expandReadyNode(node)
            self._expanded_raw_count += 1

    def _appendBuiltNode(self, node):
        node.source = node
        self.list.append(node)
        self.expanded.append(node)
        self._expanded_raw_count += 1
        if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            self.lastbox = node
            self.prevdepth = node.depth
        elif node.node_type == nd.NODE_TYPE.RULE:
            self.prevdepth = init_prevdepth
        elif self._expanded_raw_count == len(self.list):
            self.prevdepth = self._expandedPrevDepth() if self.expanded else init_prevdepth

    def extendBuilt(self, nodes):
        self._realizeReadyTailNodes()
        for node in nodes:
            self._appendBuiltNode(node)

    def append(self, node):
        self.can_lastbox = False
        self._realizeReadyTailNodes()
        base_prevdepth = self.resolvePrevDepth()
        is_box = node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST)
        if is_box:
            self._appendInterlineMaterial(node, base_prevdepth)
            if getattr(node, "interline_penalty", None) is not None:
                node.interline_penalty = None
            if getattr(node, "interline_glue", None) is not None:
                node.interline_glue = None
            self.prevdepth = getattr(node, "depth", None)
        elif node.node_type == nd.NODE_TYPE.RULE:
            self.prevdepth = init_prevdepth
        if (not is_box and node.node_type != nd.NODE_TYPE.RULE) and getattr(node, "box_materializable", False):
            self.prevdepth = None
        self.list.append(node)
        self._realizeReadyTailNodes()
        if self._expanded_raw_count == len(self.list):
            self.prevdepth = self._expandedPrevDepth() if self.expanded else init_prevdepth

    def resolvePrevDepth(self):
        if self.prevdepth is not None:
            return self.prevdepth
        self._realizeReadyTailNodes()
        if self.prevdepth is not None:
            return self.prevdepth
        for i in range(len(self) - 1, -1, -1):
            node = self[i]
            if getattr(node, "box_materializable", False):
                return _expanded_tail_depth(self.parser, node)
            elif node.node_type == nd.NODE_TYPE.RULE:
                break
        return self._expandedPrevDepth()

    def pop(self, *args):
        index = args[0] if args else -1
        if index not in (-1, len(self.list) - 1):
            raise NotImplementedError("VList.pop only supports removing the tail")
        node = self.list.pop(*args)
        if self._expanded_raw_count > len(self.list):
            self._expanded_raw_count = len(self.list)
        while self.expanded and getattr(self.expanded[-1], "source", None) is node:
            self.expanded.pop()
        self._syncExpandedTailState()
        if self._expanded_raw_count < len(self.list):
            self.prevdepth = None
        else:
            self.prevdepth = self._expandedPrevDepth() if self.expanded else init_prevdepth
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
