"""
Page breaking for the main vertical list.
"""


from math import inf

from pytex import box as bx
from pytex import node as nd
from pytex import vmode
from pytex.glue import Glue
from pytex.dimen import Dimen


class MainVList(vmode.VList):
    """
    The document's main vertical list.
    """

    def __init__(self, parser):
        super().__init__(parser, inner=False)

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
        if node.node_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
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
        return node.node_type not in (
            nd.NODE_TYPE.GLUE,
            nd.NODE_TYPE.KERN,
            nd.NODE_TYPE.PENALTY,
        )

    @classmethod
    def _isLegalBreak(cls, nodes, start, index):
        node = nodes[index]
        if node.node_type == nd.NODE_TYPE.PENALTY:
            return True
        if node.node_type == nd.NODE_TYPE.GLUE:
            if index <= start:
                return False
            return cls._isNonDiscardable(nodes[index - 1])
        if node.node_type == nd.NODE_TYPE.KERN:
            return index + 1 < len(nodes) and nodes[index + 1].node_type == nd.NODE_TYPE.GLUE
        return False

    @staticmethod
    def _prunePageTop(nodes, start):
        while start < len(nodes) and nodes[start].node_type in (
            nd.NODE_TYPE.GLUE,
            nd.NODE_TYPE.KERN,
            nd.NODE_TYPE.PENALTY,
        ):
            start += 1
        return start

    def _bestPageBreak(self, nodes, start, goal, topskip):
        total = Glue()
        topskip_added = False
        best = None
        for i in range(start, len(nodes)):
            node = nodes[i]
            if not topskip_added:
                top = self._pageTopskip(topskip, node)
                if top is not None:
                    total = total + top
                    topskip_added = True
            if node.node_type == nd.NODE_TYPE.PENALTY:
                if node.penalty >= 10000:
                    continue
                cost = self._pageCost(total, goal, node.penalty)
                current = (cost, i, False)
                if best is None or cost <= best[0]:
                    best = current
                if node.penalty <= -10000:
                    return best if best is not None else current
                continue
            self._pageMeasure(total, node)
            if self._isLegalBreak(nodes, start, i):
                cost = self._pageCost(total, goal, 0)
                if best is None or cost <= best[0]:
                    best = (cost, i, True)
            if self._pageBadness(total, goal) == inf and best is not None:
                break
        if best is None:
            return len(nodes), len(nodes)
        _, index, include = best
        end = index + 1 if include else index
        return end, index + 1

    def _buildPage(self, parser, nodes, start, end):
        built = []
        topskip = parser.state.layout["topskip"]
        topskip_added = False
        for node in nodes[start:end]:
            if not topskip_added:
                top = self._pageTopskip(topskip, node)
                if top is not None:
                    built.append(nd.Glue(top, "\\topskip"))
                    topskip_added = True
            built.append(node)
        return built

    def pageBreak(self, parser):
        material = []
        self.typesetNodes(parser, material)
        pages = []
        goal = parser.state.layout["vsize"]
        topskip = parser.state.layout["topskip"]
        start = 0
        while True:
            start = self._prunePageTop(material, start)
            if start >= len(material):
                break
            end, next_start = self._bestPageBreak(material, start, goal, topskip)
            if end <= start:
                end = min(start + 1, len(material))
                next_start = end
            page = bx.VBox(parser, goal, Dimen())
            page.list[:] = self._buildPage(parser, material, start, end)
            page.typeset(parser, [])
            pages.append(page)
            start = next_start
        return pages
