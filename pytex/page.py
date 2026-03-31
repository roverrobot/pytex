"""
Page breaking for the main vertical list.
"""


from fractions import Fraction
from math import inf

from pytex import box as bx
from pytex import accessor
from pytex import lexer
from pytex import node as nd
from pytex import vmode
from pytex.dimen import Dimen
from pytex.glue import Glue
from pytex.lists import LISTTYPE
from pytex.module import Module
from pytex.state import GROUP_TYPE
from pytex.token import Command, Token
from pytex.paragraph import Paragraph
from pytex.align import HAlignment, MAlignment
from pytex.mmode import DisplayMathNode


def _copy_mark_register(register):
    return [list(mark) for mark in register]


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


class Shipout:
    """
    Default shipout collector.
    """

    def __init__(self, parser, output=None):
        self.parser = parser
        self.output = output
        self.pages = []

    def shipout(self, box):
        self._flushWhatsits(box)
        self.pages.append(box)

    def _flushWhatsits(self, box):
        items = getattr(box, "list", None)
        if items is None:
            return
        for node in items:
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._flushWhatsits(node)
                continue
            if node.node_type == nd.NODE_TYPE.WHATSIT:
                node.output(self.parser, self)

    def special(self, text):
        pass

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
        raise ValueError("no active shipout backend")
    if getattr(box, "_packed", None) is box:
        shipped_box = box
    else:
        shipped_box = box.typeset(parser)
    parser.traceOutputPage(shipped_box)
    backend.shipout(shipped_box)
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


class OutputRoutineEndCallback:
    """
    Pop the temporary output list when the output routine group ends.
    """

    def __init__(self, vlist):
        self.vlist = vlist

    def __call__(self, parser):
        if parser.lists and parser.lists[-1] is self.vlist:
            parser.lists.pop()


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


class PageBreaker(VerticalBreaker):
    def __init__(self, parser, nodes, initial_context):
        super().__init__(nodes, initial_context)
        self.parser = parser
        self._insert_boxes = {}
        self._register_box_heights = {}
        self._insert_actions = {}
        self.last_insert_penalties = 0

    @staticmethod
    def _delaysPageStart(node):
        return node.node_type in (nd.NODE_TYPE.WHATSIT, nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS)

    def insertBox(self, node):
        cache_key = id(node)
        box = self._insert_boxes.get(cache_key)
        if box is not None:
            return box
        box = bx.VBox(self.parser, None, Dimen())
        box.list[:] = list(node.list)
        box = box.typeset(self.parser)
        self._insert_boxes[cache_key] = box
        return box

    def _registerBoxHeight(self, index):
        cached = self._register_box_heights.get(index)
        if cached is not None:
            return cached
        box = self.parser.box[index]
        if box is None:
            h = Dimen()
        else:
            box = box.typeset(self.parser)
            if box.node_type != nd.NODE_TYPE.VLIST:
                raise ValueError(f"insert box {index} must be a vbox", self.parser.input.position())
            h = box.height + box.depth
        self._register_box_heights[index] = h
        return h

    @staticmethod
    def _insertNatural(box):
        return box.height + box.depth

    @staticmethod
    def _fitsWithShrink(goal, total_dimen, shrink, delta):
        if delta <= 0:
            return True
        if total_dimen + delta <= goal:
            return True
        shortfall = total_dimen + delta - goal
        if shrink.order > 0 and shrink.factor > 0:
            return True
        if shrink.order == 0 and shortfall <= shrink.factor:
            return True
        return False

    def _splitInsertion(self, node, target):
        source = self.insertBox(node)
        nodes = list(source.list)
        split_context = VSplitContext(
            target,
            Glue(),
            self.parser.layout["splitmaxdepth"],
        )
        breaker = VSplitBreaker(nodes, split_context)
        start, split_context = breaker.pruneTop(0, split_context)
        if start >= len(nodes):
            return None, [], Dimen(), 0
        end, next_start, break_context, break_penalty, _ = breaker.bestBreak(start, split_context)
        if end <= start:
            end = min(start + 1, len(nodes))
            next_start = end
            break_context = breaker.advanceContext(start, end, split_context)
            break_penalty = 0
        head = bx.VBox(self.parser, None, Dimen())
        head.list[:] = breaker.buildRawSlice(start, end, split_context)
        head = head.typeset(self.parser)
        used = self._insertNatural(head)
        tail = [] if next_start >= len(nodes) else list(nodes[next_start:])
        return head, tail, used, break_penalty

    def _classState(self, index, class_states):
        state = class_states.get(index)
        if state is not None:
            return state
        state = {
            "seen": False,
            "split": False,
            "base": self._registerBoxHeight(index),
            "inserted": Dimen(),
        }
        class_states[index] = state
        return state

    def _processInsert(
        self,
        node,
        total,
        bottom_depth,
        goal,
        goal_adjust,
        insert_penalties,
        class_states,
        context,
    ):
        index = node.index
        state = self._classState(index, class_states)
        f_count = int(self.parser.count[index])
        f = Fraction(f_count, 1000)
        limit = self.parser.dimen[index]
        skip = self.parser.skip[index]
        if not state["seen"]:
            # Step 1: reserve existing insert box and insertion skip glue.
            delta = state["base"] * f + skip.dimen
            goal_adjust += delta
            goal = context.vsize - goal_adjust
            total.stretch = total.stretch + skip.stretch
            total.shrink = total.shrink + skip.shrink
            state["seen"] = True
        if state["split"]:
            # Step 2: once split, later inserts of the same class defer and
            # contribute floatingpenalty to insert penalties.
            insert_penalties += int(self.parser.layout["floatingpenalty"])
            action = {"kind": "defer", "index": index}
            return goal, goal_adjust, insert_penalties, action

        insert_box = self.insertBox(node)
        x = self._insertNatural(insert_box)
        xf = x * f
        fits_box = state["base"] + state["inserted"] + x <= limit
        effective = self.effectiveTotal(total, bottom_depth, context.maxdepth)
        fits_page = self._fitsWithShrink(goal, effective.dimen, effective.shrink, xf)
        if fits_box and fits_page:
            # Step 3: full insertion fits.
            goal_adjust += xf
            goal = context.vsize - goal_adjust
            state["inserted"] += x
            action = {
                "kind": "full",
                "index": index,
                "head": insert_box,
                "tail": [],
                "used": x,
                "penalty": 0,
            }
            return goal, goal_adjust, insert_penalties, action

        # Step 4: split insertion tentatively.
        available_box = limit - (state["base"] + state["inserted"])
        if available_box < 0:
            available_box = Dimen()
        if f > 0:
            available_page = goal - effective.dimen
            available_page = available_page / f
            v = available_box if available_box <= available_page else available_page
        else:
            v = available_box
        if v < 0:
            v = Dimen()
        head, tail, used, split_penalty = self._splitInsertion(node, v)
        goal_adjust += used * f
        goal = context.vsize - goal_adjust
        insert_penalties += split_penalty
        state["inserted"] += used
        state["split"] = len(tail) > 0
        action = {
            "kind": "split",
            "index": index,
            "head": head,
            "tail": tail,
            "used": used,
            "penalty": split_penalty,
        }
        return goal, goal_adjust, insert_penalties, action

    def actionFor(self, node):
        return self._insert_actions.get(id(node))

    def bestBreak(self, start, context):
        total = Glue()
        topskip_added = False
        best = None
        bottom_depth = None
        current_context = context
        goal_adjust = Dimen()
        goal = current_context.vsize
        insert_penalties = 0
        class_states = {}
        actions = {}
        triggered = False

        for i in range(start, len(self.nodes)):
            node = self.nodes[i]
            new_context = self.contextFor(node)
            if new_context is not None:
                current_context = new_context
                goal = current_context.vsize - goal_adjust
                continue
            if not topskip_added:
                if self._isTopDiscardable(node):
                    continue
                top = self.topskip(current_context.topskip, node)
                if top is not None:
                    total = total + top
                    topskip_added = True
                elif not self._delaysPageStart(node):
                    topskip_added = True
            if node.node_type == nd.NODE_TYPE.INS:
                goal, goal_adjust, insert_penalties, action = self._processInsert(
                    node,
                    total,
                    bottom_depth,
                    goal,
                    goal_adjust,
                    insert_penalties,
                    class_states,
                    current_context,
                )
                actions[id(node)] = action
                continue
            if not topskip_added:
                continue
            if node.node_type == nd.NODE_TYPE.PENALTY:
                if node.penalty >= 10000:
                    continue
                effective = self.pendingTotal(total, bottom_depth)
                cost = self.cost(effective, goal, node.penalty, insert_penalties)
                current = (
                    cost,
                    i,
                    "penalty",
                    current_context,
                    node.penalty,
                    insert_penalties,
                )
                if best is None or cost <= best[0]:
                    best = current
                if cost == inf or node.penalty <= -10000:
                    self._insert_actions = actions
                    if best is None:
                        self.last_insert_penalties = insert_penalties
                        end, next_start = self.candidateBreak(i, "penalty")
                        return end, next_start, current_context, node.penalty, True
                    _, index, kind, best_context, best_penalty, best_q = best
                    self.last_insert_penalties = best_q
                    end, next_start = self.candidateBreak(index, kind)
                    return end, next_start, best_context, best_penalty, True
                continue
            before_total = total.copy()
            self.measure(total, node)
            if self.hasDepth(node):
                bottom_depth = node.depth
            if self.isLegalBreak(start, i):
                break_total = before_total if node.node_type == nd.NODE_TYPE.GLUE else total
                effective = self.pendingTotal(break_total, bottom_depth)
                cost = self.cost(effective, goal, 0, insert_penalties)
                if best is None or cost <= best[0]:
                    best = (
                        cost,
                        i,
                        node.node_type.name.lower(),
                        current_context,
                        0,
                        insert_penalties,
                    )
                if cost == inf:
                    triggered = True
                    break

        final_penalty = self.finalPenalty()
        if final_penalty is not None:
            effective = self.pendingTotal(total, bottom_depth)
            cost = self.cost(effective, goal, final_penalty, insert_penalties)
            if best is None or cost <= best[0]:
                best = (
                    cost,
                    len(self.nodes),
                    "end",
                    current_context,
                    final_penalty,
                    insert_penalties,
                )

        self._insert_actions = actions
        if best is None:
            self.last_insert_penalties = insert_penalties
            return len(self.nodes), len(self.nodes), current_context, 0, False
        _, index, kind, best_context, best_penalty, best_q = best
        self.last_insert_penalties = best_q
        end, next_start = self.candidateBreak(index, kind)
        return end, next_start, best_context, best_penalty, triggered


class PageBuilder:
    """
    Page-building state for the parser's outer vertical list.
    """

    def __init__(self, parser):
        self.parser = parser
        self.contrib = []
        self._processing_pages = False

    def reset(self):
        self.contrib[:] = []
        self._processing_pages = False

    @staticmethod
    def _delaysPageStart(node):
        return node.node_type in (nd.NODE_TYPE.WHATSIT, nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS)

    def concreteNodes(self, pending):
        return list(self.contrib) + list(pending.list)

    def rawNodes(self, pending):
        return [node for node in self.concreteNodes(pending) if getattr(node, "source", None) is None]

    @staticmethod
    def _syncLastItem(pending, contrib):
        pending.lastitem = contrib[-1] if contrib else None

    def _currentPageContext(self):
        return PageBuilderContext(self.parser.layout)

    def _pruneContribTop(self, pending):
        if not self.contrib:
            self._syncLastItem(pending, self.contrib)
            return
        kept = []
        index = 0
        found_content = False
        while index < len(self.contrib):
            node = self.contrib[index]
            if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY):
                index += 1
                continue
            if self._delaysPageStart(node):
                kept.append(node)
                index += 1
                continue
            found_content = True
            break
        if found_content and index > 0:
            self.contrib[:] = kept + self.contrib[index:]
        self._syncLastItem(pending, self.contrib)

    def contributePending(self, pending):
        if not pending.list:
            self._syncLastItem(pending, self.contrib)
            return
        self.contrib.extend(pending.list)
        pending.list[:] = []
        pending.raw[:] = []
        self._pruneContribTop(pending)

    def _triggersPageBuilder(self, node):
        # we do not trigger page building if a box is deposited by paragraph, display math or alignment.
        # instead, we check the raw node
        if isinstance(node, MAlignment):
            return True
        if node.source is not None:
            return False
        if node.node_type == nd.NODE_TYPE.PENALTY:
            return True
        if isinstance(node, Paragraph) or isinstance(node, DisplayMathNode) or isinstance(node, HAlignment):
            return True
        return node.node_type in (
            nd.NODE_TYPE.HLIST,
            nd.NODE_TYPE.VLIST,
            nd.NODE_TYPE.RULE,
            nd.NODE_TYPE.INS,
        )

    def noteAppend(self, pending, node):
        if not self._triggersPageBuilder(node):
            return
        self.contributePending(pending)
        if float(self.parser.layout["vsize"]) > 0:
            self.processPendingPages(pending)

    def _consumePagePrefix(self, pending, count):
        if count > 0:
            del self.contrib[:count]
            self._pruneContribTop(pending)
        else:
            self._syncLastItem(pending, self.contrib)

    def _prependCarryNodes(self, pending, nodes):
        if not nodes:
            return
        for node in nodes:
            node.source = node
        self.contrib[:0] = list(nodes)
        self._pruneContribTop(pending)

    def processPendingPages(self, pending, force=False):
        if self._processing_pages:
            return
        if float(self.parser.layout["vsize"]) <= 0:
            return
        self._processing_pages = True
        try:
            while True:
                if pending.list:
                    self.contributePending(pending)
                if not self.contrib:
                    return
                current_context = self._currentPageContext()
                breaker = PageBreaker(self.parser, self.contrib, current_context)
                start, start_context = breaker.pruneTop(0, current_context)
                if start >= len(self.contrib):
                    return
                (
                    end,
                    next_start,
                    break_context,
                    break_penalty,
                    triggered,
                ) = breaker.bestBreak(start, start_context)
                if not triggered and not force:
                    return
                if end <= start:
                    end = min(start + 1, len(self.contrib))
                    next_start = end
                    break_context = breaker.advanceContext(start, end, start_context)
                    break_penalty = 0
                page = bx.VBox(self.parser, break_context.vsize, None)
                topmark = list(self.parser.parameters["botmark"])
                firstmark, botmark = self._pageMarks(self.contrib, start, end, topmark)
                self._updatePageMarksByClass(self.parser, self.contrib, start, end, topmark)
                self.parser.parameters["topmark"] = list(topmark)
                self.parser.parameters["firstmark"] = list(firstmark)
                self.parser.parameters["botmark"] = list(botmark)
                self.parser.layout["outputpenalty"] = break_penalty
                page_nodes = breaker.buildSlice(start, end, start_context, "\\topskip")
                has_content = self._hasPageContent(page_nodes)
                self._clearInsertScratch(self.parser)
                page.list[:], insert_carry = self._extractPageInserts(self.parser, page_nodes, breaker)
                self.parser.globals["insertpenalties"] = breaker.last_insert_penalties
                carry = list(insert_carry)
                if not has_content:
                    self._flushPageWhatsits(self.parser, page.list)
                else:
                    out_carry = self._runOutputRoutine(
                        self.parser,
                        page.typeset(self.parser, maxdepth=break_context.maxdepth),
                    )
                    if out_carry:
                        carry.extend(out_carry)
                self._consumePagePrefix(pending, next_start)
                if carry:
                    self._prependCarryNodes(pending, carry)
        finally:
            self._processing_pages = False

    @staticmethod
    def _pageMarks(nodes, start, end, topmark):
        first = None
        bot = None
        for node in nodes[start:end]:
            if node.node_type != nd.NODE_TYPE.MARK:
                continue
            if getattr(node, "index", 0) != 0:
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
    def _pageMarksByClass(nodes, start, end, topmarks):
        firstmarks = _copy_mark_register(topmarks)
        botmarks = _copy_mark_register(topmarks)
        seen = set()
        for node in nodes[start:end]:
            if node.node_type != nd.NODE_TYPE.MARK:
                continue
            index = getattr(node, "index", 0)
            mark = list(node.tokens)
            if index not in seen:
                _set_mark_class(firstmarks, index, mark)
                seen.add(index)
            _set_mark_class(botmarks, index, mark)
        return firstmarks, botmarks

    @staticmethod
    def _pageHasNonZeroMarks(nodes, start, end):
        for node in nodes[start:end]:
            if node.node_type != nd.NODE_TYPE.MARK:
                continue
            if getattr(node, "index", 0) != 0:
                return True
        return False

    def _updatePageMarksByClass(self, parser, nodes, start, end, topmark):
        topmarks = parser.globals.get("botmarks")
        if topmarks is None:
            assert not self._pageHasNonZeroMarks(nodes, start, end), \
                "nonzero mark nodes require the etex module"
            return None
        topmarks = _copy_mark_register(topmarks)
        _set_mark_class(topmarks, 0, topmark)
        firstmarks, botmarks = self._pageMarksByClass(nodes, start, end, topmarks)
        parser.globals["topmarks"] = _copy_mark_register(topmarks)
        parser.globals["firstmarks"] = firstmarks
        parser.globals["botmarks"] = botmarks
        return botmarks

    @staticmethod
    def _hasPageContent(nodes):
        for node in nodes:
            if node.node_type == nd.NODE_TYPE.RULE:
                return True
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                return True
            if node.node_type == nd.NODE_TYPE.INS:
                return True
        return False

    @staticmethod
    def _ensureInsertScratch(parser):
        scratch = parser.globals.get("insert")
        if not isinstance(scratch, list):
            scratch = [[] for _ in range(256)]
            parser.globals["insert"] = scratch
            return scratch
        if len(scratch) < 256:
            scratch.extend([] for _ in range(256 - len(scratch)))
        return scratch

    @classmethod
    def _clearInsertScratch(cls, parser):
        scratch = cls._ensureInsertScratch(parser)
        for items in scratch:
            items.clear()
        parser.globals["insertpenalties"] = 0
        return scratch

    @staticmethod
    def _appendInsertToBoxRegister(parser, index, insert_box):
        current = parser.box[index]
        if current is None:
            parser.box[index] = insert_box.copy()
            return
        current = current.typeset(parser)
        if current.node_type != nd.NODE_TYPE.VLIST:
            raise ValueError(f"insert box {index} must be a vbox", parser.input.position())
        merged = bx.VBox(parser, None, Dimen())
        merged.list[:] = list(current.list)
        merged.list.extend(list(insert_box.list))
        parser.box[index] = merged.typeset(parser)

    @classmethod
    def _extractPageInserts(cls, parser, nodes, breaker):
        scratch = cls._ensureInsertScratch(parser)
        kept = []
        carry = []
        for node in nodes:
            if node.node_type != nd.NODE_TYPE.INS:
                kept.append(node)
                continue
            action = breaker.actionFor(node)
            if action is None:
                insert_box = breaker.insertBox(node)
                action = {
                    "kind": "full",
                    "index": node.index,
                    "head": insert_box,
                    "tail": [],
                    "used": breaker._insertNatural(insert_box),
                }
            index = action["index"]
            if action["kind"] == "defer":
                carry.append(vmode.Insert(index, list(node.list)))
                continue
            head = action.get("head")
            used = action.get("used", Dimen())
            if head is not None and (used > 0 or len(head.list) > 0):
                while len(scratch) <= index:
                    scratch.append([])
                scratch[index].append(head.copy())
                cls._appendInsertToBoxRegister(parser, index, head)
            tail = action.get("tail") or []
            if tail:
                carry.append(vmode.Insert(index, list(tail)))
        return kept, carry

    @staticmethod
    def _flushPageWhatsits(parser, nodes):
        device = getattr(parser, "shipout", None)
        for node in nodes:
            if node.node_type != nd.NODE_TYPE.WHATSIT:
                continue
            node.output(parser, device)

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
        parser.box[255] = page
        if not output:
            parser.globals["deadcycles"] += 1
            shipout(parser, page)
            parser.box[255] = None
            return []
        if parser.globals["deadcycles"] >= parser.parameters["maxdeadcycles"]:
            parser.message(
                f"Output loop---{parser.globals['deadcycles']} consecutive dead cycles"
            )
            parser.globals["deadcycles"] += 1
            shipout(parser, page)
            parser.box[255] = None
            return []
        parser.globals["deadcycles"] += 1
        outlist = vmode.VList(parser, [])
        parser.lists.append(outlist)
        parser.beginGroup(
            parser.input.position(),
            GROUP_TYPE.OUTPUT,
            ended=OutputRoutineEndCallback(outlist),
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
        if parser.current_group.aftergroup:
            raise NotImplementedError("aftergroup in the output routine is not implemented yet")
        parser.endGroup(parser.input.position(), GROUP_TYPE.OUTPUT)
        parser.box[255] = None
        carry = []
        carry.extend(outlist.list)
        return carry

    def finish(self, pending):
        parser = self.parser
        if float(parser.layout["vsize"]) <= 0:
            self._flushPageWhatsits(parser, self.contrib)
            self._flushPageWhatsits(parser, pending.list)
            return
        self.contributePending(pending)
        self.processPendingPages(pending, force=True)


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
    parser.page_builder = PageBuilder(parser)
    parser.shipout = Shipout(parser)


class VSplit(Command):
    """
    The \\vsplit command.
    """

    def getTarget(self, parser):
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
            return accessor.ReadOnlyTarget(None, accessor.VALUE_TYPE.BOX)
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
            return accessor.ReadOnlyTarget(None, accessor.VALUE_TYPE.BOX)
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
        return accessor.ReadOnlyTarget(
            result.typeset(parser, maxdepth=break_context.maxdepth),
            accessor.VALUE_TYPE.BOX,
        )

    def execute(self, parser):
        box = self.getTarget(parser).get()
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
