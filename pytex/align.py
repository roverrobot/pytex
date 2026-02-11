"""
This module implements the \\halign and \\valign commands
"""

from pytex import serialization
from pytex import lists
from pytex import node as nd
from pytex import box as bx
from pytex import hmode
from pytex import vmode
from pytex.token import Token, CATCODE, Command
from pytex import lexer
from pytex import glue
from pytex import accessor
from pytex.state import GROUP_TYPE
from pytex.module import Module
from pytex.dimen import Dimen


class Row(serialization.Serializable):
    """
    A row in an alignment.

    In vertical alignment, this is a column.
    """
    def __init__(self):
        # the noalign vertical list
        self.noalign = None
        # a list of restricted hlists
        self.cells = []

    def saveInfo(self):
        return {
            "extra": {
                "noalign": self.noalign,
                "cells": self.cells,
            },
        }

    def __repr__(self):
        return f"Row({self.cells})"


class Alignment(nd.Node):
    """
    An alignment node.
    """
    def __init__(self, to=None, spread=Dimen()):
        self.rows = []
        # the first noalign before the first row
        self.noalign = None
        self.tabskips = []
        self.to = to
        self.spread = spread

    node_type = nd.NODE_TYPE.ALIGNMENT

    def saveInfo(self):
        return {
            "extra": {
                "rows": self.rows,
                "noalign": self.noalign,
            },
        }
    
    def __repr__(self):
        return f"Alignment({self.rows})"


class CrCr(Command):
    """
    The \\crcr command.
    It is used to terminate a row in an alignment.
    """
    def execute(self, parser):
        """
        Execute the command. It terminates the current row in an alignment.
        @param parser: the parser
        """
        alignment = parser.alignment
        if alignment is None:
            raise ValueError("misplaced \\crcr", parser.input.position())
        if alignment.row is None:
            # we just finished reading the preamble
            end = alignment.readNoAlign(parser)
            if end:
                # if the next token is a closing }, we end the alignment
                parser.endGroup(parser.input.position(), GROUP_TYPE.ALIGN)
                return
            alignment.newRow(parser)
        else:
            # check for a noalign AND the closing } for the alignment
            alignment.endOfCell(parser, command=self)


class Cr(CrCr):
    """
    A generic class for \\cr, \\cr, \\span, \\omit, \\noalign commands.
    """
    def execute(self, parser):
        # check if it is followed by a \crcr
        t = parser.token_expand()
        if t is not None and (not t.is_command or t.definition != crcr):
            parser.input.unread(t)
        super().execute(parser)


class Span(Command):
    """
    The \\span command.
    It is used to terminate a row in an alignment and start a new one.
    """
    def execute(self, parser):
        """
        Execute the command. It terminates the current row in an alignment and starts a new one.
        @param parser: the parser
        """
        alignment = parser.alignment
        if alignment is None:
            raise ValueError("misplaced \\span", parser.input.position())
        alignment.endOfCell(parser, command=self)


cr = Cr()
crcr = CrCr()
span = Span()
omit = Command()
noalign = Command()


class AlignmentBuilder:
    """
    A builder for an alignment.
    It is used to build an alignment from a list of tokens.
    @param enclosing: the enclosing list in the parser
    """
    def __init__(self, vertical: bool, to=None, spread=Dimen()):
        self.vertical = vertical
        # the alignment being built
        self.alignment = Alignment(to, spread)
        # the current row being built
        self.row = None
        # the current cell being built
        self.cell = None
        # the preamble for the alignment, whiich is a list of templates
        # each template is a tuple of two lists, the tokens to the left and right of the # token
        self.preamble = []
        # the tabskips for the alignment
        self.tabskips = []

    def readToken(self, parser, expand=False):
        """
        read a token and check if it terminates a cell
        @param parser: the parser
        @param expand: whether to expand the token
        @return the token and the terminator (or None for not terminating)

        the tokens that terminate a cell are: \\cr, \\crcr, &, and \\span
        """
        t = parser.token_expand() if expand else parser.token()
        if t is None:
            return t, t
        if t.catcode == CATCODE.ALIGNMENT_TAB:
            terminator = t
        elif not t.is_command:
            terminator = None
        elif t.definition is crcr:
            terminator = cr
        elif t.definition is cr:
            # is the next token a \crcr? \cr\crcr is the same
            t1 = parser.token()
            if t1 is not None and (not t1.is_command or t1.definition != crcr):
                parser.input.unread(t1)
            terminator = cr
        elif t.definition is span:
            terminator = span
        else:
            terminator = None
        if terminator is cr:
            every = parser.everycr.value
            if every:
                parser.input.push(lexer.TokenListScanner(every))
                if parser.tracingcommands > 0 and parser.checkRange():
                    parser.message(f"everycr: {parser.toksToString(every)}")
        return t, terminator
        
    def readTokens(self, parser):
        """
        read a list of tokens until a terminator is found
        @param parser: the parser
        @param is_template: whether the tokens are part of a template
        @return: a list of tokens (not including the terminator) and the terminator. 
        
        If  is_template is True, a \\tabskip is read, it is an attribute of the toks list.

        The terminator is one of \\cr, \\crcr, &, and one of # (if is_template is True) or \\span
        (if is_template is False)
        """
        toks = []
        tabskip = parser.builtin["\\tabskip"]
        # the scanner
        while True:
            t, terminator = self.readToken(parser)
            if terminator is None:
                if t.catcode == CATCODE.PARAMETER:
                    return toks, t
                # we need to check for \tabskip
                if t.is_command and t.definition == tabskip:
                    t.definition.execute(parser)
                    continue
                toks.append(t)
                continue
            if t is None:
                raise ValueError("expecting a \\cr", parser.input.position())
            if terminator.catcode == CATCODE.ALIGNMENT_TAB:
                return toks, terminator
            if terminator == span:
                # expand the next token
                t = parser.token_expand()
                if t is None:
                    raise ValueError("expecting a \\cr", parser.input.position())
                parser.input.unread(t)
                continue
            return toks, terminator
            
    def readHeader(self, parser):
        """
        read one cell in the templace row
        @param parser: the parser
        @return: the template, and whether the column ends
        The template is a tuple of two lists for the tokens before and after the #
        """
        left, terminator = self.readTokens(parser)
        if terminator.catcode == CATCODE.PARAMETER:
            right, terminator = self.readTokens(parser)
        else:
            right = []
        return (left, right), terminator
    
    def readNoAlign(self, parser):
        """
        Read a noalign and check if the next token is a closing }.
        @param parser: the parser
        @param scanner: an AlignScanner instance
        @return 
        """
        t = parser.skipSpaces()
        if t is None:
            raise ValueError("unexpected end of input in alignment", parser.input.position())
        if t.is_command and t.definition == noalign:
            list = vmode.VList(parser) if self.vertical else hmode.HList(parser, True)
            parser.readList(list, GROUP_TYPE.NO_ALIGN)
            if self.row is None:
                # we are in the preamble, so we just store the noalign list
                self.alignment.noalign = list
            else:
                # we are in a row, so we store the noalign list in the row
                self.row.noalign = list
            t = parser.skipSpaces()
        if t.catcode == CATCODE.END_GROUP:
            parser.endGroup(parser.input.position(), GROUP_TYPE.ALIGN)
            return True
        parser.input.unread(t)
        return False
    
    def newRow(self, parser):
        self.row = Row()
        self.alignment.rows.append(self.row)
        self.right = None
        self.cell = None
        self.newCell(parser, span=False)

    def finishCell(self, parser, command):
        parser.endGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        if command != span:
            parser.lists.pop()
            self.cell = None
        if command.catcode == CATCODE.ALIGNMENT_TAB:
            self.newCell(parser, span=False)
        elif command == span:
            self.newCell(parser, span=True)
#        assert token.definition == cr or token.definition == crcr
        elif not self.readNoAlign(parser):
            self.newRow(parser)
        return False

    def endOfCell(self, parser, command):
        """
        reading to the end of current cell.
        @param parser: the parser
        @param span: whether the next cell is a span cell
        @param row_end: whether the cell is at the end of a row

        The right bracket of the template is read, if present.
        """
        if self.cell is None:
            raise ValueError("no cell to end", parser.input.position())
        if self.right is not None and self.right:
            scanner = lexer.TokenListScanner(self.right)
            scanner.stop = lambda: self.finishCell(parser, command)
            parser.input.push(scanner)
            self.right = None
        else:
            self.finishCell(parser, command)

    def newCell(self, parser, span: bool):
        """
        Read a cell.
        @param parser: the parser
        @param span: whether the cell is a span cell
        @return: the cell and the terminator
        """
        n = len(self.row.cells)
        if n >= len(self.preamble):
            raise ValueError("too many columns in alignment", parser.input.position())
        if span:
            self.cell.span += 1
        else:
            cell = hmode.HList(parser, True) if self.vertical else vmode.VList(parser)
            cell.span = 0
            self.cell = cell
            self.row.cells.append(cell)
            parser.lists.append(cell)
        parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        # check for \omit, if present as the next token, then do not use template.
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting a \\cr", parser.input.position())
        self.omit = t.definition == omit
        if not self.omit:
            parser.input.unread(t)
            left, self.right = self.preamble[n]
            if left:
                parser.input.push(lexer.TokenListScanner(left))

    def begin(self, parser):
        """
        begin a new alignment
        """
        def callback():
            parser.finishAlignment()
        t = parser.token_expand()
        if t is None or t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a {", parser.input.position())
        self.alignment.tabskips = [parser.tabskip.value]
        parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN, callback)
        # read the preamble
        while True:
            header, terminator = self.readHeader(parser)
            self.preamble.append(header)
            self.alignment.tabskips.append(parser.tabskip.value)
            if terminator == cr or terminator == crcr:
                terminator.execute(parser)
                break


class HAlign(lists.ModeDependentCommand):
    """
    The \\halign command.
    """
    def vertical(self, parser, vlist):
        parser.newAlignment()
    
    def math(self, parser, mlist):
        if len(mlist) > 0 or mlist.inner:
            raise ValueError("improper \\halign inside math mode", parser.input.position())
        parser.newAlignment()


class VAlign(lists.ModeDependentCommand):
    """
    The \\valign command.
    """
    def horizontal(self, parser, hlist):
        parser.newAlignment()


mod = Module("align",
    commands = {
        "halign": HAlign(),
        "valign": VAlign(),
        "cr": cr,
        "crcr": crcr,
        "span": span,
        "omit": omit,
        "noalign": noalign,
    }
)
