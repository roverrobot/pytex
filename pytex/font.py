"""
The module implements font handling
"""


import os
from fractions import Fraction
from pytex.token import Command
from pytex.module import Module
from pytex.font_backend import FontBackend
from pytex.tfm import nullfont_backend
from pytex.accessor import Accessor, VALUE_TYPE, AttrTarget, KeyTarget, ReadOnlyTarget, canReadAs
from pytex.integer import IntegerArrayItemAccessor
from pytex.dimen import Dimen
from pytex.glue import Glue, Stretchness
from pytex.node import CharNode
from pytex.define import EquitableAccessor
from pytex.state import Array
from pytex.expandable import toToks
from pytex.serialization import Builtin, Serializable


def _fontSizeForOutput(parser, at):
    at = at if isinstance(at, Dimen) else Dimen(at)
    if parser.font_size_in_bp:
        # Reflow backends express font sizes in PostScript points.  Increase
        # the internal TeX-point size so its physical size is unchanged when
        # DOCX/CSS writes the same numeric value in bp.
        return at / 72 * 72.27
    return at


class Font(Command):
    """
    A font. Using it as a command set the current font.

    @param backend: the backend that provides the font data
    @param at: the size of the font
    """
    def __init__(self, backend: FontBackend, at, font_name=None, requested_at=None):
        self.backend = backend
        # Preserve the font request, not the backend selected for it.  A
        # deserializing parser must repeat font search under its output
        # backend's supported font classes.
        self.font_name = backend.name if font_name is None else font_name
        self.at = at if isinstance(at, Dimen) else Dimen(at)
        self.requested_at = (
            self.at
            if requested_at is None
            else requested_at if isinstance(requested_at, Dimen) else Dimen(requested_at)
        )
        self.param = self._backendParams(backend, self.at)
        self.charnode = {}
        self._rebuildSpaceGlue()
        # special characters
        self.fontchar = {"skewchar": 0, "hyphenchar": 0}

    @staticmethod
    def _backendParams(backend, at):
        raw_param = list(backend.fontdimen)
        params = [Dimen()] * len(raw_param)
        if params:
            # param[0] is the only parameter that does not scale with the design size
            params[0] = Dimen(raw_param[0])
            for index in range(1, len(raw_param)):
                params[index] = raw_param[index] * at
        return params

    def _rebuildSpaceGlue(self):
        zero = Dimen()
        space = self.param[1] if len(self.param) > 1 else zero
        stretch = self.param[2] if len(self.param) > 2 else zero
        shrink = self.param[3] if len(self.param) > 3 else zero
        self.spaceglue = Glue(space, Stretchness(stretch, 0), Stretchness(shrink, 0))

    def _paramOverrides(self):
        defaults = self._backendParams(self.backend, self.at)
        return [
            None if index < len(defaults) and value == defaults[index] else value
            for index, value in enumerate(self.param)
        ]

    def _saveExtras(self):
        return {
            "fontchar": self.fontchar,
            "name": getattr(self, "name", None),
            "param_overrides": self._paramOverrides(),
        }
    
    def className(self):
        return Serializable.className(self)
    
    def saveInfo(self):
        return {
            "font_name": self.font_name,
            # Store TeX's requested size, not the output-specific size used by
            # the backend that happened to serialize this font.
            "at": self.requested_at,
        }, self._saveExtras()

    @classmethod
    def new(cls, parser, at, font_name=None, name=None, kind=None):
        # ``name`` and ``kind`` are accepted for old format files.  Backend
        # kind is intentionally ignored so even those formats repeat generic
        # font search and can select or create an output-compatible backend.
        font_name = name if font_name is None else font_name
        backend = parser.loadFontBackend(font_name)
        return cls(
            backend,
            _fontSizeForOutput(parser, at),
            font_name=font_name,
            requested_at=at,
        )

    def afterDeserialize(self, parser):
        """Merge serialized fontdimen overrides into the selected backend."""
        overrides = getattr(self, "param_overrides", None)
        if overrides is None:
            # Legacy formats restored full param and spaceglue snapshots.
            return
        for index, value in enumerate(overrides):
            if index >= len(self.param):
                self.param.extend(Dimen() for _ in range(index - len(self.param) + 1))
            if value is not None:
                self.param[index] = value
        del self.param_overrides
        self._rebuildSpaceGlue()

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

    def shape(
        self,
        source,
        *,
        parser=None,
        left_boundary=False,
        right_boundary=False,
    ):
        return self.backend.shape(
            self,
            source,
            parser=parser,
            left_boundary=left_boundary,
            right_boundary=right_boundary,
        )

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

    def fetchValue(self, parser, requested_type):
        if not canReadAs(VALUE_TYPE.FONT, requested_type):
            return None, None
        return self, VALUE_TYPE.FONT
    
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
    def _serializeAsBuiltin(self):
        return (
            all(value is None for value in self._paramOverrides())
            and self.fontchar == {"skewchar": 0, "hyphenchar": 0}
        )

    def className(self):
        if self._serializeAsBuiltin():
            return Builtin.className(self)
        return Serializable.className(self)

    def saveInfo(self):
        if self._serializeAsBuiltin():
            return Builtin.saveInfo(self)
        return {}, self._saveExtras()

    @classmethod
    def new(cls, parser):
        return parser.builtin["\\nullfont"]


def readFont(parser):
    """
    read a font from the input stack
    @param parser: the parser
    """
    value = parser.readInternalValue(VALUE_TYPE.FONT)
    if value is None:
        raise ValueError("expecting a font")
    return value


FontArrayItemAccessor = lambda domain=None, key=None, builtin=True: Accessor(
    domain,
    key,
    builtin=builtin,
    value_type=VALUE_TYPE.FONT,
    read_key=lambda parser: parser.readInteger(),
)

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
    value_type = VALUE_TYPE.INT

    def __init__(self, field, key=None, builtin=True):
        super().__init__(None, key, builtin=builtin)
        self.field = field

    def readKey(self, parser):
        return readFont(parser)

    def readValue(self, parser):
        return parser.readInteger()

    def getTarget(self, parser):
        font = self.currentKey(parser)
        return KeyTarget(font.fontchar, self.field, self.value_type, supports_global=False)

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
        name = parser.parseFontName(name)
        try:
            backend = parser.loadFontBackend(name)
        except FileNotFoundError:
            suppress = dict.get(
                parser.parameters,
                "suppressfontnotfounderror",
            )
            if suppress is None or suppress.value == 0:
                raise
            keyword = parser.readKeyword({"at", "scaled"})
            if keyword == "at":
                parser.readDimen()
            elif keyword == "scaled":
                parser.readInteger()
            return nullfont
        keyword = parser.readKeyword({"at", "scaled"})
        design = Dimen(backend.design_size)
        mag = Fraction(parser.mag.value, 1000)
        if keyword == "at":
            at = parser.readDimen()
        elif keyword == "scaled":
            at = design * Fraction(parser.readInteger(), 1000) * mag
        else:
            at = design * mag
        requested_at = at
        at = _fontSizeForOutput(parser, requested_at)
        f = Font(backend, at, font_name=name, requested_at=requested_at)
        f.name = self.key
        f.fontchar["hyphenchar"] = parser.parameters["defaulthyphenchar"]
        f.fontchar["skewchar"] = parser.parameters["defaultskewchar"]
        return f


class FontAccessor(Accessor):
    """
    An accessor for the current font
    """
    value_type = VALUE_TYPE.FONT
        

class FontCommand(FontDefineAccessor):
    """
    The \\font command
    """
    value_type = VALUE_TYPE.FONT

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
    value_type = VALUE_TYPE.DIMEN

    def readKey(self, parser):
        index = parser.readInteger() - 1
        return readFont(parser), index

    def readValue(self, parser):
        return parser.readDimen()

    def getTarget(self, parser):
        font, index = self.currentKey(parser)
        pos = parser.input.position()
        return AttrTarget(FontDimenSlot(font, font.param, index, pos), "value", self.value_type)


class FontDimenSlot:
    def __init__(self, font, params, index, pos):
        self.font = font
        self.params = params
        self.index = index
        self.pos = pos

    @property
    def value(self):
        if self.index < 0:
            raise ValueError(f"fontdimen index {self.index} out of range {len(self.params)} for font {self.font.backend.name}  @{int(self.font.at)}", self.pos)
        if self.index >= len(self.params):
            return Dimen()
        return self.params[self.index]

    @value.setter
    def value(self, new_value):
        if self.index >= len(self.params):
            self.params.extend([Dimen() for _ in range(self.index - len(self.params) + 1)])
        self.params[self.index] = new_value
        if self.index in (1, 2, 3):
            self.font._rebuildSpaceGlue()


class FontName(Command):
    """
    the \\fontname command
    """
    def expand(self, parser):
        f = readFont(parser)
        parser.input.pushTokenList(toToks(f.backend.name))

        
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
    attributes= {
        "font_size_in_bp": False,
    }
)
