"""
This module implements the \\halign and \\valign commands
"""

from pytex import serialization
from pytex import lists
from pytex import node as nd
from pytex import box as bx
from pytex import hmode
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
        # a list of restricted boxes, one for each cell.
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


class RowBuildState:
    """
    Runtime-only row parsing state.
    Keeps parser details (alignment/preamble template) off Row.
    """
    def __init__(self, row, alignment, template):
        self.row = row
        self.alignment = alignment
        self.template = template


class Alignment(nd.Node):
    """
    An alignment node.
    """
    def __init__(self, to=None, spread=Dimen(), vertical=True):
        self.rows = []
        # the first noalign before the first row
        self.noalign = None
        self.vertical = vertical
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
    
    def newBox(self, parser):
        if self.vertical:
            return bx.HBox(parser, None, 0)
        return bx.VBox(parser, None, 0)


def _readNoAlign(parser, owner, alignment, row_state, column_no):
    owner.noalign = parser.readVList(
        GROUP_TYPE.NO_ALIGN,
        lambda: newCell(parser, row_state, column_no),
    )


def newCell(parser, row_state, column_no):
    alignment = row_state.alignment
    row = row_state.row
    # read in all the tokens up to the end of the cell
    toks = []
    has_omit = False
    t = parser.skipSpaces(True)
    if t is None:
        raise ValueError("expecting \\cr", parser.input.position())
    if getattr(t, "definition", None) is omit:
        has_omit = True
        t = parser.token_expand()
    while True:
        if t is None:
            raise ValueError("expecting \\cr", parser.input.position())
        if t.catcode == CATCODE.END_GROUP:
            if column_no != 0 or toks:
                raise ValueError("expecting \\cr", parser.input.position())
            # We may have started a fresh row (e.g. after \\cr\\noalign{...})
            # but reached the alignment-closing `}` before any cell content.
            # Drop that empty row frame from the alignment rows.
            if not row.cells and alignment.rows and alignment.rows[-1] is row:
                alignment.rows.pop()
            parser.input.unread(t)
            return
        if t.catcode == CATCODE.ALIGNMENT_TAB or t.definition is span or t.definition is cr or t.definition is crcr:
            parser.input.unread(t)
            break
        toks.append(t)
        t = parser.token_expand()
    # start a new cell
    cell = alignment.newBox(parser)
    cell.list.row = row_state
    cell.list.column_no = column_no
    row.cells.append(cell)
    parser.lists.append(cell.list)
    # start the group fo the cell
    parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN)
    if has_omit:
        parser.input.push(lexer.TokenListScanner(toks))
        return
    column: Column = row_state.template[column_no]
    parser.input.push(lexer.TokenListScanner(column.u))
    parser.input.push(lexer.TokenListScanner(toks))
    parser.input.push(lexer.TokenListScanner(column.v))


def endCell(parser, is_last):
    parser.endGroup(parser.input.position(), GROUP_TYPE.ALIGN)
    cell = parser.lists.pop()
    row_state = cell.row
    alignment = row_state.alignment
    if is_last:
        return row_state
    newCell(parser, row_state, cell.column_no + 1)
    return row_state


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
        # end the cell
        row_state = endCell(parser, is_last=True)
        template = row_state.template
        alignment = row_state.alignment
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting }", parser.input.position())
        if t.catcode == CATCODE.END_GROUP:
            parser.input.unread(t)
            return
        command = getattr(t, "definition", None)
        if command != noalign:
            parser.input.unread(t)
        noalign_owner = alignment if len(alignment.rows) == 0 else alignment.rows[-1]
        # start a new line
        row = Row()
        alignment.rows.append(row)
        row_state = RowBuildState(row, alignment, template)
        # check for noalign
        if command == noalign:
            _readNoAlign(parser, noalign_owner, alignment, row_state, 0)
        else:
            # build the first cell
            newCell(parser, row_state, 0)


class Cr(CrCr):
    """
    the \\cr command
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
        parser.lists[-1].span = True
        endCell(parser, is_last=False)


class Omit(Command):
    """
    The \\Omit command.
    It is used to terminate a row in an alignment and start a new one.
    """
    def execute(self, parser):
        """
        Execute the command. It terminates the current row in an alignment and starts a new one.
        @param parser: the parser
        """
        raise ValueError("misplaced \\omit", parser.input.position())
    

class NoAlign(Command):
    """
    The \\noalign.
    It is used to terminate a row in an alignment and start a new one.
    """
    def execute(self, parser):
        """
        Execute the command. It terminates the current row in an alignment and starts a new one.
        @param parser: the parser
        """
        raise ValueError("unexpected \\noalign", parser.input.position())


cr = Cr()
crcr = CrCr()
span = Span()
noalign = NoAlign()
omit = Omit()


class Column:
    """
    The column definition
    """
    def __init__(self):
        self.u = []
        self.v = []


class AlignmentEndCallback:
    def __init__(self, parser):
        self.parser = parser

    def __call__(self):
        # are we still handling cells?
        top = self.parser.lists[-1]
        if getattr(top, "row", None) is not None:
            raise ValueError("expecting \\cr", self.parser.input.position())


class AlignmentBuilder:
    """
    A builder for an alignment.
    It is used to build an alignment from a list of tokens.
    @param enclosing: the enclosing list in the parser
    """
    def __init__(self, alignment):
        self.alignment = alignment
        # the current row being built
        self.row = None
        # the current cell being built
        self.cell = None
        # the preamble for the alignment, whiich is a list of templates
        # each template is a tuple of two lists, the tokens to the left and right of the # token
        self.preamble = None
        
    def readPreamble(self, parser):
        """
        read the preamble
        @param parser: the parser
        @return: a list of tokens (not including the terminator) and the terminator. 
        
        a \\tabskip is read, it is an attribute of the toks list.

        The terminator is one of \\cr, \\crcr, 
        """
        # we start a new group, which will be terminated by \cr or \crcr
        column = Column()
        self.preamble = [column]
        self.alignment.tabskips.append(parser.state.parameters["tabskip"])
        # the template of a column looks like u # v
        current = column.u
        tabskip = parser.builtin["\\tabskip"]
        # the scanner
        # Build the preamble against a synthetic row that seeds the first real row.
        row = Row()
        row_state = RowBuildState(row, self.alignment, self.preamble)
        cell = self.alignment.newBox(parser)
        cell.list.row = row_state
        cell.list.column_no = 0
        row.cells.append(cell)
        parser.lists.append(cell.list)
        parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        t = parser.skipSpaces(False)
        if t is None:
            raise ValueError("expecting a \\cr", parser.input.position())
        parser.input.unread(t)
        while True:
            t = parser.token()
            if t and t.definition == span:
                t = parser.token_expand()
            if t is None:
                raise ValueError("expecting a \\cr", parser.input.position())
            # \span
            if t.catcode == CATCODE.PARAMETER:
                if current is column.u:
                    current = column.v
                else:
                    raise ValueError("displaced #", parser.input.position())
                continue
            if t.catcode == CATCODE.ALIGNMENT_TAB:
                column = Column()
                self.preamble.append(column)
                self.alignment.tabskips.append(parser.state.parameters["tabskip"])
                current = column.u
                t = parser.skipSpaces(False)
                if t is None:
                    raise ValueError("expecting a \\cr", parser.input.position())
                parser.input.unread(t)
                continue
            if t.definition is tabskip:
                t.definition.execute(parser)
            elif t.definition is cr or t.definition is crcr:
                self.alignment.tabskips.append(parser.state.parameters["tabskip"])
                t.definition.execute(parser)
                break
            else:
                current.append(t)

    def run(self, parser):
        """
        begin a new alignment
        """
        # start a new group
        parser.skipFiller()
        t = parser.token_expand()
        if t is None or t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a {", parser.input.position())
        parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN, AlignmentEndCallback(parser))
        self.readPreamble(parser)


def _newAlignment(parser, list, vertical):
    to, spread = parser.readToSpread()
    alignment = Alignment(to, spread, vertical)
    list.append(alignment)
    AlignmentBuilder(alignment).run(parser)


class HAlign(lists.ModeDependentCommand):
    """
    The \\halign command.
    """
    def vertical(self, parser, vlist):
        _newAlignment(parser, vlist, True)
    
    def math(self, parser, mlist):
        if len(mlist) > 0 or mlist.inner:
            raise ValueError("improper \\halign inside math mode", parser.input.position())
        _newAlignment(parser, mlist, True)


class VAlign(lists.ModeDependentCommand):
    """
    The \\valign command.
    """
    def horizontal(self, parser, hlist):
        _newAlignment(parser, hlist, False)


mod = Module("align",
    commands = {
        "halign": HAlign(),
        "valign": VAlign(),
        "cr": cr,
        "crcr": crcr,
        "span": span,
        "omit": omit,
        "noalign": noalign,
    },
    attributes={
        "endCell": endCell,
    }
)
