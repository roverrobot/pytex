"""
Page breaking for the main vertical list.
"""


from math import inf

from pytex import box as bx
from pytex import lexer
from pytex import node as nd
from pytex import vmode
from pytex.dimen import Dimen
from pytex.glue import Glue
from pytex.lists import LISTTYPE
from pytex.module import Module
from pytex.state import GROUP_TYPE
from pytex.token import Command, Token


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


class Shipout:
    """
    Default shipout collector.
    """

    def __init__(self, parser, output=None):
        self.pages = []

    def shipout(self, box):
        self.pages.append(box)

    def __enter__(self):
        self.open()
        return self
    
    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def open(self):
        pass

    def close(self):
        pass


def shipout(parser, box):
    """
    Ship out a box and perform the runtime bookkeeping TeX does around \\shipout.
    """
    backend = getattr(parser, "shipout", None)
    if backend is None:
        if parser.lists and isinstance(parser.lists[0], MainVList):
            parser.lists[0].append(ShipoutNode(box))
            return
        raise ValueError("no active shipout backend")
    backend.shipout(box.typeset(parser))
    parser.state.globals["deadcycles"] = 0


class ShipOutCommand(vmode.VerticalCommand):
    """
    The \\shipout command.
    """

    def vertical(self, parser, vlist):
        box = parser.readBox()
        if box is None:
            return
        shipout(parser, box)


class OutputRoutineEndCallback:
    """
    Pop the temporary output list when the output routine group ends.
    """

    def __init__(self, parser, vlist):
        self.parser = parser
        self.vlist = vlist

    def __call__(self):
        if self.parser.lists and self.parser.lists[-1] is self.vlist:
            self.parser.lists.pop()


class EndOutputRoutineToken(Token):
    """
    Internal token that stops a nested parser.loop() for an output routine.
    """

    def __init__(self):
        super().__init__("\\endoutput", None)

    def execute(self, parser):
        parser.run = False


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


class ShipoutNode(nd.Node):
    """
    Transparent marker for a deferred \\shipout in the main vertical list.
    """

    node_type = nd.NODE_TYPE.WHATSIT

    def __init__(self, box):
        self.box = box

    def saveInfo(self):
        return {"init": {"box": self.box}}

    @classmethod
    def new(cls, parser, box):
        return cls(box)

    def __repr__(self):
        return "Shipout"


class MainVListBreaker(VListBreaker):
    def contextFor(self, node):
        if isinstance(node, PageStateNode):
            return node.context
        return None

    def isTransparent(self, node):
        return isinstance(node, (PageStateNode, ShipoutNode))


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
        if isinstance(node, (PageStateNode, ShipoutNode)):
            return False
        return node.node_type not in (
            nd.NODE_TYPE.GLUE,
            nd.NODE_TYPE.KERN,
            nd.NODE_TYPE.PENALTY,
        )

    @staticmethod
    def _isTransparent(node):
        return isinstance(node, (PageStateNode, ShipoutNode))

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
            if isinstance(node, ShipoutNode):
                start += 1
                continue
            if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY):
                start += 1
                continue
            break
        return start, context

    @staticmethod
    def _candidateBreak(index, kind):
        if kind == "kern":
            return index + 1, index + 1
        return index, index + 1

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
                current = (cost, i, "penalty", current_context, node.penalty)
                if best is None or cost <= best[0]:
                    best = current
                if cost == inf or node.penalty <= -10000:
                    _, index, kind, best_context, best_penalty = best if best is not None else current
                    end, next_start = self._candidateBreak(index, kind)
                    return end, next_start, best_context, best_penalty
                continue
            self._pageMeasure(total, node)
            if self._hasDepth(node):
                bottom_depth = node.depth
            if self._isLegalBreak(nodes, start, i):
                effective = self._effectiveTotal(total, bottom_depth, current_context.maxdepth)
                cost = self._pageCost(effective, current_context.vsize, 0)
                if best is None or cost <= best[0]:
                    best = (cost, i, node.node_type.name.lower(), current_context, 0)
            if self._pageBadness(
                self._effectiveTotal(total, bottom_depth, current_context.maxdepth),
                current_context.vsize,
            ) == inf and best is not None:
                break
        if best is None:
            return len(nodes), len(nodes), current_context, 0
        _, index, kind, best_context, best_penalty = best
        end, next_start = self._candidateBreak(index, kind)
        return end, next_start, best_context, best_penalty

    def _buildPage(self, parser, nodes, start, end, context):
        built = []
        topskip_added = False
        last_box = None
        current_context = context
        for node in nodes[start:end]:
            if isinstance(node, PageStateNode):
                current_context = node.context
                continue
            if isinstance(node, ShipoutNode):
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

    @staticmethod
    def _pageMarks(nodes, start, end, topmark):
        first = None
        bot = None
        for node in nodes[start:end]:
            if isinstance(node, ShipoutNode):
                continue
            if node.node_type != nd.NODE_TYPE.MARK:
                continue
            mark = list(node.tokens)
            if first is None:
                first = mark
            bot = mark
        if first is None:
            first = list(topmark)
            bot = list(topmark)
        return first, bot

    @staticmethod
    def _shipLeading(nodes, start, context, parser):
        while start < len(nodes):
            node = nodes[start]
            if isinstance(node, PageStateNode):
                context = node.context
                start += 1
                continue
            if isinstance(node, ShipoutNode):
                shipout(parser, node.box)
                start += 1
                continue
            break
        return start, context

    @staticmethod
    def _pageShipouts(nodes, start, end):
        return [node.box for node in nodes[start:end] if isinstance(node, ShipoutNode)]

    @staticmethod
    def _runNestedLoop(parser):
        saved = parser.run
        parser.run = True
        try:
            parser.loop()
        finally:
            parser.run = saved

    def _runOutputRoutine(self, parser, page):
        output = parser.output.value
        parser.state.box[255] = page
        if not output:
            parser.state.globals["deadcycles"] += 1
            shipout(parser, page)
            parser.state.box[255] = None
            return []
        if parser.state.globals["deadcycles"] >= parser.state.parameters["maxdeadcycles"]:
            parser.message(
                f"Output loop---{parser.state.globals['deadcycles']} consecutive dead cycles"
            )
            parser.state.globals["deadcycles"] += 1
            shipout(parser, page)
            parser.state.box[255] = None
            return []
        parser.state.globals["deadcycles"] += 1
        outlist = vmode.VList(parser)
        parser.lists.append(outlist)
        parser.beginGroup(
            parser.input.position(),
            GROUP_TYPE.OUTPUT,
            OutputRoutineEndCallback(parser, outlist),
        )
        parser.input.push(lexer.TokenListScanner([EndOutputRoutineToken()]))
        parser.input.push(lexer.TokenListScanner(output))
        self._runNestedLoop(parser)
        top = parser.lists[-1]
        if top.type == LISTTYPE.HORIZONTAL:
            if top.inner:
                raise ValueError("output routine ended in internal horizontal mode")
            parser.endParagraph()
            top = parser.lists[-1]
        elif top.type == LISTTYPE.MATH:
            raise ValueError("output routine ended in math mode")
        if top is not outlist:
            raise ValueError("output routine did not end in internal vertical mode")
        if parser.state.current_group.aftergroup:
            raise NotImplementedError("aftergroup in the output routine is not implemented yet")
        parser.endGroup(parser.input.position(), GROUP_TYPE.OUTPUT)
        parser.state.box[255] = None
        carry = []
        outlist.typesetNodes(parser, carry)
        return carry

    def pageBreak(self, parser):
        material = []
        self.typesetNodes(parser, material)
        breaker = MainVListBreaker(material, self.page_initial_context)
        pages = []
        context = self.page_initial_context
        topmark = list(parser.state.parameters["botmark"])
        start = 0
        while True:
            start, context = breaker.pruneTop(start, context)
            if start >= len(material):
                break
            end, next_start, break_context, break_penalty = breaker.bestBreak(start, context)
            if end <= start:
                end = min(start + 1, len(material))
                next_start = end
                break_context = breaker.advanceContext(start, end, context)
                break_penalty = 0
            page = bx.VBox(parser, break_context.vsize, Dimen())
            firstmark, botmark = self._pageMarks(material, start, end, topmark)
            # The page material is already fully typeset. Keep it as a plain list so
            # VBox.pretypeset() computes box dimensions without re-running
            # VList.typesetNodes() and duplicating interline penalties/glue.
            page.list[:] = breaker.buildSlice(start, end, context, "\\topskip")
            pages.append(page.typeset(parser))
            parser.state.layout["outputpenalty"] = break_penalty
            parser.state.parameters["topmark"] = list(topmark)
            parser.state.parameters["firstmark"] = list(firstmark)
            parser.state.parameters["botmark"] = list(botmark)
            topmark = list(botmark)
            context = breaker.advanceContext(start, next_start, context)
            start = next_start
        return pages

    def outputPages(self, parser):
        material = []
        self.typesetNodes(parser, material)
        breaker = MainVListBreaker(material, self.page_initial_context)
        shipped = len(parser.shipout.pages)
        context = self.page_initial_context
        topmark = list(parser.state.parameters["botmark"])
        start = 0
        while True:
            start, context = self._shipLeading(material, start, context, parser)
            start, context = breaker.pruneTop(start, context)
            if start >= len(material):
                break
            end, next_start, break_context, break_penalty = breaker.bestBreak(start, context)
            if end <= start:
                end = min(start + 1, len(material))
                next_start = end
                break_context = breaker.advanceContext(start, end, context)
                break_penalty = 0
            page = bx.VBox(parser, break_context.vsize, Dimen())
            firstmark, botmark = self._pageMarks(material, start, end, topmark)
            parser.state.parameters["topmark"] = list(topmark)
            parser.state.parameters["firstmark"] = list(firstmark)
            parser.state.parameters["botmark"] = list(botmark)
            parser.state.layout["outputpenalty"] = break_penalty
            for box in self._pageShipouts(material, start, end):
                shipout(parser, box)
            # Keep the built page material as a plain list; it is already packed.
            page.list[:] = breaker.buildSlice(start, end, context, "\\topskip")
            carry = self._runOutputRoutine(parser, page.typeset(parser))
            if carry:
                material[next_start:next_start] = carry
            topmark = list(botmark)
            context = breaker.advanceContext(start, next_start, context)
            start = next_start
        return parser.shipout.pages[shipped:]


class VSplitContext:
    """
    Context used by the generic vertical-list breaker for \\vsplit.
    """

    def __init__(self, vsize, topskip, maxdepth):
        self.vsize = Dimen(vsize)
        self.topskip = topskip
        self.maxdepth = maxdepth


class VSplitBreaker(VListBreaker):
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
    parser.state.globals["insert"] = [[] for _ in range(256)]


class VSplit(Command):
    """
    The \\vsplit command.
    """

    def boxValue(self, parser, setbox):
        index = parser.readInteger()
        spec, dim = parser.readBoxSpec(["to"])
        if spec != "to":
            raise ValueError("expecting \\vsplit<number> to <dimen>", parser.input.position())
        source = parser.state.box[index]
        if source is None:
            return None
        if source.node_type != nd.NODE_TYPE.VLIST:
            raise ValueError("expecting a vbox", parser.input.position())
        source = source.typeset(parser)
        nodes = list(source.list)
        split_context = VSplitContext(
            dim,
            Glue(),
            parser.state.layout["splitmaxdepth"],
        )
        breaker = VSplitBreaker(nodes, split_context)
        start, split_context = breaker.pruneTop(0, split_context)
        if start >= len(nodes):
            parser.state.box[index] = None
            return None
        end, next_start, break_context, _ = breaker.bestBreak(start, split_context)
        if end <= start:
            end = min(start + 1, len(nodes))
            next_start = end
            break_context = breaker.advanceContext(start, end, split_context)
        result = bx.VBox(parser, break_context.vsize, Dimen())
        result.list[:] = breaker.buildRawSlice(start, end, split_context)
        remainder_context = VSplitContext(
            Dimen(),
            parser.state.layout["splittopskip"],
            parser.state.layout["boxmaxdepth"],
        )
        next_start, _ = breaker.pruneTop(next_start, remainder_context)
        if next_start >= len(nodes):
            parser.state.box[index] = None
        else:
            remainder = bx.VBox(parser, None, Dimen())
            remainder.list[:] = breaker.buildSlice(next_start, len(nodes), remainder_context, "\\splittopskip")
            parser.state.box[index] = remainder.typeset(parser)
        return result

    def execute(self, parser):
        box = self.boxValue(parser, False)
        if box is not None:
            parser.lists[-1].append(box)


class Insert(Command):
    """
    The \\insert command.
    """

    def execute(self, parser):
        index = parser.readInteger()
        if index < 0 or index == 255:
            raise ValueError(f"invalid insert number {index}", parser.input.position())
        top = parser.lists[-1]
        vlist = parser.readVList(GROUP_TYPE.INSERT)
        top.append(nd.Insert(index, vlist))


mod = Module(
    "page",
    init=init,
    commands={
        "insert": Insert(),
        "shipout": ShipOutCommand(),
        "vsplit": VSplit(),
    },
    attributes={
        "shipout_class": Shipout,
    }
)
