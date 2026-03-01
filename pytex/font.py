"""
The module implements font handling
"""


from pytex.token import Command
from pytex.module import Module
from pytex.tfm import TFM, nullfont as nullfont_tfm
from pytex.accessor import ArrayAccessor, ArrayItemAccessor, ParameterAccessor
from pytex.integer import IntegerArrayAccessor, IntegerArrayItemAccessor
from pytex.dimen import Dimen, DimenArrayAccessor, DimenArrayItemAccessor
from pytex.glue import Glue, Stretchness
from pytex.node import CharNode
from pytex.define import Define
from pytex.state import Array
from pytex.expandable import toToks
from pytex.lexer import TokenListScanner


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
        parser.currentfont.set(self)

    def meaning(self, parser):
        at = f"at {self.at}pt" if self.at != self.tfm.header.size else ""
        return f"select font {self.tfm.name} {at}"
        
    def fontValue(self, parser):
        """
        get the font value
        @param parser: the parser
        """
        return self
    
    def hyphenChar(self):
        """
        get the hyphenchar of the font as a CharNode 
        """
        h = self.fontchar["hyphenchar"]
        return self.charnode[h-self.bc] if self.bc <= h <= self.ec else None


def readFont(parser):
    """
    read a font from the input stack
    @param parser: the parser
    """
    t = parser.token_expand()
    if t is None or t.definition is None:
        raise ValueError("expecting a font")
    # is the font specified by a command seqeunce?
    try:
        return t.definition.fontValue(parser)
    except AttributeError:
        raise ValueError("expecting a font")


class FontArrayItemAccessor(ArrayItemAccessor):
    """
    A font accessor
    """
    def readValue(self, parser):
        return readFont(parser)
    
    def fontValue(self, parser):
        """
        get the font value
        @param parser: the parser
        """
        return self.entry.value


class FontArrayAccessor(ArrayAccessor):
    """
    A font array accessor
    """
    def getItemAccessor(self, parser):
        return FontArrayItemAccessor(self.domain, parser.readInteger())
    
    def fontValue(self, parser):
        """
        get the font value
        @param parser: the parser
        """
        i = parser.readInteger()
        return self.domain[i]


nullfont = Font(tfm=nullfont_tfm, at=0)
nullfont.name = "\\nullfont"


def fontarray(name): 
    return lambda state: Array(name, state, default=nullfont, size=256)


class FontCharAccessor(IntegerArrayItemAccessor):
    def setGlobal(self, parser, value):
        """
        set the value of the font character globally
        @param parser: the parser
        @param value: the value to set
        """
        self.set(parser, value)


class FontChar(IntegerArrayAccessor):
    """
    A font character
    """
    def __init__(self, field):
        super().__init__(None)
        self.field = field

    def getItemAccessor(self, parser):
        font = readFont(parser)
        return FontCharAccessor(font.fontchar, self.field)
    
    def intValue(self, parser):
        font = readFont(parser)
        return font.fontchar[self.field]


class FontDefineAccessor(ParameterAccessor):
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
            at = parser.readInteger() / 1000 * tfm.header.size * parser.mag.value / 1000
        else:
            at = tfm.header.size * parser.mag.value / 1000
        f = Font(tfm, at)
        f.name = self.entry.name
        f.fontchar["hyphenchar"] = parser.state.parameters["defaulthyphenchar"]
        f.fontchar["skewchar"] = parser.state.parameters["defaultskewchar"]
        return f


class FontAccessor(ParameterAccessor):
    """
    An accessor for the current font
    """
    def fontValue(self, parser):
        """
        get the current font value
        @param parser: the parser
        """
        return self.entry.value
        

class FontCommand(Define):
    """
    The \\font command
    """
    def __init__(self):
        super().__init__(FontDefineAccessor, default=nullfont)
        
    def fontValue(self, parser):
        return parser.currentfont.value


class FontDimenAccessor(DimenArrayItemAccessor):
    """
    An accessor for the \\fontdimen command
    """
    def __init__(self, font, index):
        super().__init__(font.param, index)
        self.font = font

    def dimenValue(self, parser):
        if self.index < 0 or self.index >= len(self.domain):
            raise ValueError(f"fontdimen index {self.index} out of range {len(self.domain)} for font {self.font.tfm.name}  @{int(self.font.at)}", parser.input.position())
        return self.domain[self.index]
    
    def set(self, parser, value):
        """
        set the value of the fontdimen
        @param parser: the parser
        @param value: the value to set
        """
        if self.index >= len(self.domain): 
            # append 0 values until the index is valid
            self.domain.extend([Dimen() for i in range(self.index - len(self.domain) + 1)])
        super().set(parser, value)

    def setGlobal(self, parser, value):
        self.set(parser, value)

    
class FontDimen(DimenArrayAccessor):
    """
    the \\fontdimen command
    """
    def __init__(self):
        super().__init__(None)
   
    def getItemAccessor(self, parser):
        i = parser.readInteger() - 1
        return FontDimenAccessor(readFont(parser), i)
    
    def dimenValue(self, parser):
        i = parser.readInteger() - 1
        f = readFont(parser)
        if i < 0 or i >= len(f.param):
            raise ValueError(f"fontdimen index {i+1} of out of range of {len(f.param)} for font {f.tfm.name}  @{int(f.at)}", parser.input.position())
        return f.param[i]


class FontName(Command):
    """
    the \\fontname command
    """
    def expand(self, parser):
        f = readFont(parser)
        parser.input.push(TokenListScanner(toToks(f.tfm.name)))

        
mod = Module("font",
    parameters = {
        "currentfont": {"value": nullfont, "accessor": FontAccessor,  "domain": "parameters"},
    },
    domains = {
        "textfont": {"generator": fontarray("textfont"), "accessor": FontArrayAccessor},
        "scriptfont": {"generator": fontarray("scriptfont"), "accessor": FontArrayAccessor},
        "scriptscriptfont": {"generator": fontarray("scriptscriptfont"), "accessor": FontArrayAccessor},
    },
    commands = {
        "fontdimen": FontDimen(),
        "hyphenchar": FontChar("hyphenchar"),
        "skewchar": FontChar("skewchar"),
        "font": FontCommand(),
        "fontname": FontName(),
        "nullfont": nullfont,
    },
)
