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
from pytex.hmode import HorizontalCommand


class Word:
    """
    Snapshot of one word in the original paragraph node list.
    """
    def __init__(self, language, begin, end, text):
        self.language = language
        self.begin = begin
        self.end = end
        self.text = text


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
        self.lefthyphenmin = parser.state.layout["lefthyphenmin"]
        self.righthyphenmin = parser.state.layout["righthyphenmin"]
        self.words = self.buildWords(parser, paragraph)
        self.actual_looseness = 0

    def setLineCount(self, line_count):
        self.line_count = line_count
        if self.next_context is not None:
            self.next_context.prevgraf = line_count

    def buildWords(self, parser, paragraph):
        # TEX looks for potentially hyphenatable words by searching ahead from each
        # glue item that is not in a math formula. The search bypasses charac-
        # ters whose \lccode is zero, or ligatures that begin with such characters; it also by-
        # passes whatsits and implicit kern items, i.e., kerns that were inserted by T EX it-
        # self because of information stored with the font. If the search finds a charac-
        # ter with nonzero \lccode, or if it finds a ligature that begins with such a charac-
        # ter, that character is called the starting letter. But if any other type of item oc-
        # curs before a suitable starting letter is found, hyphenation is abandoned (until af-
        # ter the next glue item). Thus, a box or rule or mark, or a kern that was explicitly in-
        # serted by \kern or \/, must not intervene between glue and a hyphenatable word. If
        # the starting letter is not lowercase (i.e., if it doesn’t equal its own \lccode), hyphen-
        # ation is abandoned unless \uchyph is positive
        words = []
        language = parser.state.parameters["language"]
        lccode = parser.state.lccode
        start = None # the start index of the current word
        # states: 0 = allow, 1 = disallow, 2 = in word
        state = 0 # allowed at the beginning of the paragraph
        text = []
        uchyph = parser.state.layout["uchyph"] > 0
        font = None
        hyphenchar = None

        for i, node in enumerate(paragraph):
            if state == 0:
                # start only if we see a char with nonzero lccode or a ligature that begins with such a char
                if node.node_type == nd.NODE_TYPE.LIGATURE:
                    chars =getattr(node, "source", None)
                    node = chars[0]
                if node.node_type == nd.NODE_TYPE.CHAR:
                    if font != node.font:
                        font = node.font
                        hyphenchar = font.fontchar["hyphenchar"]
                    if hyphenchar < 0 or font.bc > hyphenchar or hyphenchar > font.ec:
                        continue
                    c = ord(node.char)
                    lc = lccode[c]
                    if lc == c or (lc !=0 and uchyph > 0):
                        state = 2
                        start = i
                        text.append(node.char)
                        continue
                state = 1
                continue
            if state == 1:
                # wait until we see a glue
                if node.node_type == nd.NODE_TYPE.GLUE:
                    state = 0
                continue
            # now state == 2. We are in a word, and we want to keep going until we see something that cannot be part of a word.
            if node.node_type == nd.NODE_TYPE.KERN and node.automatic and start is not None:
                continue
            if node.node_type == nd.NODE_TYPE.CHAR and lccode[ord(node.char)] != 0:
                text.append(node.char)
                continue
            if node.node_type == nd.NODE_TYPE.LIGATURE:
                source = getattr(node, "source", [])
                all = True
                chars = []
                for c in source:
                    if c.node_type == nd.NODE_TYPE.CHAR:
                        if lccode[ord(c.char)] == 0:
                            all = False
                            break
                        chars.append(c.char)
                if all:
                    text.extend(chars)
                    continue
            if isinstance(node, Language):
                language = node.language
            # if the word is too short, do not hyphenate
            text = "".join(text)
            if len(text) >= self.lefthyphenmin + self.righthyphenmin:
                words.append(Word(language, start, i, text))
            start = None
            state = 0 if node.node_type == nd.NODE_TYPE.GLUE else 1
            text = []
        return words


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
    
    def typeset(self, parser, vlist): 
        """
        typeset the paragraph into the given vertical list, using the current typeset context.
        """
        # TODO: add a parskip into vlist first
        # pre-typeset the nodes into a new HList
        context = self.typeset_context
        hlist = hmode.HList(parser, inner=True)
        words = iter(context.words)
        word = next(words, None)
        for i, node in enumerate(self):
            if word is not None:
                if i == word.begin:
                    word.begin = len(hlist)
                elif i == word.end:
                    word.end = len(hlist)
                    word = next(words, None)
            self.typesetNode(parser, node, hlist)
        # line break the hlist into lines and pack them into the vlist
        lines = self.lineBreak(parser, hlist)
        # add the lines into the vlist
        if lines:
            for i, line in enumerate(lines):
                packed = []
                indent, measure = _lineShape(context, i + 1)
                if indent != 0:
                    packed.append(nd.Glue(Glue(indent)))
                packed.append(nd.Glue(context.leftskip))
                # if the line starts with a ligature then add in the post nodes
                if line.begin.disc is not None:
                    packed.extend(line.begin.disc.post)
                discarding = True
                # for any disc node in between, replace it with the replace list
                for node in hlist[line.begin.break_index:line.end.break_index]:
                    if discarding:
                        if _isDiscardable(node):
                            continue
                        else:
                            discarding = False
                    if node.node_type == nd.NODE_TYPE.DISC:
                        packed.extend(node.replace)
                    else:
                        packed.append(node)
                # if the line ends at a ligature, append the pre nodes
                if line.end.disc is not None:
                    packed.extend(line.end.disc.pre)
                packed.append(nd.Glue(context.rightskip))
                hbox = bx.HBox(parser, measure, None)
                hbox.list = packed
                hbox.typeset(parser, [])
                hbox.source = self
                # TODO add an interline glue into the vlist
                vlist.append(hbox)
            context.setLineCount(len(lines))

    def lineBreak(self, parser, hlist):
        """
        Break the paragraph into lines (TeXbook Chapter 14).

        This routine is paragraph-driven (the paragraph is explicit), so lazy
        typesetting can line-break paragraphs later.

        Round strategy:
        - Round 1: no automatic hyphenation.
        - If no feasible result, hyphenate and run round 2.
        - If still infeasible, run a fallback round that allows overfull forced
        breaks (matching TeX's "always break somehow" behavior).
        """
        context = self.typeset_context
        scan = _BreakCandidateScan(context, hlist)
        pre_tolerance = context.pretolerance
        if pre_tolerance < 0:
            pre_tolerance = context.tolerance
        breaker = _LineBreaker(
            self,
            scan.candidates,
            pre_tolerance,
        )
        lines = breaker.run()
        if lines is None or (
            context.looseness != 0
            and breaker.actual_looseness != context.looseness
        ):
            breaks = self._hyphenate(parser, hlist, scan.candidates)
            if breaks:
                hyphen_breaker = _LineBreaker(
                    self,
                    breaks,
                    context.tolerance,
                )
                hyphen_lines = hyphen_breaker.run()
                if hyphen_lines is not None:
                    breaker = hyphen_breaker
                    lines = hyphen_lines
        if lines is None:
            breaker = _LineBreaker(
                self,
                scan.candidates,
                max(context.tolerance, 10000),
                allow_overfull=True,
            )
            lines = breaker.run()
        context.actual_looseness = breaker.actual_looseness
        return lines

    def _hyphenate(self, parser, hlist, scan):
        """
        Build virtual discretionary break candidates for automatic hyphenation.
        @param scan: the initial break candidate scan result without hyphenation.
        @return boolean indicating whether virtual discretionary candidates are available.
        """
        context = self.typeset_context
        breaks = []
        words = iter(context.words)
        current_word = next(words, None)
        # if no word to hyphenate, return immediately
        if not scan or current_word is None:
            return None
        # for each candidate, check if the current word is hyphenatable
        n = len(scan)
        next_candidate = scan[0]
        hyphen = None
        font = None
        for i in range(n-1):
            candidate = next_candidate
            next_candidate = scan[i + 1]
            breaks.append(candidate)
            # while current_word is in the candidate, try to hyphenate it
            while candidate.break_index <= current_word.begin < next_candidate.break_index:
                parser.hyphenator.setLanguage(current_word.language)
                hyphen_points = parser.hyphenator.hyphenate(current_word.text)
                if hyphen_points:
                    hyphens = iter(hyphen_points)
                    left = hyphen_points[0]
                    right = len(current_word.text) - hyphen_points[-1]
                    if left >= context.lefthyphenmin and right >= context.righthyphenmin:
                        # check if the word contains a ligature, as these have different DISC nodes.
                        pos = 0 # the current character position in the word
                        hyphen_point = next(hyphens, None)
                        for j in range(current_word.begin, current_word.end):
                            disc = None
                            node = hlist[j]
                            if node.node_type == nd.NODE_TYPE.LIGATURE:
                                if font != node.font:
                                    font = node.font
                                    hyphen = font.hyphenChar()
                                if pos <= hyphen_point < pos + len(node.source):
                                    # we are breaking in the middle of a ligature.
                                    if hyphen is None:
                                        break
                                    pre = node.source[0:hyphen_point - pos]
                                    pre.append(hyphen)
                                    post = node.source[hyphen_point - pos:]
                                    replace = [node]
                                    disc = nd.Disc(pre, post, replace)
                                    disc.source = node
                                    # TODO We are chaning the original paragraph node list here, which is not ideal. 
                                    hlist[j] = disc
                                pos += len(node.source)
                            elif node.node_type == nd.NODE_TYPE.CHAR:
                                if font != node.font:
                                    font = node.font
                                    hyphen = font.hyphenChar()
                                if pos == hyphen_point:
                                    # we are breaking at a character boundary.
                                    if hyphen is None:
                                        break
                                    disc = nd.Disc([hyphen], [], [])
                                pos += 1
                            if disc is not None:
                                # add a break candidate here
                                new = _BreakCandidate(j)
                                new.disc = disc
                                new.hyphenated = True
                                breaks.append(new)
                                # move to the next hyphenation point
                                hyphen_point = next(hyphens, None)
                                if hyphen_point is None:
                                    break
                current_word = next(words, None)
                if current_word is None:
                    breaks.extend(scan[i + 1:])
                    return _BreakCandidateScan.fillMetrics(context, hlist, breaks)
        breaks.extend(scan[n - 1:])
        return _BreakCandidateScan.fillMetrics(context, hlist, breaks)


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
    """
    def __init__(self, break_index):
        self.break_index = break_index
        self.penalty = 0
        self.hyphenated = False
        self.disc = None
        self.disc_skip = 0
        self.discard = Glue()
        self.line_start_index = break_index
        self.natural = Glue()

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
    def __init__(self, breaker, prev, begin, end, natural):
        context = breaker.context
        self.begin = begin
        self.end = end
        self.prev = prev
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
    def __init__(self, context, para):
        self.para = para
        self.context = context
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
            candidate.line_start_index = candidate.break_index + candidate.disc_skip
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
                candidate.disc_skip = 1
                candidate.hyphenated = self._discHyphenated(node)
                candidate.penalty = self.context.exhyphenpenalty
                append_candidate(candidate)

        if candidates[-1].break_index != self.end:
            end_candidate = _BreakCandidate(self.end)
            end_candidate.penalty = -10000
            append_candidate(end_candidate)

        return self._fillMetrics(candidates)

    @classmethod
    def fillMetrics(cls, context, para, candidates):
        scan = cls.__new__(cls)
        scan.context = context
        scan.para = para
        scan.end = len(para)
        return scan._fillMetrics(candidates)

    def _fillMetrics(self, candidates):

        for candidate in candidates:
            self._prepareCandidateStart(candidate)

        for i, candidate in enumerate(candidates[:-1]):
            nxt = candidates[i + 1]
            if candidate.disc is not None:
                start = candidate.break_index + candidate.disc_skip
            else:
                start = candidate.break_index
            candidate.natural = self.segmentNatural(start, nxt.break_index)
        candidates[-1].natural = Glue()
        return candidates


class _VirtualDisc:
    """
    Discretionary payload for an automatic hyphenation break candidate.
    """
    def __init__(self, pre, post=None, replace=None):
        self.pre = list(pre)
        self.post = [] if post is None else list(post)
        self.replace = [] if replace is None else list(replace)
        self.pre_width = nd.Disc._fixedWidth(self.pre)
        self.post_width = nd.Disc._fixedWidth(self.post)
        self.replace_width = nd.Disc._fixedWidth(self.replace)


class _LineBreaker:
    """
    One line-breaking round based on candidate graph nodes and a double loop.
    """
    def __init__(self, para, breaks, tolerance, allow_overfull=False):
        self.para = para
        self.context = para.typeset_context
        self.end = breaks[-1].break_index if breaks else len(para)
        self.tolerance = tolerance
        self.allow_overfull = allow_overfull
        self.breaks = breaks
        self.actual_looseness = 0

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

    class _State:
        """
        DP state at one breakpoint.
        """
        def __init__(self, break_pos, line):
            self.break_pos = break_pos
            self.line = line
            if line is None:
                self.line_no = 0
                self.fitness = 1
                self.hyphenated = False
                self.demerits = 0
            else:
                self.line_no = line.line_no
                self.fitness = line.fitness
                self.hyphenated = line.hyphenated
                self.demerits = line.demerits

    @staticmethod
    def _selectFinal(finals, looseness):
        baseline = min(finals, key=lambda state: state.demerits)
        if looseness == 0:
            return baseline, baseline
        base_lines = baseline.line_no
        if looseness > 0:
            admissible = [
                state
                for state in finals
                if 0 <= state.line_no - base_lines <= looseness
            ]
        else:
            admissible = [
                state
                for state in finals
                if looseness <= state.line_no - base_lines <= 0
            ]
        if not admissible:
            return baseline, baseline
        chosen = min(
            admissible,
            key=lambda state: (
                abs((state.line_no - base_lines) - looseness),
                state.demerits,
            ),
        )
        return baseline, chosen

    def run(self):
        """
        Execute one line-breaking round using DP and return chosen lines.
        """
        n = len(self.breaks)
        if n == 0:
            return None

        frontier = [self._State(0, None)]
        finals = []

        while frontier:
            next_states = {}
            for state in frontier:
                i = state.break_pos
                begin = self.breaks[i]
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
                    line = _Line(self, state.line, begin, end, natural_for_line)
                    if not line.feasible:
                        if (
                            line.ratio is not None
                            and line.ratio < -1.0
                            and not end.forced
                            and not self.allow_overfull
                        ):
                            break
                    else:
                        key = (j, line.line_no, line.fitness, line.hyphenated)
                        best = next_states.get(key)
                        if best is None or line.demerits < best.demerits:
                            next_states[key] = self._State(j, line)
                    if end.disc is not None:
                        natural.dimen += end.disc.replace_width
            if not next_states:
                break
            frontier = list(next_states.values())
            finals.extend([state for state in frontier if state.break_pos == n - 1])

        if not finals:
            return None

        baseline, best = self._selectFinal(finals, self.context.looseness)
        self.actual_looseness = best.line_no - baseline.line_no

        plan = []
        line = best.line
        while line is not None:
            plan.append(line)
            line = line.prev
        plan.reverse()
        return plan


class SetLanguage(HorizontalCommand):
    def horizontal(self, parser, hlist):
        language = parser.readInteger()
        hlist.append(Language(language))


mod = Module("paragraph",
    commands={
        "setlanguage": SetLanguage(),
    },
)
