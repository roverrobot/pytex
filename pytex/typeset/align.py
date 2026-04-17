"""Parser-owned alignment realization pipeline."""

from pytex import align as al
from pytex import box as bx
from pytex import glue
from pytex import node as nd
from pytex import vmode
from pytex.dimen import Dimen

HAlignment = al.HAlignment
VAlignment = al.VAlignment
MAlignment = al.MAlignment


class NoAlignNodeWrapper:
    def __init__(self, node, source):
        self.node = node
        self.source = source

    def __getattr__(self, name):
        return getattr(self.node, name)


class AlignmentTypesetter:
    def __init__(self, parser):
        self.parser = parser

    def _appendNoAlign(self, alignment, noalign, vlist):
        for n in noalign:
            vlist.append(NoAlignNodeWrapper(n, alignment), add_interline=False)

    def typesetHAlignment(self, alignment, vlist):
        parser = self.parser
        if not isinstance(vlist, vmode.VList):
            raise TypeError("HAlignment typesetting expects a VList")
        rows, w, t = alignment._collectEntries(parser)
        prepared = []
        for row, entries in rows:
            rowbox = bx.HBox(parser, alignment.to, alignment.spread)
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
                    box = alignment.reboxEntry(parser, entry["cell"], w[i])
                    row_entries.append(box)
                    if box.height > row_height:
                        row_height = box.height
                    if box.depth > row_depth:
                        row_depth = box.depth
                    rowbox.list.append(box)
                    row_width += box.width
                else:
                    box = alignment.reboxEntry(parser, entry["cell"], w[i])
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
                        empty = alignment._emptyEntry(parser, w[k])
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
        if alignment.noalign is not None:
            self._appendNoAlign(alignment, alignment.noalign, vlist)
        for row, rowbox, row_total, row_width in prepared:
            rowbox.source = alignment
            vlist.append(rowbox.typeset(parser))
            if row.noalign is not None:
                self._appendNoAlign(alignment, row.noalign, vlist)

    def typesetVAlignment(self, alignment, packed):
        parser = self.parser
        rows, w, t = alignment._collectEntries(parser)
        out = bx.HBox(parser, alignment.to, alignment.spread)
        for row, entries in rows:
            colbox = bx.VBox(parser, None, 0)
            entry_boxes = []
            col_width = Dimen()
            if t:
                colbox.list.append(nd.Glue(t[0], "\\tabskip"))
            for entry in entries:
                box = entry["cell"]
                i = entry["start"]
                j = i + entry["span"] - 1
                target = alignment._spanTarget(w, t, i, j)
                box = alignment.reboxEntry(parser, box, target)
                entry_boxes.append(box)
                if box.width > col_width:
                    col_width = box.width
                colbox.list.append(box)
                if j + 1 < len(t):
                    colbox.list.append(nd.Glue(t[j + 1], "\\tabskip"))
            for box in entry_boxes:
                box.width = col_width
            out.list.append(colbox.typeset(parser))
        packed.extend(out.typeset(parser).list)
        return packed

    def typesetMAlignment(self, alignment, vlist):
        if not isinstance(vlist, vmode.VList):
            raise TypeError("MAlignment typesetting expects a VList")
        vlist.append(nd.Penalty(alignment.predisplaypenalty))
        vlist.append(nd.Glue(alignment.abovedisplayskip, "\\abovedisplayskip"))
        vlist.extend(alignment.list, add_interline=False)
        vlist.append(nd.Penalty(alignment.postdisplaypenalty))
        vlist.append(nd.Glue(alignment.belowdisplayskip, "\\belowdisplayskip"))
