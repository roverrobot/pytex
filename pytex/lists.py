"""
The horizontal and vertical lists of TeX.
"""


from pytex import serialization
from pytex import node as nd
from pytex.token import Command, CATCODE
from math import inf
from pytex.dimen import Dimen, NEG_MAX_DIMEN
import enum
from pytex.module import Module
from pytex.state import GROUP_TYPE
from pytex import conditional


class LISTTYPE(enum.Enum):
    VERTICAL = 0
    HORIZONTAL = 1
    MATH = 2


class List(list, serialization.Serializable):
    """
    A list of nodes.
    @param parser: The parser the created the list
    @param type: The type of list.
    @param inner: Whether the list is in internal mode.

    The internal mode means an internal vlist, or restricted hlist, or nondisplay mlist.
    """
    def __init__(self, parser, type: LISTTYPE, inner: bool=True, nodes=None):
        super().__init__([] if nodes is None else nodes)
        self.parser = parser
        self.type = type
        self.inner = inner

    def __repr__(self):
        if self.type == LISTTYPE.VERTICAL:
            type = "VList"
        elif self.type == LISTTYPE.HORIZONTAL:
            type = "HList"
        else:
            type = "MList"
        inner = "inner" if self.inner else ""
        return f'{type}({inner}, [{", ".join(repr(node) for node in self)}])'

    def meaning(self, parser):
        if self.type == LISTTYPE.VERTICAL:
            return "VList" if self.inner else "VList(outer)"
        if self.type == LISTTYPE.HORIZONTAL:
            return "HList(inner)" if self.inner else "HList"
        return "MList(inner)" if self.inner else "DisplayMathList"

    def append(self, node):
        # A raw horizontal list must not become a node in another list.
        # Paragraph is the only horizontal-list-like value allowed on a list,
        # and it marks itself with node_type = None.
        if isinstance(node, List) and node.type == LISTTYPE.HORIZONTAL:
            if getattr(node, "node_type", nd.NODE_TYPE.HLIST) == nd.NODE_TYPE.HLIST:
                raise ValueError("HList cannot be added directly to a list")
        super().append(node)
    
    def saveInfo(self):
        return {
            "init": {
                "inner": self.inner,
                "nodes": [x for x in self],
            }
        }
    
    @classmethod
    def new(cls, parser, **kwargs):
        return cls(parser, **kwargs)


class ListBuildState:
    """
    Runtime-only parser-stack wrapper around a list node.

    Build-time state (for example, spacefactor while scanning horizontal
    material) lives here instead of on the node object that will later be
    typeset/materialized.
    """
    _local_attrs = {"parser", "node", "group_type"}

    def __init__(self, parser, node):
        object.__setattr__(self, "parser", parser)
        object.__setattr__(self, "node", node)
        # build commands may stash temporary metadata (e.g., group_type) here
        object.__setattr__(self, "group_type", None)

    @property
    def list_node(self):
        # Backward-compatible alias during the transition to node-oriented naming.
        return self.node

    def __repr__(self):
        return repr(self.node)

    def __getattr__(self, name):
        return getattr(self.node, name)

    def __setattr__(self, name, value):
        if name in self._local_attrs:
            object.__setattr__(self, name, value)
            return
        setattr(self.node, name, value)

    def __len__(self):
        return len(self.node)

    def __iter__(self):
        return iter(self.node)

    def __getitem__(self, index):
        return self.node[index]

    def __setitem__(self, index, value):
        self.node[index] = value

    def __delitem__(self, key):
        del self.node[key]

    def _raw_append(self, node):
        target = self.node
        if isinstance(target, list):
            list.append(target, node)
            return
        target.append(node)

    def append(self, node):
        self.node.append(node)

    def extend(self, values):
        for value in values:
            self.append(value)

    def pop(self, *args):
        return self.node.pop(*args)

    def clear(self):
        self.node.clear()


class MathListBuildState(ListBuildState):
    _local_attrs = ListBuildState._local_attrs | {"building_atom"}

    def __init__(self, parser, node):
        super().__init__(parser, node)
        object.__setattr__(self, "building_atom", None)

    def clear(self):
        self.building_atom = None
        target = self.node
        if isinstance(target, list):
            list.clear(target)
            return
        target.clear()

    def buildAtom(self, field, atom=None):
        from pytex import mmode

        if atom is None:
            atom = self[-1] if len(self) > 0 else None
            if not isinstance(atom, mmode.Atom):
                atom = mmode.Atom(mmode.ATOM_TYPE.ORD)
                atom.nucleus = mmode.MList(self.parser)
                self.append(atom)
        else:
            self.append(atom)
        if getattr(atom, field, None) is not None:
            if field == "sub":
                raise ValueError("double subscript", self.parser.input.position())
            if field == "sup":
                raise ValueError("double superscript", self.parser.input.position())
            raise ValueError("double field", self.parser.input.position())
        self.building_atom = (atom, field)

    def append(self, node):
        from pytex import box
        from pytex import mmode

        if self.building_atom is not None:
            atom, field = self.building_atom
            setattr(atom, field, node)
            self.building_atom = None
            return
        if isinstance(node, box.Box):
            node = mmode.Box(node)
        elif isinstance(node, mmode.MList):
            n = mmode.Atom(mmode.ATOM_TYPE.ORD)
            n.nucleus = node
            node = n
        elif isinstance(node, mmode.MathSymbol):
            n = mmode.Op() if node.type == mmode.ATOM_TYPE.OP else mmode.Atom(node.type)
            n.nucleus = node
            node = n
        self._raw_append(node)


class ModeDependentCommand(Command):
    """
    A command that behaves differently in different modes.
    """
    def execute(self, parser):
        top = parser.lists[-1]
        mode = top.type
        if mode == LISTTYPE.HORIZONTAL:
            self.horizontal(parser, top)
        elif mode == LISTTYPE.VERTICAL:
            self.vertical(parser, top)
        elif mode == LISTTYPE.MATH:
            self.math(parser, top)
    
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
        if not isinstance(state, ListBuildState):
            raise TypeError("readList expects a ListBuildState")
        parser.lists.append(state)
        ended = ListReadEndCallback(parser, state, ended)
    parser.beginGroup(pos, reason, ended=ended)
    return None if state is None else state.node


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
        "/" : ItalicCorrection(),
    },
    attributes={
        "readList": readList,
    },
)
