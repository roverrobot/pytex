"""
This module implements the \\halign and \\valign commands
"""

from pytex import serialization
from pytex import lists
from pytex import node as nd
from pytex import box as bx
from pytex import hmode
from pytex import vmode
from pytex.token import Token, CATCODE, Command, CellEndType
from pytex import lexer
from pytex import glue
from pytex.state import GROUP_TYPE
from pytex.module import Module
from pytex.dimen import Dimen, NEG_MAX_DIMEN


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
        return {}, {
                "noalign": self.noalign,
                "cells": self.cells,
            }

    def __repr__(self):
        return f"Row({self.cells})"


class AlignmentBuildStack(list):
    def currentCell(self):
        if not self:
            return None
        row_state = self[-1].row_state
        if row_state is None:
            return None
        return row_state.current_cell


class CellBuildState:
    """
    Wrapper around the list holding a cell being built.
    This is pushed onto parser.lists so build-time state does not live on the list.

    @param node: the box node whose list holds the cell content
    @param column_no: the column number of the cell
    @param templates: remaining template parts to inject, in reverse push order
    """
    def __init__(self, cell_box, column_no, templates):
        self.node = cell_box
        self.node.span = 1
        self.column_no = column_no
        self.templates = templates

    def pushTemplate(self, parser):
        if self.templates:
            template = self.templates.pop()
            if template:
                parser.input.pushTokenList(template)

    def close(self, parser):
        self.node.typeset(parser)
        parser.endGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        parser.lists.pop()
        return self.node


class RowBuildState:
    """
    Runtime-only row parsing state.
    Keeps parser details (alignment/preamble) off Row.
    """
    def __init__(self, alignment, builder):
        self.row = None
        self.alignment = alignment
        self.preamble = builder.preamble
        self.builder = builder
        self.current_cell = None

    def newCell(self, parser, column_no, span:bool=False):
        cell = self.alignment.newBox(parser)
        preamble = self.preamble
        t = parser.skipSpaces()
        if t is None:
            raise ValueError("expecting \\cr", parser.input.position())
        if getattr(t, "definition", None) is omit:
            templates = []
        else:
            parser.input.unread(t)
            if column_no >= len(preamble):
                if not self.builder.repeat_start:
                    raise ValueError("extra alignment tab", parser.input.position())
                column_no %= len(preamble)
            column = preamble[column_no]
            templates = [column.v, column.u]
        if span:
            self.current_cell.node.span += 1
        else:
            self.current_cell = CellBuildState(cell, column_no, templates)
            if cell.node_type == nd.NODE_TYPE.HLIST:
                state = hmode.HList(parser, cell.list, inner=True, raw=cell.raw)
            else:
                state = vmode.VList(parser, cell.list, inner=True)
            parser.lists.append(state)
            parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        self.current_cell.pushTemplate(parser)

    def startNextRow(self, parser):
        self.row = Row()
        self.alignment.rows.append(self.row)
        self.current_cell = None
        self.newCell(parser, 0)

    def readNoAlign(self, parser, owner):
        if owner.noalign is None:
            owner.noalign = parser.readVList(
                GROUP_TYPE.NO_ALIGN,
                lambda parser: self.finishRow(parser),
            )
            return
        parser.clearParagraphSettings()
        state = vmode.VList(parser, owner.noalign, add_interline=False)
        parser.readList(
            state,
            GROUP_TYPE.NO_ALIGN,
            lambda parser: self.finishRow(parser),
        )

    def finishRow(self, parser):
        while True:
            t = parser.skipSpaces()
            if t is None:
                raise ValueError("expecting }", parser.input.position())
            meaning = parser.token_meaning(t)
            command = getattr(meaning, "definition", None)
            if command == noalign:
                noalign_owner = self.alignment if len(self.alignment.rows) == 0 else self.alignment.rows[-1]
                self.readNoAlign(parser, noalign_owner)
                return
            if command != crcr:
                parser.input.unread(t)
                if meaning.catcode != CATCODE.END_GROUP:
                    self.startNextRow(parser)
                return


class Alignment(nd.Node):
    """
    An alignment node.
    """
    def __init__(self, to=None, spread=Dimen()):
        self.rows = []
        # the first noalign before the first row
        self.noalign = None
        self.tabskips = []
        self.to = None if to is None else Dimen(to)
        self.spread = None if spread is None else Dimen(spread)
        self.initial_prevdepth = vmode.init_prevdepth

    node_type = nd.NODE_TYPE.ALIGNMENT
    box_materializable = True

    def saveInfo(self):
        return {
                "to": self.to,
                "spread": self.spread,
            }, {
                "rows": self.rows,
                "noalign": self.noalign,
                "tabskips": self.tabskips,
            },
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.rows})"
    
    def newBox(self, parser):
        raise NotImplementedError

    def _collectEntries(self, parser):
        # TeXBook notation is 1-based; this implementation uses the same names
        # with 0-based indices. Thus `w[j]` is TeX's w_{j+1}, and `t[k+1]` is
        # the glue between columns k and k+1.
        rows = []
        n_raw = 0
        for row in self.rows:
            entries = []
            i = 0
            column = 0
            for cell in row.cells:
                start = column
                cells = []
                column += cell.span
                entry = {
                    "start": start,
                    "span": cell.span,
                    "cell": cell,
                    "measure": self.entryMeasure(cell),
                }
                entries.append(entry)
                i += 1
            if column > n_raw:
                n_raw = column
            rows.append((row, entries))
        if n_raw == 0:
            return rows, [], list(self.tabskips[:1])
        for _, entries in rows:
            entries[-1]["span"] = n_raw - entries[-1]["start"]
        merge = self._mergeColumns(rows, n_raw)
        column_map = []
        j = -1
        for raw_j in range(n_raw):
            if raw_j == 0 or not merge[raw_j - 1]:
                j += 1
            column_map.append(j)
        n = j + 1
        t = [self._tabskip(0)]
        for k, merged in enumerate(merge):
            if not merged:
                t.append(self._tabskip(k + 1))
        t.append(self._tabskip(n_raw))
        reduced_rows = []
        for row, entries in rows:
            mapped = []
            for entry in entries:
                i = column_map[entry["start"]]
                j = column_map[entry["start"] + entry["span"] - 1]
                inner_t = []
                raw_i = entry["start"]
                raw_j = entry["start"] + entry["span"] - 1
                for raw_k in range(raw_i, raw_j):
                    if merge[raw_k]:
                        continue
                    inner_t.append(t[column_map[raw_k + 1]])
                mapped.append(entry | {"start": i, "span": j - i + 1, "inner_t": inner_t})
            reduced_rows.append((row, mapped))
        w_ij = [[] for _ in range(n)]
        for _, entries in reduced_rows:
            for entry in entries:
                i = entry["start"]
                j = i + entry["span"] - 1
                w_ij[j].append((i, Dimen(entry["measure"])))
        w = []
        for j in range(n):
            w_j = None
            for i, wij in w_ij[j]:
                candidate = Dimen(wij)
                for k in range(i, j):
                    candidate -= w[k] + t[k + 1].dimen
                if w_j is None or candidate > w_j:
                    w_j = candidate
            if w_j is None:
                raise ValueError("alignment column has no usable entry", parser.input.position())
            w.append(w_j)
        return reduced_rows, w, t

    def _tabskip(self, index):
        if index < len(self.tabskips):
            return self.tabskips[index]
        return glue.Glue()

    def _mergeColumns(self, rows, raw_columns):
        merge_after = [False] * max(0, raw_columns - 1)
        for boundary in range(raw_columns - 1):
            seen = False
            merged = True
            for _, entries in rows:
                left = False
                right = False
                spanned = False
                for entry in entries:
                    start = entry["start"]
                    end = start + entry["span"]
                    if start <= boundary < end:
                        left = True
                    if start <= boundary + 1 < end:
                        right = True
                    if start <= boundary < end - 1:
                        spanned = True
                if not (left or right):
                    continue
                seen = True
                if not spanned:
                    merged = False
                    break
            merge_after[boundary] = seen and merged
        return merge_after

    def _glueSet(self, total, delta):
        if delta > 0 and total.stretch.factor != 0:
            return delta / total.stretch.factor, total.stretch.order, True
        if delta < 0 and total.shrink.factor != 0:
            return delta / total.shrink.factor, total.shrink.order, False
        return Dimen(), None, delta > 0

    def _spanTarget(self, w, t, i, j):
        target = Dimen()
        for k in range(i, j + 1):
            target += w[k]
        for k in range(i + 1, j + 1):
            target += t[k].dimen
        return target

    def entryMeasure(self, cells):
        raise NotImplementedError

    def entryBox(self, parser):
        raise NotImplementedError

    def reboxEntry(self, parser, box, target):
        raise NotImplementedError


class HAlignment(Alignment):
    """
    A \\halign node. It expands immediately into explicit vertical material.
    The surrounding vlist supplies the outer first-row interline when this node
    is expanded.
    """

    def __init__(self, to=None, spread=Dimen()):
        super().__init__(to, spread)

    def newBox(self, parser):
        return bx.HBox(parser, None, 0)

    def entryMeasure(self, cell):
        return cell.width

    def entryBox(self, parser):
        return bx.HBox(parser, None, 0)

    def reboxEntry(self, parser, box, target):
        target = Dimen(target)
        box = box.typeset(parser)
        if box.width == target:
            return box
        out = bx.HBox(parser, target, None)
        out.list[:] = box.list
        out.source = box.source
        return out.typeset(parser)

    def _emptyEntry(self, parser, width):
        box = bx.HBox(parser, width, None)
        return box.typeset(parser)
            

class VAlignment(Alignment):
    """
    A \\valign node. It behaves like an hbox with respect to surrounding layout.
    """
    def newBox(self, parser):
        return bx.VBox(parser, None, 0)

    def entryMeasure(self, cell):
        return cell.height + cell.depth

    def entryBox(self, parser):
        return bx.VBox(parser, None, 0)

    def reboxEntry(self, parser, box, target):
        target = Dimen(target)
        if box.height + box.depth == target:
            return box
        out = bx.VBox(parser, target, None)
        vss = glue.Glue(0, glue.Stretchness(1, 1), glue.Stretchness(1, 1))
        out.list.append(nd.Glue(vss, None))
        out.list.append(box)
        out.list.append(nd.Glue(vss, None))
        return out.typeset(parser)

    def typeset(self, parser, packed):
        return parser.typeset.align.typesetVAlignment(self, packed)


class EndCellToken(Token):
    def __init__(self, type: CellBuildState):
        super().__init__("\\endcell", None)
        self.type = type

    def execute(self, parser):
        top = parser.lists[-1]
        if top.type == lists.LISTTYPE.HORIZONTAL and not top.inner:
            parser.endParagraph()
        row: RowBuildState = parser.alignments[-1].row_state
        if self.type != CellEndType.SPAN:
            row.row.cells.append(row.current_cell.close(parser))
            row.current_cell = None
        if self.type != CellEndType.CR:
            row.newCell(parser, len(row.row.cells), self.type == CellEndType.SPAN)
        else:
            everycr = parser.everycr.value
            if everycr:
                parser.input.pushTokenList(list(everycr))
            row.finishRow(parser)


def endCell(parser, type: CellEndType):
    cell = parser.alignments.currentCell()
    if cell is None:
        raise ValueError(f"unexpected {parser.current_token.name}", parser.input.position())
    parser.input.pushTokenList([EndCellToken(type)])
    cell.pushTemplate(parser)


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
        alignments = parser.alignments
        if not alignments:
            raise ValueError("unexpected \\cr", parser.input.position())
        builder: AlignmentBuilder = alignments[-1]
        if builder.row_state is not None:
            endCell(parser, CellEndType.CR)
        else:
            parser.endGroup(parser.input.position(), GROUP_TYPE.ALIGN)
            builder.row_state = RowBuildState(builder.alignment, builder)
            everycr = parser.everycr.value
            if everycr:
                parser.input.pushTokenList(list(everycr))
            builder.row_state.finishRow(parser)
        

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
        cell = parser.alignments.currentCell()
        if cell is None:
            raise ValueError("unexpected \\span", parser.input.position())
        endCell(parser, CellEndType.SPAN)


class Omit(Command):
    """
    The \\Omit command.
    It is used to terminate a row in an alignment and start a new one.
    """
    def execute(self, parser):
        """
        Switch the current entry to omit mode.
        @param parser: the parser
        """
        cell = parser.alignments.currentCell()
        if cell is None:
            raise ValueError("misplaced \\omit", parser.input.position())
        # Entry-leading \omit is handled in newCell() before template injection.
        # If \omit appears later in the entry, keep behavior permissive and do not
        # raise, but do not rewrite template state mid-cell.
        return
    

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


cr = CrCr()
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
    def __init__(self, builder, target):
        self.builder = builder
        self.target = target

    def __call__(self, parser):
        if parser.alignments.currentCell() is not None:
            raise ValueError("expecting \\cr", parser.input.position())
        top = parser.lists[-1]
        alignment = self.builder.alignment
        if top.type == lists.LISTTYPE.MATH:
            top.pending_alignment = alignment
            top.isalign = True
        elif isinstance(self.target, vmode.VList) and isinstance(alignment, HAlignment):
            self.target.appendHAlignment(alignment)
        elif isinstance(self.target, hmode.HList) and isinstance(alignment, VAlignment):
            self.target.appendVAlignment(alignment)
        else:
            self.target.append(alignment)
        if parser.alignments and parser.alignments[-1] is self.builder:
            parser.alignments.pop()


class AlignmentBuilder:
    """
    A builder for an alignment.
    It is used to build an alignment from a list of tokens.
    @param enclosing: the enclosing list in the parser
    """
    def __init__(self, alignment):
        self.alignment = alignment
        # the current row being built
        self.row_state = None
        # the preamble for the alignment, whiich is a list of templates
        # each template is a tuple of two lists, the tokens to the left and right of the # token
        self.preamble = []
        self.repeat_start = False
        
    def readPreamble(self, parser):
        """
        read the preamble
        @param parser: the parser
        @return: a list of tokens (not including the terminator) and the terminator. 
        
        a \\tabskip is read, it is an attribute of the toks list.

        The terminator is one of \\cr, \\crcr, 
        """
        # we first remember the current \tabskip settings        
        self.alignment.tabskips.append(parser.parameters["tabskip"])
        tabskip = parser.builtin["\\tabskip"]
        # Build the preamble. We start a new group, which will be terminated by \cr or \crcr
        parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        while True:
            template = [] # the tokans in the column template
            # we collect all the columns in the outer loop
            # the leading spaces in a column are ignored
            # TeX does not ordinarily expand preamble tokens while scanning an
            # alignment template. The special case is \span: it causes the next
            # token to be expanded, which is needed for LaTeX-style preambles
            # such as \span\align@preamble and placeholder macros like \@sharp.
            t = parser.skipSpacesNoExpand()
            t = parser.token_meaning(t)
            # now T is the first meaningful token in a column.
            # in the following loop, we collect the tokens in a column
            while True:
                if getattr(t, "definition", None) is span:
                    t = parser.token_expand()
                    t = parser.token_meaning(t)
                if t is None:
                    raise ValueError("expecting a \\cr", parser.input.position())
                if t.catcode == CATCODE.BEGIN_GROUP:
                    group, end = parser.readTo(CATCODE.END_GROUP, [t])
                    group.append(end)
                    template.extend(group)
                elif t.catcode == CATCODE.ALIGNMENT_TAB:
                    # end of column, but no crcr
                    t = None
                    break
                elif t.definition is tabskip or t.name == "\\tabskip":
                    t.definition.execute(parser)
                elif t.definition is cr or t.definition is crcr or t.name == "\\cr" or t.name == "\\crcr":
                    break
                else:
                    template.append(t)
                t = parser.token()
                t = parser.token_meaning(t)
            # now a column is read in template. We look for the # token
            if not template and not self.preamble and t is None:
                # A leading & does not introduce a real column. It means the
                # preamble templates are to be reused cyclically.
                self.repeat_start = True
                continue
            template = [parser.token_meaning(x) for x in template]
            catcodes = [x.catcode for x in template]
            try:
                i = catcodes.index(CATCODE.PARAMETER)
            except ValueError:
                raise ValueError("expecting a #", parser.input.position())
            if CATCODE.PARAMETER in catcodes[i+1:]:
                raise ValueError("multiple # tokens", parser.input.position())
            column = Column()
            column.u = template[:i]
            column.v = template[i+1:]
            self.preamble.append(column)
            # we shoudl set the tabskip too
            self.alignment.tabskips.append(parser.parameters["tabskip"])
            if t is not None: # t must be \cr or \crcr
                t.definition.execute(parser)
                break


    def run(self, parser, target):
        """
        begin a new alignment
        """
        # start a new group
        parser.skipFiller()
        t = parser.token_expand()
        if t is None or not t.isTokenExpand(CATCODE.BEGIN_GROUP):
            raise ValueError("expecting a {", parser.input.position())
        parser.alignments.append(self)
        parser.beginGroup(
            parser.input.position(),
            GROUP_TYPE.ALIGN,
            to_end=AlignmentEndCallback(self, target),
        )
        self.readPreamble(parser)


class MAlignment(nd.Node):
    node_type = nd.NODE_TYPE.ALIGNMENT

    def __init__(
        self,
        source,
        list=None,
        predisplaypenalty=0,
        abovedisplayskip=None,
        postdisplaypenalty=0,
        belowdisplayskip=None,
    ):
        self.source = source
        self.list = [] if list is None else list
        self.predisplaypenalty = predisplaypenalty
        self.abovedisplayskip = glue.Glue() if abovedisplayskip is None else abovedisplayskip
        self.postdisplaypenalty = postdisplaypenalty
        self.belowdisplayskip = glue.Glue() if belowdisplayskip is None else belowdisplayskip

    def saveInfo(self):
        return {
            "source": self.source,
            "list": self.list,
            "predisplaypenalty": self.predisplaypenalty,
            "abovedisplayskip": self.abovedisplayskip,
            "postdisplaypenalty": self.postdisplaypenalty,
            "belowdisplayskip": self.belowdisplayskip,
        }, None
            

class Align(lists.ModeDependentCommand):
    """
    The \\halign command.
    """
    def newAlignment(self, parser, list, cls):
        spec, d = parser.readBoxSpec()
        alignment = cls(d, None) if spec == "to" else cls(None, d)
        AlignmentBuilder(alignment).run(parser, list)


class HAlign(Align):
    def vertical(self, parser, vlist):
        self.newAlignment(parser, vlist, HAlignment)
    
    def math(self, parser, mlist):
        if mlist.inner or len(mlist) > 0:
            raise ValueError("improper \\halign inside math mode", parser.input.position())
        self.newAlignment(parser, mlist, HAlignment)


class VAlign(Align):
    """
    The \\valign command.
    """
    def horizontal(self, parser, hlist):
        self.newAlignment(parser, hlist, VAlignment)


def init(parser):
    # initialize the alignments stack
    parser.alignments = AlignmentBuildStack()


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
    },
    init=init,
)
