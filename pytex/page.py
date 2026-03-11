"""
Page breaking for the main vertical list.
"""


from fractions import Fraction
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


def _copy_mark_register(register):
    return [list(mark) for mark in register]


def _set_mark_class(register, index, tokens):
    while len(register) <= index:
        register.append([])
    register[index] = list(tokens)


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
        self.last_triggered = False
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
                            self.last_triggered = True
                            return end, next_start, best_context, best_penalty
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
                    self.last_triggered = True
                    return end, next_start, best_context, best_penalty
                continue
            before_total = total.copy()
            self.measure(total, node)
            if self.hasDepth(node):
                bottom_depth = node.depth
            if self.isLegalBreak(start, i):
                break_total = before_total if node.node_type == nd.NODE_TYPE.GLUE else total
                effective = self.pendingTotal(break_total, bottom_depth)
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
            return len(self.nodes), len(self.nodes), current_context, 0
        _, index, kind, best_context, best_penalty = best
        end, next_start = self.candidateBreak(index, kind)
        self.last_triggered = triggered
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
    if getattr(box, "_typeset_cache", None) is box:
        shipped_box = box
    else:
        shipped_box = box.typeset(parser)
    parser.traceOutputPage(shipped_box)
    backend.shipout(shipped_box)
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


class _PendingPageEntry:
    """
    One raw main-vlist node and the page-builder material currently derived from it.
    """

    __slots__ = ("node", "ready", "material")

    def __init__(self, node):
        self.node = node
        self.ready = False
        self.material = []


class ContributedVList(vmode.VList):
    """
    Concrete contributed material waiting to be considered by the page builder.
    """

    list_type_name = "ContributedVList"

    def __init__(self, parser):
        super().__init__(parser, [], inner=False)
        self.page_seen_box = False

    def appendConcrete(self, node):
        self.can_lastbox = False
        self.list.append(node)
        if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            self.prevdepth = node.depth
            self.page_seen_box = True
        elif node.node_type == nd.NODE_TYPE.RULE:
            self.prevdepth = vmode.init_prevdepth

    def prependConcrete(self, nodes):
        if not nodes:
            return
        self.list[:0] = list(nodes)
        self.rebuildState()

    def removePrefix(self, count):
        if count <= 0:
            return
        del self.list[:count]
        self.rebuildState()

    def removeTail(self, count):
        if count <= 0:
            return
        del self.list[-count:]
        self.rebuildState()

    def rebuildState(self):
        self.prevdepth = vmode.init_prevdepth
        self.page_seen_box = False
        self.can_lastbox = False
        for node in self.list:
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self.prevdepth = node.depth
                self.page_seen_box = True
            elif node.node_type == nd.NODE_TYPE.RULE:
                self.prevdepth = vmode.init_prevdepth


class MainVListBreaker(VListBreaker):
    def __init__(self, parser, nodes, initial_context):
        super().__init__(nodes, initial_context)
        self.parser = parser
        self._insert_boxes = {}
        self._register_box_heights = {}
        self._insert_actions = {}
        self.last_insert_penalties = 0

    def contextFor(self, node):
        if isinstance(node, PageStateNode):
            return node.context
        return None

    def isTransparent(self, node):
        return isinstance(node, PageStateNode)

    @staticmethod
    def _delaysPageStart(node):
        return node.node_type in (nd.NODE_TYPE.WHATSIT, nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS)

    def insertBox(self, node):
        cache_key = id(node)
        box = self._insert_boxes.get(cache_key)
        if box is not None:
            return box
        box = bx.VBox(self.parser, None, Dimen())
        box.list[:] = list(node.vlist)
        box = box.typeset(self.parser)
        self._insert_boxes[cache_key] = box
        return box

    def _registerBoxHeight(self, index):
        cached = self._register_box_heights.get(index)
        if cached is not None:
            return cached
        box = self.parser.state.box[index]
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
            self.parser.state.layout["splitmaxdepth"],
        )
        breaker = VSplitBreaker(nodes, split_context)
        start, split_context = breaker.pruneTop(0, split_context)
        if start >= len(nodes):
            return None, [], Dimen(), 0
        end, next_start, break_context, break_penalty = breaker.bestBreak(start, split_context)
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
        f_count = int(self.parser.state.count[index])
        f = Fraction(f_count, 1000)
        limit = self.parser.state.dimen[index]
        skip = self.parser.state.skip[index]
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
            insert_penalties += int(self.parser.state.layout["floatingpenalty"])
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
        self.last_triggered = False
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
                        self.last_triggered = True
                        return end, next_start, current_context, node.penalty
                    _, index, kind, best_context, best_penalty, best_q = best
                    self.last_insert_penalties = best_q
                    end, next_start = self.candidateBreak(index, kind)
                    self.last_triggered = True
                    return end, next_start, best_context, best_penalty
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
            return len(self.nodes), len(self.nodes), current_context, 0
        _, index, kind, best_context, best_penalty, best_q = best
        self.last_insert_penalties = best_q
        end, next_start = self.candidateBreak(index, kind)
        self.last_triggered = triggered
        return end, next_start, best_context, best_penalty


class MainVList(vmode.VList):
    """
    The document's main vertical list.
    """

    list_type_name = "MainVList"

    def __init__(self, parser):
        super().__init__(parser, [], inner=False)
        self.page_initial_context = PageBuilderContext(parser.state.layout)
        self.page_context = self.page_initial_context
        self.contributed = ContributedVList(parser)
        self._pending_entries = []
        self._processing_pages = False

    @staticmethod
    def _entryReadyForPageBuilder(node):
        if isinstance(node, PageStateNode):
            return True
        if getattr(node, "page_builder_ready", True) is False:
            return False
        if getattr(node, "box_materializable", False) and node.node_type is None:
            return getattr(node, "_typeset_cache", None) is not None
        next_paragraph = getattr(node, "next_paragraph", None)
        if (
            next_paragraph is not None
            and hasattr(next_paragraph, "typeset_context")
            and getattr(next_paragraph, "typeset_context", None) is None
        ):
            return False
        return True

    def _appendPageNode(self, node):
        entry = _PendingPageEntry(node)
        self._pending_entries.append(entry)
        if self._entryReadyForPageBuilder(node):
            self._realizePendingEntry(entry)

    @classmethod
    def _triggersPageBuilder(cls, node):
        if isinstance(node, PageStateNode):
            return False
        if node.node_type == nd.NODE_TYPE.PENALTY:
            return True
        if getattr(node, "box_materializable", False):
            return cls._entryReadyForPageBuilder(node)
        return node.node_type in (
            nd.NODE_TYPE.HLIST,
            nd.NODE_TYPE.VLIST,
            nd.NODE_TYPE.RULE,
            nd.NODE_TYPE.INS,
        )

    def _materializePageEntry(self, node):
        generated = []
        contributed = self.contributed
        context = getattr(node, "typeset_context", None)
        if context is None and getattr(node, "needs_vcontext", False):
            node.typeset_context = vmode.VNodeContext(self.parser.state.layout, contributed.prevdepth)
            context = node.typeset_context
        is_box = node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST)
        if context is None and is_box:
            node.typeset_context = vmode.VNodeContext(self.parser.state.layout, contributed.prevdepth)
            context = node.typeset_context
        expanded = vmode.expandVerticalNode(self.parser, node)
        node_context = context

        def appendItem(item):
            nonlocal node_context
            if item.node_type == nd.NODE_TYPE.ADJUST:
                for sub in vmode.expandVerticalNode(self.parser, item):
                    appendItem(sub)
                return
            if item.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                item_context = getattr(item, "typeset_context", None)
                if item_context is None:
                    item_context = node_context
                    node_context = None
                else:
                    item.typeset_context = None
                if item_context is None:
                    if contributed.page_seen_box:
                        prev = contributed.list[-1] if contributed.list else None
                        if prev is not None and prev.node_type in (
                            nd.NODE_TYPE.HLIST,
                            nd.NODE_TYPE.VLIST,
                            nd.NODE_TYPE.RULE,
                        ):
                            interlinepenalty = self.parser.state.layout["interlinepenalty"]
                            if interlinepenalty != 0:
                                penalty = nd.Penalty(interlinepenalty)
                                contributed.appendConcrete(penalty)
                                generated.append(penalty)
                            if float(contributed.prevdepth) > float(vmode.init_prevdepth):
                                baselineskip = self.parser.state.layout["baselineskip"]
                                diff = baselineskip.dimen - contributed.prevdepth - item.height
                                if diff < self.parser.state.layout["lineskiplimit"]:
                                    glue = nd.Glue(
                                        self.parser.state.layout["lineskip"], "\\lineskip"
                                    )
                                else:
                                    glue = nd.Glue(
                                        Glue(diff, baselineskip.stretch, baselineskip.shrink),
                                        "\\baselineskip",
                                    )
                                contributed.appendConcrete(glue)
                                generated.append(glue)
                else:
                    if item_context.interlinepenalty != 0 and contributed.page_seen_box:
                        penalty = nd.Penalty(item_context.interlinepenalty)
                        contributed.appendConcrete(penalty)
                        generated.append(penalty)
                    prevdepth = getattr(item_context, "prevdepth", None)
                    if prevdepth is None:
                        prevdepth = contributed.prevdepth
                    if float(prevdepth) > float(vmode.init_prevdepth) and contributed.page_seen_box:
                        baselineskip = item_context.baselineskip
                        diff = baselineskip.dimen - prevdepth - item.height
                        if diff < item_context.lineskiplimit:
                            glue = nd.Glue(item_context.lineskip, "\\lineskip")
                        else:
                            glue = nd.Glue(
                                Glue(diff, baselineskip.stretch, baselineskip.shrink),
                                "\\baselineskip",
                            )
                        contributed.appendConcrete(glue)
                        generated.append(glue)
                contributed.appendConcrete(item)
                generated.append(item)
                return
            contributed.appendConcrete(item)
            generated.append(item)

        for item in expanded:
            appendItem(item)
        return generated

    def _realizePendingEntry(self, entry):
        if entry.ready:
            return
        entry.material = self._materializePageEntry(entry.node)
        entry.ready = True

    def finalizePendingNode(self, node):
        for entry in reversed(self._pending_entries):
            if entry.node is node:
                if getattr(node, "box_materializable", False) and node.node_type is None:
                    if getattr(node, "_typeset_cache", None) is None:
                        node.pretypeset(self.parser)
                self._realizePendingEntry(entry)
                if self._triggersPageBuilder(node):
                    self._processPendingPages()
                return
        raise ValueError("cannot finalize missing main-vlist node")

    def _realizeReadyTailEntries(self):
        start = len(self._pending_entries)
        while start > 0:
            entry = self._pending_entries[start - 1]
            if entry.ready:
                start -= 1
                continue
            if not self._entryReadyForPageBuilder(entry.node):
                break
            start -= 1
        for entry in self._pending_entries[start:]:
            if not entry.ready:
                self._realizePendingEntry(entry)

    def _rebuildRawState(self):
        self.prevdepth = self.contributed.prevdepth if self.contributed.list else vmode.init_prevdepth
        context = self.page_initial_context
        for node in self.list:
            if isinstance(node, PageStateNode):
                context = node.context
        if not self.list:
            self.can_lastbox = False
        self.page_context = context

    def _rebuildPageState(self):
        self.contributed.rebuildState()

    def _consumePagePrefix(self, count):
        if count <= 0:
            return
        remaining = count
        raw_remove = 0
        while remaining > 0:
            entry = self._pending_entries[0]
            if not entry.ready:
                raise AssertionError("page builder reached an unrealized main-vlist node")
            material_len = len(entry.material)
            if remaining < material_len:
                entry.material = entry.material[remaining:]
                remaining = 0
                break
            remaining -= material_len
            self._pending_entries.pop(0)
            raw_remove += 1
        self.contributed.removePrefix(count)
        if raw_remove:
            del self.list[:raw_remove]
        self._rebuildRawState()

    def _prependCarryNodes(self, nodes):
        if not nodes:
            return
        entries = []
        for node in nodes:
            entry = _PendingPageEntry(node)
            entry.ready = True
            entry.material = [node]
            entries.append(entry)
        self.list[:0] = list(nodes)
        self._pending_entries[:0] = entries
        self.contributed.prependConcrete(list(nodes))
        self._rebuildRawState()

    def _flushDeferredFileOps(self, box):
        from pytex import file as filemod

        items = getattr(box, "list", None)
        if items is None:
            return
        kept = []
        for node in items:
            if node.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._flushDeferredFileOps(node)
                kept.append(node)
                continue
            if isinstance(node, filemod.FileOpNode):
                node.output(self.parser, None)
                continue
            kept.append(node)
        box.list[:] = kept

    def _processPendingPages(self, force=False):
        if self._processing_pages:
            return
        if float(self.parser.state.layout["vsize"]) <= 0:
            return
        self._processing_pages = True
        try:
            while True:
                if not self.contributed.list:
                    return
                breaker = MainVListBreaker(self.parser, self.contributed.list, self.page_initial_context)
                start, start_context = breaker.pruneTop(0, self.page_initial_context)
                if start >= len(self.contributed.list):
                    return
                end, next_start, break_context, break_penalty = breaker.bestBreak(start, start_context)
                if not getattr(breaker, "last_triggered", False) and not force:
                    return
                if end <= start:
                    end = min(start + 1, len(self.contributed.list))
                    next_start = end
                    break_context = breaker.advanceContext(start, end, start_context)
                    break_penalty = 0
                page = bx.VBox(self.parser, break_context.vsize, Dimen())
                topmark = list(self.parser.state.parameters["botmark"])
                firstmark, botmark = self._pageMarks(self.contributed.list, start, end, topmark)
                self._updatePageMarksByClass(self.parser, self.contributed.list, start, end, topmark)
                self.parser.state.parameters["topmark"] = list(topmark)
                self.parser.state.parameters["firstmark"] = list(firstmark)
                self.parser.state.parameters["botmark"] = list(botmark)
                self.parser.state.layout["outputpenalty"] = break_penalty
                page_nodes = breaker.buildSlice(start, end, start_context, "\\topskip")
                has_content = self._hasPageContent(page_nodes)
                self._clearInsertScratch(self.parser)
                page.list[:], insert_carry = self._extractPageInserts(self.parser, page_nodes, breaker)
                self.parser.state.globals["insertpenalties"] = breaker.last_insert_penalties
                pending = list(insert_carry)
                if not has_content:
                    self._flushPageWhatsits(self.parser, page.list)
                else:
                    out_carry = self._runOutputRoutine(self.parser, page.typeset(self.parser))
                    if out_carry:
                        pending.extend(out_carry)
                self.page_initial_context = breaker.advanceContext(0, next_start, self.page_initial_context)
                self._consumePagePrefix(next_start)
                if pending:
                    self._prependCarryNodes(pending)
        finally:
            self._processing_pages = False

    def append(self, node):
        self._realizeReadyTailEntries()
        if not isinstance(node, PageStateNode):
            context = PageBuilderContext(self.parser.state.layout)
            if not self.page_context.sameLayout(self.parser.state.layout):
                marker = PageStateNode(context)
                super().append(marker)
                self._appendPageNode(marker)
                self.page_context = context
        super().append(node)
        self._appendPageNode(node)
        if self._triggersPageBuilder(node):
            self._processPendingPages()

    def pop(self, *args):
        index = args[0] if args else -1
        if index not in (-1, len(self.list) - 1):
            raise NotImplementedError("MainVList.pop only supports removing the tail")
        node = super().pop(*args)
        entry = self._pending_entries.pop()
        assert entry.node is node
        if entry.ready and entry.material:
            self.contributed.removeTail(len(entry.material))
        self._rebuildRawState()
        return node

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
            parser = getattr(getattr(node, "vlist", None), "parser", None)
            if parser is None:
                return total
            box = getattr(node, "_legacy_insert_box", None)
            if box is None:
                box = bx.VBox(parser, None, Dimen())
                box.list[:] = list(node.vlist)
                box = box.typeset(parser)
                node._legacy_insert_box = box
            total.dimen += box.height + box.depth
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
    def _pendingTotal(total, bottom_depth):
        if bottom_depth is None:
            return total
        return Glue(total.dimen - bottom_depth, total.stretch, total.shrink)

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
                effective = self._pendingTotal(total, bottom_depth)
                cost = self._pageCost(effective, current_context.vsize, node.penalty)
                current = (cost, i, "penalty", current_context, node.penalty)
                if best is None or cost <= best[0]:
                    best = current
                if cost == inf or node.penalty <= -10000:
                    _, index, kind, best_context, best_penalty = best if best is not None else current
                    end, next_start = self._candidateBreak(index, kind)
                    return end, next_start, best_context, best_penalty
                continue
            before_total = total.copy()
            self._pageMeasure(total, node)
            if self._hasDepth(node):
                bottom_depth = node.depth
            if self._isLegalBreak(nodes, start, i):
                break_total = before_total if node.node_type == nd.NODE_TYPE.GLUE else total
                effective = self._pendingTotal(break_total, bottom_depth)
                cost = self._pageCost(effective, current_context.vsize, 0)
                if best is None or cost <= best[0]:
                    best = (cost, i, node.node_type.name.lower(), current_context, 0)
                if cost == inf:
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
        topmarks = parser.state.globals.get("botmarks")
        if topmarks is None:
            assert not self._pageHasNonZeroMarks(nodes, start, end), \
                "nonzero mark nodes require the etex module"
            return None
        topmarks = _copy_mark_register(topmarks)
        _set_mark_class(topmarks, 0, topmark)
        firstmarks, botmarks = self._pageMarksByClass(nodes, start, end, topmarks)
        parser.state.globals["topmarks"] = _copy_mark_register(topmarks)
        parser.state.globals["firstmarks"] = firstmarks
        parser.state.globals["botmarks"] = botmarks
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
        scratch = parser.state.globals.get("insert")
        if not isinstance(scratch, list):
            scratch = [[] for _ in range(256)]
            parser.state.globals["insert"] = scratch
            return scratch
        if len(scratch) < 256:
            scratch.extend([] for _ in range(256 - len(scratch)))
        return scratch

    @classmethod
    def _clearInsertScratch(cls, parser):
        scratch = cls._ensureInsertScratch(parser)
        for items in scratch:
            items.clear()
        parser.state.globals["insertpenalties"] = 0
        return scratch

    @staticmethod
    def _appendInsertToBoxRegister(parser, index, insert_box):
        current = parser.state.box[index]
        if current is None:
            parser.state.box[index] = insert_box.copy()
            return
        current = current.typeset(parser)
        if current.node_type != nd.NODE_TYPE.VLIST:
            raise ValueError(f"insert box {index} must be a vbox", parser.input.position())
        merged = bx.VBox(parser, None, Dimen())
        merged.list[:] = list(current.list)
        merged.list.extend(list(insert_box.list))
        parser.state.box[index] = merged.typeset(parser)

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
                carry.append(vmode.Insert(index, list(node.vlist)))
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
        outlist = vmode.VList(parser, [])
        parser.lists.append(outlist)
        parser.beginGroup(
            parser.input.position(),
            GROUP_TYPE.OUTPUT,
            ended=OutputRoutineEndCallback(parser, outlist),
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
        vmode.typesetVerticalNodes(parser, outlist.list, carry)
        return carry

    def finish(self, parser):
        self._realizeReadyTailEntries()
        if float(parser.state.layout["vsize"]) <= 0:
            self._flushPageWhatsits(parser, self.contributed.list)
            return
        self._processPendingPages(force=True)


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
    parser.shipout = Shipout(parser)


class VSplit(Command):
    """
    The \\vsplit command.
    """

    def boxValue(self, parser, setbox):
        index = parser.readInteger()
        spec, dim = parser.readBoxSpec(["to"])
        if spec != "to":
            raise ValueError("expecting \\vsplit<number> to <dimen>", parser.input.position())
        splitfirst = None
        splitbot = None
        splitfirstmarks = parser.state.globals.get("splitfirstmarks")
        splitbotmarks = parser.state.globals.get("splitbotmarks")
        split_seen = set()
        if splitfirstmarks is not None:
            splitfirstmarks = [[]]
            splitbotmarks = [[]]
        source = parser.state.box[index]
        if source is None:
            parser.state.globals["splitfirstmark"] = []
            parser.state.globals["splitbotmark"] = []
            if splitfirstmarks is not None:
                parser.state.globals["splitfirstmarks"] = splitfirstmarks
                parser.state.globals["splitbotmarks"] = splitbotmarks
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
            parser.state.globals["splitfirstmark"] = []
            parser.state.globals["splitbotmark"] = []
            if splitfirstmarks is not None:
                parser.state.globals["splitfirstmarks"] = splitfirstmarks
                parser.state.globals["splitbotmarks"] = splitbotmarks
            return None
        end, next_start, break_context, _ = breaker.bestBreak(start, split_context)
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
        parser.state.globals["splitfirstmark"] = [] if splitfirst is None else splitfirst
        parser.state.globals["splitbotmark"] = [] if splitbot is None else splitbot
        if splitfirstmarks is not None:
            parser.state.globals["splitfirstmarks"] = splitfirstmarks
            parser.state.globals["splitbotmarks"] = splitbotmarks
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
