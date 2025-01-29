"""
The module implements font handling
"""


from pytex.token import CATCODE, Command
from pytex.module import Module
from pytex.tfm import TFM, nullfont as nullfont_tfm
from pytex.accessor import ValuePointer, ParameterAccessor, ArrayAccessor, Accessor
from pytex.integer import IntegerValuePointer, IntegerCommand
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
    def __init__(self, name, tfm: TFM, at):
        self.name = name
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
        self.charnode = [CharNode(info, self) for info in tfm.char_info]
        self.spaceglue = Glue(self.param[1], Stretchness(self.param[2], 0), Stretchness(self.param[3], 0))
        # special characters
        self.fontchar = {"skewchar": 0, "hyphenchar": 0}
    
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
        return f"Font({self.name}, {self.at})"
        
    def fontValue(self, parser):
        """
        get the font value
        @param parser: the parser
        """
        return self


class FontValueAccessor:
    """
    A font value accessor
    """
    def fontValue(self, parser):
        return self.getValue(parser)


class FontValuePointer(ValuePointer, FontValueAccessor):
    """
    A font value pointer
    """
    def readValue(self, parser):
        """
        read a font specification from the input stack
        @param parser: the parser
        """
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting a font")
        # is the font specified by a command seqeunce?
        if t.is_command:
            try:
                return t.fontValue(parser)
            except AttributeError:
                pass
            # the font could be prefixed by a relax
            parser.input.unread(t)
            raise ValueError("expecting a font")
        parser.input.unread(t)
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
        return Font(name, tfm, at)
    

class FontValueCommand(FontValueAccessor):
    """
    access the font value of command
    """
    def getValue(self, parser):
        """
        get the value of the command
        @param parser: the parser
        """
        return self.pointer(parser).getValue(parser)


class FontArrayAccessor(ArrayAccessor, FontValueCommand):
    """
    A font array
    """
    def __init__(self, domain):
        super().__init__(domain, FontValuePointer)


class FontParameterAccessor(ParameterAccessor, FontValueCommand):
    """
    A font parameter accessor
    """
    def __init__(self, domain, name):
        super().__init__(domain, name, FontValuePointer)


nullfont = Font("nullfont", tfm=nullfont_tfm, at=0)


class FontArray(Array):
    """
    A font array
    """
    def __init__(self):
        super().__init__(nullfont)


class FontChar(Accessor, IntegerCommand):
    """
    A font character
    """
    def __init__(self, name):
        super().__init__(None, None, eq=True)
        self.name = name

    def getIndex(self, parser):
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting a font")
        if isinstance(t, Font):
            return t
        try:
            pointer = t.pointer(parser)
            return pointer.getValue(parser)
        except AttributeError:
            raise ValueError("expecting a font")

    def pointer(self, parser):
        """
        get the value pointer
        @param parser: the parser
        @return: the value pointer and possible prefixes
        """
        font = self.getIndex(parser)
        p = IntegerValuePointer(font.fontchar, self.name, eq=True)
        p.allow_global = False
        return p


class FontCommand(Define):
    """
    The \\font command
    """
    def __init__(self):
        super().__init__(FontValuePointer, eq=True)

    def pointer(self, parser):
        """
        get the value pointer
        @param parser: the parser
        @return: the value pointer and possible prefixes
        """
        return FontValuePointer(parser.state.parameter, "currentfont")
    
    def execute(self, parser):
        p = super().pointer(parser)
        p.execute(parser)


mod = Module("font",
    parameters = {
        "currentfont": {"value": nullfont, "accessor": FontParameterAccessor,  "domain": "parameters"},
    },
    domains = {
        "textfont": {"generator": FontArray, "accessor": FontArrayAccessor},
        "scriptfont": {"generator": FontArray, "accessor": FontArrayAccessor},
        "scriptscriptfont": {"generator": FontArray, "accessor": FontArrayAccessor},
    },
    commands = {
        "hyphenchar": FontChar("hyphenchar"),
        "skewchar": FontChar("skewchar"),
        "font": FontCommand(),
    },
)