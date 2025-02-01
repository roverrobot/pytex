"""
Implementation of horizontal commands and hlist handling.
"""


from pytex import node as nd
from pytex import lists
from pytex.glue import Glue, Stretchness
from pytex.module import Module
from pytex.token import Command
from pytex.state import GROUP_TYPE


class Ligature(nd.CharNode):
    """
    A ligature node.

    It is a char node that stores the characters that are combined into the
    ligature.
    @param char: the ligature character
    """
    def __init__(self, char, characters):
        super().__init__(char.char_info, char.font)
        self.characters = characters

    node_type = nd.NODE_TYPE.LIGATURE

    def __repr__(self):
        s = "".join([c.char for c in self.characters])
        return f"Ligature({s})"


def addNode(nodes, node):
    if node.node_type == nd.NODE_TYPE.CHAR and len(nodes) > 0:
        last = nodes[-1]
        if isinstance(last, nd.CharNode) and last.font == node.font:
            # check if there is a program
            next = ord(node.char)
            program = last.char_info.program
            if program is not None and next in program:
                op = last.char_info.program[next]
                if op.isKern:
                    nodes.append(nd.Kern(op.kern*last.font.at, True))
                    nodes.append(node)
                    return nodes
                # a ligature
                if last.node_type != nd.NODE_TYPE.LIGATURE:
                    last = Ligature(last, [last])
                    nodes[-1] = last
                last.characters.append(node)
                insert = Ligature(last.font[chr(op.insert)], last.characters)
                move = op.move
                if op.delete_current:
                    nodes.pop()
                    nodes.append(insert)
                elif move == 0:
                    nodes = addNode(nodes, insert)
                else:
                    nodes.append(insert)
                    move -= 1
                if not op.keep_next:
                    return nodes
                if move == 0:
                    return addNode(nodes, Ligature(node, last.characters))
    nodes.append(node)
    return nodes


class HList(lists.List):
    """
    A horizontal list.
    """
    def __init__(self, parser, inner=True):
        super().__init__(parser, lists.LISTTYPE.HORIZONTAL, inner=inner)

    def append(self, node):
        # \spacefactor for characters has been handled in parser.addChar. Now we need to set
        # \spacefactor to 1000 for other nodes.
        if node.node_type != nd.NODE_TYPE.CHAR:
            self.parser.state.globals["spacefactor"] = 1000
        super().append(node)
    
    def pack(self):
        """
        prepare the list for typesetting.

        @return a new list with ligatures combined, and the glues in the list

        This will combine characters into ligatures, glues, and  nodes that need
        to be migrated.
        """
        nodes = []
        glues = []
        migrate = []
        for node in self:
            node_type = node.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                glues.append(node)
                nodes.append(node)
            elif node_type == nd.NODE_TYPE.ACCENT:
                hlist = []
                node.typeset(hlist)
                for n in hlist:
                    nodes = addNode(nodes, n)
            elif node_type == nd.NODE_TYPE.ADJUST or node_type == nd.NODE_TYPE.MARK or node_type == nd.NODE_TYPE.INS:
                migrate.append(node)
            else:
                nodes = addNode(nodes, node)
        return nodes, glues, migrate


class HorizontalCommand(lists.ModeDependentCommand):
    """
    A command that behaves differently in different modes.
    """
    def vertical(self, parser, vlist):
        """
        In vertical mode, a horizontal command should start a new paragraph
        """
        hlist = parser.newParagraph()
        self.horizontal(parser, hlist)
    

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


class HFil(HSkip):
    """
    Add a horizontal skip of 0pt plus 1fil.
    """
    def __init__(self):
        super().__init__(Glue(0, Stretchness(1, 1)))


class HFill(HSkip):
    """
    Add a horizontal skip of 0pt plus 1fill.
    """
    def __init__(self):
        super().__init__(Glue(0, Stretchness(1, 2)))


class Hss(HSkip):
    """
    Add a horizontal skip of 0pt plus 1fil minus 1fil.
    """
    def __init__(self):
        super().__init__(Glue(0, Stretchness(1, 1), Stretchness(1, 1)))


class HNegFil(HSkip):
    """
    Add a horizontal skip of 0pt plus -1fil.
    """
    def __init__(self):
        super().__init__(Glue(0, Stretchness(-1, 1)))


class Par(HorizontalCommand):
    """
    the \\par command, which ends the current paragraph

    The primitive \\par command, also called \endgraf in plain TeX, does
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


class IndentBox(nd.Box):
    """
    An box for indentation
    """
    node_type = nd.NODE_TYPE.HLIST
    def __init__(self, parser):
        width = parser.state.parameters["parindent"]
        super().__init__(width, 0, 0)


class Indent(lists.ModeDependentCommand):
    """
    The \\indent command.
    """
    def vertical(self, parser, vlist):
        # The \parskip glue is appended to the current list, unless TeX is in
        # internal vertical mode and the current list is empty. Then TeX enters 
        # unrestricted horizontal mode (i.e., start a new paragraph). See 
        # The TeX Book pp.282
        if not vlist.inner or len(vlist) > 0:
            vlist.append(nd.Glue(parser.state.parameters["parskip"]))
        parser.newParagraph()
    
    def horizontal(self, parser, hlist):
        # An empty box of width \parindent is appended to the current list,
        # and the space factor is set to 1000. (The TeX Book pp.286)
        hlist.append(IndentBox(parser))
        parser.state.globals.spacefactor = 1000

    def math(self, parser, mlist):
        # An empty box of width \parindent is appended to the current list,
        # as the nucleus of a new Ord atom.
        mlist.addBox(IndentBox(parser))


class NoIndent(lists.ModeDependentCommand):
    """
    The \\noindent command.
    """
    def vertical(self, parser, vlist):
        # This is exactly like \indent, except that T EX starts out in 
        # horizontal mode with an empty list instead of with an indentation.
        if not vlist.inner or len(vlist) > 0:
            vlist.append(nd.Glue(parser.state.parameters["parskip"]))
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


class DiscHList(HList):
    """
    A horizontal list that can contain discretionary nodes.
    """
    def __init__(self):
        # this list probably does not need to know the parser
        super().__init__(None, inner=True)

    def append(self, node):
        if isinstance(node, nd.Box) or isinstance(node, nd.Kern):
            list.append(self, node)
        else:
            raise ValueError("invalid node in this \\disctretionary")


class Discretionary(HorizontalCommand):
    """
    The \\discretionary command.
    """
    def readValue(self, parser):
        pre = DiscHList()
        parser.readList(pre, GROUP_TYPE.DISC)
        post = DiscHList()
        parser.readList(post, GROUP_TYPE.DISC)
        replace = DiscHList()
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


mod = Module("hmode",
    commands={
        "char": Char(),
        "hskip": HSkip(),
        "hfil": HFil(),
        "hfill": HFill(),
        "hss": Hss(),
        "hnegfil": HNegFil(),
        "par": Par(),
        "indent": Indent(),
        "noindent": NoIndent(),
        "parshape": ParShape(),
        " ": ControlledSpace(),
        "discretionary": Discretionary(),
    },
    parameters={
        "parshape": {"value": list, "accessor": None, "domain": "globals"},
    },
)
