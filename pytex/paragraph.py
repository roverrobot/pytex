"""
This module implement paragraph handling (unrestricted hlist).
"""

from pytex import hmode
from pytex import node as nd
from pytex import box as bx
from pytex import lists
from pytex.module import Module
from pytex.dimen import Dimen
from pytex.glue import Glue, Stretchness
from pytex.hmode import HorizontalCommand
from pytex.integer import IntegerArrayItemAccessor


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
        self.uchyph = parser.state.layout["uchyph"] > 0
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
        context = self.typeset_context
        scan = self._typesetNodesWithBreaks(parser, self)
        hlist = scan
        # line break the hlist into lines and pack them into the vlist
        hlist, lines = self.lineBreak(parser, hlist, scan.candidates)
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
            hbox.list[:] = packed
            hbox = hbox.typeset(parser)
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
        out.list = list(rendered)
        out.source = getattr(disc, "source", None)
        return out

    def _typesetNodesWithBreaks(self, parser, nodes):
        """
        Expand raw horizontal nodes and mark legal breakpoints in one pass.
        """
        scan = _BreakCandidateScan(self.typeset_context)
        ligature_state = {"lig_base": None, "in_word": False}
        for node in nodes:
            self.typesetNodeWithLigatures(parser, node, scan, ligature_state)
        if ligature_state["in_word"]:
            self._applyRightBoundary(scan, ligature_state)
        scan.finish()
        return scan

    def lineBreak(self, parser, hlist, breaks=None):
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
        pre_tolerance = context.pretolerance
        if pre_tolerance < 0:
            pre_tolerance = context.tolerance
        if breaks is None:
            breaks = _BreakCandidateScan(context, hlist).candidates
        breaker = _LineBreaker(self, hlist, breaks, pre_tolerance)
        lines = breaker.run()
        working_hlist = hlist
        working_breaks = breaks
        if lines is None or (
            context.looseness != 0
            and breaker.actual_looseness != context.looseness
        ):
            hyphenated = self._hyphenate(parser, hlist, breaks)
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
        Insert virtual discretionary breakpoints into a copied break chain by
        scanning the already-expanded node list.
        """
        context = self.typeset_context
        if hlist is None or scan is None:
            expanded = self._typesetNodesWithBreaks(parser, self)
            hlist = expanded
            scan = expanded.candidates
        extras = self._hyphenBreakCandidates(parser, hlist)
        if not extras:
            return None
        hyphenated = _BreakCandidateChain()
        source = scan.head
        extra_i = 0
        while source is not None or extra_i < len(extras):
            use_extra = False
            if extra_i < len(extras):
                if source is None:
                    use_extra = True
                else:
                    extra = extras[extra_i]
                    if extra.break_index < source.break_index:
                        use_extra = True
                    elif extra.break_index == source.break_index:
                        source_kind = 0 if source.disc is not None else 1
                        extra_kind = 0 if extra.disc is not None else 1
                        use_extra = (extra_kind, extra.disc_skip) < (source_kind, source.disc_skip)
            if use_extra:
                candidate = extras[extra_i]
                extra_i += 1
            else:
                candidate = _BreakCandidate(source.break_index)
                candidate.penalty = source.penalty
                candidate.hyphenated = source.hyphenated
                candidate.disc = source.disc
                candidate.disc_skip = source.disc_skip
                candidate.at_penalty = source.at_penalty
                source = source.next
            hyphenated.append(candidate)
        for candidate in hyphenated:
            _BreakCandidateScan.prepareCandidateStart(hlist, len(hlist), candidate)
        return hlist, hyphenated

    def _typesetFragment(self, parser, chars):
        packed = []
        state = {"lig_base": None, "in_word": True}
        for node in chars:
            self.typesetNodeWithLigatures(parser, node, packed, state)
        return packed

    def _virtualDisc(self, pre, post):
        out = nd.Disc(pre, post, [])
        out.list = []
        return out

    @staticmethod
    def _hyphenItemLetters(node):
        if node.node_type == nd.NODE_TYPE.CHAR:
            return [node]
        if node.node_type == nd.NODE_TYPE.LIGATURE:
            source = getattr(node, "source", None) or []
            if all(c.node_type == nd.NODE_TYPE.CHAR for c in source):
                return list(source)
        return None

    def _hyphenSkipToStart(self, nodes, start, language, uchyph, lccode):
        """
        Search from a potential boundary to the first possible starting item.
        it returns a tuple of the starting index, the hyphen char, and the current language
        if hyphen is None, the scan is not successful
        """
        j = start-1
        n = len(nodes) - 1
        found = False
        while j < n:
            j += 1
            trial = nodes[j]
            trial_type = trial.node_type
            if isinstance(trial, Language):
                language = trial.language
                continue
            if trial_type == nd.NODE_TYPE.WHATSIT:
                continue
            if trial_type == nd.NODE_TYPE.KERN and trial.automatic:
                continue
            if trial_type == nd.NODE_TYPE.CHAR:
                char = ord(trial.char)
                lc = lccode[char]
                if lc == 0:
                    continue
                if lc != char and not uchyph:
                    break
                found = True
                break
            if trial_type == nd.NODE_TYPE.LIGATURE:
                char = ord(trial.source[0].char)
                lc = lccode[char]
                if lc == 0:
                    continue
                if lc != char and not uchyph:
                    break
                found = True
                break
            break
        # If a suitable starting letter is found, let it be in font f. Hyphenation is abandoned unless the 
        # \hyphenchar of f is between 0 and 255, and unless a character of that number exists in the font. 
        hyphen = trial.font.hyphenChar() if found else None
        return j, hyphen, language

    def _hyphenCollectWord(self, nodes, start, lccode):
        """
        Collect one trial word from the expanded node list.

        Return `(tail, hyphen, text, parts)` or `None` if no admissible word
        starts here.
        """
        start_node = nodes[start]
        font = start_node.font

        parts = []
        text = []
        k = start
        n = len(nodes)
        while k < n:
            part = nodes[k]
            if part.node_type == nd.NODE_TYPE.KERN and part.automatic:
                k += 1
                continue
            letters = self._hyphenItemLetters(part)
            if letters is None:
                break
            ok = True
            for letter in letters:
                if letter.font != font or lccode[ord(letter.char)] == 0:
                    ok = False
                    break
            if not ok:
                break
            parts.append((k, part, letters))
            text.extend(letter.char for letter in letters)
            k += 1
        return k, "".join(text), parts

    @staticmethod
    def _hyphenTailAllowed(node):
        return (
            node.node_type == nd.NODE_TYPE.GLUE
            or node.node_type == nd.NODE_TYPE.PENALTY
            or (node.node_type == nd.NODE_TYPE.KERN and not node.automatic)
            or node.node_type == nd.NODE_TYPE.WHATSIT
            or node.node_type in (nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS, nd.NODE_TYPE.ADJUST)
        )

    def _hyphenWordValid(self, nodes, tail, text):
        """
        Check whether a collected trial word is valid for hyphenation.
        """
        context = self.typeset_context
        if len(text) < max(1, context.lefthyphenmin) + max(1, context.righthyphenmin):
            return False
        n = len(nodes)
        while tail < n:
            tail_node = nodes[tail]
            if tail_node.node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                tail += 1
                continue
            if tail_node.node_type == nd.NODE_TYPE.KERN and tail_node.automatic:
                tail += 1
                continue
            break
        return tail < n and self._hyphenTailAllowed(nodes[tail])

    def _iterHyphenWords(self, parser, nodes):
        """
        Yield trial words from the expanded horizontal list according to
        TeXBook Appendix H.

        Each yielded item is `(language, hyphen, text, parts)`, where `parts`
        is a list of `(node_index, node, letters)` for the admissible items
        forming the word.
        """
        in_math = False
        current_language = parser.state.parameters["language"]
        lccode = parser.state.lccode
        i = 0
        n = len(nodes)

        while i < n:
            node = nodes[i]
            node_type = node.node_type
            if isinstance(node, Language):
                current_language = node.language
                i += 1
                continue
            if node_type == nd.NODE_TYPE.MATH:
                in_math = node.on
                i += 1
                continue
            if in_math:
                i += 1
                continue
            if i != 0:
                i += 1
                if node_type != nd.NODE_TYPE.GLUE:
                    continue

            j, hyphen, current_language = self._hyphenSkipToStart(
                nodes,
                i,
                current_language,
                self.typeset_context.uchyph,
                lccode,
            )
            if hyphen is None:
                i = j if j > i else i + 1
                continue

            tail, text, parts = self._hyphenCollectWord(nodes, j, lccode)
            if not self._hyphenWordValid(nodes, tail, text):
                i = tail
                continue
            yield current_language, hyphen, text, parts
            i = tail

    def _hyphenBreakCandidates(self, parser, nodes):
        context = self.typeset_context
        lambda_ = max(1, context.lefthyphenmin)
        rho = max(1, context.righthyphenmin)
        extras = []

        for language, hyphen, text, parts in self._iterHyphenWords(parser, nodes):
            parser.hyphenator.setLanguage(language)
            hyphen_points = parser.hyphenator.hyphenate(text)
            if hyphen_points:
                total = 0
                for index, part_node, letters in parts:
                    next_total = total + len(letters)
                    for point in hyphen_points:
                        if not (total < point <= next_total):
                            continue
                        left = point
                        right = len(text) - point
                        if left < lambda_ or right < rho:
                            continue
                        split = point - total
                        candidate = _BreakCandidate(index if split < len(letters) else index + 1)
                        candidate.penalty = context.hyphenpenalty
                        candidate.hyphenated = True
                        if split == len(letters):
                            candidate.disc = self._virtualDisc([hyphen], [])
                            candidate.disc_skip = 0
                        else:
                            candidate.disc = self._virtualDisc(
                                self._typesetFragment(parser, letters[:split]) + [hyphen],
                                self._typesetFragment(parser, letters[split:]),
                            )
                            candidate.disc_skip = 1
                        extras.append(candidate)
                    total = next_total
        return extras


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
    __slots__ = (
        "break_index",
        "penalty",
        "hyphenated",
        "disc",
        "disc_skip",
        "at_penalty",
        "line_start_index",
        "next",
    )

    def __init__(self, break_index):
        self.break_index = break_index
        self.penalty = 0
        self.hyphenated = False
        self.disc = None
        self.disc_skip = 0
        self.at_penalty = False
        self.line_start_index = break_index
        self.next = None

    @property
    def forced(self):
        return self.penalty <= -10000


class _BreakCandidateChain:
    """
    Linked list of legal break candidates over one immutable expanded node list.

    The chain keeps insertions O(1) for future hyphenation work while preserving
    a minimal list-like API for the current DP breaker and tests.
    """
    __slots__ = ("head", "tail", "length", "_cache")

    def __init__(self):
        self.head = None
        self.tail = None
        self.length = 0
        self._cache = None

    def _touch(self):
        self._cache = None

    def append(self, candidate):
        candidate.next = None
        if self.tail is None:
            self.head = candidate
        else:
            self.tail.next = candidate
        self.tail = candidate
        self.length += 1
        self._touch()
        return candidate

    def insert_after(self, prev, candidate):
        if prev is None:
            candidate.next = self.head
            if self.head is None:
                self.tail = candidate
            self.head = candidate
        else:
            candidate.next = prev.next
            prev.next = candidate
            if candidate.next is None:
                self.tail = candidate
        self.length += 1
        self._touch()
        return candidate

    def _as_list(self):
        if self._cache is None:
            self._cache = list(self)
        return self._cache

    def __iter__(self):
        current = self.head
        while current is not None:
            yield current
            current = current.next

    def __len__(self):
        return self.length

    def __getitem__(self, index):
        return self._as_list()[index]

    def clone(self):
        out = _BreakCandidateChain()
        for candidate in self:
            copy = _BreakCandidate(candidate.break_index)
            copy.penalty = candidate.penalty
            copy.hyphenated = candidate.hyphenated
            copy.disc = candidate.disc
            copy.disc_skip = candidate.disc_skip
            copy.at_penalty = candidate.at_penalty
            copy.line_start_index = candidate.line_start_index
            out.append(copy)
        return out


class _Line:
    """
    One feasible line from `begin` to `end`.

    Demerits are computed in `__init__` using TeX-style terms:
    `(linepenalty + badness)^2`, penalty contribution, fitness adjacency
    demerits, and hyphenation demerits.
    """
    __slots__ = (
        "begin",
        "end",
        "prev",
        "line_no",
        "hyphenated",
        "badness",
        "ratio",
        "fitness",
        "demerits",
        "feasible",
    )

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


class _BreakCandidateScan(list):
    """
    Expanded node list plus its legal break candidates.

    Nodes can be appended incrementally during expansion, so ligature formation
    and breakpoint discovery happen in the same pass.
    """
    def __init__(self, context, nodes=None):
        super().__init__()
        self.context = context
        self.candidates = _BreakCandidateChain()
        self.candidates.append(_BreakCandidate(0))
        self.in_math = False
        self.end = 0
        self._finished = False
        if nodes is not None:
            self.extend(nodes)
            self.finish()

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
    def _isDiscardable(node):
        return node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY)

    @classmethod
    def prepareCandidateStart(cls, nodes, end, candidate):
        if candidate.break_index >= end:
            candidate.line_start_index = end
            return

        if candidate.disc is not None:
            candidate.line_start_index = candidate.break_index + candidate.disc_skip
            return

        start = candidate.break_index + 1 if candidate.at_penalty else candidate.break_index
        while start < end and cls._isDiscardable(nodes[start]):
            start += 1
        candidate.line_start_index = start

    @property
    def nodes(self):
        return self

    def append(self, node):
        if self._finished:
            raise ValueError("cannot append after finishing break scan")
        i = len(self)
        super().append(node)
        node_type = node.node_type

        # line breaks can happen at these points (TeXBook, page 98)
        # a) at glue, provided that this glue is immediately preceded by a non-discardable
        # item, and that it is not part of a math formula (i.e., not between math-on and
        # math-oﬀ). A break “at glue” occurs at the left edge of the glue space.
        # b) at a kern, provided that this kern is immediately followed by glue, and that it
        # is not part of a math formula.
        # c) at a math-oﬀ that is immediately followed by glue.
        # d) at a penalty (which might have been inserted automatically in a formula).
        # e) at a discretionary break.
        if node_type == nd.NODE_TYPE.MATH:
            self.in_math = node.on
            return

        if node_type == nd.NODE_TYPE.GLUE:
            if self.in_math or i == 0:
                return
            prev = self[i - 1]
            prev_type = prev.node_type
            if prev_type == nd.NODE_TYPE.KERN:
                self.candidates.append(_BreakCandidate(i))
            elif prev_type == nd.NODE_TYPE.MATH and not prev.on:
                self.candidates.append(_BreakCandidate(i))
            elif not self._isDiscardable(prev):
                self.candidates.append(_BreakCandidate(i))
            return

        if node_type == nd.NODE_TYPE.PENALTY and node.penalty < 10000:
            candidate = self.candidates.append(_BreakCandidate(i))
            candidate.penalty = node.penalty
            candidate.at_penalty = True
            return

        if node_type == nd.NODE_TYPE.DISC:
            candidate = self.candidates.append(_BreakCandidate(i))
            candidate.disc = node
            candidate.disc_skip = 1
            candidate.hyphenated = self._discHyphenated(node)
            candidate.penalty = self.context.exhyphenpenalty

    def extend(self, nodes):
        for node in nodes:
            self.append(node)

    def finish(self):
        if self._finished:
            return self
        self.end = len(self)
        if (
            self.end < 2
            or self[-2].node_type != nd.NODE_TYPE.PENALTY
            or self[-2].penalty != 10000
            or self[-1].node_type != nd.NODE_TYPE.GLUE
            or self[-1].glue != self.context.parfillskip
        ):
            raise ValueError("paragraph does not end with \\penalty10000 and \\parfillskip")
        if self.candidates.tail.break_index != self.end:
            end_candidate = _BreakCandidate(self.end)
            end_candidate.penalty = -10000
            self.candidates.append(end_candidate)
        for candidate in self.candidates:
            self.prepareCandidateStart(self.nodes, self.end, candidate)
        self._finished = True
        return self


class _LineBreaker:
    """
    One line-breaking round based on expanded nodes and direct slice
    measurement between legal breakpoints.
    """
    def __init__(self, para, nodes, breaks, tolerance, allow_overfull=False):
        self.para = para
        self.nodes = nodes
        self.context = para.typeset_context
        self.breaks = breaks
        self.start = breaks.head
        self.end = breaks.tail.break_index if breaks.tail is not None else len(nodes)
        self.last_break = breaks.tail
        self.tolerance = tolerance
        self.allow_overfull = allow_overfull
        self.actual_looseness = 0
        self._prefix_dimen = [Dimen()]
        self._prefix_stretch = [[Dimen()] for _ in range(4)]
        self._prefix_shrink = [[Dimen()] for _ in range(4)]
        for node in nodes:
            dimen, stretch, shrink = self._nodeContribution(node)
            self._prefix_dimen.append(self._prefix_dimen[-1] + dimen)
            for order in range(4):
                stretch_part = stretch.factor if stretch.order == order else Dimen()
                shrink_part = shrink.factor if shrink.order == order else Dimen()
                self._prefix_stretch[order].append(self._prefix_stretch[order][-1] + stretch_part)
                self._prefix_shrink[order].append(self._prefix_shrink[order][-1] + shrink_part)

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

    @staticmethod
    def _nodeContribution(node):
        node_type = node.node_type
        if node_type == nd.NODE_TYPE.GLUE:
            return node.glue.dimen, node.glue.stretch, node.glue.shrink
        if node_type == nd.NODE_TYPE.KERN:
            return node.kern, Stretchness(), Stretchness()
        if node_type == nd.NODE_TYPE.DISC:
            return node.replace_width, Stretchness(), Stretchness()
        if node_type == nd.NODE_TYPE.MATH:
            width = getattr(node, "kern", None)
            if width is None:
                raise ValueError("math shift node is missing kern")
            return width, Stretchness(), Stretchness()
        width = getattr(node, "width", None)
        return (width, Stretchness(), Stretchness()) if width is not None else (Dimen(), Stretchness(), Stretchness())

    @staticmethod
    def _prefixStretchness(prefix, start, end):
        for order in range(3, -1, -1):
            factor = prefix[order][end] - prefix[order][start]
            if factor != 0:
                return Stretchness(factor, order)
        return Stretchness()

    def _sliceGlue(self, start, end):
        return Glue(
            self._prefix_dimen[end] - self._prefix_dimen[start],
            self._prefixStretchness(self._prefix_stretch, start, end),
            self._prefixStretchness(self._prefix_shrink, start, end),
        )

    def _lineNatural(self, begin, end):
        natural = self._sliceGlue(begin.line_start_index, end.break_index)
        if begin.disc is not None:
            natural.dimen += begin.disc.post_width
        if end.disc is not None:
            natural.dimen += end.disc.pre_width
        return natural

    class _State:
        """
        DP state at one breakpoint.
        """
        __slots__ = ("break_pos", "line", "line_no", "fitness", "hyphenated", "demerits")

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
        if self.start is None:
            return None

        frontier = [self._State(self.start, None)]
        finals = []

        while frontier:
            next_states = {}
            for state in frontier:
                begin = state.break_pos
                end = begin.next
                while end is not None:
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
                        key = (end, line.line_no, line.fitness, line.hyphenated)
                        best = next_states.get(key)
                        if best is None or line.demerits < best.demerits:
                            next_states[key] = self._State(end, line)
                    end = end.next
            if not next_states:
                break
            frontier = list(next_states.values())
            finals.extend([state for state in frontier if state.break_pos is self.last_break])

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
