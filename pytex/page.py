"""
Page breaking for the main vertical list.
"""


from math import inf

from pytex import box as bx
from pytex import accessor
from pytex import node as nd
from pytex import vmode
from pytex.dimen import Dimen
from pytex.glue import Glue
from pytex.module import Module
from pytex.state import GROUP_TYPE
from pytex.token import Command, Token


def _set_mark_class(register, index, tokens):
    while len(register) <= index:
        register.append([])
    register[index] = list(tokens)


class VerticalBreaker:
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

    def measureBeforeTopskip(self, node):
        return False

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

    @classmethod
    def _isTopDiscardable(cls, node):
        return node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY)

    @staticmethod
    def _delaysPageStart(node):
        return node.node_type in (nd.NODE_TYPE.WHATSIT, nd.NODE_TYPE.MARK)

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

    @staticmethod
    def pendingTotal(total, bottom_depth):
        if bottom_depth is None:
            return total
        return Glue(total.dimen - bottom_depth, total.stretch, total.shrink)

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
        delayed_start = False
        best = None
        bottom_depth = None
        current_context = context
        triggered = False
        for i in range(start, len(self.nodes)):
            node = self.nodes[i]
            new_context = self.contextFor(node)
            if new_context is not None:
                current_context = new_context
                continue
            if not topskip_added:
                if self._isTopDiscardable(node):
                    if delayed_start and self.isLegalBreak(start, i):
                        penalty = node.penalty if node.node_type == nd.NODE_TYPE.PENALTY else 0
                        effective = self.pendingTotal(total, bottom_depth)
                        cost = self.cost(effective, current_context.vsize, penalty)
                        current = (
                            cost,
                            i,
                            node.node_type.name.lower(),
                            current_context,
                            penalty,
                        )
                        if best is None or cost <= best[0]:
                            best = current
                        if node.node_type == nd.NODE_TYPE.PENALTY and (
                            cost == inf or node.penalty <= -10000
                        ):
                            _, index, kind, best_context, best_penalty = current
                            end, next_start = self.candidateBreak(index, kind)
                            return end, next_start, best_context, best_penalty, True
                    if delayed_start and node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
                        self.measure(total, node)
                    continue
                top = self.topskip(current_context.topskip, node)
                if top is not None:
                    total = total + top
                    topskip_added = True
                elif not self._delaysPageStart(node):
                    topskip_added = True
                else:
                    delayed_start = True
            if not topskip_added:
                if self.measureBeforeTopskip(node):
                    self.measure(total, node)
                continue
            if node.node_type == nd.NODE_TYPE.PENALTY:
                if node.penalty >= 10000:
                    continue
                effective = self.pendingTotal(total, bottom_depth)
                cost = self.cost(effective, current_context.vsize, node.penalty)
                current = (cost, i, "penalty", current_context, node.penalty)
                if best is None or cost <= best[0]:
                    best = current
                if cost == inf or node.penalty <= -10000:
                    _, index, kind, best_context, best_penalty = best if best is not None else current
                    end, next_start = self.candidateBreak(index, kind)
                    return end, next_start, best_context, best_penalty, True
                continue
            before_total = total.copy()
            before_bottom_depth = bottom_depth
            self.measure(total, node)
            if self.hasDepth(node):
                bottom_depth = node.depth
            elif node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
                bottom_depth = None
            if self.isLegalBreak(start, i):
                break_total = before_total if node.node_type == nd.NODE_TYPE.GLUE else total
                break_depth = before_bottom_depth if node.node_type == nd.NODE_TYPE.GLUE else bottom_depth
                effective = self.pendingTotal(break_total, break_depth)
                cost = self.cost(effective, current_context.vsize, 0)
                if best is None or cost <= best[0]:
                    best = (cost, i, node.node_type.name.lower(), current_context, 0)
                if cost == inf:
                    triggered = True
                    break
        final_penalty = self.finalPenalty()
        if final_penalty is not None:
            effective = self.pendingTotal(total, bottom_depth)
            cost = self.cost(effective, current_context.vsize, final_penalty)
            if best is None or cost <= best[0]:
                best = (cost, len(self.nodes), "end", current_context, final_penalty)
        if best is None:
            return len(self.nodes), len(self.nodes), current_context, 0, False
        _, index, kind, best_context, best_penalty = best
        end, next_start = self.candidateBreak(index, kind)
        return end, next_start, best_context, best_penalty, triggered

    def _buildSlice(self, start, end, context, topskip_name):
        built = []
        topskip_added = False
        current_context = context
        for node in self.nodes[start:end]:
            new_context = self.contextFor(node)
            if new_context is not None:
                current_context = new_context
                continue
            if self.isTransparent(node):
                continue
            if not topskip_added:
                if self._isTopDiscardable(node):
                    continue
                if topskip_name is not None:
                    top = self.topskip(current_context.topskip, node)
                    if top is not None:
                        built.append(nd.Glue(top, topskip_name))
                        topskip_added = True
                    elif not self._delaysPageStart(node):
                        topskip_added = True
                elif not self._delaysPageStart(node):
                    topskip_added = True
            built.append(node)
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


def shipout(parser, box):
    """
    Ship out a box and perform the runtime bookkeeping TeX does around \\shipout.
    """
    backend = getattr(parser, "shipout", None)
    if backend is None:
        raise ValueError("no active shipout backend")
    parser.traceOutputPage(box)
    backend.shipout(box)
    parser.globals["deadcycles"] = 0


class ShipOutCommand(vmode.VerticalCommand):
    """
    The \\shipout command.
    """

    def vertical(self, parser, vlist):
        box = parser.readBox()
        if box is None:
            return
        shipout(parser, box)


class VSplitContext:
    """
    Context used by the generic vertical-list breaker for \\vsplit.
    """

    def __init__(self, vsize, topskip, maxdepth):
        self.vsize = Dimen(vsize)
        self.topskip = topskip
        self.maxdepth = maxdepth


class VSplitBreaker(VerticalBreaker):
    """
    Vertical-list breaker for \\vsplit. Unlike page breaking, the end of the
    source list acts as an implicit \\penalty-10000 breakpoint.
    """

    def finalPenalty(self):
        return -10000


def init(parser):
    """
    Runtime scratch storage for insertion classes during page building.
    """
    parser.globals["insert"] = [[] for _ in range(256)]


class VSplit(Command):
    """
    The \\vsplit command.
    """

    def readValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.BOX, requested_type):
            return None, None
        index = parser.readInteger()
        spec, dim = parser.readBoxSpec(["to"])
        if spec != "to":
            raise ValueError("expecting \\vsplit<number> to <dimen>", parser.input.position())
        splitfirst = None
        splitbot = None
        splitfirstmarks = parser.globals.get("splitfirstmarks")
        splitbotmarks = parser.globals.get("splitbotmarks")
        split_seen = set()
        if splitfirstmarks is not None:
            splitfirstmarks = [[]]
            splitbotmarks = [[]]
        source = parser.box[index]
        if source is None:
            parser.globals["splitfirstmark"] = []
            parser.globals["splitbotmark"] = []
            if splitfirstmarks is not None:
                parser.globals["splitfirstmarks"] = splitfirstmarks
                parser.globals["splitbotmarks"] = splitbotmarks
            return None, accessor.VALUE_TYPE.BOX
        if source.node_type != nd.NODE_TYPE.VLIST:
            raise ValueError("expecting a vbox", parser.input.position())
        source = source.typeset(parser)
        nodes = list(source.list)
        split_context = VSplitContext(
            dim,
            Glue(),
            parser.layout["splitmaxdepth"],
        )
        breaker = VSplitBreaker(nodes, split_context)
        start, split_context = breaker.pruneTop(0, split_context)
        if start >= len(nodes):
            parser.box[index] = None
            parser.globals["splitfirstmark"] = []
            parser.globals["splitbotmark"] = []
            if splitfirstmarks is not None:
                parser.globals["splitfirstmarks"] = splitfirstmarks
                parser.globals["splitbotmarks"] = splitbotmarks
            return None, accessor.VALUE_TYPE.BOX
        end, next_start, break_context, _, _ = breaker.bestBreak(start, split_context)
        if end <= start:
            end = min(start + 1, len(nodes))
            next_start = end
            break_context = breaker.advanceContext(start, end, split_context)
        for node in nodes[start:end]:
            if node.node_type != nd.NODE_TYPE.MARK:
                continue
            mark_index = getattr(node, "index", 0)
            mark = list(node.tokens)
            if splitfirstmarks is None:
                assert mark_index == 0, "nonzero mark nodes require the etex module"
            else:
                if mark_index not in split_seen:
                    _set_mark_class(splitfirstmarks, mark_index, mark)
                    split_seen.add(mark_index)
                _set_mark_class(splitbotmarks, mark_index, mark)
            if mark_index != 0:
                continue
            if splitfirst is None:
                splitfirst = mark
            splitbot = mark
        parser.globals["splitfirstmark"] = [] if splitfirst is None else splitfirst
        parser.globals["splitbotmark"] = [] if splitbot is None else splitbot
        if splitfirstmarks is not None:
            parser.globals["splitfirstmarks"] = splitfirstmarks
            parser.globals["splitbotmarks"] = splitbotmarks
        result = bx.VBox(parser, break_context.vsize, None)
        result.list[:] = breaker.buildRawSlice(start, end, split_context)
        remainder_context = VSplitContext(
            Dimen(),
            parser.layout["splittopskip"],
            parser.layout["boxmaxdepth"],
        )
        next_start, _ = breaker.pruneTop(next_start, remainder_context)
        if next_start >= len(nodes):
            parser.box[index] = None
        else:
            remainder = bx.VBox(parser, None, Dimen())
            remainder.list[:] = breaker.buildSlice(next_start, len(nodes), remainder_context, "\\splittopskip")
            parser.box[index] = remainder.typeset(parser, maxdepth=remainder_context.maxdepth)
        return result.typeset(parser, maxdepth=break_context.maxdepth), accessor.VALUE_TYPE.BOX

    def execute(self, parser):
        box, _ = self.readValue(parser, accessor.VALUE_TYPE.BOX)
        if box is not None:
            parser.lists[-1].append(box)


class Insert(Command):
    """
    The \\insert command.
    """

    def execute(self, parser):
        index = parser.readInteger()
        if index < 0 or index >= 255:
            raise ValueError(f"invalid insert number {index}", parser.input.position())
        top = parser.lists[-1]
        vlist = parser.readVList(GROUP_TYPE.INSERT)
        top.append(vmode.Insert(index, vlist))


mod = Module(
    "page",
    init=init,
    commands={
        "insert": Insert(),
        "shipout": ShipOutCommand(),
        "vsplit": VSplit(),
    }
)
