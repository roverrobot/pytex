"""
The horizontal and vertical lists of TeX.
"""


from pytex import serialization
from pytex import node as nd
from pytex.token import Command, CATCODE
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
    def __init__(self, parser, type: LISTTYPE, inner: bool=True, nodes=[]):
        super().__init__(nodes)
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
        raise ValueError(f"this command cannot be used in {mode} mode", pos)
    
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
    def __init__(self, name, mode):
        super().__init__(name)
        self.mode = mode
    
    def saveInfo(self):
        return {"init": {"mode": self.mode}}

    def condition(self, parser):
        return 0 if parser.lists[-1].type == self.mode else 1


class IfInner(conditional.Conditional):
    """
    The \\ifinner command.
    """
    def __init__(self):
        super().__init__("\\ifinner")
    
    def condition(self, parser):
        return 0 if parser.lists[-1].inner else 1


def readList(parser, list, reason: GROUP_TYPE):
    """
    Read a list from the input stack.
    @param parser: The parser.
    @param list: The list to read.
    @param reason: The reason for reading the list.
    """
    def callback():
        parser.run = False
    parser.skipFiller()
    pos = parser.input.position()
    t = parser.token_expand()
    if t.catcode != CATCODE.BEGIN_GROUP:
        raise ValueError("expecting a {", pos)
    # when in math mode, beginning a group will create a new math list
    # so there is no need to provide one
    if list is not None:
        parser.lists.append(list)
    parser.beginGroup(pos, reason, callback)
    parser.loop()
    parser.run = True
    # math list has already been popped in endgroup
    if list is not None:
        parser.lists.pop()
    return list


class Rule(ModeDependentCommand):
    """
    The \\hrule or \\vrule command.
    @param vertical: Whether the rule is vertical.

    Note that \\hrule is vertical and \\vrule is horizontal.
    """
    def __init__(self, vertical):
        self.vert = vertical

    def saveInfo(self):
        return {"init": {"vertical": self.vert}}

    def readRule(self, parser):
        if self.vert:
            width = None
            height = 0.4
            depth = 0
        else:
            width = 0.4
            height = None
            depth = None
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


class Penalty(Command):
    """
    The \\penalty command.
    """
    def execute(self, parser):
        penalty = parser.readInteger()
        node = nd.Penalty(penalty)
        parser.lists[-1].append(node)


class Insert(Command):
    """
    The \\insert command.
    """
    def execute(self, parser):
        pos = parser.input.position()
        n = parser.readInteger()
        if n < 0 or n == 255:
            raise ValueError(f"invalid insert number {n}", pos)
        vlist = parser.readVList(GROUP_TYPE.INSERT)
        parser.lists[-1].append(nd.Insert(n, vlist))


class Mark(Command):
    """
    The \\mark command.
    """
    def execute(self, parser):
        text = parser.readGeneralText(expand=True)
        parser.lists[-1].append(nd.Mark(text))


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

    def saveInfo(self):
        return {"init": {"glue": self.glue}}
    
    def glueValue(self, parser):
        return parser.readGlue() if self.glue is None else self.glue
    
    def glueNode(self, parser):
        return nd.Glue(self.glueValue(parser))


class Remove(Command):
    """
    Remove the last node from the current list if it is of the given type
    """
    def __init__(self, node_type):
        self.node_type = node_type

    def saveInfo(self):
        return {"init": {"node_type": self.node_type}}
    
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
        "ifvmode": IfMode("\\ifvmode", LISTTYPE.VERTICAL),
        "ifhmode": IfMode("\\ifhmode", LISTTYPE.HORIZONTAL),
        "ifmmode": IfMode("\\ifmmode", LISTTYPE.MATH),
        "ifinner": IfInner(),
        "hrule": Rule(True),
        "vrule": Rule(False),
        "penalty": Penalty(),
        "insert": Insert(),
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
