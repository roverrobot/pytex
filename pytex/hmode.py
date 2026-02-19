"""
Implementation of horizontal commands and hlist handling.
"""


from pytex import node as nd
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.module import Module
from pytex.token import Command, CATCODE, relax
from pytex.state import GROUP_TYPE
from pytex.box import SetBox, AccentNode, IndentBox
from pytex.accessor import Accessor


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


class HList(lists.List):
    """
    A horizontal list.
    """
    def __init__(self, parser, inner=True, nodes=[]):
        super().__init__(parser, lists.LISTTYPE.HORIZONTAL, inner=inner, nodes=nodes)
        self.lig_base = None
        self.in_word = False
        self.spacefactor = 1000
        self.sfcode = parser.state.sfcode

    def append(self, node):
        # \spacefactor for characters has been handled in parser.addChar. Now we need to set
        # \spacefactor to 1000 for other nodes.
        if node.node_type != nd.NODE_TYPE.CHAR:
            self.spacefactor = 1000
            list.append(self, node)
            self.lig_base = None
            self.in_word = False
            return
        sf = self.sfcode[ord(node.char)]
        if sf != 0:
            if self.spacefactor < 1000 < sf:
                sf = 1000
            self.spacefactor = sf
        # we should check for the start/end of a word to handle boundary characters.
        nextchar = ord(node.char)
        lc = self.parser.state.lccode[nextchar]
        if not self.in_word and  lc != 0:
            # boundary character at the start of a word, we should check for left boundary
            self.in_word = True
            # todo
        elif self.in_word and lc == 0:
            # boundary character at the end of a word, we should check for right boundary
            self.in_word = False
            # todo
        # we should check for ligature
        if self.lig_base is None:
            self.lig_base = node
            list.append(self, node)
            return
        # now we are building a ligature, we need to check if the current node can be combined with the ligature base
        base = self.lig_base
        font = base.font
        if font != node.font:
            # different fonts, cannot be combined
            list.append(self, node)
            self.lig_base = node
            return
        assert self[-1] is base, "the ligature base should always be the last character in the list"
        program = base.char_info.program
        if program is None or nextchar not in program:
            # no ligature program, cannot be combined
            list.append(self, node)
            self.lig_base = node
            return
        self.pop()
        # The ligature program may recurse; run it on a temporary working list.
        working = [base, node]
        cursor = 0
        def replaced_nodes(n):
            return list(n.source) if isinstance(n, Ligature) else [n]
        while cursor < len(working) - 1:
            base, next = working[cursor:cursor+2]
            if not isinstance(base, nd.CharNode) or not isinstance(next, nd.CharNode):
                break
            if base.font != next.font:
                break
            program = base.char_info.program
            nextchar = ord(next.char)
            if program is None or nextchar not in program:
                break
            step = program[nextchar]
            if step.isKern:
                # this is a kerning step, we should insert a kern and stop
                working.insert(cursor+1, nd.Kern(step.kern * base.font.at, True))
                cursor += 2
            else:
                # this is a ligature step
                insert_char = base.font[chr(step.insert)]
                if step.delete_current:
                    replaced = replaced_nodes(base)
                    if not step.keep_next:
                        replaced.extend(replaced_nodes(next))
                        working[cursor:cursor+2] = [Ligature(insert_char, replaced)]
                    else:
                        working[cursor] = Ligature(insert_char, replaced)
                elif not step.keep_next:
                    replaced = replaced_nodes(next)
                    working[cursor+1] = Ligature(insert_char, replaced)
                else:
                    working.insert(cursor+1, insert_char)
                cursor += step.move
        self.extend(working)
        self.lig_base = working[-1]

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

    def typesetNodes(self, parser, packed):
        """
        Typeset/expand nodes into packed output.
        """
        for node in self:
            self.typesetNode(parser, node, packed)
        return packed
    
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
        hlist.append(nd.Glue(font.spaceglue))

    def math(self, parser, mlist):
        # In math mode, a space is a no-op
        self.horizontal(parser, mlist)


class Discretionary(HorizontalCommand):
    """
    The \\discretionary command.
    """
    def readValue(self, parser):
        pre = HList(parser)
        parser.readList(pre, GROUP_TYPE.DISC)
        post = HList(parser)
        parser.readList(post, GROUP_TYPE.DISC)
        replace = HList(parser)
        parser.readList(replace, GROUP_TYPE.DISC)
        # Add the discretionary node
        return nd.Disc(pre, post, replace)
    
    def horizontal(self, parser, hlist):
        # Read the three arguments
        hlist.append(self.readValue(parser))

    def math(self, parser, mlist):
        node = self.readValue(parser)
        if len(node.replace) > 0:
            raise ValueError("replace part of discretionary must be empty in math mode")
        mlist.append(node)


class VAdjust(HorizontalCommand):
    """
    The \\vadjust command.
    """
    def horizontal(self, parser, hlist):
        # Read the argument
        
        vlist = parser.readVList(GROUP_TYPE.VADJUST)
        # Add the vadjust node
        hlist.append(nd.VAdjust(vlist))

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
        return top.spacefactor
    
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
