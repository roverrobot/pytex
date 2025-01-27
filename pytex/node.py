"""
This module implements the nodes of horizontal and vertical lists.
"""


import enum
from pytex.dimen import Dimen


class NODE_TYPE(enum.Enum):
    CHAR = 0
    HLIST = 1
    VLIST = 2
    RULE = 3
    INS = 4
    MARK = 5
    ADJUST = 6
    LIGATURE = 7
    DISC = 8
    WHATSIT = 9
    MATH = 10 # mlist
    GLUE = 11
    KERN = 12
    PENALTY = 13
    UNSET = 14
    MATHS = 15 # math mode nodes


class Node:
    """
    Base class for all nodes.
    """
    def __repr__(self):
        return self.node_type.name
    

class Box(Node):
    """
    A box node.
    """
    def __init__(self, width, height, depth):
        self.width = Dimen(width)
        self.height = Dimen(height)
        self.depth = Dimen(depth)


class CharNode(Box):
    """
    A character node.
    @param char_info: the character information
    @param font: the font of the character
    """
    def __init__(self, char_info, font):
        at = font.at
        super().__init__(char_info.width * at, char_info.height * at, char_info.depth * at)
        self.char = char_info.char
        self.italic = char_info.italic * at
        self.char_info = char_info
        self.font = font

    node_type = NODE_TYPE.CHAR

    def __repr__(self):
        return f"{self.char}"


class Rule(Box):
    """
    A rule node.
    """
    node_type = NODE_TYPE.RULE
    
    def __init__(self, width, height, depth):
        w = 0 if width is None else width
        h = 0 if height is None else height
        d = 0 if depth is None else depth
        super().__init__(w, h, d)
        if width is None:
            self.width = None
        if height is None:
            self.height = None
        if depth is None:
            self.depth = None
    def __repr__(self):
        return f"Rule({self.width}, {self.height}, {self.depth})"


class Glue(Node):
    """
    A glue node.
    @param glue: the glue
    """
    def __init__(self, glue):
        self.glue = glue
        self.kern = None

    def __repr__(self):
        set = self.glue if self.kern is None else f"{self.kern}pt"
        return f"Glue({set})"
    
    node_type = NODE_TYPE.GLUE


class Kern(Node):
    """
    A kern node.
    @param kern: the kern
    @param automatic: whether the kern is automatic (from a ligature)
    """
    def __init__(self, kern, automatic: bool = False):
        self.kern = Dimen(kern)
        self.automatic = automatic

    node_type = NODE_TYPE.KERN

    def __repr__(self):
        return f"Kern({self.kern}pt)"


class Penalty(Node):
    """
    A penalty node.
    @param penalty: the penalty
    """
    def __init__(self, penalty):
        self.penalty = penalty

    node_type = NODE_TYPE.PENALTY

    def __repr__(self):
        return f"Penalty(self.penalty)"


class Disc(Node):
    """
    A discretionary node.
    """
    def __init__(self, pre, post, replace):
        self.pre = pre
        self.post = post
        self.replace = replace

    def __repr__(self):
        return f"Disc({self.pre}, {self.post}, {self.replace})"

    node_type = NODE_TYPE.DISC
   

class WhatsIt(Node):
    """
    A whatsit node.
    """
    node_type = NODE_TYPE.WHATSIT

    def output(self, parser, device):
        """
        Output the whatsit node.
        @param parser: the parser
        @param device: the output device
        """
        raise NotImplementedError("output method should be implemented in subclass")


class Special(WhatsIt):
    """
    A special node.
    """
    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return f"Special({self.text})"

    def output(self, parser, device):
        device.special(self.text)


class VAdjust(Node):
    """
    A vadjust node.
    """
    def __init__(self, vlist):
        self.vlist = vlist

    node_type = NODE_TYPE.ADJUST


class Mark(Node):
    """
    A \mark node.
    """
    def __init__(self, tokens):
        self.tokens = tokens

    node_type = NODE_TYPE.MARK


class Insert(Node):
    """
    An insert node.
    """
    def __init__(self, index, vlist):
        self.index = index
        self.vlist = vlist

    node_type = NODE_TYPE.INS