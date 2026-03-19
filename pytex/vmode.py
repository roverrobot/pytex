"""
Implement vertical mode commands and vlist handling.
"""


from pytex import node as nd
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.module import Module
from pytex.token import Command, CommandToken
from pytex.dimen import Dimen, DimenArrayItemAccessor


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
        realize_ready = getattr(item.vlist, "_realizeReadyTailNodes", None)
        if realize_ready is not None:
            realize_ready()
            subitems = item.vlist.list
        else:
            subitems = item.vlist
        for sub in subitems:
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

class VList(lists.List):
    """
    Vertical list build-state wrapper.

    This is what lives on parser.lists while vertical material is scanned.
    It serves a concrete vertical list node and tracks \\prevdepth/\\lastbox
    build-time state.
    """

    def __init__(self, parser, nodes, inner=True):
        self.parser = parser
        self.raw = nodes
        self.list = []
        self.expanded = self.list
        self._expanded_raw_count = 0
        self.inner = inner
        self.lastbox = None
        self.can_lastbox = False
        self.saved_prevdepth = parser.state.globals.get("prevdepth", init_prevdepth)
        self.type = lists.LISTTYPE.VERTICAL
        self.parser.state.globals["prevdepth"] = init_prevdepth

    def enter(self):
        return

    list_type_name = "VList"

    def setBuilderPrevdepth(self, value):
        self.parser.state.globals["prevdepth"] = value

    def restorePrevdepth(self):
        self.parser.state.globals["prevdepth"] = self.saved_prevdepth

    @property
    def prevdepth(self):
        return self.parser.state.globals["prevdepth"]

    @prevdepth.setter
    def prevdepth(self, value):
        self.parser.state.globals["prevdepth"] = value

    def _expandedPrevDepth(self):
        for node in reversed(self.list):
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                return node.depth
            if node.node_type == nd.NODE_TYPE.RULE:
                return init_prevdepth
        return init_prevdepth

    def _expandedLastBox(self):
        for node in reversed(self.list):
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                return node
        return None

    def _syncExpandedTailState(self):
        self.lastbox = self._expandedLastBox()

    def _currentExpandedState(self):
        pending = bool(self.list and getattr(self.list[-1], "interline_generated", False))
        prevdepth = self.prevdepth
        if prevdepth is None:
            prevdepth = self._expandedPrevDepth() if self.list else init_prevdepth
        return {
            "prevdepth": prevdepth,
            "seen_box": self.lastbox is not None,
            "pending_interline": pending,
            "builder_mode": True,
        }

    def _dropDrainedRawTail(self, source):
        if not self.raw or self.raw[-1] is not source:
            return False
        if self.list and getattr(self.list[-1], "source", None) is source:
            return False
        self.raw.pop()
        if self._expanded_raw_count > len(self.raw):
            self._expanded_raw_count = len(self.raw)
        return True

    def _expandReadyNode(self, node):
        start = len(self.list)
        state = self._currentExpandedState()
        _append_expanded_node(self.parser, self.list, state, node)
        self._syncExpandedTailState()
        self.setBuilderPrevdepth(state["prevdepth"])
        return self.list[start:]

    def _realizeReadyTailNodes(self):
        while self._expanded_raw_count < len(self.raw):
            node = self.raw[self._expanded_raw_count]
            self._expandReadyNode(node)
            self._expanded_raw_count += 1

    def _appendBuiltNode(self, node):
        node.source = node
        self.raw.append(node)
        self.list.append(node)
        self._expanded_raw_count = len(self.raw)
        if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            self.lastbox = node
            self.setBuilderPrevdepth(node.depth)
        elif node.node_type == nd.NODE_TYPE.RULE:
            self.setBuilderPrevdepth(init_prevdepth)
        elif self._expanded_raw_count == len(self.raw):
            self.setBuilderPrevdepth(self._expandedPrevDepth() if self.list else init_prevdepth)

    def extendBuilt(self, nodes):
        for node in nodes:
            self._appendBuiltNode(node)

    def append(self, node):
        self.can_lastbox = False
        self._realizeReadyTailNodes()
        self.raw.append(node)
        self._realizeReadyTailNodes()

    def resolvePrevDepth(self):
        self._realizeReadyTailNodes()
        if self.prevdepth is not None:
            return self.prevdepth
        return self._expandedPrevDepth() if self.list else init_prevdepth

    def removeLastConcrete(self, node_type):
        self._realizeReadyTailNodes()
        if not self.list or self.list[-1].node_type != node_type:
            return None
        node = self.list.pop()
        source = getattr(node, "source", None) or node
        self._dropDrainedRawTail(source)
        self._syncExpandedTailState()
        if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            self.setBuilderPrevdepth(self.lastbox.depth if self.lastbox is not None else init_prevdepth)
        elif node.node_type == nd.NODE_TYPE.RULE:
            self.setBuilderPrevdepth(self._expandedPrevDepth() if self.list else init_prevdepth)
        return node

    def pop(self, *args):
        index = args[0] if args else -1
        if index not in (-1, len(self.list) - 1):
            raise NotImplementedError("VList.pop only supports removing the tail")
        self._realizeReadyTailNodes()
        node = self.list.pop()
        source = getattr(node, "source", None) or node
        self._dropDrainedRawTail(source)
        self._syncExpandedTailState()
        if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            self.setBuilderPrevdepth(self.lastbox.depth if self.lastbox is not None else init_prevdepth)
        elif node.node_type == nd.NODE_TYPE.RULE:
            self.setBuilderPrevdepth(self._expandedPrevDepth() if self.list else init_prevdepth)
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
        return {"vlist": self.vlist}, None

    node_type = nd.NODE_TYPE.ADJUST


class Mark(nd.Node):
    """
    A \\mark node.
    """

    def __init__(self, tokens):
        self.tokens = tokens

    def saveInfo(self):
        return {"tokens": self.tokens}, None

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
        return {"index": self.index, "vlist": self.vlist}, None

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
        par.entry = parser.state.equitable.entry("\\par")
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
        "end": End(),
    },
    attributes={
        "readVList": readVList
    },
    parameters={
        "prevdepth": {"value": Dimen(), "accessor": DimenArrayItemAccessor, "domain": "globals"},
    },
)
