"""
Implementation of horizontal commands and hlist handling.
"""


from pytex import node as nd
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.dimen import Dimen
from pytex.module import Module
from pytex.token import Command, CATCODE, relax
from pytex.state import GROUP_TYPE
from pytex.accessor import Accessor, VALUE_TYPE, KeyTarget
from pytex.define import CharDefValue
from pytex.ligature import ligature_step, run_ligature_program
import types


class Ligature(nd.CharNode):
    """
    A ligature node.

    It is a char node that stores the characters that are combined into the
    ligature.
    @param char: the ligature character
    @param replaced: the original char nodes replaced by the ligature
    """
    def __init__(self, char, replaced):
        super().__init__(char.char, char.font)
        self.source = list(replaced)

    node_type = nd.NODE_TYPE.LIGATURE

    def __repr__(self):
        s = "".join([c.char for c in self.source])
        return f"Ligature({s})"

from pytex.box import AccentNode, IndentBox


class HList(lists.List):
    """
    Horizontal list wrapper.

    This is what lives on parser.lists while horizontal material is scanned.
    It serves a concrete horizontal list node and updates \\spacefactor.
    """
    @staticmethod
    def _leftBoundaryNode(font):
        program = font.leftBoundaryProgram()
        if program is None:
            return None
        return types.SimpleNamespace(
            _boundary=True,
            font=font,
            char="\0",
            node_type=nd.NODE_TYPE.CHAR,
            char_info=types.SimpleNamespace(program=program),
        )

    @staticmethod
    def _rightBoundaryNode(font):
        boundary_char = font.rightBoundaryChar()
        if boundary_char is None:
            return None
        return types.SimpleNamespace(
            _boundary=True,
            font=font,
            char=boundary_char,
            node_type=nd.NODE_TYPE.CHAR,
            char_info=types.SimpleNamespace(program=None),
        )

    @staticmethod
    def _runBoundaryProgram(working):
        working = run_ligature_program(
            working,
            make_ligature=lambda insert_char, replaced, step, current, nxt: Ligature(insert_char, replaced),
            make_kern=lambda step, current, nxt: nd.Kern(step.kern * current.font.at, True),
            source_nodes=lambda n: [] if getattr(n, "_boundary", False) else (list(n.source) if isinstance(n, Ligature) else [n]),
        )
        return [n for n in working if not getattr(n, "_boundary", False)]

    @staticmethod
    def _lastLigBase(packed):
        for n in reversed(packed):
            if n.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                return n
            if n.node_type not in (nd.NODE_TYPE.KERN,):
                break
        return None

    @classmethod
    def _applyLeftBoundary(cls, node, packed, state):
        boundary = cls._leftBoundaryNode(node.font)
        if boundary is None:
            return False
        working = cls._runBoundaryProgram([boundary, node])
        packed.extend(working)
        state["lig_base"] = cls._lastLigBase(working)
        return True

    @classmethod
    def _applyRightBoundary(cls, packed, state):
        base = state["lig_base"]
        if base is None:
            return
        boundary = cls._rightBoundaryNode(base.font)
        if boundary is None:
            return
        assert packed[-1] is base, "the ligature base should be the last emitted character"
        packed.pop()
        packed.extend(cls._runBoundaryProgram([base, boundary]))

    @classmethod
    def processLigature(cls, parser, node, packed, state):
        """
        Append one character node, forming ligatures from adjacent characters.
        """
        assert node.node_type == nd.NODE_TYPE.CHAR
        is_word = parser.lccode[ord(node.char)] != 0
        if is_word:
            if not state["in_word"]:
                state["in_word"] = True
                state["lig_base"] = None
                if cls._applyLeftBoundary(node, packed, state):
                    return
        elif state["in_word"]:
            cls._applyRightBoundary(packed, state)
            state["in_word"] = False
            state["lig_base"] = None
        base = state["lig_base"]
        if base is None:
            packed.append(node)
            state["lig_base"] = node
            return
        assert packed[-1] is base, "the ligature base should be the last emitted character"
        if ligature_step(base, node) is None:
            packed.append(node)
            state["lig_base"] = node
            return
        packed.pop()
        working = run_ligature_program(
            [base, node],
            make_ligature=lambda insert_char, replaced, step, current, nxt: Ligature(insert_char, replaced),
            make_kern=lambda step, current, nxt: nd.Kern(step.kern * current.font.at, True),
            source_nodes=lambda n: list(n.source) if isinstance(n, Ligature) else [n],
        )
        for n in working:
            packed.append(n)
        state["lig_base"] = working[-1]

    def __init__(self, parser, list, inner=True, raw=None, paragraph=None):
        super().__init__(parser, list, inner)
        self.raw = [] if raw is None else raw
        self.paragraph = paragraph
        self.sfcode = parser.sfcode
        self.type = lists.LISTTYPE.HORIZONTAL
        self._ligature_state = {"lig_base": None, "in_word": False}

    def open(self):
        super().open()
        self.saved_spacefactor = self.parser.globals["spacefactor"]
        self.parser.globals["spacefactor"] = 1000
        self._syncLigatureState()

    def close(self):
        if self._ligature_state["in_word"]:
            self._applyRightBoundary(self.list, self._ligature_state)
            self._ligature_state["in_word"] = False
            self._ligature_state["lig_base"] = None
        self.parser.globals["spacefactor"] = self.saved_spacefactor
        super().close()

    @property
    def list_type_name(self):
        return "HList" if self.inner else "Paragraph"

    def concreteNodes(self):
        return list(self.list)

    def rawNodes(self):
        return list(self.raw)

    def _nodeEndsWord(self, node):
        if node is None:
            return False
        if node.node_type == nd.NODE_TYPE.CHAR:
            return self.parser.lccode[ord(node.char)] != 0
        if node.node_type == nd.NODE_TYPE.LIGATURE:
            source = getattr(node, "source", None) or []
            tail = source[-1] if source else None
            if tail is not None and tail.node_type == nd.NODE_TYPE.CHAR:
                return self.parser.lccode[ord(tail.char)] != 0
        return False

    def _syncLigatureState(self):
        base = self._lastLigBase(self.list)
        self._ligature_state["lig_base"] = base
        self._ligature_state["in_word"] = self._nodeEndsWord(base)

    def _resetNonCharState(self):
        if self._ligature_state["in_word"]:
            self._applyRightBoundary(self.list, self._ligature_state)
            self._ligature_state["in_word"] = False
        self._ligature_state["lig_base"] = None
        self.parser.globals["spacefactor"] = 1000

    def appendInlineMath(self, node, cache):
        if getattr(node, "source", None) is None:
            self.raw.append(node)
        self._resetNonCharState()
        self.list.extend(cache)

    def appendAccent(self, node):
        if getattr(node, "source", None) is None:
            self.raw.append(node)
        self._resetNonCharState()
        start = len(self.list)
        node.typeset(self.parser, self.list)
        for concrete in self.list[start:]:
            if getattr(concrete, "source", None) is None:
                concrete.source = node

    def appendVAlignment(self, node):
        if getattr(node, "source", None) is None:
            self.raw.append(node)
        self._resetNonCharState()
        start = len(self.list)
        self.parser.typeset.align.typesetVAlignment(node, self.list)
        for concrete in self.list[start:]:
            if getattr(concrete, "source", None) is None:
                concrete.source = node

    def append(self, node):
        if getattr(node, "source", None) is None:
            self.raw.append(node)
        if node.node_type != nd.NODE_TYPE.CHAR:
            self._resetNonCharState()
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
        self.processLigature(
            self.parser,
            node,
            self.list,
            self._ligature_state,
        )

    def pop(self, *args):
        node = self.list.pop(*args)
        self._syncLigatureState()
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
        if node.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
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
    target_type = VALUE_TYPE.INT

    def getTarget(self, parser):
        key = self.currentKey(parser)
        top = parser.lists[-1]
        if top.type != lists.LISTTYPE.HORIZONTAL:
            raise ValueError("\\spacefactor can only be used in horizontal mode")
        return KeyTarget(self.domain, key, self.target_type)
    
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
