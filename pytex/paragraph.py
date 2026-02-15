"""
This module implement paragraph handling (unrestricted hlist).
"""

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
        super().__init__(parser, inner=False)
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


def _lineShape(context, line_no):
    # TEX provides a special abbreviation
    # for it in terms of two parameters called \hangindent and \hangafter. The command
    # ‘\hangindent=⟨dimen⟩’ specifies a so-called hanging indentation, and the command
    # ‘\hangafter=⟨number⟩’ specifies the duration of that indentation. Let x and n be the
    # respective values of \hangindent and \hangafter, and let h be the value of \hsize;
    # then if n≥0, hanging indentation will occur on lines n+1, n+2,...of the paragraph,
    # but if n<0 it will occur on lines 1, 2,..., |n|. Hanging indentation means that lines will
    # be of width h−|x|instead of their normal width h; if x≥0, the lines will be indented
    # at the left margin, otherwise they will be indented at the right margin. If \parshape is present, 
    # then it takes precedence.
    if context.parshape:
        i = line_no - 1
        if i >= len(context.parshape):
            i = len(context.parshape) - 1
        return context.parshape[i]
    hang = context.hangindent
    if hang == 0:
        return Dimen(), context.hsize
    after = context.hangafter
    if after >= 0:
        hanging = line_no > after
    else:
        hanging = line_no <= -after
    if not hanging:
        return Dimen(), context.hsize
    if hang > 0:
        return hang, context.hsize - abs(hang)
    return Dimen(), context.hsize - abs(hang)


class _BreakCandidate:
    """
    A legal line-break candidate.

    Fields:
    - `break_index`: index where the break happens.
    - `penalty`: break penalty (`<= -10000` means forced).
    - `hyphenated`: whether a break here is hyphenated.
    - `disc`: discretionary node if this is a discretionary break.
    - `discard`: total discardable glue/kern right after this break.
    - `line_start_index`: first non-discardable index when the next line starts.
    - `natural`: natural segment (dimen/stretch/shrink) from this start to next candidate.
    - `line`: best `_Line` ending at this break.
    """
    def __init__(self, break_index):
        self.break_index = break_index
        self.penalty = 0
        self.hyphenated = False
        self.disc = None
        self.discard = Glue()
        self.line_start_index = break_index
        self.natural = Glue()
        self.line = None

    @property
    def forced(self):
        return self.penalty <= -10000


class _Line:
    """
    One feasible line from `begin` to `end`.

    Demerits are computed in `__init__` using TeX-style terms:
    `(linepenalty + badness)^2`, penalty contribution, fitness adjacency
    demerits, and hyphenation demerits.
    """
    def __init__(self, breaker, begin, end, natural):
        context = breaker.context
        self.begin = begin
        self.end = end
        self.prev = begin.line
        self.line_no = 1 if self.prev is None else self.prev.line_no + 1
        self.hyphenated = end.hyphenated
        self.badness = 10001
        self.ratio = None
        self.fitness = 1
        self.demerits = float("inf")
        self.feasible = False

        last_line = end.break_index == breaker.end
        line_glue = context.leftskip + context.rightskip
        _, measure = breaker._lineShape(self.line_no)
        target = measure
        natural_width = natural.dimen + line_glue.dimen
        glue_total = natural + line_glue

        ratio, badness = breaker._adjustment(target - natural_width, glue_total, end.forced)
        if ratio is None:
            return
        self.ratio = ratio
        self.badness = badness
        if badness > breaker.tolerance and not (end.forced and breaker.allow_overfull):
            return

        self.feasible = True
        self.fitness = breaker._fitnessClass(ratio)

        line = context.linepenalty + badness
        demerits = line * line
        penalty = end.penalty
        if penalty >= 0:
            demerits += penalty * penalty
        elif penalty > -10000:
            demerits -= penalty * penalty

        if self.prev is not None:
            if abs(self.fitness - self.prev.fitness) > 1:
                demerits += context.adjdemerits
            if self.prev.hyphenated and self.hyphenated:
                demerits += context.doublehyphendemerits
            if last_line and self.prev.hyphenated:
                demerits += context.finalhyphendemerits
            demerits += self.prev.demerits

        self.demerits = demerits


class _BreakCandidateScan:
    """
    Scan one paragraph into break candidates and segment metrics.

    This preprocessing is independent from tolerance and demerit settings,
    so one scan can be reused across multiple line-breaking rounds.
    """
    def __init__(self, para):
        self.para = para
        self.context = para.typeset_context
        if (
            len(para) < 2
            or para[-2].node_type != nd.NODE_TYPE.PENALTY
            or para[-2].penalty != 10000
            or para[-1].node_type != nd.NODE_TYPE.GLUE
            or para[-1].glue != self.context.parfillskip
        ):
            raise ValueError("paragraph does not end with \\penalty10000 and \\parfillskip")
        # Keep tail nodes in the stream, as TeX does; the final line then
        # naturally includes \\parfillskip during line fitting/packaging.
        self.end = len(self.para)
        self.candidates = self._buildBreakCandidates()

    def segmentNatural(self, start, end):
        if end < start:
            end = start
        natural = Glue()
        for node in self.para[start:end]:
            node_type = node.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                natural += node.glue
                continue
            if node_type == nd.NODE_TYPE.KERN:
                width = node.kern
            elif node_type == nd.NODE_TYPE.DISC:
                width = Dimen()
            elif node_type == nd.NODE_TYPE.MATH:
                width = getattr(node, "kern", None)
                if width is None:
                    raise ValueError("math shift node is missing kern")
            else:
                width = getattr(node, "width", None)
                if width is None:
                    width = Dimen()
            natural.dimen += width
        return natural

    @staticmethod
    def _discHyphenated(disc):
        if not disc.pre:
            return False
        last = disc.pre[-1]
        if last.node_type == nd.NODE_TYPE.CHAR:
            return ord(last.char) == last.font.fontchar["hyphenchar"]
        if last.node_type == nd.NODE_TYPE.LIGATURE and getattr(last, "source", None):
            tail = last.source[-1]
            return (
                tail.node_type == nd.NODE_TYPE.CHAR
                and ord(tail.char) == tail.font.fontchar["hyphenchar"]
            )
        return False

    @staticmethod
    def _discardContribution(node):
        node_type = node.node_type
        if node_type == nd.NODE_TYPE.GLUE:
            return node.glue
        if node_type == nd.NODE_TYPE.KERN:
            return Glue(node.kern)
        return Glue()

    def _prepareCandidateStart(self, candidate):
        if candidate.break_index >= self.end:
            candidate.line_start_index = self.end
            candidate.discard = Glue()
            return

        if candidate.disc is not None:
            # For discretionary breaks, start with post-break material;
            # discardables after the break are not subtracted here.
            candidate.line_start_index = candidate.break_index + 1
            candidate.discard = Glue()
            return

        start = candidate.break_index
        discard = Glue()
        while start < self.end and _isDiscardable(self.para[start]):
            discard += self._discardContribution(self.para[start])
            start += 1
        candidate.line_start_index = start
        candidate.discard = discard

    def _buildBreakCandidates(self):
        # line breaks can happen at these points (TeXBook, page 98)
        # a) at glue, provided that this glue is immediately preceded by a non-discardable
        # item, and that it is not part of a math formula (i.e., not between math-on and
        # math-oﬀ). A break “at glue” occurs at the left edge of the glue space.
        # b) at a kern, provided that this kern is immediately followed by glue, and that it
        # is not part of a math formula.
        # c) at a math-oﬀ that is immediately followed by glue.
        # d) at a penalty (which might have been inserted automatically in a formula).
        # e) at a discretionary break.
        candidates = [_BreakCandidate(0)]
        in_math = False

        def append_candidate(candidate):
            candidates.append(candidate)

        for i, node in enumerate(self.para):
            node_type = node.node_type

            if node_type == nd.NODE_TYPE.MATH:
                in_math = node.on
                continue

            if node_type == nd.NODE_TYPE.GLUE:
                if in_math or i == 0:
                    continue
                prev = self.para[i - 1]
                prev_type = prev.node_type
                if prev_type == nd.NODE_TYPE.KERN:
                    append_candidate(_BreakCandidate(i - 1))
                elif prev_type == nd.NODE_TYPE.MATH and not prev.on:
                    append_candidate(_BreakCandidate(i - 1))
                elif not _isDiscardable(prev):
                    append_candidate(_BreakCandidate(i))
                continue

            if node_type == nd.NODE_TYPE.PENALTY and node.penalty < 10000:
                candidate = _BreakCandidate(i)
                candidate.penalty = node.penalty
                append_candidate(candidate)
                continue

            if node_type == nd.NODE_TYPE.DISC:
                candidate = _BreakCandidate(i)
                candidate.disc = node
                candidate.hyphenated = self._discHyphenated(node)
                candidate.penalty = self.context.exhyphenpenalty
                append_candidate(candidate)

        if candidates[-1].break_index != self.end:
            end_candidate = _BreakCandidate(self.end)
            end_candidate.penalty = -10000
            append_candidate(end_candidate)

        for candidate in candidates:
            self._prepareCandidateStart(candidate)

        for i, candidate in enumerate(candidates[:-1]):
            nxt = candidates[i + 1]
            start = candidate.break_index + 1 if candidate.disc is not None else candidate.break_index
            candidate.natural = self.segmentNatural(start, nxt.break_index)
        candidates[-1].natural = Glue()
        return candidates


class _LineBreaker:
    """
    One line-breaking round based on candidate graph nodes and a double loop.
    """
    def __init__(self, para, breaks, tolerance, allow_overfull=False):
        self.para = para
        self.context = para.typeset_context
        self.end = len(para)
        self.tolerance = tolerance
        self.allow_overfull = allow_overfull
        self.breaks = breaks

    def _lineShape(self, line_no):
        return _lineShape(self.context, line_no)

    @staticmethod
    def _badness(ratio):
        value = abs(ratio)
        return min(10000, int(100 * (value ** 3) + 0.5))

    @staticmethod
    def _fitnessClass(ratio):
        if ratio < -0.5:
            return 0  # tight
        if ratio <= 0.5:
            return 1  # decent
        if ratio <= 1.0:
            return 2  # loose
        return 3  # very loose

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
            return ratio, self._badness(ratio)

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
        return ratio, self._badness(ratio)

    def run(self):
        """
        Execute one line-breaking round and return chosen lines.
        """
        n = len(self.breaks)
        if n == 0:
            return None

        for candidate in self.breaks:
            candidate.line = None

        for i, begin in enumerate(self.breaks[:-1]):
            if i > 0 and begin.line is None:
                continue
            natural = Glue() - begin.discard
            if begin.disc is not None:
                natural.dimen += begin.disc.post_width
            for j in range(i + 1, n):
                natural += self.breaks[j - 1].natural
                end = self.breaks[j]
                natural_for_line = natural
                if end.disc is not None:
                    natural_for_line = natural.copy()
                    natural_for_line.dimen += end.disc.pre_width
                line = _Line(self, begin, end, natural_for_line)
                if not line.feasible:
                    if (
                        line.ratio is not None
                        and line.ratio < -1.0
                        and not end.forced
                        and not self.allow_overfull
                    ):
                        break
                elif end.line is None or line.demerits < end.line.demerits:
                    end.line = line
                if end.disc is not None:
                    natural.dimen += end.disc.replace_width

        final = self.breaks[-1].line
        if final is None:
            return None

        plan = []
        line = final
        while line is not None:
            plan.append(line)
            line = line.prev
        plan.reverse()
        return plan


def _hyphenate(para):
    """
    Insert discretionary nodes for automatic hyphenation before round 2.
    @param para the paragraph to hyphenate
    @return boolean indicating whether discretionary nodes have been inserted.
    """
    # TODO: implement paragraph hyphenation pass.
    return False


def _lineNodes(nodes, line):
    line_nodes = list(nodes[line.begin.line_start_index:line.end.break_index])
    expanded = []
    for node in line_nodes:
        if node.node_type == nd.NODE_TYPE.DISC:
            expanded.extend(node.replace)
        else:
            expanded.append(node)
    if line.begin.disc is not None and line.begin.disc.post:
        expanded = list(line.begin.disc.post) + expanded
    if line.end.disc is not None and line.end.disc.pre:
        expanded.extend(line.end.disc.pre)
    return expanded


def lineBreak(parser, para, vlist):
    """
    Break one paragraph into lines (TeXbook Chapter 14).

    This routine is paragraph-driven (the paragraph is explicit), so lazy
    typesetting can line-break paragraphs later.

    Round strategy:
    - Round 1: no automatic hyphenation.
    - If no feasible result, hyphenate and run round 2.
    - If still infeasible, run a fallback round that allows overfull forced
      breaks (matching TeX's "always break somehow" behavior).
    """
    if not isinstance(para, Paragraph):
        raise ValueError("lineBreak expects a Paragraph node")
    if para.typeset_context is None:
        raise ValueError("paragraph is missing typeset context")
    if getattr(vlist, "type", None) != lists.LISTTYPE.VERTICAL:
        raise ValueError("lineBreak expects a vertical list output")

    # Expand typesettable nodes once before round 1.
    if not getattr(para, "_linebreak_prepared", False):
        para[:] = para.typesetNodes(para.parser, para)
        para._linebreak_prepared = True

    context = para.typeset_context
    scan = _BreakCandidateScan(para)
    pre_tolerance = context.pretolerance
    if pre_tolerance < 0:
        pre_tolerance = context.tolerance
    lines = _LineBreaker(
        para,
        scan.candidates,
        pre_tolerance,
    ).run()
    if lines is None and _hyphenate(para):
        scan = _BreakCandidateScan(para)
        lines = _LineBreaker(
            para,
            scan.candidates,
            context.tolerance,
        ).run()
    if lines is None:
        lines = _LineBreaker(
            para,
            scan.candidates,
            max(context.tolerance, 10000),
            allow_overfull=True,
        ).run()
    if lines is None:
        return
    for i, line in enumerate(lines):
        line_nodes = _lineNodes(para, line)
        indent, measure = _lineShape(context, i + 1)
        packed = [nd.Glue(context.leftskip)]
        if indent != 0:
            packed.insert(0, nd.Glue(Glue(indent)))
        packed.extend(line_nodes)
        packed.append(nd.Glue(context.rightskip))
        hbox = bx.HBox(parser, measure, Dimen())
        hbox.list[:] = packed
        hbox.typeset(parser, [])
        hbox.source = para
        vlist.append(hbox)
    context.setLineCount(len(lines))


mod = Module("paragraph",
    attributes={
        "lineBreak": lineBreak,
    },
)
