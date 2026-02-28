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
    def __init__(self, to=None, spread=Dimen()):
        self.rows = []
        # the first noalign before the first row
        self.noalign = None
        self.tabskips = []
        self.to = to
        self.spread = spread
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
            return float(delta) / total.stretch.factor, total.stretch.order, True
        if delta < 0 and total.shrink.factor != 0:
            return float(delta) / total.shrink.factor, total.shrink.order, False
        return 0.0, None, delta > 0

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
        if box.width == target:
            return box
        out = bx.HBox(parser, target, None)
        hss = glue.Glue(0, glue.Stretchness(1, 1), glue.Stretchness(1, 1))
        out.list.append(nd.Glue(hss))
        out.list.append(box)
        out.list.append(nd.Glue(hss))
        out.typeset(parser, [])
        return out

    def _buildSpanBox(self, parser, entry):
        box = bx.HBox(parser, None, Dimen())
        total = glue.Glue()
        inner = iter(entry["inner_t"])
        for idx, item in enumerate(entry["cells"]):
            if idx != 0:
                tabskip = next(inner, None)
                if tabskip is not None:
                    box.list.append(nd.Glue(tabskip))
                    total += tabskip
            box.list.append(item)
        box.typeset(parser, [])
        return box, total

    def _applyBoxGlueSet(self, box, ratio, order, stretching):
        box.glue_ratio = ratio
        if order is None:
            return
        natural = box.width
        if stretching:
            stretch = box.natural.stretch
            if stretch.order != order:
                return
            box.width = natural + stretch.factor * ratio
            return
        shrink = box.natural.shrink
        if shrink.order != order:
            return
        box.width = natural + shrink.factor * ratio

    def _rowContext(self, prevdepth):
        if self.typeset_context is None:
            return None

        class RowContext:
            def __init__(self, context, prevdepth):
                self.baselineskip = context.baselineskip
                self.lineskip = context.lineskip
                self.lineskiplimit = context.lineskiplimit
                self.interlinepenalty = context.interlinepenalty
                self.prevdepth = prevdepth

        return RowContext(self.typeset_context, prevdepth)

    def pretypeset(self, parser):
        if self._typeset_cache is not None:
            return
        rows, w, t = self._collectEntries(parser)
        prepared = []
        W = Dimen()
        for row, entries in rows:
            rowbox = bx.HBox(parser, None, Dimen())
            row_total = glue.Glue()
            span_boxes = []
            if t:
                rowbox.list.append(nd.Glue(t[0]))
                row_total += t[0]
            for entry in entries:
                i = entry["start"]
                j = i + entry["span"] - 1
                if entry["span"] == 1:
                    box = self.reboxEntry(parser, self._combineCells(parser, entry["cells"]), w[i])
                else:
                    box, inner = self._buildSpanBox(parser, entry)
                    row_total += inner
                    span_boxes.append(box)
                rowbox.list.append(box)
                if j + 1 < len(t):
                    rowbox.list.append(nd.Glue(t[j + 1]))
                    row_total += t[j + 1]
            rowbox.typeset(parser, [])
            prepared.append((row, rowbox, row_total, span_boxes))
            if rowbox.width > W:
                W = Dimen(rowbox.width)
        if self.to is not None:
            W = self.to
        else:
            W += self.spread
        out = bx.VBox(parser, None, Dimen())
        out.typeset_context = self.typeset_context
        if self.noalign is not None:
            self._appendVerticalMaterial(parser, out.list, self.noalign)
        for row, rowbox, row_total, span_boxes in prepared:
            ratio, order, stretching = self._glueSet(row_total, W - rowbox.width)
            for box in span_boxes:
                self._applyBoxGlueSet(box, ratio, order, stretching)
            rowbox.glue_ratio = ratio
            rowbox.width = W
            context = self._rowContext(out.list.prevdepth)
            if context is not None:
                rowbox.typeset_context = context
            out.list.append(rowbox)
            if row.noalign is not None:
                self._appendVerticalMaterial(parser, out.list, row.noalign)
        out.typeset(parser, [])
        self._typeset_cache = out


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
        out.list.append(nd.Glue(vss))
        out.list.append(box)
        out.list.append(nd.Glue(vss))
        out.typeset(parser, [])
        return out

    def pretypeset(self, parser):
        if self._typeset_cache is not None:
            return
        rows, w, t = self._collectEntries(parser)
        out = bx.HBox(parser, self.to, self.spread)
        for row, entries in rows:
            colbox = bx.VBox(parser, None, 0)
            if t:
                colbox.list.append(nd.Glue(t[0]))
            for entry in entries:
                box = self._combineCells(parser, entry["cells"])
                i = entry["start"]
                j = i + entry["span"] - 1
                target = self._spanTarget(w, t, i, j)
                colbox.list.append(self.reboxEntry(parser, box, target))
                if j + 1 < len(t):
                    colbox.list.append(nd.Glue(t[j + 1]))
            colbox.typeset(parser, [])
            out.list.append(colbox)
        out.typeset(parser, [])
        self._typeset_cache = out


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
    while getattr(parser.lists[-1], "row", None) is None:
        top = parser.lists[-1]
        if top.type == lists.LISTTYPE.HORIZONTAL and not top.inner:
            parser.endParagraph()
            continue
        break
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


def _newAlignment(parser, list, cls):
    to, spread = parser.readToSpread()
    alignment = cls(to, spread)
    list.append(alignment)
    AlignmentBuilder(alignment).run(parser)


class HAlign(lists.ModeDependentCommand):
    """
    The \\halign command.
    """
    def vertical(self, parser, vlist):
        _newAlignment(parser, vlist, HAlignment)
    
    def math(self, parser, mlist):
        if len(mlist) > 0 or mlist.inner:
            raise ValueError("improper \\halign inside math mode", parser.input.position())
        _newAlignment(parser, mlist, HAlignment)


class VAlign(lists.ModeDependentCommand):
    """
    The \\valign command.
    """
    def horizontal(self, parser, hlist):
        _newAlignment(parser, hlist, VAlignment)


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
