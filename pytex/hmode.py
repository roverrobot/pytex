"""
Implementation of horizontal commands and hlist handling.
"""


from pytex import node as nd
from pytex import glyph as glyph_data
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.dimen import Dimen
from pytex.module import Module
from pytex.token import Command, Token, CATCODE, relax
from pytex.state import GROUP_TYPE
from pytex.accessor import Accessor, VALUE_TYPE, KeyTarget
from pytex.define import CharDefValue


INTERCHAR_CLASS_BOUNDARY = 4095
INTERCHAR_CLASS_IGNORED = 4096


class _IntercharAppendToken(Token):
    """Runtime continuation used while an interchar token list is executed."""

    __slots__ = ("hlist", "resume")

    def __init__(self, hlist, resume):
        super().__init__("<interchar append>", None)
        self.hlist = hlist
        self.resume = resume

    def execute(self, parser):
        if parser is not self.hlist.parser:
            raise RuntimeError("interchar append resumed in a different parser")
        self.resume()

    def meaning(self, parser):
        return "interchar append continuation"


from pytex.box import AccentNode, IndentBox


class HList(lists.List):
    """
    Horizontal list wrapper.

    This is what lives on parser.lists while horizontal material is scanned.
    It serves a concrete horizontal list node and updates \\spacefactor.
    """
    def __init__(self, parser, list, inner=True, raw=None, paragraph=None):
        super().__init__(parser, list, inner)
        self.raw = [] if raw is None else raw
        self.paragraph = paragraph
        self.sfcode = parser.sfcode
        self.type = lists.LISTTYPE.HORIZONTAL
        self._interchar_class = INTERCHAR_CLASS_BOUNDARY
        self._pending_text = []
        self._pending_space = None

    def open(self):
        super().open()
        self.saved_spacefactor = self.parser.globals["spacefactor"]
        self.parser.globals["spacefactor"] = 1000

    def finish(self):
        self._flushTextRun()
        self._interchar_class = INTERCHAR_CLASS_BOUNDARY

    def close(self):
        self.finish()
        self.parser.globals["spacefactor"] = self.saved_spacefactor
        super().close()

    @property
    def list_type_name(self):
        return "HList" if self.inner else "Paragraph"

    def concreteNodes(self):
        self._flushTextRun()
        return list(self.list)

    def rawNodes(self):
        self._flushTextRun()
        return list(self.raw)

    def __len__(self):
        self._flushTextRun()
        return super().__len__()

    def __iter__(self):
        self._flushTextRun()
        return super().__iter__()

    def __getitem__(self, index):
        self._flushTextRun()
        return super().__getitem__(index)

    def __setitem__(self, index, value):
        self._flushTextRun()
        self._pending_space = None
        return super().__setitem__(index, value)

    def __delitem__(self, key):
        self._flushTextRun()
        self._pending_space = None
        return super().__delitem__(key)

    def clear(self):
        self._flushTextRun()
        self._pending_space = None
        super().clear()

    def _interwordSpaceShaping(self):
        entry = dict.get(self.parser.parameters, "XeTeXinterwordspaceshaping")
        return 0 if entry is None else entry.value

    @staticmethod
    def _shapeWidth(nodes):
        width = Dimen()
        for node in nodes:
            width += node.width
        return width

    @staticmethod
    def _contextualSpaceBackend(font):
        return bool(
            getattr(font.backend, "supports_contextual_space_shaping", False)
        )

    def _applyContextualSpace(self, right_source, right_width):
        pending = self._pending_space
        self._pending_space = None
        if pending is None or not right_source:
            return
        font = pending["font"]
        if right_source[0].font is not font:
            return
        source = pending["left_source"] + [pending["space_source"]] + right_source
        shaped = font.shape(
            source,
            parser=self.parser,
            left_boundary=True,
            right_boundary=True,
        )
        contextual_space = (
            self._shapeWidth(shaped)
            - pending["left_width"]
            - right_width
        )
        adjustment = contextual_space - font.spaceglue.dimen
        glue_node = pending["glue"]
        for index, item in enumerate(self.list):
            if item is glue_node:
                self.list.insert(
                    index + 1,
                    nd.Kern(adjustment, space_adjustment=True),
                )
                return

    def _flushTextRun(self):
        if not self._pending_text:
            return None
        source = self._pending_text
        self._pending_text = []
        font = source[0].font
        shaped = font.shape(
            source,
            parser=self.parser,
            left_boundary=True,
            right_boundary=True,
        )
        width = self._shapeWidth(shaped)
        self._applyContextualSpace(source, width)
        self.list.extend(shaped)
        result = {
            "source": source,
            "font": font,
            "width": width,
        }
        return result

    @staticmethod
    def _invisibleToInterwordSpace(node):
        return node.node_type in (
            nd.NODE_TYPE.PENALTY,
            nd.NODE_TYPE.INS,
            nd.NODE_TYPE.MARK,
            nd.NODE_TYPE.ADJUST,
        )

    def _appendSpace(self):
        left = self._flushTextRun()
        font = self.parser.parameters["currentfont"]
        glue = self.parser.interwordGlue()
        source = glyph_data.TextChar(
            " ",
            font,
            False,
            interword_glue=glue,
        )
        glue_node = nd.Glue(glue, None, text_source=source)
        self.raw.append(glue_node)
        self.list.append(glue_node)
        mode = self._interwordSpaceShaping()
        if (
            mode > 0
            and left is not None
            and left["font"] is font
            and self._contextualSpaceBackend(font)
        ):
            self._pending_space = {
                "font": font,
                "left_source": left["source"],
                "left_width": left["width"],
                "space_source": source,
                "glue": glue_node,
            }
        else:
            self._pending_space = None
        self.parser.globals["spacefactor"] = 1000

    def _resetNonCharState(self):
        self._flushTextRun()
        self.parser.globals["spacefactor"] = 1000

    def _intercharClass(self, item):
        if not isinstance(item, str) and item.node_type == nd.NODE_TYPE.CHAR:
            return self.parser.xetexcharclass[ord(item.char)], True
        return INTERCHAR_CLASS_BOUNDARY, False

    def _deferIntercharAppend(self, toks, resume):
        self.parser.input.unread(_IntercharAppendToken(self, resume))
        self.parser.input.pushTokenList(toks)

    def _insertIntercharTokens(self, item, resume, backed_up=False):
        """
        Insert the class-pair token list before an hlist append when required.

        A deferred character is marked as backed up.  If the inserted token
        list leaves the previous class at the boundary, this suppresses the
        same boundary-to-character transition when the character resumes.
        Material appended by the token list still participates normally.
        """
        token_state_entry = dict.get(
            self.parser.parameters,
            "XeTeXinterchartokenstate",
        )
        token_state = 0 if token_state_entry is None else token_state_entry.value
        if token_state <= 0:
            self._interchar_class = INTERCHAR_CLASS_BOUNDARY
            return False

        current, is_character = self._intercharClass(item)
        if current == INTERCHAR_CLASS_IGNORED:
            return False

        previous = self._interchar_class
        if previous == INTERCHAR_CLASS_BOUNDARY:
            if backed_up and is_character:
                self._interchar_class = current
                return False
            if current == INTERCHAR_CLASS_BOUNDARY and not is_character:
                return False

        toks = self.parser.xetexinterchartoks[(previous, current)]
        if toks is None:
            self._interchar_class = current
            return False

        if previous != INTERCHAR_CLASS_BOUNDARY:
            self._interchar_class = INTERCHAR_CLASS_BOUNDARY
        self._deferIntercharAppend(toks, resume)
        return True

    def appendInlineMath(self, node, cache, _interchar_backed_up=False):
        if self._insertIntercharTokens(
            node,
            lambda: self.appendInlineMath(node, cache, _interchar_backed_up=True),
            _interchar_backed_up,
        ):
            return
        if getattr(node, "source", None) is None:
            self.raw.append(node)
        self._resetNonCharState()
        self._pending_space = None
        self.list.extend(cache)

    def appendAccent(self, node, _interchar_backed_up=False):
        if self._insertIntercharTokens(
            node,
            lambda: self.appendAccent(node, _interchar_backed_up=True),
            _interchar_backed_up,
        ):
            return
        if getattr(node, "source", None) is None:
            self.raw.append(node)
        self._resetNonCharState()
        self._pending_space = None
        start = len(self.list)
        node.typeset(self.parser, self.list)
        for concrete in self.list[start:]:
            if getattr(concrete, "source", None) is None:
                concrete.source = node

    def appendVAlignment(self, node, _interchar_backed_up=False):
        if self._insertIntercharTokens(
            node,
            lambda: self.appendVAlignment(node, _interchar_backed_up=True),
            _interchar_backed_up,
        ):
            return
        if getattr(node, "source", None) is None:
            self.raw.append(node)
        self._resetNonCharState()
        self._pending_space = None
        start = len(self.list)
        self.parser.typeset.align.typesetVAlignment(node, self.list)
        for concrete in self.list[start:]:
            if getattr(concrete, "source", None) is None:
                concrete.source = node

    def append(self, node, _interchar_backed_up=False):
        if self._insertIntercharTokens(
            node,
            lambda: self.append(node, _interchar_backed_up=True),
            _interchar_backed_up,
        ):
            return
        if isinstance(node, str):
            if node != "\u0020":
                raise ValueError("horizontal text strings must be U+0020 spaces")
            self._appendSpace()
            return
        if getattr(node, "source", None) is None:
            self.raw.append(node)
        if node.node_type != nd.NODE_TYPE.CHAR:
            self._resetNonCharState()
            if not self._invisibleToInterwordSpace(node):
                self._pending_space = None
            if node.node_type in (nd.NODE_TYPE.ADJUST, nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS):
                self.list.append(node)
                return
            if node.node_type in (nd.NODE_TYPE.ACCENT, nd.NODE_TYPE.MATH, nd.NODE_TYPE.ALIGNMENT):
                raise ValueError("non-standard horizontal nodes require dedicated append handling")
            self.list.append(node)
            return
        sf = self.sfcode[ord(node.char)]
        if sf != 0:
            spacefactor = self.parser.globals["spacefactor"]
            if spacefactor < 1000 < sf:
                sf = 1000
            self.parser.globals["spacefactor"] = sf
        if self._pending_text and self._pending_text[-1].font is not node.font:
            self._flushTextRun()
            self._pending_space = None
        self._pending_text.append(
            glyph_data.TextChar.fromCharNode(
                node,
                self.parser.lccode[ord(node.char)] != 0,
            )
        )

    def pop(self, *args):
        self._flushTextRun()
        self._pending_space = None
        node = self.list.pop(*args)
        return node


class HorizontalCommand(lists.ModeDependentCommand):
    """
    A command that behaves differently in different modes.
    """
    def vertical(self, parser, vlist):
        """
        perform the command in vertical mode.

        @param parser the parser
        @param vlis tthe current vertical list

        In vertical mode, when a horizontal command is encountered, 
        the current token is first unread, then
        then the parser start a new paragraph, the command token is then encountered
        """
        parser.input.unread(parser.current_token)
        hlist = parser.newParagraph()
    

class Char(HorizontalCommand):
    """
    Add a character to the current list.
    """
    def horizontal(self, parser, hlist):
        # read the character from the input stack
        c = parser.readInteger()
        if c < 0:
            raise ValueError("invalid character code")
        parser.addChar(chr(c))

    def math(self, parser, mlist):
        self.horizontal(parser)

    def charValue(self, parser):
        c = parser.readInteger()
        return chr(c)


class HSkip(lists.GlueCommand, HorizontalCommand):
    """
    Add a horizontal skip to the current list.
    """
    def __init__(self, glue=None):
        lists.GlueCommand.__init__(self, False, glue)

    def horizontal(self, parser, hlist):
        hlist.append(self.glueNode(parser))

    def math(self, parser, mlist):
        mlist.append(self.glueNode(parser))


class Par(HorizontalCommand):
    """
    the \\par command, which ends the current paragraph

    The primitive \\par command, also called \\endgraf in plain TeX, does
    nothing in restricted horizontal mode. But it terminates horizontal mode: 
    The current list is finished oﬀ by doing 
    \\unskip \\penalty10000 \\hskip\\parfillskip, 
    then it is broken into lines as explained in Chapter 14, and TeX returns 
    to the enclosing vertical or internal vertical mode. The lines of the 
    paragraph are appended to the enclosing vertical list, interspersed with 
    interline glue and interline penalties, and with the migration of vertical 
    material that was in the horizontal list. Then TeX exercises the page 
    builder. 
    """
    def horizontal(self, parser, hlist):
        # has no effect for restricted horizontal mode
        if hlist.inner:
            return
        # end the current paragraph:
        return parser.endParagraph()

    def vertical(self, parser, vlist):
        # The primitive \par command has no eﬀect when TeX is in vertical
        # mode, except that the page builder is exercised in case something 
        # is present on the contribution list, and the paragraph shape 
        # parameters are cleared.
        parser.volatile["parshape"] = []
        pass


class Indent(lists.ModeDependentCommand):
    """
    The \\indent command.
    """
    def vertical(self, parser, vlist):
        # Enter unrestricted horizontal mode (i.e., start a new paragraph).
        # \parskip handling is centralized in Parser.newParagraph.
        parser.newParagraph()
    
    def horizontal(self, parser, hlist):
        # An empty box of width \parindent is appended to the current list,
        # and the space factor is set to 1000. (The TeX Book pp.286)
        hlist.append(IndentBox(parser))

    def math(self, parser, mlist):
        # An empty box of width \parindent is appended to the current list,
        # as the nucleus of a new Ord atom.
        mlist.append(IndentBox(parser))


class NoIndent(lists.ModeDependentCommand):
    """
    The \\noindent command.
    """
    def vertical(self, parser, vlist):
        # This is exactly like \indent, except that T EX starts out in 
        # horizontal mode with an empty list instead of with an indentation.
        # \parskip handling is centralized in Parser.newParagraph.
        parser.newParagraph(indent=False)
    
    def horizontal(self, parser, hlist):
        # This command has no eﬀect in horizontal modes.
        pass

    def math(self, parser, mlist):
        # This command has no eﬀect in math mode.
        pass


class ParShape(Command):
    """
    Set the paragraph shape.
    """
    def execute(self, parser):
        n = parser.readInteger()
        if n < 0:
            raise ValueError("invalid number of lines")
        parshape = []
        for i in range(n):
            indent = parser.readDimen()
            width = parser.readDimen()
            parshape.append((indent, width))
        parser.volatile["parshape"] = parshape


class ControlledSpace(HorizontalCommand):
    """
    A command that inserts a controlled space "\\ ".
    """
    def horizontal(self, parser, hlist):
        font = parser.parameters["currentfont"]
        hlist.append(nd.Glue(font.spaceglue, None))

    def math(self, parser, mlist):
        # In math mode, a space is a no-op
        self.horizontal(parser, mlist)


def _sumHorizontalNodes(nodes):
    width = Dimen()
    for node in nodes:
        if isinstance(node, nd.Box):
            width += node.width
            continue
        if node.node_type == nd.NODE_TYPE.KERN:
            width += node.kern
            continue
        raise ValueError(f"not valid in \\discretionary lists: {node}")
    return width


class Disc(nd.Node):
    """
    A discretionary node.
    """
    def __init__(self, pre, post, replace):
        self.pre = pre
        self.post = post
        self.replace = replace
        self.pre_width = _sumHorizontalNodes(pre)
        self.post_width = _sumHorizontalNodes(post)
        self.replace_width = _sumHorizontalNodes(replace)
        self.list = self.replace
        
    def saveInfo(self):
        return {"pre": self.pre, "post": self.post, "replace": self.replace}, None
    
    def __repr__(self):
        return f"Disc({self.pre}, {self.post}, {self.replace})"

    def meaning(self, parser):
        pre = "{" + "".join([x.meaning(parser) for x in self.pre]) + "}"
        post = "{" + "".join([x.meaning(parser) for x in self.post]) + "}"
        replace = "{" + "".join([x.meaning(parser) for x in self.replace]) + "}"
        return f"\\discretionary{pre}{post}{replace}"

    node_type = nd.NODE_TYPE.DISC


class Discretionary(HorizontalCommand):
    """
    The \\discretionary command.
    """
    @staticmethod
    def _validatePart(parser, nodes):
        for node in nodes:
            try:
                _sumHorizontalNodes([node])
            except ValueError as err:
                raise ValueError(str(err), parser.input.position()) from None

    def _readParts(self, parser, out, math):
        pre = []
        post = []
        replace = []
        pre_state = HList(parser, pre)
        post_state = HList(parser, post)
        replace_state = HList(parser, replace)
        
        def finish(_parser):
            self._validatePart(parser, pre)
            self._validatePart(parser, post)
            self._validatePart(parser, replace)
            node = Disc(pre, post, replace)
            if math and len(node.replace) > 0:
                raise ValueError("replace part of discretionary must be empty in math mode")
            out.append(node)

        def readReplace(_parser):
            parser.readList(replace_state, GROUP_TYPE.DISC, finish)

        def readPost(_parser):
            parser.readList(post_state, GROUP_TYPE.DISC, readReplace)

        parser.readList(pre_state, GROUP_TYPE.DISC, readPost)
    
    def horizontal(self, parser, hlist):
        self._readParts(parser, hlist, False)

    def math(self, parser, mlist):
        self._readParts(parser, mlist, True)


class VAdjust(HorizontalCommand):
    """
    The \\vadjust command.
    """
    def horizontal(self, parser, hlist):
        from pytex import vmode

        # Read the argument
        vlist = parser.readVList(GROUP_TYPE.ADJUSTED_HBOX)
        # Add the vadjust node
        hlist.append(vmode.VAdjust(vlist))

    def math(self, parser, mlist):
        # Preserve \vadjust as a migratory vertical node in the math list.
        self.horizontal(parser, mlist)


class Accent(HorizontalCommand):
    """
    The \\accent command.
    """

    def readArgs(self, parser):
        """
        read the accent char and the accented char
        """
        c = parser.readInteger()
        font = parser.parameters["currentfont"]
        if not font.hasCharCode(c):
            raise ValueError("invalid accent", parser.input.position())
        accent = font[chr(c)]
        while True:
            t = parser.token_expand()
            if t is None:
                break
            meaning = t.definition
            # is t is an assignment, run it
            if isinstance(meaning, Accessor):
                meaning.execute(parser)
            elif meaning != relax:
                break
        if t is not None:
            if t.catcode == CATCODE.LETTER or t.catcode == CATCODE.OTHER:
                c = t.name
            elif isinstance(meaning, CharDefValue):
                c = chr(meaning.value)
            else:
                c = None
                if hasattr(meaning, "charValue"):
                    c = meaning.charValue(parser)
                else:
                    parser.input.unread(t)
            if c is not None:
                # the font may have changed in the assignments
                font = parser.parameters["currentfont"]
                char = font[c]
                return char, accent
        return None, accent

    def horizontal(self, parser, hlist):
        char, accent = self.readArgs(parser)
        hlist.appendAccent(AccentNode(accent, char))

    def math(self, parser, mlist):
        raise ValueError("please use \\mathaccent in math mode")
    

class SpaceFactor(Accessor):
    """
    The \\spacefactor command, which sets the space factor in a horizontal list.
    """
    value_type = VALUE_TYPE.INT

    def getTarget(self, parser):
        key = self.currentKey(parser)
        top = parser.lists[-1]
        if top.type != lists.LISTTYPE.HORIZONTAL:
            raise ValueError("\\spacefactor can only be used in horizontal mode")
        return KeyTarget(self.domain, key, self.value_type)
    
    def readValue(self, parser):
        value = parser.readInteger()
        if value < 0:
            raise ValueError("invalid space factor")
        return value
    

mod = Module("hmode",
    commands={
        "char": Char(),
        "hskip": HSkip(),
        "hfil": HSkip(Glue(0, Stretchness(1, 1))),
        "hfill": HSkip(Glue(0, Stretchness(1, 2))),
        "hss": HSkip(Glue(0, Stretchness(1, 1), Stretchness(1, 1))),
        "hnegfil": HSkip(Glue(0, Stretchness(-1, 1))),
        "par": Par(),
        "indent": Indent(),
        "noindent": NoIndent(),
        "parshape": ParShape(),
        " ": ControlledSpace(),
        "discretionary": Discretionary(),
        "vadjust": VAdjust(),
        "accent": Accent(),
    },
    parameters={
        "parshape": {"value": list, "accessor": None, "domain": "volatile"},
        "spacefactor": {"value": 1000, "accessor": SpaceFactor, "domain": "globals"},
    },
)
