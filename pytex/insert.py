"""
Helpers for insertions and vertical-list splitting.
"""

from math import inf

from pytex import node as nd
from pytex.dimen import Dimen
from pytex.glue import Glue
from pytex.module import Module


class VListBreaker:
    """
    Common vertical-list breaking logic shared by page breaks and \\vsplit.
    """

    def __init__(self, nodes, initial_context):
        self.nodes = nodes
        self.initial_context = initial_context

    def contextFor(self, node):
        return None

    def isTransparent(self, node):
        return False

    def finalPenalty(self):
        return None

    @staticmethod
    def measure(total, node):
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
    def topskip(topskip, node):
        if node.node_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.RULE):
            return None
        dimen = topskip.dimen - node.height
        if dimen < 0:
            dimen = Dimen()
        return Glue(dimen, topskip.stretch, topskip.shrink)

    @staticmethod
    def badness(total, goal):
        delta = goal - total.dimen
        if delta == 0:
            return 0
        if delta > 0:
            stretch = total.stretch
            if stretch.factor == 0:
                return 10000
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

    def cost(self, total, goal, penalty, insert_penalties=0):
        badness = self.badness(total, goal)
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

    def isNonDiscardable(self, node):
        if self.isTransparent(node):
            return False
        return node.node_type not in (
            nd.NODE_TYPE.GLUE,
            nd.NODE_TYPE.KERN,
            nd.NODE_TYPE.PENALTY,
        )

    def previousRealNode(self, start, index):
        index -= 1
        while index >= start and self.isTransparent(self.nodes[index]):
            index -= 1
        return index

    def nextRealNode(self, index):
        index += 1
        while index < len(self.nodes) and self.isTransparent(self.nodes[index]):
            index += 1
        return index

    def isLegalBreak(self, start, index):
        node = self.nodes[index]
        if node.node_type == nd.NODE_TYPE.PENALTY:
            return True
        if node.node_type == nd.NODE_TYPE.GLUE:
            prev = self.previousRealNode(start, index)
            if prev < start:
                return False
            return self.isNonDiscardable(self.nodes[prev])
        if node.node_type == nd.NODE_TYPE.KERN:
            nxt = self.nextRealNode(index)
            return nxt < len(self.nodes) and self.nodes[nxt].node_type == nd.NODE_TYPE.GLUE
        return False

    @staticmethod
    def hasDepth(node):
        return node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST, nd.NODE_TYPE.RULE)

    @staticmethod
    def effectiveTotal(total, bottom_depth, maxdepth):
        if bottom_depth is None:
            return total
        excess = bottom_depth - maxdepth
        if excess <= 0:
            return total
        return Glue(total.dimen - excess, total.stretch, total.shrink)

    def pruneTop(self, start, context):
        while start < len(self.nodes):
            node = self.nodes[start]
            new_context = self.contextFor(node)
            if new_context is not None:
                context = new_context
                start += 1
                continue
            if self.isTransparent(node):
                start += 1
                continue
            if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY):
                start += 1
                continue
            break
        return start, context

    @staticmethod
    def candidateBreak(index, kind):
        if kind == "end":
            return index, index
        if kind == "kern":
            return index + 1, index + 1
        return index, index + 1

    def bestBreak(self, start, context):
        total = Glue()
        topskip_added = False
        best = None
        bottom_depth = None
        current_context = context
        for i in range(start, len(self.nodes)):
            node = self.nodes[i]
            new_context = self.contextFor(node)
            if new_context is not None:
                current_context = new_context
                continue
            if not topskip_added:
                top = self.topskip(current_context.topskip, node)
                if top is not None:
                    total = total + top
                    topskip_added = True
            if node.node_type == nd.NODE_TYPE.PENALTY:
                if node.penalty >= 10000:
                    continue
                effective = self.effectiveTotal(total, bottom_depth, current_context.maxdepth)
                cost = self.cost(effective, current_context.vsize, node.penalty)
                current = (cost, i, "penalty", current_context, node.penalty)
                if best is None or cost <= best[0]:
                    best = current
                if cost == inf or node.penalty <= -10000:
                    _, index, kind, best_context, best_penalty = best if best is not None else current
                    end, next_start = self.candidateBreak(index, kind)
                    return end, next_start, best_context, best_penalty
                continue
            self.measure(total, node)
            if self.hasDepth(node):
                bottom_depth = node.depth
            if self.isLegalBreak(start, i):
                effective = self.effectiveTotal(total, bottom_depth, current_context.maxdepth)
                cost = self.cost(effective, current_context.vsize, 0)
                if best is None or cost <= best[0]:
                    best = (cost, i, node.node_type.name.lower(), current_context, 0)
            if self.badness(
                self.effectiveTotal(total, bottom_depth, current_context.maxdepth),
                current_context.vsize,
            ) == inf and best is not None:
                break
        final_penalty = self.finalPenalty()
        if final_penalty is not None:
            effective = self.effectiveTotal(total, bottom_depth, current_context.maxdepth)
            cost = self.cost(effective, current_context.vsize, final_penalty)
            if best is None or cost <= best[0]:
                best = (cost, len(self.nodes), "end", current_context, final_penalty)
        if best is None:
            return len(self.nodes), len(self.nodes), current_context, 0
        _, index, kind, best_context, best_penalty = best
        end, next_start = self.candidateBreak(index, kind)
        return end, next_start, best_context, best_penalty

    def _buildSlice(self, start, end, context, topskip_name):
        built = []
        topskip_added = False
        last_box = None
        current_context = context
        for node in self.nodes[start:end]:
            new_context = self.contextFor(node)
            if new_context is not None:
                current_context = new_context
                continue
            if self.isTransparent(node):
                continue
            if topskip_name is not None and not topskip_added:
                top = self.topskip(current_context.topskip, node)
                if top is not None:
                    built.append(nd.Glue(top, topskip_name))
                    topskip_added = True
            built.append(node)
            if self.hasDepth(node):
                last_box = node
        if last_box is not None and last_box.depth > current_context.maxdepth:
            last_box.depth = current_context.maxdepth
        return built

    def buildSlice(self, start, end, context, topskip_name):
        return self._buildSlice(start, end, context, topskip_name)

    def buildRawSlice(self, start, end, context):
        return self._buildSlice(start, end, context, None)

    def advanceContext(self, start, end, context):
        for node in self.nodes[start:end]:
            new_context = self.contextFor(node)
            if new_context is not None:
                context = new_context
        return context


mod = Module("insert")
