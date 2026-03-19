"""
The horizontal and vertical lists of TeX.
"""


from pytex import serialization
from pytex import node as nd
from pytex.token import Command, CATCODE
from math import inf
from copy import deepcopy
from pytex.dimen import Dimen, NEG_MAX_DIMEN, DimenCommand
from pytex.glue import Glue, GlueCommand as GlueValueCommand
import enum
from pytex.module import Module
from pytex.state import GROUP_TYPE
from pytex import conditional


class LISTTYPE(enum.Enum):
    VERTICAL = 0
    HORIZONTAL = 1
    MATH = 2


class List:
    """
    Runtime-only parser-stack wrapper around a list node.

    Build-time state (for example, spacefactor while scanning horizontal
    material) lives here instead of on the node object that will later be
    typeset/expanded.
    """
    def __init__(self, parser, nodes: list, inner: bool):
        self.parser = parser
        self.list = nodes
        self.inner = inner

    list_type_name = None

    def __repr__(self):
        return f"{self.list_type_name}{repr(self.list)}"

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
        for node in nodes:
            self.append(node)

    def pop(self, *args):
        return self.list.pop(*args)

    def clear(self):
        self.list.clear()


class ModeDependentCommand(Command):
    """
    A command that behaves differently in different modes.
    """
    def execute(self, parser):
        top = parser.lists[-1]
        mode = top.type
        if mode == LISTTYPE.HORIZONTAL:
            return self.horizontal(parser, top)
        elif mode == LISTTYPE.VERTICAL:
            return self.vertical(parser, top)
        elif mode == LISTTYPE.MATH:
            return self.math(parser, top)
    
    def modeError(self, parser, mode):
        pos = parser.input.position()
        raise ValueError(f"The command {self.name} cannot be used in {mode} mode", pos)
    
    def horizontal(self, parser, hlist):
        self.modeError(parser, "horizontal")
    
    def vertical(self, parser, vlist):
        self.modeError(parser, "vertical")
    
    def math(self, parser, mlist):
        self.modeError(parser, "math")


class Kern(Command):
    """
    Add a kern node.

    This command is mode-independent.
    """
    def execute(self, parser):
        dimen = parser.readDimen()
        node = nd.Kern(dimen)
        parser.lists[-1].append(node)


class Penalty(Command):
    """
    Add a penalty node.

    This command is mode-independent.
    """
    def execute(self, parser):
        penalty = parser.readInteger()
        node = nd.Penalty(penalty)
        parser.lists[-1].append(node)


class IfMode(conditional.Conditional):
    """
    A conditional that checks the current mode.
    """
    def __init__(self, mode):
        super().__init__()
        self.mode = mode
    
    def condition(self, parser):
        return 0 if parser.lists[-1].type == self.mode else 1


class IfInner(conditional.Conditional):
    """
    The \\ifinner command.
    """
    def condition(self, parser):
        return 0 if parser.lists[-1].inner else 1


class ListReadEndCallback:
    def __init__(self, parser, state, ended):
        self.parser = parser
        self.state = state
        self.ended = ended

    def __call__(self):
        if self.state is not None:
            self.parser.lists.pop()
        if self.ended is not None:
            self.ended()


def readList(parser, state, reason: GROUP_TYPE, ended=None):
    """
    Read a list from the input stack.
    @param parser: The parser.
    @param state: The list build-state to read into.
    @param reason: The reason for reading the list.
    @param ended: Called after the list group closes and the list is popped.
    """
    parser.skipFiller()
    pos = parser.input.position()
    t = parser.token_expand()
    t = parser.token_meaning(t)
    if t.catcode != CATCODE.BEGIN_GROUP:
        raise ValueError("expecting a {", pos)
    if state is not None:
        assert isinstance(state, List)
        parser.lists.append(state)
        ended = ListReadEndCallback(parser, state, ended)
    parser.beginGroup(pos, reason, ended=ended)
    return None if state is None else state.list


class Rule(ModeDependentCommand):
    """
    The \\hrule or \\vrule command.
    @param vertical: Whether the rule is vertical.

    Note that \\hrule is vertical and \\vrule is horizontal.
    """
    def __init__(self, vertical):
        self.vert = vertical

    def readRule(self, parser):
        if self.vert:
            width = NEG_MAX_DIMEN
            height = Dimen(0.4)
            depth = Dimen()
        else:
            width = Dimen(0.4)
            height = NEG_MAX_DIMEN
            depth = NEG_MAX_DIMEN
        while True:
            k = parser.readKeyword(["width", "height", "depth"])
            if k is None:
                break
            if k == "width":
                width = parser.readDimen()
            elif k == "height":
                height = parser.readDimen()
            elif k == "depth":
                depth = parser.readDimen()
        return nd.Rule(width, height, depth)

    def horizontal(self, parser, hlist):
        if self.vert:
            super().horizontal(parser, hlist)
        hlist.append(self.readRule(parser))
    
    def vertical(self, parser, vlist):
        if not self.vert:
            super().vertical(parser, vlist)
        vlist.append(self.readRule(parser))
    
    def math(self, parser, mlist):
        self.horizontal(parser, mlist)


# Duplicate Penalty class removed (see above).


class Mark(Command):
    """
    The \\mark command.
    """
    def execute(self, parser):
        from pytex import vmode

        text = parser.readGeneralText(expand=True)
        parser.lists[-1].append(vmode.Mark(text))


class Special(Command):
    """
    The \\special command.
    """
    def execute(self, parser):
        text = parser.readGeneralText(expand=True)
        parser.lists[-1].append(nd.Special(text))


class GlueCommand:
    """
    Add a horizontal skip to the current list.
    @param vertical: whether the glue is vertical
    @param glue: The glue to add
    """
    def __init__(self, vertical: bool, glue=None):
        self.vert = vertical
        self.glue = glue

    def glueValue(self, parser):
        return parser.readGlue() if self.glue is None else self.glue
    
    def glueNode(self, parser):
        return nd.Glue(self.glueValue(parser), None)


class Remove(Command):
    """
    Remove the last node from the current list if it is of the given type
    """
    def __init__(self, node_type):
        self.node_type = node_type

    def execute(self, parser):
        top = parser.lists[-1]
        if len(top) > 0:
            if top[-1].node_type == self.node_type:
                top.pop()


def _lastConcreteNode(top):
    """
    Return the concrete tail node of the current list.

    For live vertical lists, raw nodes and concrete contributed nodes differ:
    the raw tail may be a paragraph/display node while TeX's \\lastskip,
    \\lastkern, and \\lastpenalty inspect the already-expanded vertical tail.
    """
    expanded = getattr(top, "expanded", None)
    if expanded is not None:
        realize_ready = getattr(top, "_realizeReadyTailNodes", None)
        if realize_ready is not None:
            realize_ready()
        if expanded:
            return expanded[-1]
        return None
    if len(top) == 0:
        return None
    return top[-1]


class LastPenalty(Command):
    """
    The \\lastpenalty command.
    """
    def intValue(self, parser):
        node = _lastConcreteNode(parser.lists[-1])
        if node is None or node.node_type != nd.NODE_TYPE.PENALTY:
            return 0
        return node.penalty


class LastKern(Command, DimenCommand):
    """
    The \\lastkern command.
    """
    def dimenValue(self, parser):
        node = _lastConcreteNode(parser.lists[-1])
        if node is None or node.node_type != nd.NODE_TYPE.KERN:
            return Dimen()
        return node.kern


class LastSkip(Command, GlueValueCommand):
    """
    The \\lastskip command.
    """
    def glueValue(self, parser):
        node = _lastConcreteNode(parser.lists[-1])
        if node is None or node.node_type != nd.NODE_TYPE.GLUE:
            return Glue()
        return deepcopy(node.glue)


class ItalicCorrection(ModeDependentCommand):
    """
    The \\/ command.
    """
    def horizontal(self, parser, hlist):
        if len(hlist) > 1:
            last = hlist[-1]
            if isinstance(last, nd.CharNode):
                hlist.append(nd.Kern(last.italic))
    
    def math(self, parser, mlist):
        # append a 0-width kern
        mlist.append(nd.Kern(0))


mod = Module("lists",
    commands={
        "kern": Kern(),
        "penalty": Penalty(),
        "ifvmode": IfMode(LISTTYPE.VERTICAL),
        "ifhmode": IfMode(LISTTYPE.HORIZONTAL),
        "ifmmode": IfMode(LISTTYPE.MATH),
        "ifinner": IfInner(),
        "hrule": Rule(True),
        "vrule": Rule(False),
        "penalty": Penalty(),
        "mark": Mark(),
        "special": Special(),
        "unkern": Remove(nd.NODE_TYPE.KERN),
        "unpenalty": Remove(nd.NODE_TYPE.PENALTY),
        "unskip": Remove(nd.NODE_TYPE.GLUE),
        "lastskip": LastSkip(),
        "lastkern": LastKern(),
        "lastpenalty": LastPenalty(),
        # Compatibility alias for misspelling seen in legacy test input.
        "lastpennalty": LastPenalty(),
        "/" : ItalicCorrection(),
    },
    attributes={
        "readList": readList,
    },
)
