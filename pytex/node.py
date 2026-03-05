"""
This module implements the nodes of horizontal and vertical lists.
"""


import enum
from pytex.dimen import Dimen
from pytex import serialization


class NODE_TYPE(enum.IntEnum):
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
    MATH = 10 # math on/off
    GLUE = 11
    KERN = 12
    PENALTY = 13
    UNSET = 14
    MATHNODE= 15 # math mode nodes
    ACCENT = 16 # accent node
    # pytex extension
    ALIGNMENT = 17


class Node(serialization.Serializable):
    """
    Base class for all nodes.
    """
    typeset = None
    source = None

    def __repr__(self):
        return self.node_type.name

    def meaning(self, parser):
        return repr(self)


class MathShift(Node):
    """
    A math on/off node.
    """
    def __init__(self, on: bool):
        self.on = on

    def saveInfo(self):
        return {"init": {"on": self.on}}

    node_type = NODE_TYPE.MATH

    def __repr__(self):
        return "MathOn" if self.on else "MathOff"

    def meaning(self, parser):
        return "\\mathon" if self.on else "\\mathoff"
    

class Box(Node):
    """
    A box node.
    """
    def __init__(self, width, height, depth):
        self.width = None if width is None else Dimen(width)
        self.height = None if height is None else Dimen(height)
        self.depth = None if depth is None else Dimen(depth)

    def saveInfo(self):
        return {"init": {"width": self.width, "height": self.height, "depth": self.depth}}

    def meaning(self, parser):
        kind = "\\hbox" if self.node_type == NODE_TYPE.HLIST else "\\vbox"
        line = f"{kind}({self.height}+{self.depth})x{self.width}"
        to = getattr(self, "to", None)
        natural = getattr(self, "natural", None)
        spread = None if natural is None or to is None else to - natural.dimen
        if spread is not None and spread != 0:
            glue = None
            ratio_info = getattr(self, "glue_ratio", (0, 0, 1))
            if isinstance(ratio_info, tuple):
                sign, num, den = ratio_info
                sign = int(sign)
                num = int(num)
                den = int(den)
                if sign == 0 or num == 0 or den == 0:
                    signed_ratio = Dimen()
                else:
                    signed_ratio = Dimen(integer=Dimen._trunc_div(sign * num * Dimen.scale, den))
            elif isinstance(ratio_info, Dimen):
                signed_ratio = ratio_info
            else:
                signed_ratio = Dimen(ratio_info)
            ratio = signed_ratio
            if spread > 0:
                glue = natural.stretch
            elif spread < 0:
                glue = natural.shrink
                ratio = -ratio
            if glue is not None and (glue.order != 0 or glue.factor != 0):
                suffix = "" if glue.order == 0 else f"fi{'l' * glue.order}"
                sign_str = "- " if signed_ratio < 0 else ""
                line += f", glue set {sign_str}{ratio}{suffix}"
        shifted = getattr(self, "shifted", 0)
        if shifted != 0:
            line += f", shifted {shifted}"
        if getattr(self, "display", False):
            line += ", display"
        return line


class CharNode(Box):
    """
    A character node.
    @param char_info: the character information
    @param font: the font of the character
    """
    def __init__(self, char, font):
        at = font.at
        char_info = font.tfm.char_info[ord(char)-font.bc]
        super().__init__(char_info.width * at, char_info.height * at, char_info.depth * at)
        self.char = char_info.char
        self.italic = char_info.italic * at
        self.char_info = char_info
        self.font = font

    def saveInfo(self):
        return {"init": {"char": self.char, "font": self.font}}

    node_type = NODE_TYPE.CHAR

    def __repr__(self):
        return f"{self.char}"

    def meaning(self, parser):
        return f"{self.font.meaning(parser)} {self.char}"


class Rule(Box):
    """
    A rule node.
    """
    node_type = NODE_TYPE.RULE
    
    def __repr__(self):
        return f"Rule({self.width}, {self.height}, {self.depth})"

    def meaning(self, parser):
        return f"\\rule({self.height}+{self.depth})x{self.width}"
    

class Glue(Node):
    """
    A glue node.
    @param glue: the glue
    """
    def __init__(self, glue, name):
        self.glue = glue
        self.name = name
        self.kern = None

    def saveInfo(self):
        return {"init": {"glue": self.glue, "name": self.name}}

    @classmethod
    def new(cls, parser, glue, name=None):
        return cls(glue, name)

    def __repr__(self):
        set = self.glue if self.kern is None else f"{self.kern}pt"
        return f"Glue({set})"

    def meaning(self, parser):
        if self.kern is not None:
            if self.name is not None:
                return f"\\glue({self.name}) set {self.kern}"
            return f"\\glue set {self.kern}"
        spec = repr(self.glue)
        if self.name is not None:
            return f"\\glue({self.name}) {spec}"
        return f"\\glue {spec}"
    
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

    def saveInfo(self):
        return {"init": {"kern": self.kern, "automatic": self.automatic}}

    node_type = NODE_TYPE.KERN

    def __repr__(self):
        return f"Kern({self.kern}pt)"

    def meaning(self, parser):
        return f"\\kern{self.kern}"


class Penalty(Node):
    """
    A penalty node.
    @param penalty: the penalty
    """
    def __init__(self, penalty):
        self.penalty = penalty

    def saveInfo(self):
        return {"init": {"penalty": self.penalty}}

    node_type = NODE_TYPE.PENALTY

    def __repr__(self):
        return f"Penalty(self.penalty)"

    def meaning(self, parser):
        return f"\\penalty {self.penalty}"


class Disc(Node):
    """
    A discretionary node.
    """
    @staticmethod
    def _fixedWidth(nodes, name):
        """
        Compute fixed width of a discretionary pre/post/replace list.

        TeX restricts these lists to fixed-width material (no glue/disc).
        """
        width = Dimen()
        for node in nodes:
            if node.node_type == NODE_TYPE.KERN:
                width += node.kern
                continue
            w = getattr(node, "width", None)
            if w is None:
                raise ValueError(f"discretionary nodes in {name} must have a fixed width")
            width += w
        return width

    def __init__(self, pre, post, replace):
        self.pre = pre
        self.post = post
        self.replace = replace
        self.list = self.replace
        self.pre_width = self._fixedWidth(pre, "pre")
        self.post_width = self._fixedWidth(post, "post")
        self.replace_width = self._fixedWidth(replace, "replace")

    def saveInfo(self):
        return {"init": {"pre": self.pre, "post": self.post, "replace": self.replace}}
    
    def __repr__(self):
        return f"Disc({self.pre}, {self.post}, {self.replace})"

    def meaning(self, parser):
        return "\\discretionary"

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

    def saveInfo(self):
        return {"init": {"text": self.text}}

    def __repr__(self):
        return f"Special({self.text})"

    def output(self, parser, device):
        text = self.text
        if isinstance(text, list):
            def token_text(token):
                s = parser.tokenToString(token)
                return s + " " if token.catcode is None else s
            text = "".join(token_text(token) for token in text)
        device.special(text)


class VAdjust(Node):
    """
    A vadjust node.
    """
    def __init__(self, vlist):
        self.list = vlist

    @property
    def vlist(self):
        return self.list

    @vlist.setter
    def vlist(self, value):
        self.list = value

    def saveInfo(self):
        return {"init": {"vlist": self.vlist}}

    node_type = NODE_TYPE.ADJUST


class Mark(Node):
    """
    A \\mark node.
    """
    def __init__(self, tokens):
        self.tokens = tokens

    def saveInfo(self):
        return {"init": {"tokens": self.tokens}}

    node_type = NODE_TYPE.MARK


class Insert(Node):
    """
    An insert node.
    """
    def __init__(self, index, vlist):
        self.index = index
        self.list = vlist

    @property
    def vlist(self):
        return self.list

    @vlist.setter
    def vlist(self, value):
        self.list = value

    def saveInfo(self):
        return {"init": {"index": self.index, "vlist": self.vlist}}
    
    node_type = NODE_TYPE.INS
