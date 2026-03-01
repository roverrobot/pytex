"""
Page breaking for the main vertical list.
"""


from math import inf

from pytex import box as bx
from pytex import node as nd
from pytex import vmode
from pytex.glue import Glue
from pytex.dimen import Dimen


class PageBuilderContext:
    """
    Snapshot of page-builder parameters that may change while building the main vlist.
    """

    def __init__(self, layout):
        self.vsize = layout["vsize"]
        self.topskip = layout["topskip"]
        self.maxdepth = layout["maxdepth"]

    def sameLayout(self, layout):
        return (
            self.vsize == layout["vsize"]
            and self.topskip == layout["topskip"]
            and self.maxdepth == layout["maxdepth"]
        )


class PageStateNode(nd.Node):
    """
    Transparent marker that records page-builder parameter changes on the main vlist.
    """

    node_type = nd.NODE_TYPE.WHATSIT

    def __init__(self, context):
        self.context = context

    def saveInfo(self):
        return {"init": {"context": self.context}}

    @classmethod
    def new(cls, parser, context):
        return cls(context)

    def __repr__(self):
        return "PageState"


class MainVList(vmode.VList):
    """
    The document's main vertical list.
    """

    def __init__(self, parser):
        super().__init__(parser, inner=False)
        self.page_initial_context = PageBuilderContext(parser.state.layout)
        self.page_context = self.page_initial_context

    def append(self, node):
        if not isinstance(node, PageStateNode):
            context = PageBuilderContext(self.parser.state.layout)
            if not self.page_context.sameLayout(self.parser.state.layout):
                super().append(PageStateNode(context))
                self.page_context = context
        super().append(node)

    @staticmethod
    def _pageMeasure(total, node):
        if node.node_type == nd.NODE_TYPE.GLUE:
            total.dimen += node.glue.dimen
            total.stretch = total.stretch + node.glue.stretch
            total.shrink = total.shrink + node.glue.shrink
        elif node.node_type == nd.NODE_TYPE.KERN:
            total.dimen += node.kern
        elif node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            total.dimen += node.height + node.depth
        elif node.node_type == nd.NODE_TYPE.RULE:
            total.dimen += node.height + node.depth
        elif node.node_type == nd.NODE_TYPE.INS:
            raise NotImplementedError("page breaking with \\insert is not implemented yet")
        return total

    @staticmethod
    def _pageTopskip(topskip, node):
        if node.node_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.RULE):
            return None
        dimen = topskip.dimen - node.height
        if dimen < 0:
            dimen = Dimen()
        return Glue(dimen, topskip.stretch, topskip.shrink)

    @staticmethod
    def _pageBadness(total, goal):
        delta = goal - total.dimen
        if delta == 0:
            return 0
        if delta > 0:
            stretch = total.stretch
            if stretch.factor == 0:
                return inf
            if stretch.order > 0:
                return 0
            num = int(delta)
            den = int(stretch.factor)
        else:
            shrink = total.shrink
            if shrink.factor == 0:
                return inf
            if shrink.order > 0:
                return 0
            num = -int(delta)
            den = int(shrink.factor)
            if num > den:
                return inf
        bad = (100 * num * num * num + (den * den * den) // 2) // (den * den * den)
        return min(10000, bad)

    def _pageCost(self, total, goal, penalty, insert_penalties=0):
        badness = self._pageBadness(total, goal)
        if penalty >= 10000:
            return inf
        if penalty <= -10000:
            if badness == inf or insert_penalties >= 10000:
                return inf
            return penalty
        if badness == inf or insert_penalties >= 10000:
            return inf
        if badness == 10000:
            return 100000
        return badness + penalty + insert_penalties

    @staticmethod
    def _isNonDiscardable(node):
        if isinstance(node, PageStateNode):
            return False
        return node.node_type not in (
            nd.NODE_TYPE.GLUE,
            nd.NODE_TYPE.KERN,
            nd.NODE_TYPE.PENALTY,
        )

    @staticmethod
    def _isTransparent(node):
        return isinstance(node, PageStateNode)

    @classmethod
    def _previousRealNode(cls, nodes, start, index):
        index -= 1
        while index >= start and cls._isTransparent(nodes[index]):
            index -= 1
        return index

    @classmethod
    def _nextRealNode(cls, nodes, index):
        index += 1
        while index < len(nodes) and cls._isTransparent(nodes[index]):
            index += 1
        return index

    @classmethod
    def _isLegalBreak(cls, nodes, start, index):
        node = nodes[index]
        if node.node_type == nd.NODE_TYPE.PENALTY:
            return True
        if node.node_type == nd.NODE_TYPE.GLUE:
            prev = cls._previousRealNode(nodes, start, index)
            if prev < start:
                return False
            return cls._isNonDiscardable(nodes[prev])
        if node.node_type == nd.NODE_TYPE.KERN:
            nxt = cls._nextRealNode(nodes, index)
            return nxt < len(nodes) and nodes[nxt].node_type == nd.NODE_TYPE.GLUE
        return False

    @staticmethod
    def _hasDepth(node):
        return node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.RULE)

    @staticmethod
    def _effectiveTotal(total, bottom_depth, maxdepth):
        if bottom_depth is None:
            return total
        excess = bottom_depth - maxdepth
        if excess <= 0:
            return total
        return Glue(total.dimen - excess, total.stretch, total.shrink)

    @staticmethod
    def _prunePageTop(nodes, start, context):
        while start < len(nodes):
            node = nodes[start]
            if isinstance(node, PageStateNode):
                context = node.context
                start += 1
                continue
            if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY):
                start += 1
                continue
            break
        return start, context

    @staticmethod
    def _candidateBreak(index, include):
        end = index + 1 if include else index
        return end, index + 1

    def _bestPageBreak(self, nodes, start, context):
        total = Glue()
        topskip_added = False
        best = None
        bottom_depth = None
        current_context = context
        for i in range(start, len(nodes)):
            node = nodes[i]
            if isinstance(node, PageStateNode):
                current_context = node.context
                continue
            if not topskip_added:
                top = self._pageTopskip(current_context.topskip, node)
                if top is not None:
                    total = total + top
                    topskip_added = True
            if node.node_type == nd.NODE_TYPE.PENALTY:
                if node.penalty >= 10000:
                    continue
                effective = self._effectiveTotal(total, bottom_depth, current_context.maxdepth)
                cost = self._pageCost(effective, current_context.vsize, node.penalty)
                current = (cost, i, False, current_context)
                if best is None or cost <= best[0]:
                    best = current
                if cost == inf or node.penalty <= -10000:
                    _, index, include, best_context = best if best is not None else current
                    end, next_start = self._candidateBreak(index, include)
                    return end, next_start, best_context
                continue
            self._pageMeasure(total, node)
            if self._hasDepth(node):
                bottom_depth = node.depth
            if self._isLegalBreak(nodes, start, i):
                effective = self._effectiveTotal(total, bottom_depth, current_context.maxdepth)
                cost = self._pageCost(effective, current_context.vsize, 0)
                if best is None or cost <= best[0]:
                    best = (cost, i, True, current_context)
            if self._pageBadness(
                self._effectiveTotal(total, bottom_depth, current_context.maxdepth),
                current_context.vsize,
            ) == inf and best is not None:
                break
        if best is None:
            return len(nodes), len(nodes), current_context
        _, index, include, best_context = best
        end, next_start = self._candidateBreak(index, include)
        return end, next_start, best_context

    def _buildPage(self, parser, nodes, start, end, context):
        built = []
        topskip_added = False
        last_box = None
        current_context = context
        for node in nodes[start:end]:
            if isinstance(node, PageStateNode):
                current_context = node.context
                continue
            if not topskip_added:
                top = self._pageTopskip(current_context.topskip, node)
                if top is not None:
                    built.append(nd.Glue(top, "\\topskip"))
                    topskip_added = True
            built.append(node)
            if self._hasDepth(node):
                last_box = node
        if last_box is not None and last_box.depth > current_context.maxdepth:
            last_box.depth = current_context.maxdepth
        return built

    @staticmethod
    def _advanceContext(nodes, start, end, context):
        for node in nodes[start:end]:
            if isinstance(node, PageStateNode):
                context = node.context
        return context

    def pageBreak(self, parser):
        material = []
        self.typesetNodes(parser, material)
        pages = []
        context = self.page_initial_context
        start = 0
        while True:
            start, context = self._prunePageTop(material, start, context)
            if start >= len(material):
                break
            end, next_start, break_context = self._bestPageBreak(material, start, context)
            if end <= start:
                end = min(start + 1, len(material))
                next_start = end
                break_context = self._advanceContext(material, start, end, context)
            page = bx.VBox(parser, break_context.vsize, Dimen())
            page.list[:] = self._buildPage(parser, material, start, end, context)
            page.typeset(parser, [])
            pages.append(page)
            context = self._advanceContext(material, start, next_start, context)
            start = next_start
        return pages
