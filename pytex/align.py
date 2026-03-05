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


class CellList(list):
    """
    Plain list payload for horizontal alignment cells with a span marker.
    """
    pass


class CellBuildState:
    """
    Wrapper around the list holding a cell being built.
    This is pushed onto parser.lists so build-time state does not live on the list.

    @param node: the box node whose list holds the cell content
    @param column_no: the column number of the cell
    @param row_build_state: the build state of the row this cell is in
    @param templates: remaining template parts to inject, in reverse push order
    """
    def __init__(self, parser, node, column_no, row_build_state, templates):
        object.__setattr__(self, "node", node)
        object.__setattr__(self, "list", node.list)
        if node.node_type == nd.NODE_TYPE.HLIST:
            build = hmode.HList(parser, inner=True, node=node.list)
        else:
            build = parser.wrapBuildState(node.list)
        object.__setattr__(self, "build", build)
        object.__setattr__(self, "column_no", column_no)
        object.__setattr__(self, "row_build_state", row_build_state)
        object.__setattr__(self, "templates", templates)

    def __getattr__(self, name):
        if name == "span":
            return getattr(self.node.list, "span", False)
        try:
            return getattr(self.build, name)
        except AttributeError:
            return getattr(self.node, name)

    def __setattr__(self, name, value):
        if name == "span":
            try:
                setattr(self.node.list, name, value)
            except AttributeError:
                setattr(self.node, name, value)
            return
        setattr(self.build, name, value)

    def __getitem__(self, index):
        return self.build[index]

    def __setitem__(self, index, value):
        self.build[index] = value

    def __delitem__(self, key):
        del self.build[key]

    def __len__(self):
        return len(self.build)

    def __iter__(self):
        return iter(self.build)

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
        if cell.node_type == nd.NODE_TYPE.HLIST and type(cell.list) is list:
            content = CellList(cell.list)
            content.span = False
            cell.list = content
        self.row.cells.append(cell)
        template = self.template if self.template is not None else self.builder.preamble
        if omit:
            templates = []
        else:
            if column_no < len(template):
                column = template[column_no]
            elif self.builder.repeat_start:
                column = template[column_no % len(template)]
            else:
                raise ValueError("extra alignment tab has been changed to \\cr", parser.input.position())
            templates = [column.v, column.u]
        self.current_cell = CellBuildState(parser, cell, column_no, self, templates)
        return self.current_cell

    def _startNextRow(self, parser):
        row = Row()
        self.alignment.rows.append(row)
        template = self.template if self.template is not None else self.builder.preamble
        row_state = RowBuildState(row, self.alignment, template, self.builder)
        self.builder.current_row_state = row_state
        newCell(parser, row_state, 0)

    def _resumeAfterCr(self, parser):
        t = parser.token_expand()
        if t is None:
            raise ValueError("expecting }", parser.input.position())
        if parser.token_meaning(t).catcode == CATCODE.END_GROUP:
            parser.input.unread(t)
            return
        command = getattr(t, "definition", None)
        if command == noalign:
            noalign_owner = self.alignment if len(self.alignment.rows) == 0 else self.alignment.rows[-1]
            noalign_owner.noalign = parser.readVList(
                GROUP_TYPE.NO_ALIGN,
                lambda: self._resumeAfterCr(parser),
            )
            return
        parser.input.unread(t)
        self._startNextRow(parser)

    def finishRow(self, parser):
        self._resumeAfterCr(parser)


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
        self._row_layout = None

    node_type = nd.NODE_TYPE.ALIGNMENT
    needs_vcontext = False
    box_materializable = True

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

    def materialize_box_nodes(self, parser):
        self.pretypeset(parser)
        prepare = getattr(self, "_prepareExpandedRows", None)
        if prepare is not None:
            prepare(getattr(self, "typeset_context", None))
        cache = self._typeset_cache
        if cache is None:
            return []
        nodes = getattr(cache, "list", None)
        if nodes is None:
            return [cache]
        return list(nodes)

    def captureRowLayout(self, parser):
        layout = parser.state.layout
        self._row_layout = {
            "baselineskip": layout["baselineskip"].copy(),
            "lineskip": layout["lineskip"].copy(),
            "lineskiplimit": Dimen(layout["lineskiplimit"]),
            "interlinepenalty": int(layout["interlinepenalty"]),
        }

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
                    cells.append(cell.typeset(parser))
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
        return box.typeset(parser)

    def _appendVerticalMaterial(self, parser, vlist, nodes):
        for node in nodes:
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                node = node.typeset(parser)
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
        box = box.typeset(parser)
        if box.width == target:
            return box
        out = bx.HBox(parser, target, None)
        out.list[:] = box.list
        out.source = box.source
        return out.typeset(parser)

    def _buildSpanBox(self, parser, entry):
        box = bx.HBox(parser, None, Dimen())
        for item in entry["cells"]:
            box.list.extend(item.typeset(parser).list)
        return box

    def _emptyEntry(self, parser, width):
        box = bx.HBox(parser, width, None)
        return box.typeset(parser)

    def _rowContext(self, prevdepth, context=None):
        if context is None:
            context = self.typeset_context
        source = self._row_layout if self._row_layout is not None else context
        if source is None:
            return None

        class RowContext:
            def __init__(self, source, prevdepth):
                if isinstance(source, dict):
                    self.baselineskip = source["baselineskip"]
                    self.lineskip = source["lineskip"]
                    self.lineskiplimit = source["lineskiplimit"]
                    self.interlinepenalty = source["interlinepenalty"]
                else:
                    self.baselineskip = source.baselineskip
                    self.lineskip = source.lineskip
                    self.lineskiplimit = source.lineskiplimit
                    self.interlinepenalty = source.interlinepenalty
                self.prevdepth = prevdepth

        return RowContext(source, prevdepth)

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
            row_width = Dimen()
            row_entries = []
            row_height = Dimen()
            row_depth = Dimen()
            if t:
                rowbox.list.append(nd.Glue(t[0], "\\tabskip"))
                row_total += t[0]
                row_width += t[0].dimen
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
                    row_width += box.width
                else:
                    box = self.reboxEntry(parser, self._buildSpanBox(parser, entry), w[i])
                    row_entries.append(box)
                    if box.height > row_height:
                        row_height = box.height
                    if box.depth > row_depth:
                        row_depth = box.depth
                    rowbox.list.append(box)
                    row_width += box.width
                    for k in range(i + 1, j + 1):
                        rowbox.list.append(nd.Glue(t[k], "\\tabskip"))
                        row_total += t[k]
                        row_width += t[k].dimen
                        empty = self._emptyEntry(parser, w[k])
                        rowbox.list.append(empty)
                        row_width += empty.width
                if j + 1 < len(t):
                    rowbox.list.append(nd.Glue(t[j + 1], "\\tabskip"))
                    row_total += t[j + 1]
                    row_width += t[j + 1].dimen
            for box in row_entries:
                box.height = row_height
                box.depth = row_depth
            prepared.append((row, rowbox, row_total, row_width))
            if row_width > W:
                W = Dimen(row_width)
        if self.to is not None:
            W = self.to
        else:
            W += self.spread
        out = bx.VBox(parser, None, Dimen())
        out.typeset_context = context
        if self.noalign is not None:
            self._appendVerticalMaterial(parser, out.list, self.noalign)
        for row, rowbox, row_total, row_width in prepared:
            rowbox.to = W
            rowbox.spread = W - row_width
            rowbox = rowbox.typeset(parser)
            row_context = self._rowContext(out.list.prevdepth, context)
            if row_context is not None:
                rowbox.typeset_context = row_context
            out.list.append(rowbox)
            if row.noalign is not None:
                self._appendVerticalMaterial(parser, out.list, row.noalign)
        self._typeset_cache = out.typeset(parser)

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

    def pretypeset(self, parser, context=None):
        if context is None:
            context = self.typeset_context
        super().pretypeset(parser, context)
        self._normalizeTagPlacement(parser, context)
        shift = Dimen() if context is None else Dimen(context.displayindent)
        for row in self._typeset_cache.list:
            if row.node_type == nd.NODE_TYPE.HLIST:
                row.shifted = shift

    def _normalizeTagPlacement(self, parser, context):
        if context is None or context.displaywidth is None:
            return
        rows = [row for row in self._typeset_cache.list if row.node_type == nd.NODE_TYPE.HLIST]
        if not rows:
            return

        tagged = []
        max_left = None
        max_right = None
        max_outer = None
        for row in rows:
            if len(row.list) < 5:
                continue
            left_glue = row.list[0]
            left_box = row.list[1]
            right_box = row.list[3]
            right_glue = row.list[4]
            if (
                getattr(left_glue, "node_type", None) != nd.NODE_TYPE.GLUE
                or getattr(right_glue, "node_type", None) != nd.NODE_TYPE.GLUE
                or getattr(left_box, "node_type", None) != nd.NODE_TYPE.HLIST
                or getattr(right_box, "node_type", None) != nd.NODE_TYPE.HLIST
            ):
                continue
            if not right_box.list:
                continue
            outer = right_box.list[0]
            if getattr(outer, "node_type", None) != nd.NODE_TYPE.HLIST or len(outer.list) < 2:
                continue
            math_box = outer.list[1]
            if getattr(math_box, "node_type", None) != nd.NODE_TYPE.HLIST or len(math_box.list) < 3:
                continue
            kneg = math_box.list[-3]
            kpos = math_box.list[-2]
            tag_box = math_box.list[-1]
            if (
                getattr(kneg, "node_type", None) != nd.NODE_TYPE.KERN
                or getattr(kpos, "node_type", None) != nd.NODE_TYPE.KERN
                or kneg.automatic
                or kpos.automatic
                or getattr(tag_box, "node_type", None) != nd.NODE_TYPE.HLIST
            ):
                continue
            tagged.append((row, left_glue, right_glue, right_box, outer, math_box, kneg, kpos))
            max_left = Dimen(left_box.width) if max_left is None or left_box.width > max_left else max_left
            max_right = Dimen(right_box.width) if max_right is None or right_box.width > max_right else max_right
            max_outer = Dimen(outer.width) if max_outer is None or outer.width > max_outer else max_outer

        if not tagged or max_left is None or max_right is None or max_outer is None:
            return

        side = (Dimen(context.displaywidth) - max_left - max_right) / 2
        if side <= 0:
            return

        for row, left_glue, right_glue, right_box, outer, math_box, kneg, kpos in tagged:
            lg = left_glue.glue.copy()
            lg.dimen = Dimen(side)
            left_glue.glue = lg
            rg = right_glue.glue.copy()
            rg.dimen = Dimen(side)
            right_glue.glue = rg
            extra = max_outer - outer.width
            if extra < 0:
                extra = Dimen()
            kneg.kern = -Dimen(side)
            # amsmath tags are emitted as a tail sequence that assumes an
            # additional tabskip slot before the tag box. Our alignment packing
            # keeps that tail in the equation cell, so add one extra side-width
            # advance here to match TeX's final tag placement. Also normalize
            # narrower rows so all tags share the same right margin.
            kpos.kern = 2 * Dimen(side) + extra
            # Repack modified nested boxes and keep the row width at \displaywidth.
            for box in (math_box, outer, right_box):
                box._typeset_cache = None
                box.pretypeset(parser)
            row.to = Dimen(context.displaywidth)
            row.spread = None
            row._typeset_cache = None
            row.pretypeset(parser)


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
        return out.typeset(parser)

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
                box._typeset_cache = box
            out.list.append(colbox.typeset(parser))
        self._typeset_cache = out.typeset(parser)

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
        if parser.token_meaning(t).catcode == CATCODE.END_GROUP:
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
    def __init__(self, parser, builder, target):
        self.parser = parser
        self.builder = builder
        self.target = target

    def __call__(self):
        if self.parser.alignments.currentCell() is not None:
            raise ValueError("expecting \\cr", self.parser.input.position())
        self.target.append(self.builder.alignment)
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
        self.alignment.tabskips.append(parser.state.parameters["tabskip"])
        tabskip = parser.builtin["\\tabskip"]
        # Build the preamble against a synthetic row that seeds the first real row.
        row = Row()
        row_state = RowBuildState(row, self.alignment, self.preamble, self)
        self.current_row_state = row_state
        cell = self.alignment.newBox(parser)
        row.cells.append(cell)
        row_state.current_cell = CellBuildState(parser, cell, 0, row_state, [])
        parser.lists.append(row_state.current_cell)
        # we start a new group, which will be terminated by \cr or \crcr
        parser.beginGroup(parser.input.position(), GROUP_TYPE.ALIGN)
        while True:
            template = [] # the tokans in the column template
            # we collect all the columns in the outer loop
            # the leading spaces in a column are ignored
            t = parser.skipSpaces(False)
            # now T is the first meaningful token in a column.
            # in the following loop, we collect the tokens in a column
            while True:
                if getattr(t, "definition", None) is span or t.name == "\\span":
                    t = parser.token_expand()
                if t is None:
                    raise ValueError("expecting a \\cr", parser.input.position())
                if t.catcode == CATCODE.BEGIN_GROUP:
                    template.extend(parser.readBalancedText([t], expand=False, macro=False))
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
            # now a column is read in template. We look for the # token
            if not template and not self.preamble and t is None:
                # we have a leading &, this is not a column, but tells us the columns are reused
                self.repeat_start = True
                continue
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
            self.alignment.tabskips.append(parser.state.parameters["tabskip"])
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
        t = parser.token_meaning(t)
        if t is None or t.catcode != CATCODE.BEGIN_GROUP:
            raise ValueError("expecting a {", parser.input.position())
        parser.alignments.append(self)
        parser.beginGroup(
            parser.input.position(),
            GROUP_TYPE.ALIGN,
            to_end=AlignmentEndCallback(parser, self, target),
        )
        self.readPreamble(parser)


class Align(lists.ModeDependentCommand):
    """
    The \\halign command.
    """
    def newAlignment(self, parser, list, cls):
        spec, d = parser.readBoxSpec()
        alignment = cls(d, None) if spec == "to" else cls(None, d)
        alignment.captureRowLayout(parser)
        AlignmentBuilder(alignment).run(parser, list)


class HAlign(Align):
    def vertical(self, parser, vlist):
        self.newAlignment(parser, vlist, HAlignment)
    
    def math(self, parser, mlist):
        from pytex import mmode
        display = getattr(mlist, "node", mlist)
        if not isinstance(display, mmode.DisplayMathList) or len(display) > 0:
            raise ValueError("improper \\halign inside math mode", parser.input.position())
        mlist = HAlignMathList(display)
        mstate = parser.wrapBuildState(mlist)
        parser.lists[-1] = mstate
        self.newAlignment(parser, mstate, MAlignment)


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
        if (
            self.typeset_context.prevgraf is None
            or self.typeset_context.displaywidth is None
            or self.typeset_context.displayindent is None
            or self.typeset_context.predisplaysize is None
        ):
            if self.prev_paragraph is not None:
                self.prev_paragraph.pretypeset(parser)
        if self.typeset_context.prevgraf is None:
            self.typeset_context.prevgraf = 0
        if self.typeset_context.displaywidth is None:
            self.typeset_context.displaywidth = parser.state.layout["hsize"]
        if self.typeset_context.displayindent is None:
            self.typeset_context.displayindent = Dimen()
        if self.typeset_context.predisplaysize is None:
            self.typeset_context.predisplaysize = NEG_MAX_DIMEN
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

    def materialize_box_nodes(self, parser):
        packed = []
        self.typeset(parser, packed)
        return packed


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
