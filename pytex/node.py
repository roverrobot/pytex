"""
This module implements the nodes of horizontal and vertical lists.
"""


import enum


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
    WHAT = 9
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
    node_type = None
    def __repr__(self):
        return self.node_type.name
    

class Box(Node):
    """
    A box node.
    """
    def __init__(self, width, height, depth):
        self.width = width
        self.height = height
        self.depth = depth


class List(Node):
    """
    a vlist or a hlist node.
    """
    def __init__(self):
        self.nodes = []
    
    def __repr__(self):
        return f"{self.node_type.name}({self.nodes})"


class CharNode(Box):
    """
    A character node.
    """
    node_type = NODE_TYPE.CHAR
    def __init__(self, char_info, font):
        self.char_info = char_info
        self.font = font

    def __repr__(self):
        return f"{self.char}"


class Rule(Box):
    """
    A rule node.
    """
    node_type = NODE_TYPE.RULE
    def __init__(self, width, height, depth):
        super().__init__(width, height, depth)
    
    def __repr__(self):
        return f"Rule({self.width}, {self.height}, {self.depth})"


class Glue(Node):
    """
    A glue node.
    """
    node_type = NODE_TYPE.GLUE
    def __init__(self, glue):
        self.glue = glue

    def __repr__(self):
        return f"Glue(self.glue)"
    

class Kern(Node):
    """
    A kern node.
    """
    node_type = NODE_TYPE.KERN
    def __init__(self, kern):
        self.kern = kern

    def __repr__(self):
        return f"Kern(self.kern)"


class Penalty(Node):
    """
    A penalty node.
    """
    node_type = NODE_TYPE.PENALTY
    def __init__(self, penalty):
        self.penalty = penalty

    def __repr__(self):
        return f"Penalty(self.penalty)"


class Disc(Node):
    """
    A discretionary node.
    """
    node_type = NODE_TYPE.DISC
    def __init__(self, pre, post, replace):
        self.pre = pre
        self.post = post
        self.replace = replace

    def __repr__(self):
        return f"Disc({self.pre}, {self.post}, {self.replace})"


class Ligature(CharNode):
    """
    A ligature node.
    """
    node_type = NODE_TYPE.LIGATURE
    def __init__(self, char_info, font, components):
        super().__init__(char_info, font)
        self.components = components

    def __repr__(self):
        s = ""
        for c in self.components:
            s += str(c)
        return f"Ligature({self.char}, {s})"
    

class What(Node):
    """
    A whatisit node.
    """
    node_type = NODE_TYPE.WHAT
    def __init__(self, subtype):
        self.subtype = subtype
