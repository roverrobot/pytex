"""Backend-neutral logical text and fixed-layout glyph data."""


import builtins
from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple, Union

from pytex import node as nd
from pytex.dimen import Dimen
from pytex.serialization import Serializable


def _character(value, name="char"):
    if not isinstance(value, str) or len(value) != 1:
        raise ValueError(f"{name} must be exactly one Unicode character")
    codepoint = ord(value)
    if 0xD800 <= codepoint <= 0xDFFF:
        raise ValueError(f"{name} must be a Unicode scalar value")
    return value


def _wordClassifier(word_char):
    if callable(word_char):
        return word_char
    value = bool(word_char)
    return lambda char: value


def _legacyTextChars(source_nodes, classify):
    source = []
    for node in source_nodes:
        if getattr(node, "node_type", None) != nd.NODE_TYPE.CHAR:
            raise TypeError("legacy text source must contain only CharNode values")
        source.append(TextChar.fromCharNode(node, classify(node.char)))
    return source


@dataclass(frozen=True)
class TextChar(Serializable):
    """One logical Unicode character presented to horizontal shaping."""

    char: str
    font: object
    word_char: bool = False
    interword_glue: object = None

    def __post_init__(self):
        object.__setattr__(self, "char", _character(self.char))
        object.__setattr__(self, "word_char", bool(self.word_char))
        glue = self.interword_glue
        if glue is not None:
            copy = getattr(glue, "copy", None)
            if copy is None:
                raise TypeError("interword_glue must provide copy()")
            object.__setattr__(self, "interword_glue", copy())

    @classmethod
    def fromCharNode(cls, node, word_char=False, interword_glue=None):
        if getattr(node, "node_type", None) != nd.NODE_TYPE.CHAR:
            raise TypeError("TextChar.fromCharNode requires a CharNode")
        return cls(node.char, node.font, word_char, interword_glue)

    def saveInfo(self):
        return {
            "char": self.char,
            "font": self.font,
            "word_char": self.word_char,
            "interword_glue": self.interword_glue,
        }, None


@dataclass(frozen=True)
class ShapedGlyph:
    """Transient position and metrics for one output glyph."""

    x_advance: Dimen
    width: Dimen
    height: Dimen
    depth: Dimen
    char: Optional[str] = None
    glyph_id: Optional[int] = None
    glyph_name: Optional[str] = None
    italic: Dimen = field(default_factory=Dimen)
    x_offset: Dimen = field(default_factory=Dimen)
    y_offset: Dimen = field(default_factory=Dimen)

    def __post_init__(self):
        if self.char is not None:
            object.__setattr__(self, "char", _character(self.char))
        if self.char is None and self.glyph_id is None and self.glyph_name is None:
            raise ValueError("a shaped glyph requires a character, glyph ID, or glyph name")
        for name in (
            "x_advance",
            "width",
            "height",
            "depth",
            "italic",
            "x_offset",
            "y_offset",
        ):
            object.__setattr__(self, name, Dimen(getattr(self, name)))


@dataclass(frozen=True)
class ShapedCluster:
    """Transient glyph output for one half-open logical source range."""

    source_start: int
    source_end: int
    glyphs: Tuple[ShapedGlyph, ...]

    def __post_init__(self):
        if self.source_start < 0 or self.source_end <= self.source_start:
            raise ValueError("a shaped cluster requires a non-empty source range")
        glyphs = tuple(self.glyphs)
        if not glyphs or not all(isinstance(glyph, ShapedGlyph) for glyph in glyphs):
            raise ValueError("a shaped cluster requires one or more ShapedGlyph values")
        object.__setattr__(self, "glyphs", glyphs)


@dataclass(frozen=True)
class ShapedKern:
    """Transient automatic adjustment associated with a logical source range."""

    amount: Dimen
    source_start: Optional[int] = None
    source_end: Optional[int] = None

    def __post_init__(self):
        object.__setattr__(self, "amount", Dimen(self.amount))
        if (self.source_start is None) != (self.source_end is None):
            raise ValueError("a shaped kern source range must be complete or omitted")
        if self.source_start is not None:
            if self.source_start < 0 or self.source_end <= self.source_start:
                raise ValueError("a shaped kern source range must be non-empty")


ShapeItem = Union[ShapedCluster, ShapedKern]


class Glyph(nd.Box):
    """A fixed-layout primitive representing exactly one font glyph."""

    node_type = nd.NODE_TYPE.GLYPH

    def __init__(
        self,
        font,
        width,
        height,
        depth,
        char=None,
        glyph_id=None,
        glyph_name=None,
        italic=0,
    ):
        if char is not None:
            char = _character(char)
        if char is None and glyph_id is None and glyph_name is None:
            raise ValueError("a glyph requires a character, glyph ID, or glyph name")
        super().__init__(width, height, depth)
        self.font = font
        self.char = char
        self.glyph_id = glyph_id
        self.glyph_name = glyph_name
        self.italic = Dimen(italic)

    @classmethod
    def fromCharNode(cls, node):
        if getattr(node, "node_type", None) not in (
            nd.NODE_TYPE.CHAR,
            nd.NODE_TYPE.LIGATURE,
        ):
            raise TypeError("Glyph.fromCharNode requires a character or ligature node")
        info = node.char_info
        return cls(
            node.font,
            node.width,
            node.height,
            node.depth,
            char=node.char,
            glyph_id=getattr(info, "glyph_id", None),
            glyph_name=getattr(info, "glyph_name", None),
            italic=node.italic,
        )

    @classmethod
    def fromShaped(cls, font, shaped):
        if not isinstance(shaped, ShapedGlyph):
            raise TypeError("Glyph.fromShaped requires a ShapedGlyph")
        return cls(
            font,
            shaped.width,
            shaped.height,
            shaped.depth,
            char=shaped.char,
            glyph_id=shaped.glyph_id,
            glyph_name=shaped.glyph_name,
            italic=shaped.italic,
        )

    def saveInfo(self):
        return {
            "font": self.font,
            "width": self.width,
            "height": self.height,
            "depth": self.depth,
            "char": self.char,
            "glyph_id": self.glyph_id,
            "glyph_name": self.glyph_name,
            "italic": self.italic,
        }, None

    def __repr__(self):
        identity = self.char
        if identity is None:
            identity = self.glyph_name
        if identity is None:
            identity = self.glyph_id
        return f"Glyph({identity!r})"

    def meaning(self, parser):
        return f"{self.font} glyph {self!r}"


class GlyphCluster(nd.Box):
    """An indivisible text unit with one measured fixed-layout payload."""

    node_type = nd.NODE_TYPE.GLYPH_CLUSTER

    def __init__(
        self,
        source: Sequence[TextChar],
        layout,
        owner=None,
    ):
        source = builtins.list(source)
        if not source or not all(isinstance(item, TextChar) for item in source):
            raise ValueError("a glyph cluster requires one or more TextChar sources")
        if not isinstance(layout, (Glyph, nd.CharNode)) and not (
            isinstance(layout, nd.Box)
            and layout.node_type == nd.NODE_TYPE.HLIST
            and hasattr(layout, "list")
        ):
            raise TypeError(
                "a glyph cluster layout must be one character/glyph node or one packed HBox"
            )
        if layout.width is None or layout.height is None or layout.depth is None:
            raise ValueError("a glyph cluster layout must already be packed")
        super().__init__(layout.width, layout.height, layout.depth)
        self.source = source
        self.layout = layout
        self.owner = owner

    @classmethod
    def fromLegacy(cls, node, word_char=False):
        node_type = getattr(node, "node_type", None)
        if node_type == nd.NODE_TYPE.CHAR:
            source_nodes = [node]
        elif node_type == nd.NODE_TYPE.LIGATURE:
            source_nodes = builtins.list(getattr(node, "source", ()))
        else:
            raise TypeError("GlyphCluster.fromLegacy requires a character or ligature node")
        classify = _wordClassifier(word_char)
        source = _legacyTextChars(source_nodes, classify)
        return cls(
            source,
            Glyph.fromCharNode(node),
        )

    @property
    def text(self):
        return "".join(item.char for item in self.source)

    @property
    def font(self):
        return self.source[0].font

    def saveInfo(self):
        return {
            "source": self.source,
            "layout": self.layout,
            "owner": self.owner,
        }, None

    def __repr__(self):
        return f"GlyphCluster({self.text!r}, {self.layout!r})"

    def meaning(self, parser):
        return f"glyph cluster {self.text!r}"


def textSource(node, word_char=False):
    """Return logical text for new clusters and legacy text nodes."""
    if isinstance(node, GlyphCluster):
        return list(node.source)
    node_type = getattr(node, "node_type", None)
    if node_type == nd.NODE_TYPE.CHAR:
        source_nodes = [node]
    elif node_type == nd.NODE_TYPE.LIGATURE:
        source_nodes = list(getattr(node, "source", ()))
    else:
        return None
    classify = _wordClassifier(word_char)
    return _legacyTextChars(source_nodes, classify)


def isTextNode(node):
    """Whether a parent horizontal list should treat a node as text."""
    return isinstance(node, GlyphCluster) or getattr(node, "node_type", None) in (
        nd.NODE_TYPE.CHAR,
        nd.NODE_TYPE.LIGATURE,
    )
