"""
The module implements font handling
"""


from pytex.token import Command
from pytex.module import Module
from pytex.tfm import TFM, nullfont as nullfont_tfm
from pytex.accessor import ArrayAccessor, Accessor
from pytex.integer import IntegerArrayAccessor, IntegerAccessor
from pytex.dimen import DimenAccessor, DimenArrayAccessor
from pytex.glue import Glue, Stretchness
from pytex.node import CharNode
from pytex.define import Define
from pytex.state import Array


class Font(Command):
    """
    A font. Using it as a command set the current font.

    @param tfm: the tfm data
    @param at: the size of the font
    """
    def __init__(self, tfm: TFM, at):
        self.tfm = tfm
        self.at = at
        # nullfont
        self.param = [0] * len(tfm.param)
        # param[0] is the only parameter that does not scale with the design size of the font
        self.param[0] = tfm.param[0]
        for i in range(1, len(tfm.param)):
            self.param[i] = tfm.param[i] * at
        self.bc = tfm.bc
        self.ec = tfm.ec
        self.charnode = [None] * (self.ec-self.bc+1)
        for i in range(self.bc, self.ec+1):
            self.charnode[i-self.bc] = CharNode(chr(i), self)
        self.spaceglue = Glue(self.param[1], Stretchness(self.param[2], 0), Stretchness(self.param[3], 0))
        # special characters
        self.fontchar = {"skewchar": 0, "hyphenchar": 0}
    
    def saveInfo(self):
        return {"init": {"tfm": self.tfm.name, "at": self.at}}

    @classmethod
    def new(cls, parser, tfm, at):
        tfm = parser.loadTFM(tfm)
        return cls(tfm, at)

    def __getitem__(self, char):
        """
        get the character node
        @param char: the character code
        """
        if self.bc <= ord(char) <= self.ec:
            return self.charnode[ord(char)-self.bc]
        return self.charnode[0]

    def execute(self, parser):
        parser.state.parameters["currentfont"] = self

    def __repr__(self):
        return f"Font({self.tfm.name}, {self.at})"
        
    def fontValue(self, parser):
        """
        get the font value
        @param parser: the parser
        """
        return self


def readFont(parser):
    """
    read a font from the input stack
    @param parser: the parser
    """
    t = parser.token_expand()
    if t is None or t.meaning is None:
        raise ValueError("expecting a font")
    # is the font specified by a command seqeunce?
    try:
        return t.meaning.fontValue(parser)
    except AttributeError:
        raise ValueError("expecting a font")


class FontValue:   
    """
    A font value accessor
    """
    def fontValue(self, parser):
        return self.getValue(parser)


class FontAccessor(FontValue, Accessor):
    """
    A font accessor
    """
    def readValue(self, parser):
        return readFont(parser)


class FontArrayAccessor(FontValue, ArrayAccessor):
    """
    A font array accessor
    """
    def newItemAccessor(self, index):
        return FontAccessor(self.domain, index)


nullfont = Font(tfm=nullfont_tfm, at=0)


class FontArray(Array):
    """
    A font array
    """
    def __init__(self):
        super().__init__(nullfont)


class FontCharAccessor(IntegerAccessor):
    def getValue(self, parser):
        return self.domain.fontchar[self.index]

    def setValue(self, parser, value, globally):
        self.domain.fontchar[self.index] = value


class FontChar(IntegerArrayAccessor):
    """
    A font character
    """
    def __init__(self, field):
        super().__init__(None)
        self.field = field

    def getIndex(self, parser):
        return readFont(parser)
    
    def getItemAccessor(self, parser, index):
        font = self.getIndex(parser)
        return FontCharAccessor(font, self.field)


class FontDefineAccessor(Accessor):
    def readValue(self, parser):
        """
        read a font specification from the input stack
        @param parser: the parser
        """
        # read the font specification
        name = parser.readFileName()
        if name is None:
            raise ValueError("expecting a font name")
        tfm = parser.loadTFM(name)
        keyword = parser.readKeyword({"at", "scaled"})
        if keyword == "at":
            at = parser.readDimen()
        elif keyword == "scaled":
            at = parser.readInteger() / 1000 * tfm.header.size * parser.state.layout["mag"] / 1000
        else:
            at = tfm.header.size * parser.state.layout["mag"] / 1000
        return Font(tfm, at)


class FontCommand(Define):
    """
    The \\font command
    """
    def newItemAccessor(self, index):
        return FontDefineAccessor(self.domain, index)


class FontDimenAccessor(DimenAccessor):
    def getIndex(self, parser):
        font = readFont(parser)
        return font
    
    def getValue(self, parser):
        font = self.getIndex(parser)
        return font.param[self.index]
    
    def setValue(self, parser, value, globally):
        font = self.getIndex(parser)
        font.param[self.index] = value


class FontDimen(DimenArrayAccessor):
    """
    the \\fontdimen command
    """
    def __init__(self):
        super().__init__(None)

    def saveInfo(self):
        return {}
    
    def newItemAccessor(self, index):
        return FontDimenAccessor(None, index-1)


mod = Module("font",
    parameters = {
        "currentfont": {"value": nullfont, "accessor": FontAccessor,  "domain": "parameters"},
    },
    domains = {
        "textfont": {"generator": FontArray, "accessor": FontArrayAccessor},
        "scriptfont": {"generator": FontArray, "accessor": FontArrayAccessor},
        "scriptscriptfont": {"generator": FontArray, "accessor": FontArrayAccessor},
    },
    commands = {
        "fontdimen": FontDimen(),
        "hyphenchar": FontChar("hyphenchar"),
        "skewchar": FontChar("skewchar"),
        "font": FontCommand(),
    },
)