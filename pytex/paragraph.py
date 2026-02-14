"""
This module implement paragraph handling (unrestricted hlist).
"""

from bisect import bisect_left

from pytex import hmode
from pytex import node as nd
from pytex import box as bx
from pytex import lists
from pytex.module import Module
from pytex.dimen import Dimen
from pytex.glue import Glue


class ParagraphTypesetContext:
    """
    Frozen typesetting context for a paragraph.
    """
    def __init__(self, parser, paragraph, prev_context=None):
        self.paragraph = paragraph
        self.prev_context = prev_context
        self.next_context = None
        self.line_count = None
        if prev_context is not None:
            prev_context.next_context = self
            self.prevgraf = 0 if prev_context.line_count is None else prev_context.line_count
        else:
            self.prevgraf = 0
        self.hsize = parser.state.layout["hsize"]
        self.leftskip = parser.state.layout["leftskip"]
        self.rightskip = parser.state.layout["rightskip"]
        self.parfillskip = parser.state.parameters["parfillskip"]
        self.pretolerance = parser.state.layout["pretolerance"]
        self.tolerance = parser.state.layout["tolerance"]
        self.linepenalty = parser.state.layout["linepenalty"]
        self.hyphenpenalty = parser.state.layout["hyphenpenalty"]
        self.exhyphenpenalty = parser.state.layout["exhyphenpenalty"]
        self.adjdemerits = parser.state.layout["adjdemerits"]
        self.doublehyphendemerits = parser.state.layout["doublehyphendemerits"]
        self.finalhyphendemerits = parser.state.layout["finalhyphendemerits"]
        self.looseness = parser.state.layout["looseness"]
        self.hangindent = parser.state.layout["hangindent"]
        self.hangafter = parser.state.layout["hangafter"]
        self.parshape = parser.state.globals["parshape"]
        self.language = parser.state.parameters["language"]

    def setLineCount(self, line_count):
        self.line_count = line_count
        if self.next_context is not None:
            self.next_context.prevgraf = line_count


class Language(nd.WhatsIt):
    """
    a language node
    """
    def __init__(self, language):
        self.language = language


class Paragraph(hmode.HList):
    """
    A paragraph.
    @param parser: the parser
    @param indent: whether to indent the paragraph
    """
    def __init__(self, parser, indent: bool):
        super().__init__(parser, inner = False)
        self.current_language = parser.state.parameters["language"]
        self.disc = False
        self.typeset_context = None
        if indent:
            self.append(bx.IndentBox(parser))

    # not a proper node
    node_type = None
    
    def saveInfo(self):
        d = super().saveInfo()
        d["init"]["indent"] = self.inner
        del d["init"]["inner"]
        return d | {"extra": {"disc": self.disc}}
    
    def discretionary(self):
        self.disc = False
        disc = nd.Disc(hmode.DiscHList(), hmode.DiscHList(), hmode.DiscHList())
        self.append(disc)
    
    def append(self, node):
        disc = False
        if isinstance(node, nd.CharNode):
            language = self.parser.state.parameters["language"]
            if self.current_language != language:
                self.current_language = language
                super().append(Language(language))
            if ord(node.char) == self.parser.hyphenChar():
                disc = True
        super().append(node)
        if disc:
            self.disc = True
        elif self.disc:
            self.discretionary()


def _isDiscardable(node):
    return node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY)


def _trimLineStart(nodes):
    i = 0
    while i < len(nodes) and _isDiscardable(nodes[i]):
        i += 1
    return nodes[i:]


def _nodeWidth(parser, node):
    node_type = node.node_type
    if node_type == nd.NODE_TYPE.GLUE:
        return node.glue.dimen
    if node_type == nd.NODE_TYPE.KERN:
        return node.kern
    if node_type == nd.NODE_TYPE.DISC:
        width = Dimen()
        for n in node.replace:
            width += _nodeWidth(parser, n)
        return width
    if node_type == nd.NODE_TYPE.MATH:
        kern = getattr(node, "kern", None)
        if kern is not None:
            return kern
        # Fallback for unresolved math markers.
        return parser.state.layout["mathsurround"]
    width = getattr(node, "width", None)
    if width is None:
        return Dimen()
    return width


def _lineShape(context, line_no):
    if context.parshape:
        i = line_no - 1
        if i >= len(context.parshape):
            i = len(context.parshape) - 1
        return context.parshape[i]
    return Dimen(), context.hsize


def _emitLine(parser, para, vlist, line_nodes, line_no, last_line, add_parfillskip):
    context = para.typeset_context
    indent, measure = _lineShape(context, line_no)
    packed = [nd.Glue(context.leftskip)]
    if indent != 0:
        packed.insert(0, nd.Glue(Glue(indent)))
    packed.extend(_trimLineStart([n for n in line_nodes if n.node_type != nd.NODE_TYPE.PENALTY]))
    if last_line and add_parfillskip:
        packed.append(nd.Glue(context.parfillskip))
    packed.append(nd.Glue(context.rightskip))
    hbox = bx.HBox(parser, measure, Dimen())
    hbox.list[:] = packed
    hbox.typeset(parser, vlist)


def _stripParagraphEnding(para):
    context = para.typeset_context
    nodes = list(para)
    if (
        len(nodes) >= 2
        and nodes[-2].node_type == nd.NODE_TYPE.PENALTY
        and nodes[-2].penalty == 10000
        and nodes[-1].node_type == nd.NODE_TYPE.GLUE
        and nodes[-1].glue == context.parfillskip
    ):
        return nodes[:-2], True
    return nodes, False


class _BreakCandidate:
    """
    A legal line-break candidate.
    """
    def __init__(self, kind, break_index, next_start, penalty, hyphenated=False):
        self.kind = kind
        self.break_index = break_index
        self.next_start = next_start
        self.penalty = penalty
        self.hyphenated = hyphenated

    @property
    def forced(self):
        return self.penalty <= -10000


class _LineMetrics:
    """
    Metrics for one feasible line candidate.
    """
    def __init__(self, badness, ratio, fitness, hyphenated):
        self.badness = badness
        self.ratio = ratio
        self.fitness = fitness
        self.hyphenated = hyphenated


class _BreakState:
    """
    Dynamic-programming state for TeX-style line breaking.
    """
    def __init__(
        self,
        position,
        line_no,
        demerits,
        fitness,
        hyphenated,
        prev=None,
        start_index=None,
        break_index=None,
        break_kind=None,
    ):
        self.position = position
        self.line_no = line_no
        self.demerits = demerits
        self.fitness = fitness
        self.hyphenated = hyphenated
        self.prev = prev
        self.start_index = start_index
        self.break_index = break_index
        self.break_kind = break_kind


class _LineBreaker:
    """
    One line-breaking round (finite-state shortest-path search).

    Model:
    - vertices: legal break positions in the paragraph stream.
    - edges: one candidate line from active break state to a later break.
    - edge weight: TeX-like demerits derived from badness/penalties/fitness.

    Implementation notes:
    - This keeps a frontier of active states per line number and propagates
      them to later legal breakpoints.
    - A state stores path history (`prev`) so final reconstruction can emit
      hboxes in order.
    - We keep only the best state per
      `(position, line_no, fitness, hyphenated)` key in each wave.
    - Discretionary reconstruction is intentionally partial for now:
      candidate generation is present, but `pre/post` insertion is TODO.
    """
    def __init__(self, parser, para, vlist, tolerance, allow_overfull=False):
        self.parser = parser
        self.para = para
        self.vlist = vlist
        self.context = para.typeset_context
        self.nodes, self.add_parfillskip = _stripParagraphEnding(para)
        self.end = len(self.nodes)
        self.tolerance = tolerance
        self.allow_overfull = allow_overfull
        self._next_non_discard = self._buildNextNonDiscard()
        self._prefix_width, self._prefix_glue = self._buildPrefix()
        self._break_candidates = self._buildBreakCandidates()
        self._break_positions = [c.break_index for c in self._break_candidates]

    def _buildNextNonDiscard(self):
        """
        Precompute next non-discardable node index for each node index.
        """
        next_index = [self.end] * (self.end + 1)
        cursor = self.end
        for i in range(self.end - 1, -1, -1):
            if not _isDiscardable(self.nodes[i]):
                cursor = i
            next_index[i] = cursor
        return next_index

    def _buildPrefix(self):
        """
        Prefix sums for natural width and variable glue over node stream.
        """
        width = [Dimen()]
        glue = [Glue()]
        for node in self.nodes:
            if node.node_type == nd.NODE_TYPE.GLUE:
                width.append(width[-1] + node.glue.dimen)
                glue.append(glue[-1] + node.glue)
                continue
            width.append(width[-1] + _nodeWidth(self.parser, node))
            glue.append(glue[-1])
        return width, glue

    def _buildBreakCandidates(self):
        """
        Collect legal break candidates in one scan.
        """
        candidates = []
        for i, node in enumerate(self.nodes):
            node_type = node.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                if i == 0 or _isDiscardable(self.nodes[i - 1]):
                    continue
                candidates.append(_BreakCandidate("glue", i, i + 1, 0))
            elif node_type == nd.NODE_TYPE.PENALTY:
                if node.penalty < 10000:
                    candidates.append(_BreakCandidate("penalty", i, i + 1, node.penalty))
            elif node_type == nd.NODE_TYPE.DISC:
                # TODO: include pre/post lists in width/reconstruction when
                # discretionary handling is fully implemented.
                candidates.append(_BreakCandidate("disc", i, i + 1, self.context.hyphenpenalty, True))
        candidates.append(_BreakCandidate("end", self.end, self.end, -10000))
        return candidates

    def _trimLineStartIndex(self, start, end):
        i = self._next_non_discard[start]
        return end if i >= end else i

    def _iterBreakCandidates(self, start):
        i = bisect_left(self._break_positions, start)
        while i < len(self._break_candidates):
            candidate = self._break_candidates[i]
            # A glue candidate cannot be the first node of a line.
            if not (candidate.kind == "glue" and candidate.break_index == start):
                yield candidate
            i += 1

    def _lineTarget(self, line_no, last_line):
        indent, measure = _lineShape(self.context, line_no)
        line_glue = self.context.leftskip + self.context.rightskip
        if last_line and self.add_parfillskip:
            line_glue += self.context.parfillskip
        return measure - indent, line_glue

    def _lineNatural(self, start, end):
        return (
            self._prefix_width[end] - self._prefix_width[start],
            self._prefix_glue[end] - self._prefix_glue[start],
        )

    @staticmethod
    def _lineBadness(ratio):
        value = abs(ratio)
        return min(10000, int(100 * (value ** 3) + 0.5))

    def _adjustment(self, diff, glue_total, forced):
        delta = float(diff)
        if delta == 0:
            return 0.0, 0
        if delta > 0:
            stretch = glue_total.stretch
            if float(stretch.factor) <= 0:
                if forced and self.allow_overfull:
                    return 0.0, 10000
                return None, None
            if stretch.order > 0:
                return 0.0, 0
            ratio = delta / float(stretch.factor)
            return ratio, self._lineBadness(ratio)
        shrink = glue_total.shrink
        if float(shrink.factor) <= 0:
            if forced and self.allow_overfull:
                return -1.0, 10000
            return None, None
        if shrink.order > 0:
            return 0.0, 0
        ratio = delta / float(shrink.factor)
        if ratio < -1.0:
            if forced and self.allow_overfull:
                return ratio, 10000
            return None, None
        return ratio, self._lineBadness(ratio)

    @staticmethod
    def _fitnessClass(ratio):
        if ratio < -0.5:
            return 0  # tight
        if ratio <= 0.5:
            return 1  # decent
        if ratio <= 1.0:
            return 2  # loose
        return 3  # very loose

    def _evaluateBreak(self, start, candidate, line_no):
        last_line = candidate.next_start == self.end
        line_end = self.end if candidate.kind == "end" else candidate.break_index
        line_start = self._trimLineStartIndex(start, line_end)
        target, fixed_glue = self._lineTarget(line_no, last_line)
        natural, variable_glue = self._lineNatural(line_start, line_end)
        natural += fixed_glue.dimen
        glue_total = variable_glue + fixed_glue
        ratio, badness = self._adjustment(target - natural, glue_total, candidate.forced)
        if ratio is None:
            return None
        if badness > self.tolerance and not (candidate.forced and self.allow_overfull):
            return None
        return _LineMetrics(
            badness=badness,
            ratio=ratio,
            fitness=self._fitnessClass(ratio),
            hyphenated=candidate.hyphenated,
        )

    def _edgeDemerits(self, prev_state, candidate, metrics):
        value = self.context.linepenalty + metrics.badness
        demerits = value * value
        penalty = candidate.penalty
        if penalty >= 0:
            demerits += penalty * penalty
        elif penalty > -10000:
            demerits -= penalty * penalty
        if prev_state.line_no > 0:
            if abs(metrics.fitness - prev_state.fitness) > 1:
                demerits += self.context.adjdemerits
            if prev_state.hyphenated and metrics.hyphenated:
                demerits += self.context.doublehyphendemerits
            if candidate.next_start == self.end and prev_state.hyphenated:
                demerits += self.context.finalhyphendemerits
        return demerits

    def _bestFinalState(self, finals):
        best = min(finals, key=lambda s: s.demerits)
        looseness = self.context.looseness
        if looseness == 0:
            return best
        target = best.line_no + looseness
        matched = [s for s in finals if s.line_no == target]
        if matched:
            return min(matched, key=lambda s: s.demerits)
        return best

    def _buildPlan(self):
        """
        Dynamic-programming pass over legal breakpoints.

        Returns a list of chosen break states (one per emitted line), or
        `None` if no feasible solution exists under current tolerance.
        """
        start = _BreakState(position=0, line_no=0, demerits=0, fitness=1, hyphenated=False)
        frontier = [start]
        finals = []
        max_lines = max(1, self.end + 1)
        for _ in range(max_lines):
            next_states = {}
            for state in frontier:
                if state.position == self.end:
                    finals.append(state)
                    continue
                line_no = state.line_no + 1
                for candidate in self._iterBreakCandidates(state.position):
                    metrics = self._evaluateBreak(state.position, candidate, line_no)
                    if metrics is None:
                        continue
                    demerits = state.demerits + self._edgeDemerits(state, candidate, metrics)
                    key = (candidate.next_start, line_no, metrics.fitness, metrics.hyphenated)
                    best = next_states.get(key)
                    if best is not None and best.demerits <= demerits:
                        continue
                    next_states[key] = _BreakState(
                        position=candidate.next_start,
                        line_no=line_no,
                        demerits=demerits,
                        fitness=metrics.fitness,
                        hyphenated=metrics.hyphenated,
                        prev=state,
                        start_index=state.position,
                        break_index=candidate.break_index,
                        break_kind=candidate.kind,
                    )
            if not next_states:
                break
            frontier = list(next_states.values())
            finals.extend([s for s in frontier if s.position == self.end])
        if not finals:
            return None
        state = self._bestFinalState(finals)
        plan = []
        while state.prev is not None:
            plan.append(state)
            state = state.prev
        plan.reverse()
        return plan

    def _lineNodes(self, state):
        if state.break_kind == "end":
            return self.nodes[state.start_index:]
        # TODO: break_kind == "disc" should include pre/post lists.
        return self.nodes[state.start_index:state.break_index]

    def run(self):
        """
        Execute one round:
        1) build best break plan under current tolerance;
        2) emit line hboxes from reconstructed states;
        3) update paragraph `line_count` for `\\prevgraf` chaining.
        """
        plan = self._buildPlan()
        if plan is None:
            return False
        for i, state in enumerate(plan):
            _emitLine(
                parser=self.parser,
                para=self.para,
                vlist=self.vlist,
                line_nodes=self._lineNodes(state),
                line_no=i + 1,
                last_line=i == len(plan) - 1,
                add_parfillskip=self.add_parfillskip,
            )
        self.context.setLineCount(len(plan))
        return True


def _lineBreakRound(parser, para, vlist, tolerance, allow_overfull=False):
    """
    Run one line-breaking round.
    @param vlist: vertical list to receive the resulting line boxes
    @return: True if a feasible set of breaks is found and emitted

    TeX-style shortest-path algorithm, at a high level:
    1) Build legal breakpoints (glue, penalties, discretionary nodes) and
       evaluate candidate lines from prior active break states.
    2) Compute badness from line shortfall/excess using the paragraph context
       (`hsize`, `parshape`, skips, hanging-indent settings).
    3) Classify each feasible line into fitness classes and accumulate
       demerits (line penalties, hyphen penalties, adjacency penalties, etc.).
    4) Keep best active candidates keyed by breakpoint/line/fitness/hyphenation
       and prune worse alternatives as scanning proceeds.
    5) At paragraph end, pick best total demerits path, reconstruct breaks,
       then package each line as an hbox.
    6) Record produced line count into `typeset_context.line_count` so
       subsequent paragraphs receive `\\prevgraf`.
    """
    return _LineBreaker(parser, para, vlist, tolerance, allow_overfull).run()


def _hyphenate(parser, para):
    """
    Insert discretionary nodes for automatic hyphenation before round 2.
    @param parser the parser
    @param para the paragraph to hyphenate
    @return boolean indicating whether discretionary nodes have been inserted.
    """
    # TODO: implement paragraph hyphenation pass.
    return False


def lineBreak(parser, para, vlist):
    """
    Break one paragraph into lines (TeXbook Chapter 14).

    This routine is intentionally paragraph-driven, not stack-driven:
    callers must pass the Paragraph node to break, so lazy typesetting can
    process paragraphs in any order.

    TeX runs this in rounds:
    - Round 1: no automatic hyphenation.
    - If no feasible breaks are found, run hyphenation and repeat the same
      algorithm in round 2.
    `_lineBreakRound` assumes discretionary nodes are already present.

    @param parser: parser environment (used for helper routines/output hooks)
    @param para: the Paragraph node to be line-broken
    @param vlist: vertical list that receives the line boxes
    """
    if not isinstance(para, Paragraph):
        raise ValueError("lineBreak expects a Paragraph node")
    if para.typeset_context is None:
        raise ValueError("paragraph is missing typeset context")
    if getattr(vlist, "type", None) != lists.LISTTYPE.VERTICAL:
        raise ValueError("lineBreak expects a vertical list output")
    # Expand typesettable nodes once before round 1; rounds operate on the same list.
    if not getattr(para, "_linebreak_prepared", False):
        para[:] = para.typesetNodes(parser, para)
        para._linebreak_prepared = True
    context = para.typeset_context
    pre_tolerance = context.pretolerance
    if pre_tolerance < 0:
        pre_tolerance = context.tolerance
    if _lineBreakRound(parser, para, vlist, pre_tolerance):
        return
    if _hyphenate(parser, para) and _lineBreakRound(parser, para, vlist, context.tolerance):
        return
    # fallback: always produce lines, even when no feasible solution under tolerance.
    _lineBreakRound(parser, para, vlist, max(context.tolerance, 10000), allow_overfull=True)


mod = Module("paragraph",
    attributes={
        "lineBreak": lineBreak,
    },
)
