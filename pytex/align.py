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


class AlignmentBuildStack(list):
    def currentCell(self):
        if not self:
            return None
        row_state = self[-1].current_row_state
        if row_state is None:
            return None
        return row_state.current_cell


class CellBuildState:
    """
    Wrapper around the list holding a cell being built.
    This is pushed onto parser.lists so build-time state does not live on the list.

    @param cell: the list holding the cell content
    @param column_no: the column number of the cell
    @param row_build_state: the build state of the row this cell is in
    @param templates: remaining template parts to inject, in reverse push order
    """
    def __init__(self, cell, column_no, row_build_state, templates):
        object.__setattr__(self, "cell", cell)
        object.__setattr__(self, "column_no", column_no)
        object.__setattr__(self, "row_build_state", row_build_state)
        object.__setattr__(self, "templates", templates)

    def __getattr__(self, name):
        return getattr(self.cell, name)

    def __setattr__(self, name, value):
        setattr(self.cell, name, value)

    def __getitem__(self, index):
        return self.cell[index]

    def __setitem__(self, index, value):
        self.cell[index] = value

    def __delitem__(self, key):
        del self.cell[key]

    def __len__(self):
        return len(self.cell)

    def __iter__(self):
        return iter(self.cell)

    def pushTemplate(self, parser):
        if self.templates:
            template = self.templates.pop()
            if template:
                parser.input.push(lexer.TokenListScanner(template))

    def close(self, parser):
        while parser.lists[-1] is not self:
            top = parser.lists[-1]
            if top.type == lists.LISTTYPE.HORIZONTAL and not top.inner:
                parser.endParagraph()
                continue
            break
        parser.endGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        parser.lists.pop()
        self.row_build_state.current_cell = None


class RowBuildState:
    """
    Runtime-only row parsing state.
    Keeps parser details (alignment/preamble template) off Row.
    """
    def __init__(self, row, alignment, template, builder):
        self.row = row
        self.alignment = alignment
        self.template = template
        self.builder = builder
        self.current_cell = None

    def newCell(self, parser, column_no, omit=False):
        cell = self.alignment.newBox(parser)
        self.row.cells.append(cell)
        if omit:
            templates = []
        else:
            column = self.template[column_no]
            templates = [column.v, column.u]
        self.current_cell = CellBuildState(cell.list, column_no, self, templates)
        return self.current_cell

    def finishRow(self, parser):
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting }", parser.input.position())
        if t.catcode == CATCODE.END_GROUP:
            parser.input.unread(t)
            return
        command = getattr(t, "definition", None)
        if command != noalign:
            parser.input.unread(t)
        noalign_owner = self.alignment if len(self.alignment.rows) == 0 else self.alignment.rows[-1]
        row = Row()
        self.alignment.rows.append(row)
        row_state = RowBuildState(row, self.alignment, self.template, self.builder)
        self.builder.current_row_state = row_state
        if command == noalign:
            noalign_owner.noalign = parser.readVList(
                GROUP_TYPE.NO_ALIGN,
                lambda: newCell(parser, row_state, 0),
            )
        else:
            newCell(parser, row_state, 0)


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
        self._typeset_cache = None

    node_type = nd.NODE_TYPE.ALIGNMENT
    needs_vcontext = False

    def saveInfo(self):
        return {
            "init": {
                "to": self.to,
                "spread": self.spread,
            },
            "extra": {
                "rows": self.rows,
                "noalign": self.noalign,
                "tabskips": self.tabskips,
            },
        }
    
    def __repr__(self):
        return f"{self.__class__.__name__}({self.rows})"
    
    def newBox(self, parser):
        raise NotImplementedError

    def typeset(self, parser, packed):
        self.pretypeset(parser)
        packed.append(self._typeset_cache)

    def pretypeset(self, parser):
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
            while i < len(row.cells):
                start = column
                cells = []
                while True:
                    cell = row.cells[i]
                    cell.typeset(parser, [])
                    cells.append(cell)
                    column += 1
                    if not getattr(cell.list, "span", 0):
                        break
                    i += 1
                    if i >= len(row.cells):
                        raise ValueError("missing cell after \\span", parser.input.position())
                entry = {
                    "start": start,
                    "span": len(cells),
                    "cells": cells,
                    "measure": self.entryMeasure(cells),
                }
                entries.append(entry)
                i += 1
            if column > n_raw:
                n_raw = column
            rows.append((row, entries))
        if n_raw == 0:
            return rows, [], list(self.tabskips[:1])
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

    def _combineCells(self, parser, cells):
        if len(cells) == 1:
            return cells[0]
        box = self.entryBox(parser)
        box.list[:] = list(cells)
        box.typeset(parser, [])
        return box

    def _appendVerticalMaterial(self, parser, vlist, nodes):
        for node in nodes:
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                node.typeset(parser, [])
            vlist.append(node)

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
    A \\halign node. It is vertical material, so it must capture vertical typesetting
    context when appended to a vlist.
    """
    needs_vcontext = True

    def __init__(self, to=None, spread=Dimen()):
        super().__init__(to, spread)
        self.typeset_context = None
        self._expanded_rows_ready = False

    def newBox(self, parser):
        return bx.HBox(parser, None, 0)

    def entryMeasure(self, cells):
        total = Dimen()
        for cell in cells:
            total += cell.width
        return total

    def entryBox(self, parser):
        return bx.HBox(parser, None, 0)

    def reboxEntry(self, parser, box, target):
        target = Dimen(target)
        box.typeset(parser, [])
        if box.width == target:
            return box
        ratio, order, stretching = self._glueSet(box.natural, target - box.width)
        box.glue_ratio = ratio
        box.width = target
        return box

    def _buildSpanBox(self, parser, entry):
        box = bx.HBox(parser, None, Dimen())
        for item in entry["cells"]:
            item.typeset(parser, [])
            box.list.extend(item.list)
        return box

    def _emptyEntry(self, parser, width):
        box = bx.HBox(parser, width, Dimen())
        box.typeset(parser, [])
        return box

    def _rowContext(self, prevdepth, context=None):
        if context is None:
            context = self.typeset_context
        if context is None:
            return None

        class RowContext:
            def __init__(self, context, prevdepth):
                self.baselineskip = context.baselineskip
                self.lineskip = context.lineskip
                self.lineskiplimit = context.lineskiplimit
                self.interlinepenalty = context.interlinepenalty
                self.prevdepth = prevdepth

        return RowContext(context, prevdepth)

    def pretypeset(self, parser, context=None):
        if self._typeset_cache is not None:
            return
        if context is None:
            context = self.typeset_context
        rows, w, t = self._collectEntries(parser)
        prepared = []
        W = Dimen()
        for row, entries in rows:
            rowbox = bx.HBox(parser, None, Dimen())
            row_total = glue.Glue()
            row_entries = []
            row_height = Dimen()
            row_depth = Dimen()
            if t:
                rowbox.list.append(nd.Glue(t[0], "\\tabskip"))
                row_total += t[0]
            for entry in entries:
                i = entry["start"]
                j = i + entry["span"] - 1
                if entry["span"] == 1:
                    box = self.reboxEntry(parser, self._combineCells(parser, entry["cells"]), w[i])
                    row_entries.append(box)
                    if box.height > row_height:
                        row_height = box.height
                    if box.depth > row_depth:
                        row_depth = box.depth
                    rowbox.list.append(box)
                else:
                    box = self.reboxEntry(parser, self._buildSpanBox(parser, entry), w[i])
                    row_entries.append(box)
                    if box.height > row_height:
                        row_height = box.height
                    if box.depth > row_depth:
                        row_depth = box.depth
                    rowbox.list.append(box)
                    for k in range(i + 1, j + 1):
                        rowbox.list.append(nd.Glue(t[k], "\\tabskip"))
                        row_total += t[k]
                        rowbox.list.append(self._emptyEntry(parser, w[k]))
                if j + 1 < len(t):
                    rowbox.list.append(nd.Glue(t[j + 1], "\\tabskip"))
                    row_total += t[j + 1]
            for box in row_entries:
                box.height = row_height
                box.depth = row_depth
            rowbox.typeset(parser, [])
            prepared.append((row, rowbox, row_total))
            if rowbox.width > W:
                W = Dimen(rowbox.width)
        if self.to is not None:
            W = self.to
        else:
            W += self.spread
        out = bx.VBox(parser, None, Dimen())
        out.typeset_context = context
        if self.noalign is not None:
            self._appendVerticalMaterial(parser, out.list, self.noalign)
        for row, rowbox, row_total in prepared:
            ratio, order, stretching = self._glueSet(row_total, W - rowbox.width)
            rowbox.glue_ratio = ratio
            rowbox.width = W
            row_context = self._rowContext(out.list.prevdepth, context)
            if row_context is not None:
                rowbox.typeset_context = row_context
            out.list.append(rowbox)
            if row.noalign is not None:
                self._appendVerticalMaterial(parser, out.list, row.noalign)
        out.typeset(parser, [])
        self._typeset_cache = out

    def _prepareExpandedRows(self, context=None):
        if self._expanded_rows_ready:
            return
        if context is None:
            context = self.typeset_context
        rowboxes = [item for item in self._typeset_cache.list if item.node_type == nd.NODE_TYPE.HLIST]
        for index, rowbox in enumerate(rowboxes):
            row_context = getattr(rowbox, "typeset_context", None)
            if row_context is None:
                continue
            if index == 0 and context is not None:
                row_context.prevdepth = context.prevdepth
                row_context.interlinepenalty = context.interlinepenalty
            else:
                row_context.prevdepth = vmode.init_prevdepth
                row_context.interlinepenalty = 0
        self._expanded_rows_ready = True

    def typeset(self, parser, packed):
        self.pretypeset(parser)
        self._prepareExpandedRows()
        packed.extend(self._typeset_cache.list)


class MAlignment(HAlignment):
    """
    A \\halign used as a display alignment inside $$...$$.
    """
    needs_vcontext = False

    def typeset(self, parser, packed, context):
        if self._typeset_cache is None:
            self.pretypeset(parser, context)
        self._prepareExpandedRows(context)
        packed.extend(self._typeset_cache.list)

    def pretypeset(self, parser, context):
        super().pretypeset(parser, context)
        shift = Dimen(context.displayindent)
        for row in self._typeset_cache.list:
            if row.node_type == nd.NODE_TYPE.HLIST:
                row.shifted = shift


class VAlignment(Alignment):
    """
    A \\valign node. It behaves like an hbox with respect to surrounding layout.
    """
    def newBox(self, parser):
        return bx.VBox(parser, None, 0)

    def entryMeasure(self, cells):
        total = Dimen()
        for cell in cells:
            total += cell.height + cell.depth
        return total

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
        out.typeset(parser, [])
        return out

    def pretypeset(self, parser):
        if self._typeset_cache is not None:
            return
        rows, w, t = self._collectEntries(parser)
        out = bx.HBox(parser, self.to, self.spread)
        for row, entries in rows:
            colbox = bx.VBox(parser, None, 0)
            entry_boxes = []
            col_width = Dimen()
            if t:
                colbox.list.append(nd.Glue(t[0], "\\tabskip"))
            for entry in entries:
                box = self._combineCells(parser, entry["cells"])
                i = entry["start"]
                j = i + entry["span"] - 1
                target = self._spanTarget(w, t, i, j)
                box = self.reboxEntry(parser, box, target)
                entry_boxes.append(box)
                if box.width > col_width:
                    col_width = box.width
                colbox.list.append(box)
                if j + 1 < len(t):
                    colbox.list.append(nd.Glue(t[j + 1], "\\tabskip"))
            for box in entry_boxes:
                box.width = col_width
            colbox.typeset(parser, [])
            out.list.append(colbox)
        out.typeset(parser, [])
        self._typeset_cache = out

    def typeset(self, parser, packed):
        self.pretypeset(parser)
        packed.extend(self._typeset_cache.list)

class EndCellToken(Token):
    def __init__(self, cell, is_last):
        super().__init__("\\endcell", None)
        self.cell = cell
        self.is_last = is_last

    def execute(self, parser):
        row = self.cell.row_build_state
        self.cell.close(parser)
        if self.is_last:
            row.finishRow(parser)
        else:
            newCell(parser, row, self.cell.column_no + 1)


def newCell(parser, row_state, column_no):
    alignment = row_state.alignment
    row = row_state.row
    has_omit = False
    t = parser.skipSpaces(True)
    if t is None:
        raise ValueError("expecting \\cr", parser.input.position())
    if getattr(t, "definition", None) is omit:
        has_omit = True
    else:
        if t.catcode == CATCODE.END_GROUP:
            if column_no != 0:
                raise ValueError("expecting \\cr", parser.input.position())
            if not row.cells and alignment.rows and alignment.rows[-1] is row:
                alignment.rows.pop()
            parser.input.unread(t)
            return
        parser.input.unread(t)
    cell = row_state.newCell(parser, column_no, has_omit)
    parser.lists.append(cell)
    parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN)
    cell.pushTemplate(parser)


def endCell(parser, is_last):
    cell = parser.alignments.currentCell()
    if cell is None:
        message = "unexpected \\cr" if is_last else "expecting \\cr"
        raise ValueError(message, parser.input.position())
    parser.input.push(lexer.TokenListScanner([EndCellToken(cell, is_last)]))
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
        endCell(parser, is_last=True)



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
        cell = parser.alignments.currentCell()
        if cell is None:
            raise ValueError("unexpected \\span", parser.input.position())
        cell.span = True
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
    def __init__(self, parser, builder):
        self.parser = parser
        self.builder = builder

    def __call__(self):
        if self.parser.alignments.currentCell() is not None:
            raise ValueError("expecting \\cr", self.parser.input.position())
        if self.parser.alignments and self.parser.alignments[-1] is self.builder:
            self.parser.alignments.pop()


class AlignmentBuilder:
    """
    A builder for an alignment.
    It is used to build an alignment from a list of tokens.
    @param enclosing: the enclosing list in the parser
    """
    def __init__(self, alignment):
        self.alignment = alignment
        # the current row being built
        self.current_row_state = None
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
        row_state = RowBuildState(row, self.alignment, self.preamble, self)
        self.current_row_state = row_state
        cell = self.alignment.newBox(parser)
        row.cells.append(cell)
        row_state.current_cell = CellBuildState(cell.list, 0, row_state, [])
        parser.lists.append(row_state.current_cell)
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
            if t.catcode == CATCODE.BEGIN_GROUP:
                current.extend(parser.readBalancedText([t], expand=False, macro=False))
                continue
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
        parser.alignments.append(self)
        parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN, AlignmentEndCallback(parser, self))
        self.readPreamble(parser)


class Align(lists.ModeDependentCommand):
    """
    The \\halign command.
    """
    def newAlignment(self, parser, list, cls):
        to, spread = parser.readToSpread()
        alignment = cls(to, spread)
        list.append(alignment)
        AlignmentBuilder(alignment).run(parser)


class HAlign(Align):
    def vertical(self, parser, vlist):
        self.newAlignment(parser, vlist, HAlignment)
    
    def math(self, parser, mlist):
        from pytex import mmode
        if not isinstance(mlist, mmode.DisplayMathList) or len(mlist) > 0:
            raise ValueError("improper \\halign inside math mode", parser.input.position())
        mlist = HAlignMathList(mlist)
        parser.lists[-1] = mlist
        self.newAlignment(parser, mlist, MAlignment)


class VAlign(Align):
    """
    The \\valign command.
    """
    def horizontal(self, parser, hlist):
        self.newAlignment(parser, hlist, VAlignment)


class HAlignMathList(nd.Node):
    """
    Wrapper around a DisplayMathList whose sole node is a display \\halign.
    """
    node_type = nd.NODE_TYPE.MATH
    type = lists.LISTTYPE.MATH

    def __init__(self, display):
        object.__setattr__(self, "display", display)

    def saveInfo(self):
        return {"init": {"display": self.display}}

    @classmethod
    def new(cls, parser, display):
        return cls(display)

    def __getattr__(self, name):
        return getattr(self.display, name)

    def __setattr__(self, name, value):
        if name == "display":
            object.__setattr__(self, name, value)
            return
        if name == "eqno" and value is not None:
            raise ValueError("misplaced equation number", self.display.parser.input.position())
        setattr(self.display, name, value)

    def __len__(self):
        return len(self.display)

    def __iter__(self):
        return iter(self.display)

    def __getitem__(self, index):
        return self.display[index]

    def append(self, node):
        if len(self.display) > 0 or not isinstance(node, MAlignment):
            raise ValueError("only assignments can follow \\halign in display math", self.display.parser.input.position())
        self.display.append(node)

    def typeset(self, parser, packed):
        if self.typeset_context.prevgraf is None:
            self.prev_paragraph.pretypeset(parser)
        alignment = self.display[0]
        packed.append(nd.Penalty(self.typeset_context.predisplaypenalty))
        packed.append(nd.Glue(self.typeset_context.abovedisplayskip, "\\abovedisplayskip"))
        alignment.typeset(parser, packed, self.typeset_context)
        packed.append(nd.Penalty(self.typeset_context.postdisplaypenalty))
        packed.append(nd.Glue(self.typeset_context.belowdisplayskip, "\\belowdisplayskip"))
        next_prevgraf = self.typeset_context.prevgraf + 3
        if self.next_paragraph is not None:
            self.next_paragraph.prevgraf = next_prevgraf
            next_context = getattr(self.next_paragraph, "typeset_context", None)
            if next_context is not None:
                next_context.prevgraf = next_prevgraf


def init(parser):
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
