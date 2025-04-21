"""
This module implements the \\halign and \\valign commands
"""

from pytex import serialization
from pytex import lists
from pytex import node as nd
from pytex import box as bx
from pytex import token
from pytex import lexer
from pytex import glue
from pytex import accessor
from pytex.state import GROUP_TYPE
from pytex.module import Module


class Row(serialization.Serializable):
    """
    A row in an alignment.

    In vertical alignment, this is a column.
    """
    def __init__(self, parser):
        # the noalign vertical list
        self.noalign = None
        # a list of tabskips
        self.tabskips = None
        # a list of restricted hlists
        self.cells = []

    def saveInfo(self):
        return {
            "extra": {
                "noalign": self.noalign,
                "tabskips": self.tabskips,
                "cells": self.cells,
            },
        }

    def __repr__(self):
        return f"Row({self.cells})"


class Alignment(nd.WhatsIt):
    """
    An alignment node.
    """
    def __init__(self):
        self.rows = []
        # the first noalign before the first row
        self.noalign = None

    def saveInfo(self):
        return {
            "extra": {
                "rows": self.rows,
                "noalign": self.noalign,
            },
        }
    
    def __repr__(self):
        return f"Alignment({self.rows})"


class Cr(token.Command):
    """
    A \\cr command.
    """
    def execute(self, parser):
        raise ValueError("\\cr not in alignment")


class CrCr(token.Command):
    """
    A \\cr command.
    """
    def execute(self, parser):
        raise ValueError("\\crcr not in alignment")


class Span(token.Command):
    """
    A span command.
    """
    def execute(self, parser):
        raise ValueError("\\span not in alignment")


class Omit(token.Command):
    """
    A span command.
    """
    def execute(self, parser):
        raise ValueError("\\omit not in alignment")


class NoAlign(token.Command):
    """
    A \\noalign command.
    """
    def execute(self, parser):
        raise ValueError("\\noalign not in alignment")


class TabSkip(glue.GlueAccessor):
    """
    the \\tabskip command.
    """
    def __init__(self):
        super().__init__("parameters", "tabskip")


cr = Cr()
crcr = CrCr()
span = Span()
omit = Omit()
noalign = NoAlign()
tabskip = TabSkip()


class AlignCommand(lists.ModeDependentCommand):
    """
    An alignment command.
    @param vert: whether the alignment is a vertical command

    \\halign is vertical, \\valign is horizontal
    """
    def __init__(self, vert: bool):
        self.vert = vert

    def readToken(self, parser, expand=False):
        """
        read a token and check if it terminates a cell
        @param parser: the parser
        @param expand: whether to expand the token
        @return the token and the terminator (or None for not terminating)

        the tokens that terminate a cell are: \\cr, \\crcr, &, and \\span
        """
        t = parser.token_expand() if expand else parser.token()
        if t is None or t.catcode == token.CATCODE.ALIGNMENT_TAB:
            return t, t
        if t.is_command:
            if t.definition == crcr:
                t.definition = cr
                return t, cr
            if t.definition == cr:
                # is the next token a \crcr? \cr\crcr is the same
                t1 = parser.token()
                if t1 is not None:
                    if t1.is_command and t1.definition == crcr:
                        return t, cr
                    parser.input.unread(t1)
                return t, cr
            if t.definition == span:
                return t, span
        return t, None
    
    def readTokens(self, parser, is_template: bool):
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
        # the scanner
        while True:
            t, terminator = self.readToken(parser)
            if terminator is None:
                if t.catcode == token.CATCODE.PARAMETER:
                    if not is_template:
                        raise ValueError("misplaced #", parser.input.position())
                    return toks, t
                if t.is_command and is_template:
                    # we need to check for \tabskip
                    if t.definition == tabskip:
                        tabskip.execute(parser)
                        continue
                toks.append(t)
                continue
            if t is None:
                raise ValueError("expecting a \\cr", parser.input.position())
            if terminator.catcode == token.CATCODE.ALIGNMENT_TAB:
                return toks, terminator
            if terminator == span:
                if is_template:
                    raise ValueError("\\span in template", parser.input.position())
                # expand the next token
                t = parser.token_expand()
                if t is None:
                    raise ValueError("expecting a \\cr", parser.input.position())
                parser.input.unread(t)
            return toks, terminator
    
    def readHeader(self, parser):
        """
        read one cell in the templace row
        @param parser: the parser
        @return: the template, and whether the row ends
        The template is a tuple of two lists for the tokens before and after the #
        """
        left, terminator = self.readTokens(parser, is_template = True)
        if terminator.catcode == token.CATCODE.PARAMETER:
            right, terminator = self.readTokens(parser, is_template = True)
        else:
            right = []
        end = terminator.catcode != token.CATCODE.ALIGNMENT_TAB
        return (left, right), end

    def readTemplate(self, parser):
        """
        Read the template.
        @param parser: the parser
        @return: the column templates and the tabskips
        """
        columns = []
        end = False
        tabskips = [parser.state.parameters["tabskip"]]
        columns = []
        while not end:
            header, end = self.readHeader(parser)
            tabskips.append(parser.state.parameters["tabskip"])
            columns.append(header)
        return columns, tabskips

    def readCell(self, parser, header):
        """
        Read a cell.
        @param parser: the parser
        @param header: the template for the cell (a tuple of two lists representing the tokens
        before and after the #)
        @return: the cell and the terminator
        """
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting a \\cr", parser.input.position())
        read_template = t.definition != omit
        if read_template:
            parser.input.unread(t)
            left, right = header
            parser.input.push(lexer.TokenListScanner(left))
        cell = parser.newHList() if self.vert else parser.newVList()
        parser.lists.append(cell)
        parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        terminator = None
        while terminator is None:
            t, terminator = self.readToken(parser, expand=True)
            if t is None:
                raise ValueError("expecting a \\cr", parser.input.position())
            if terminator is None:
                t.execute(parser)
        if read_template:
            scanner = lexer.TokenListScanner(right)
            scanner.terminate = True
            parser.input.push(scanner)
            while True:
                t = parser.token_expand()
                if t is None:
                    break
                t.execute(parser)
            parser.input.pop(scanner)
        parser.endGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        assert parser.lists[-1] == cell
        cell.span = terminator == span
        return parser.lists.pop(), terminator

    def readNoAlign(self, parser):
        """
        Read a noalign.
        @param parser: the parser
        @param scanner: an AlignScanner instance
        """
        t = parser.skipSpaces()
        if t is None:
            return None
        if t.is_command and t.definition == noalign:
            list = parser.newVList() if self.vert else parser.newHList()
            parser.readList(list, GROUP_TYPE.NO_ALIGN)
            return list
        parser.input.unread(t)
        return None

    def readRow(self, parser, template):
        """
        Read a row.
        @param parser: the parser
        @param template: the template for the row
        """
        columns, tabskips = template
        row = Row(parser)
        row.tabskips = tabskips
        for header in columns:
            cell, terminator = self.readCell(parser, header)
            if cell:
                row.cells.append(cell)
            if terminator == cr:
                return row
        raise ValueError("expecting a \\cr", parser.input.position())

    def readValue(self, parser):
        material = parser.readGeneralText(expand = False)
        parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        scanner = lexer.TokenListScanner(material)
        scanner.terminate = True
        parser.input.push(scanner)
        template = self.readTemplate(parser)
        node = Alignment()
        node.noalign = self.readNoAlign(parser)
        while True:
            t = parser.token_expand()
            if t is None:
                break
            parser.input.unread(t)
            row = self.readRow(parser, template)
            row.noalign = self.readNoAlign(parser)
            node.rows.append(row)
        parser.input.pop(scanner)
        parser.endGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        return node


class HAlign(AlignCommand, lists.ModeDependentCommand):
    """
    The \\halign command.
    """
    def __init__(self):
        super().__init__(True)

    def vertical(self, parser, vlist):
        vlist.append(self.readValue(parser))
    
    def math(self, parser, mlist):
        if len(mlist) > 0 or mlist.inner:
            raise ValueError("improper \\halign inside math mode", parser.input.position())
        mlist.append(self.readValue(parser))
        while True:
            t = parser.token_expand()
            if t is None:
                raise ValueError("expecting $$", parser.input.position())
            if t.catcode == token.CATCODE.MATH_SHIFT:
                parser.input.unread(t)
                break
            c = t.definition
            if not isinstance(c, accessor.Prefix):
                try:
                    c = c.getItemAccess(parser, None)
                except AttributeError:
                    raise ValueError("expecting $$", parser.input.position())
            c.execute(parser)


class VAlign(AlignCommand, lists.ModeDependentCommand):
    """
    The \\valign command.
    """
    def __init__(self):
        super().__init__(False)

    def horizontal(self, parser, hlist):
        hlist.append(self.readValue(parser))


mod = Module("align",
    commands = {
        "halign": HAlign(),
        "valign": VAlign(),
        "cr": cr,
        "crcr": crcr,
        "span": span,
        "omit": omit,
        "noalign": noalign,
        "tabskip": tabskip
    }
)
