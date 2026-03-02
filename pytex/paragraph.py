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
from pytex.integer import IntegerArrayItemAccessor


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
    def __init__(self, parser, paragraph):
        self.paragraph = paragraph
        self.line_count = None
        # In TeX, \prevgraf is usually 0, except after a display.
        self.prevgraf = paragraph.prevgraf
        self.hsize = parser.state.layout["hsize"]
        self.leftskip = parser.state.layout["leftskip"]
        self.rightskip = parser.state.layout["rightskip"]
        self.parfillskip = parser.state.parameters["parfillskip"]
        self.interlinepenalty = parser.state.layout["interlinepenalty"]
        self.baselineskip = parser.state.layout["baselineskip"]
        self.lineskip = parser.state.layout["lineskip"]
        self.lineskiplimit = parser.state.layout["lineskiplimit"]
        self.pretolerance = parser.state.layout["pretolerance"]
        self.tolerance = parser.state.layout["tolerance"]
        self.linepenalty = parser.state.layout["linepenalty"]
        self.hyphenpenalty = parser.state.layout["hyphenpenalty"]
        self.exhyphenpenalty = parser.state.layout["exhyphenpenalty"]
        self.adjdemerits = parser.state.layout["adjdemerits"]
        self.doublehyphendemerits = parser.state.layout["doublehyphendemerits"]
        self.finalhyphendemerits = parser.state.layout["finalhyphendemerits"]
        self.looseness = parser.state.volatile["looseness"]
        self.hangindent = parser.state.volatile["hangindent"]
        self.hangafter = parser.state.volatile["hangafter"]
        self.parshape = parser.state.globals["parshape"]
        # Current em (fontdimen6) at paragraph typeset snapshot time.
        self.em = parser.state.parameters["currentfont"].param[5]
        self.lefthyphenmin = parser.state.layout["lefthyphenmin"]
        self.righthyphenmin = parser.state.layout["righthyphenmin"]
        self.words = self.buildWords(parser, paragraph)
        self.actual_looseness = 0

    def lineShape(self, line_no):
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
        if self.parshape:
            i = line_no - 1
            if i >= len(self.parshape):
                i = len(self.parshape) - 1
            return self.parshape[i]
        hang = self.hangindent
        if hang == 0:
            return Dimen(), self.hsize
        after = self.hangafter
        if after >= 0:
            hanging = line_no > after
        else:
            hanging = line_no <= -after
        if not hanging:
            return Dimen(), self.hsize
        if hang > 0:
            return hang, self.hsize - abs(hang)
        return Dimen(), self.hsize - abs(hang)

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


class LineContext:
    """
    Context for line-breaking a paragraph.
    """
    def __init__(self, parser, context, line):
        line_no = line.line_no
        if line_no == 2:
            adjust = parser.state.layout["clubpenalty"]
        elif line_no == context.line_count - 1:
            adjust = parser.state.layout["widowpenalty"]
        else:
            adjust = 0
        if line.hyphenated:
            adjust += parser.state.layout["hyphenpenalty"]
        self.interlinepenalty = context.interlinepenalty + adjust
        self.baselineskip = context.baselineskip
        self.lineskip = context.lineskip
        self.lineskiplimit = context.lineskiplimit


class Paragraph(hmode.HList):
    """
    A paragraph.
    @param parser: the parser
    @param indent: whether to indent the paragraph
    """
    def __init__(self, parser, indent: bool):
        super().__init__(parser, inner=False)
        # \prevgraf for this paragraph (set by display-math machinery when needed).
        self.prevgraf = 0
        self.typeset_context = None
        if indent:
            self.append(bx.IndentBox(parser))
        # these two fields are used to link paragraphs together for display math integration,
        self.next_paragraph = None
        self.prev_paragraph = None
        # if this paragraph has been typeset, then the line boxes are stored in this cache
        self._typeset_cache = None

    # not a proper node
    node_type = None

    def saveInfo(self):
        d = super().saveInfo()
        d["init"]["indent"] = self.inner
        del d["init"]["inner"]
        return d | {"extra": {"disc": self.disc}}
    
    def pretypeset(self, parser): 
        """
        pretypeset the paragraph, i.e., break into lines, and set the , using the current typeset context.
        """
        if self._typeset_cache is not None:
            return
        # Pre-typeset the paragraph nodes into a temporary horizontal stream.
        context = self.typeset_context
        hlist = []
        ligature_state = {"lig_base": None, "in_word": False}
        for node in self:
            self.typesetNodeWithLigatures(parser, node, hlist, ligature_state)
        # line break the hlist into lines and pack them into the vlist
        hlist, lines = self.lineBreak(parser, hlist)
        line_count = len(lines)
        context.line_count = line_count
        # add the lines into the vlist
        hbox = None
        self._typeset_cache = []
        for i, line in enumerate(lines):
            packed = []
            indent, measure = context.lineShape(i + 1)
            if indent != 0:
                packed.append(nd.Glue(Glue(indent), "\\parindent"))
            if context.leftskip != Glue():
                packed.append(nd.Glue(context.leftskip, "\\leftskip"))
            # if the line starts with a ligature then add in the post nodes
            if line.begin.disc is not None:
                packed.extend(line.begin.disc.post)
            # for any disc node in between, replace it with the replace list
            for node in hlist[line.begin.line_start_index:line.end.break_index]:
                if node.node_type == nd.NODE_TYPE.DISC:
                    packed.append(self._lineDisc(node, broken=False))
                else:
                    packed.append(node)
            # TeX keeps an explicit breakpoint penalty in the ending line box
            # when the break is chosen at that penalty node.
            if line.end.break_index < len(hlist):
                end_node = hlist[line.end.break_index]
                if line.end.at_penalty:
                    packed.append(end_node)
            # if the line ends at a ligature, append the pre nodes
            if line.end.disc is not None:
                packed.append(self._lineDisc(line.end.disc, broken=True))
            packed.append(nd.Glue(context.rightskip, "\\rightskip"))
            hbox = bx.HBox(parser, measure, None)
            hbox.list = packed
            hbox.typeset(parser, [])
            hbox.source = self
            hbox.typeset_context = LineContext(parser, context, line)
            self._typeset_cache.append(hbox)
        if self.next_paragraph is not None:
            self.next_paragraph.prevgraf = line_count
            # For an immediately following display, TeX uses the next line-shape
            # slot to determine \displayindent and \displaywidth.
            displayindent, displaywidth = context.lineShape(line_count + 1)
            next_context = self.next_paragraph.typeset_context
            next_context.prevgraf = line_count
            self.line_count = line_count
            next_context.displayindent = displayindent
            next_context.displaywidth = displaywidth
            # Furthermore, \predisplaysize is set to the eﬀective width p of the line preceding the display, as
            # follows: If there was no previous line (e.g., if the $$ was preceded by \noindent or by
            # the closing $$ of another display), p is set to -16383.99999 pt (i.e., to the smallest legal
            # dimension, -\maxdimen). Otherwise TEX looks inside the hbox that was formed by the
            # previous line, and sets p to the position of the right edge of the rightmost box inside
            # that hbox, plus the indentation by which the enclosing hbox has been moved right, plus
            # two ems in the current font.
            if hbox is None:
                next_context.predisplaysize = Dimen(-16383.99999)
                next_context.prevdepth = Dimen()
            else:
                next_context.predisplaysize = hbox.rightmost() + 2 * context.em
                next_context.prevdepth = hbox.depth

    def typeset(self, parser, vlist):
        self.pretypeset(parser)
        for line in self._typeset_cache:
            vlist.append(line)

    @staticmethod
    def _lineDisc(disc, broken):
        rendered = disc.pre if broken else disc.replace
        out = nd.Disc(disc.pre, disc.post, rendered)
        out.list = rendered
        out.source = getattr(disc, "source", None)
        return out

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
        breaker = _LineBreaker(self, hlist, scan.candidates, pre_tolerance)
        lines = breaker.run()
        working_hlist = hlist
        working_breaks = scan.candidates
        if lines is None or (
            context.looseness != 0
            and breaker.actual_looseness != context.looseness
        ):
            hyphenated = self._hyphenate(parser)
            if hyphenated:
                working_hlist, working_breaks = hyphenated
                hyphen_breaker = _LineBreaker(self, working_hlist, working_breaks, context.tolerance)
                hyphen_lines = hyphen_breaker.run()
                if hyphen_lines is not None:
                    breaker = hyphen_breaker
                    lines = hyphen_lines
        if lines is None:
            breaker = _LineBreaker(
                self,
                working_hlist,
                working_breaks,
                max(context.tolerance, 10000),
                allow_overfull=True,
            )
            lines = breaker.run()
        context.actual_looseness = breaker.actual_looseness
        return working_hlist, lines

    def _hyphenate(self, parser, hlist=None, scan=None):
        """
        Insert explicit discretionary nodes into a copied raw paragraph, then
        re-expand and rescan breakpoints.
        """
        context = self.typeset_context
        if not context.words:
            return None
        raw = list(self)
        inserted = 0
        for word in context.words:
            parser.hyphenator.setLanguage(word.language)
            hyphen_points = parser.hyphenator.hyphenate(word.text)
            if not hyphen_points:
                continue
            for point in hyphen_points:
                left = point
                right = len(word.text) - point
                if left < context.lefthyphenmin or right < context.righthyphenmin:
                    continue
                index = word.begin + inserted + point
                prev = raw[index - 1]
                if prev.node_type != nd.NODE_TYPE.CHAR:
                    continue
                hyphen = prev.font.hyphenChar()
                if hyphen is None:
                    continue
                raw.insert(index, nd.Disc([hyphen], [], []))
                inserted += 1
        if inserted == 0:
            return None
        packed = []
        ligature_state = {"lig_base": None, "in_word": False}
        for node in raw:
            self.typesetNodeWithLigatures(parser, node, packed, ligature_state)
        return packed, _BreakCandidateScan(context, packed).candidates


class _BreakCandidate:
    """
    A legal line-break candidate.

    Fields:
    - `break_index`: first node not included in the current line.
    - `penalty`: break penalty (`<= -10000` means forced).
    - `hyphenated`: whether a break here is hyphenated.
    - `disc`: discretionary node if this is a discretionary break.
    - `line_start_index`: first non-discardable index when the next line starts.
    """
    def __init__(self, break_index):
        self.break_index = break_index
        self.penalty = 0
        self.hyphenated = False
        self.disc = None
        self.at_penalty = False
        self.line_start_index = break_index

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
    def __init__(self, breaker, prev, begin, end):
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
        _, measure = breaker.context.lineShape(self.line_no)
        target = measure
        natural = breaker._lineNatural(begin, end)
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
    Scan one expanded paragraph stream into legal break candidates.
    """
    def __init__(self, context, nodes):
        self.nodes = nodes
        self.context = context
        if (
            len(nodes) < 2
            or nodes[-2].node_type != nd.NODE_TYPE.PENALTY
            or nodes[-2].penalty != 10000
            or nodes[-1].node_type != nd.NODE_TYPE.GLUE
            or nodes[-1].glue != self.context.parfillskip
        ):
            raise ValueError("paragraph does not end with \\penalty10000 and \\parfillskip")
        self.end = len(self.nodes)
        self.candidates = self._buildBreakCandidates()

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

    @staticmethod
    def _isDiscardable(node):
        return node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY)

    def _prepareCandidateStart(self, candidate):
        if candidate.break_index >= self.end:
            candidate.line_start_index = self.end
            return

        if candidate.disc is not None:
            candidate.line_start_index = candidate.break_index + 1
            return

        start = candidate.break_index + 1 if candidate.at_penalty else candidate.break_index
        while start < self.end and self._isDiscardable(self.nodes[start]):
            start += 1
        candidate.line_start_index = start

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

        for i, node in enumerate(self.nodes):
            node_type = node.node_type

            if node_type == nd.NODE_TYPE.MATH:
                in_math = node.on
                continue

            if node_type == nd.NODE_TYPE.GLUE:
                if in_math or i == 0:
                    continue
                prev = self.nodes[i - 1]
                prev_type = prev.node_type
                if prev_type == nd.NODE_TYPE.KERN:
                    append_candidate(_BreakCandidate(i))
                elif prev_type == nd.NODE_TYPE.MATH and not prev.on:
                    append_candidate(_BreakCandidate(i))
                elif not self._isDiscardable(prev):
                    append_candidate(_BreakCandidate(i))
                continue

            if node_type == nd.NODE_TYPE.PENALTY and node.penalty < 10000:
                candidate = _BreakCandidate(i)
                candidate.penalty = node.penalty
                candidate.at_penalty = True
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
        return candidates


class _LineBreaker:
    """
    One line-breaking round based on expanded nodes and direct slice
    measurement between legal breakpoints.
    """
    def __init__(self, para, nodes, breaks, tolerance, allow_overfull=False):
        self.para = para
        self.nodes = nodes
        self.context = para.typeset_context
        self.end = breaks[-1].break_index if breaks else len(nodes)
        self.tolerance = tolerance
        self.allow_overfull = allow_overfull
        self.breaks = breaks
        self.actual_looseness = 0

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

    def _lineNatural(self, begin, end):
        natural = Glue()
        if begin.disc is not None:
            natural.dimen += begin.disc.post_width
        for node in self.nodes[begin.line_start_index:end.break_index]:
            node_type = node.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                natural += node.glue
            elif node_type == nd.NODE_TYPE.KERN:
                natural.dimen += node.kern
            elif node_type == nd.NODE_TYPE.DISC:
                natural.dimen += node.replace_width
            elif node_type == nd.NODE_TYPE.MATH:
                width = getattr(node, "kern", None)
                if width is None:
                    raise ValueError("math shift node is missing kern")
                natural.dimen += width
            else:
                width = getattr(node, "width", None)
                if width is not None:
                    natural.dimen += width
        if end.disc is not None:
            natural.dimen += end.disc.pre_width
        return natural

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
                for j in range(i + 1, n):
                    end = self.breaks[j]
                    line = _Line(self, state.line, begin, end)
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


class PrevGraf(IntegerArrayItemAccessor):
    def intValue(self, parser):
        value = parser.state.globals["prevgraf"]
        if value is not None:
            return value
        # when this is accessed here, we are in building a list. So we use parser.paragraph_before_last_display_math
        # if this paragraph does not exist, then the value has not been changed. we should have returned early
        para = parser.last_paragraph
        assert para is not None
        para.pretypeset(parser)
        return para.line_count

mod = Module("paragraph",
    commands={
        "setlanguage": SetLanguage(),
    },
    parameters={
        "prevgraf": {"value": 0, "accessor": PrevGraf, "domain": "globals"},
    },
    attributes={
        "last_paragraph": None,
    }
)
