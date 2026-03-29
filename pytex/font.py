"""
The module implements font handling
"""


from fractions import Fraction
from pytex.token import Command
from pytex.module import Module
from pytex.font_backend import FontBackend
from pytex.tfm import nullfont_backend
from pytex.accessor import Accessor, VALUE_TYPE, AttrTarget, KeyTarget, ReadOnlyTarget
from pytex.integer import IntegerArrayItemAccessor
from pytex.dimen import Dimen
from pytex.glue import Glue, Stretchness
from pytex.node import CharNode
from pytex.define import EquitableAccessor
from pytex.state import Array
from pytex.expandable import toToks
from pytex.lexer import TokenListScanner
from pytex.serialization import Builtin, Serializable


class Font(Command):
    """
    A font. Using it as a command set the current font.

    @param backend: the backend that provides the font data
    @param at: the size of the font
    """
    def __init__(self, backend: FontBackend, at):
        self.backend = backend
        self.at = at if isinstance(at, Dimen) else Dimen(at)
        raw_param = list(backend.fontdimen)
        self.param = [0] * len(raw_param)
        if self.param:
            # param[0] is the only parameter that does not scale with the design size
            self.param[0] = Dimen(raw_param[0])
            for i in range(1, len(raw_param)):
                self.param[i] = raw_param[i] * self.at
        self.charnode = {}
        zero = Dimen()
        space = self.param[1] if len(self.param) > 1 else zero
        stretch = self.param[2] if len(self.param) > 2 else zero
        shrink = self.param[3] if len(self.param) > 3 else zero
        self.spaceglue = Glue(space, Stretchness(stretch, 0), Stretchness(shrink, 0))
        # special characters
        self.fontchar = {"skewchar": 0, "hyphenchar": 0}
    
    def className(self):
        return Serializable.className(self)
    
    def saveInfo(self):
        return {
            "name": self.backend.name,
            "kind": self.backend.kind,
            "at": self.at,
        }, {"fontchar": self.fontchar, "name": getattr(self, "name", None)}

    @classmethod
    def new(cls, parser, at, name, kind=None):
        backend = parser.loadFontBackend(name, kind=kind)
        return cls(backend, at)

    def glyphInfo(self, char):
        return self.backend.glyphInfo(char)

    def glyphInfos(self):
        return self.backend.glyphInfos()

    def hasCharCode(self, code: int):
        try:
            return self.backend.hasChar(chr(code))
        except ValueError:
            return False

    def leftBoundaryProgram(self):
        return self.backend.leftBoundaryProgram()

    def rightBoundaryChar(self):
        return self.backend.rightBoundaryChar()

    def _charNode(self, char):
        node = self.charnode.get(char)
        if node is not None:
            return node
        char_info = self.glyphInfo(char)
        if char_info is None:
            char_info = self.backend.fallbackGlyphInfo(char)
        if char_info is None:
            return None
        node = CharNode(char, self, char_info=char_info)
        self.charnode[char] = node
        return node

    def __getitem__(self, char):
        """
        get the character node
        @param char: the character code
        """
        node = self._charNode(char)
        if node is not None:
            return node
        raise KeyError(f"character {ord(char)} not found in font {self.backend.name}")

    def execute(self, parser):
        parser.currentfont.set(self)

    def __repr__(self):
        name = getattr(self, "name", None)
        return name if name is not None else f"\\{self.backend.name}"

    def meaning(self, parser):
        return f"select font {self.backend.name} at {self.at}pt"

    def getTarget(self, parser):
        return ReadOnlyTarget(self, VALUE_TYPE.FONT)
    
    def hyphenChar(self):
        """
        get the hyphenchar of the font as a CharNode 
        """
        h = self.fontchar["hyphenchar"]
        if not self.hasCharCode(h):
            return None
        return self[chr(h)]


class NullFont(Font):
    """
    Builtin wrapper for \\nullfont.

    Regular font values should keep concrete serialization, but the parser's
    builtin \\nullfont should round-trip by builtin name.
    """
    def className(self):
        return Builtin.className(self)

    def saveInfo(self):
        return Builtin.saveInfo(self)


def readFont(parser):
    """
    read a font from the input stack
    @param parser: the parser
    """
    value = parser.readInternalValue(VALUE_TYPE.FONT)
    if value is None:
        raise ValueError("expecting a font")
    return value


class FontArrayItemAccessor(Accessor):
    """
    A font accessor
    """
    target_type = VALUE_TYPE.FONT

    def readKey(self, parser):
        return parser.readInteger()

    def readValue(self, parser):
        return readFont(parser)

nullfont = NullFont(backend=nullfont_backend, at=0)
nullfont.name = "\\nullfont"


class MathFontArray(Array):
    def _validateMathFamily(self, index, font):
        if index == 2:
            params = getattr(font, "param", ())
            if len(params) < 22:
                raise ValueError(f"{self.name}[2] has {len(params)} fontdimen params; need at least 22 for math typesetting")
        elif index == 3:
            params = getattr(font, "param", ())
            if len(params) < 13:
                raise ValueError(f"{self.name}[3] has {len(params)} fontdimen params; need at least 13 for math typesetting")

    def __setitem__(self, index, value):
        self._validateMathFamily(index, value)
        super().__setitem__(index, value)

    def setGlobal(self, index, value):
        self._validateMathFamily(index, value)
        super().setGlobal(index, value)


def fontarray(name): 
    return lambda state: MathFontArray(name, state, default=nullfont)


class FontCharAccessor(Accessor):
    target_type = VALUE_TYPE.INT

    def __init__(self, field, key=None, builtin=True):
        super().__init__(None, key, builtin=builtin)
        self.field = field

    def readKey(self, parser):
        return readFont(parser)

    def readValue(self, parser):
        return parser.readInteger()

    def getTarget(self, parser):
        font = self.currentKey(parser)
        return KeyTarget(font.fontchar, self.field, self.target_type, supports_global=False)

    def setGlobal(self, parser, value):
        """
        set the value of the font character globally
        @param parser: the parser
        @param value: the value to set
        """
        self.set(parser, value)


class FontDefineAccessor(EquitableAccessor):
    def setDefault(self, t):
        t.entry.value = t.definition = nullfont

    def readValue(self, parser):
        """
        read a font specification from the input stack
        @param parser: the parser
        """
        # While a font assignment is being scanned, TeX treats the target
        # control sequence as \nullfont, even if it already had a meaning.
        name = parser.readFileName()
        if name is None:
            raise ValueError("expecting a font name")
        backend = parser.loadFontBackend(name)
        keyword = parser.readKeyword({"at", "scaled"})
        design = Dimen(backend.design_size)
        mag = Fraction(parser.mag.value, 1000)
        if keyword == "at":
            at = parser.readDimen()
        elif keyword == "scaled":
            at = design * Fraction(parser.readInteger(), 1000) * mag
        else:
            at = design * mag
        f = Font(backend, at)
        f.name = self.key
        f.fontchar["hyphenchar"] = parser.parameters["defaulthyphenchar"]
        f.fontchar["skewchar"] = parser.parameters["defaultskewchar"]
        return f


class FontAccessor(Accessor):
    """
    An accessor for the current font
    """
    target_type = VALUE_TYPE.FONT
        

class FontCommand(FontDefineAccessor):
    """
    The \\font command
    """
    target_type = VALUE_TYPE.FONT

    def __init__(self):
        super().__init__(None)

    def getTarget(self, parser):
        if self.key is not None:
            return super().getTarget(parser)
        return ReadOnlyTarget(parser.parameters["currentfont"], VALUE_TYPE.FONT)


class FontDimenAccessor(Accessor):
    """
    An accessor for the \\fontdimen command
    """
    target_type = VALUE_TYPE.DIMEN

    def readKey(self, parser):
        index = parser.readInteger() - 1
        return readFont(parser), index

    def readValue(self, parser):
        return parser.readDimen()

    def getTarget(self, parser):
        font, index = self.currentKey(parser)
        pos = parser.input.position()
        return AttrTarget(FontDimenSlot(font, font.param, index, pos), "value", self.target_type)


class FontDimenSlot:
    def __init__(self, font, params, index, pos):
        self.font = font
        self.params = params
        self.index = index
        self.pos = pos

    @property
    def value(self):
        if self.index < 0 or self.index >= len(self.params):
            raise ValueError(f"fontdimen index {self.index} out of range {len(self.params)} for font {self.font.backend.name}  @{int(self.font.at)}", self.pos)
        return self.params[self.index]

    @value.setter
    def value(self, new_value):
        if self.index >= len(self.params):
            self.params.extend([Dimen() for _ in range(self.index - len(self.params) + 1)])
        self.params[self.index] = new_value


class FontName(Command):
    """
    the \\fontname command
    """
    def expand(self, parser):
        f = readFont(parser)
        parser.input.push(TokenListScanner(toToks(f.backend.name)))

        
mod = Module("font",
    parameters = {
        "currentfont": {"value": nullfont, "accessor": FontAccessor,  "domain": "parameters"},
    },
    domains = {
        "textfont": {"generator": fontarray("textfont"), "accessor": FontArrayItemAccessor},
        "scriptfont": {"generator": fontarray("scriptfont"), "accessor": FontArrayItemAccessor},
        "scriptscriptfont": {"generator": fontarray("scriptscriptfont"), "accessor": FontArrayItemAccessor},
    },
    commands = {
        "fontdimen": FontDimenAccessor(),
        "hyphenchar": FontCharAccessor("hyphenchar"),
        "skewchar": FontCharAccessor("skewchar"),
        "font": FontCommand(),
        "fontname": FontName(),
        "nullfont": nullfont,
    },
)
