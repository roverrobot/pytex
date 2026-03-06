"""
Implementation of horizontal commands and hlist handling.
"""


from pytex import node as nd
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.module import Module
from pytex.token import Command, CATCODE, relax
from pytex.state import GROUP_TYPE
from pytex.accessor import Accessor
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


class HListHolder:
    """
    Common holder for horizontal node lists.

    This helper stays in hmode because it provides horizontal list
    typesetting behavior.
    """
    def __init__(self, nodes=None):
        self.list = [] if nodes is None else nodes

    def __len__(self):
        return len(self.list)

    def __iter__(self):
        return iter(self.list)

    def __getitem__(self, index):
        return self.list[index]

    def __setitem__(self, index, value):
        self.list[index] = value

    def __delitem__(self, key):
        del self.list[key]

    def append(self, node):
        self.list.append(node)

    def extend(self, nodes):
        self.list.extend(nodes)

    def pop(self, *args):
        return self.list.pop(*args)

    def clear(self):
        self.list.clear()

    def typesetNode(self, parser, node, packed):
        """
        Typeset/expand one node into packed output with source propagation.
        """
        typeset = node.typeset
        if typeset is None:
            packed.append(node)
            return
        start = len(packed)
        typeset(parser, packed)
        if len(packed) == start:
            packed.append(node)
            return
        for n in packed[start:]:
            if n is node:
                continue
            if getattr(n, "source", None) is None:
                n.source = node

    def _leftBoundaryNode(self, font):
        step = font.tfm.program.left_boundary
        if step is None:
            return None
        program = {}
        while step is not None:
            program[step.next_char] = step
            step = step.next_step
        return types.SimpleNamespace(
            _boundary=True,
            font=font,
            char="\0",
            node_type=nd.NODE_TYPE.CHAR,
            char_info=types.SimpleNamespace(program=program),
        )

    def _rightBoundaryNode(self, font):
        step = font.tfm.program.right_boundary
        if step is None:
            return None
        return types.SimpleNamespace(
            _boundary=True,
            font=font,
            char=chr(step.next_char),
            node_type=nd.NODE_TYPE.CHAR,
            char_info=types.SimpleNamespace(program=None),
        )

    def _runBoundaryProgram(self, working):
        working = run_ligature_program(
            working,
            make_ligature=lambda insert_char, replaced, step, current, nxt: Ligature(insert_char, replaced),
            make_kern=lambda step, current, nxt: nd.Kern(step.kern * current.font.at, True),
            source_nodes=lambda n: [] if getattr(n, "_boundary", False) else (list(n.source) if isinstance(n, Ligature) else [n]),
        )
        return [n for n in working if not getattr(n, "_boundary", False)]

    def _lastLigBase(self, packed):
        for n in reversed(packed):
            if n.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                return n
            if n.node_type not in (nd.NODE_TYPE.KERN,):
                break
        return None

    def _applyLeftBoundary(self, node, packed, state):
        boundary = self._leftBoundaryNode(node.font)
        if boundary is None:
            return False
        working = self._runBoundaryProgram([boundary, node])
        packed.extend(working)
        state["lig_base"] = self._lastLigBase(working)
        return True

    def _applyRightBoundary(self, packed, state):
        base = state["lig_base"]
        if base is None:
            return
        boundary = self._rightBoundaryNode(base.font)
        if boundary is None:
            return
        assert packed[-1] is base, "the ligature base should be the last emitted character"
        packed.pop()
        packed.extend(self._runBoundaryProgram([base, boundary]))

    def typesetNodeWithLigatures(self, parser, node, packed, state):
        """
        Typeset one source node, forming ligatures from adjacent raw characters.
        """
        if node.node_type != nd.NODE_TYPE.CHAR:
            if state["in_word"]:
                self._applyRightBoundary(packed, state)
                state["in_word"] = False
            state["lig_base"] = None
            self.typesetNode(parser, node, packed)
            return
        is_word = parser.state.lccode[ord(node.char)] != 0
        if is_word:
            if not state["in_word"]:
                state["in_word"] = True
                state["lig_base"] = None
                if self._applyLeftBoundary(node, packed, state):
                    return
        elif state["in_word"]:
            self._applyRightBoundary(packed, state)
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

    def typesetNodes(self, parser, packed):
        state = {"lig_base": None, "in_word": False}
        for node in self.list:
            self.typesetNodeWithLigatures(parser, node, packed, state)
        if state["in_word"]:
            self._applyRightBoundary(packed, state)
        return packed


from pytex.box import SetBox, AccentNode, IndentBox


class HList(lists.ListBuildState):
    """
    Horizontal list build-state wrapper.

    This is what lives on parser.lists while horizontal material is scanned.
    It serves a concrete horizontal list node and updates \\spacefactor.
    """
    _local_attrs = lists.ListBuildState._local_attrs | {"spacefactor", "sfcode", "type", "inner"}

    def __init__(self, parser, inner=True, nodes=None, node=None):
        if node is None:
            node = [] if nodes is None else nodes
        if hasattr(node, "inner"):
            inner = node.inner
        super().__init__(parser, node)
        object.__setattr__(self, "spacefactor", 1000)
        object.__setattr__(self, "sfcode", parser.state.sfcode)
        object.__setattr__(self, "type", lists.LISTTYPE.HORIZONTAL)
        object.__setattr__(self, "inner", inner)

    def append(self, node):
        if node.node_type != nd.NODE_TYPE.CHAR:
            self.spacefactor = 1000
            self._raw_append(node)
            return
        sf = self.sfcode[ord(node.char)]
        if sf != 0:
            if self.spacefactor < 1000 < sf:
                sf = 1000
            self.spacefactor = sf
        self._raw_append(node)

    def typesetNodes(self, parser, packed):
        return typesetHorizontalNodes(parser, self, packed)


def typesetHorizontalNodes(parser, nodes, packed):
    """
    Typeset a raw horizontal node list into packed output.
    """
    return HListHolder(nodes).typesetNodes(parser, packed)
    
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
        parser.endParagraph()

    def vertical(self, parser, vlist):
        # The primitive \par command has no eﬀect when TeX is in vertical
        # mode, except that the page builder is exercised in case something 
        # is present on the contribution list, and the paragraph shape 
        # parameters are cleared.
        parser.state.globals["parshape"] = []
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
        parser.state.globals["parshape"] = parshape


class ControlledSpace(HorizontalCommand):
    """
    A command that inserts a controlled space "\\ ".
    """
    def horizontal(self, parser, hlist):
        font = parser.state.parameters["currentfont"]
        hlist.append(nd.Glue(font.spaceglue, None))

    def math(self, parser, mlist):
        # In math mode, a space is a no-op
        self.horizontal(parser, mlist)

class Discretionary(HorizontalCommand):
    """
    The \\discretionary command.
    """
    def _readParts(self, parser, out, math):
        pre = []
        post = []
        replace = []
        pre_state = HList(parser, node=pre)
        post_state = HList(parser, node=post)
        replace_state = HList(parser, node=replace)
        
        def finish():
            # we need to handle ligatures and boxes so their width are fixed.
            packed_pre = []
            typesetHorizontalNodes(parser, pre, packed_pre)
            packed_post = []
            typesetHorizontalNodes(parser, post, packed_post)
            packed_replace = []
            typesetHorizontalNodes(parser, replace, packed_replace)
            node = nd.Disc(packed_pre, packed_post, packed_replace)
            if math and len(node.replace) > 0:
                raise ValueError("replace part of discretionary must be empty in math mode")
            out.append(node)

        def readReplace():
            parser.readList(replace_state, GROUP_TYPE.DISC, finish)

        def readPost():
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
        vlist = parser.readVList(GROUP_TYPE.VADJUST)
        # Add the vadjust node
        hlist.append(vmode.VAdjust(vlist))

    def math(self, parser, mlist):
        # In math mode, a vadjust is a no-op
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
        font = parser.state.parameters["currentfont"]
        if c < font.bc or c > font.ec:
            raise ValueError("invalid accent", parser.input.position())
        accent = font[chr(c)]
        while True:
            t = parser.token_expand()
            if t is None:
                break
            meaning = t.definition
            # is t is an assignment, run it
            if isinstance(meaning, Accessor) and not isinstance(meaning, SetBox):
                meaning.execute(parser)
            elif meaning != relax:
                break
        if t is not None:
            if t.catcode == CATCODE.LETTER or t.catcode == CATCODE.OTHER:
                c = t.name
            else:
                try:
                    c = meaning.charValue(parser)
                except AttributeError:
                    parser.input.unread(t)
                c = None
            if c is not None:
                # the font may have changed in the assignments
                font = parser.state.parameters["currentfont"]
                char = font[c]
                return char, accent
        return None, accent

    def horizontal(self, parser, hlist):
        char, accent = self.readArgs(parser)
        hlist.append(AccentNode(accent, char))

    def math(self, parser, mlist):
        raise ValueError("please use \\mathaccent in math mode")
    

class SpaceFactor(Accessor):
    """
    The \\spacefactor command, which sets the space factor in a horizontal list.
    """
    def setGlobal(self, parser, value):
        return self.set(parser, value)
    
    def set(self, parser, value):
        if value < 0:
            raise ValueError("invalid space factor")
        top = parser.lists[-1]
        if top.type != lists.LISTTYPE.HORIZONTAL:
            raise ValueError("\\spacefactor can only be used in horizontal mode")
        top.spacefactor = value

    def intValue(self, parser):
        top = parser.lists[-1]
        if top.type != lists.LISTTYPE.HORIZONTAL:
            raise ValueError("\\spacefactor can only be used in horizontal mode")
        return getattr(top, "spacefactor", 1000)
    
    def readValue(self, parser):
        return parser.readInteger()
    

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
        "accent": Accent(),
        "spacefactor": SpaceFactor(),
    },
    parameters={
        "parshape": {"value": list, "accessor": None, "domain": "globals"},
    },
)
