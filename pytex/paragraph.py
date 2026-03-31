"""
This module implement paragraph handling (unrestricted hlist).
"""

from pytex import hmode
from pytex import node as nd
from pytex import box as bx
from pytex import vmode
from pytex import lists
from pytex.module import Module
from pytex.accessor import Accessor, VALUE_TYPE
from pytex.dimen import Dimen
from pytex.glue import Glue, Stretchness
from pytex.hmode import HorizontalCommand


class Language(nd.WhatsIt):
    """
    a language node
    """
    def __init__(self, language):
        self.language = language


class LineBreaker:
    """
    Parser-owned paragraph line breaker.
    """
    def __init__(self, parser):
        self.parser = parser

    def _packLine(self, para, hlist, line):
        parser = self.parser
        packed = []
        indent, measure = para.lineShape(parser, line.line_no)
        if indent != 0:
            packed.append(nd.Glue(Glue(indent), "\\parindent"))
        leftskip = parser.layout["leftskip"]
        if leftskip != Glue():
            packed.append(nd.Glue(leftskip, "\\leftskip"))
        if line.begin.disc is not None:
            packed.extend(line.begin.disc.post)
        for node in hlist[line.begin.line_start_index:line.end.break_index]:
            if node.node_type == nd.NODE_TYPE.DISC:
                packed.append(para._lineDisc(parser, node, broken=False))
            else:
                packed.append(node)
        if line.end.break_index < len(hlist):
            end_node = hlist[line.end.break_index]
            if line.end.at_penalty:
                packed.append(end_node)
        if line.end.disc is not None:
            packed.append(para._lineDisc(parser, line.end.disc, broken=True))
        packed.append(nd.Glue(parser.layout["rightskip"], "\\rightskip"))
        hbox = bx.HBox(parser, measure, None)
        hbox.list[:] = packed
        hbox = hbox.typeset(parser)
        migratory = [n for n in hbox.list if n.node_type in para._migratory_node_types]
        if migratory:
            hbox.list[:] = [n for n in hbox.list if n.node_type not in para._migratory_node_types]
        hbox.migratory = migratory
        hbox.source = para
        if line.line_no != 1:
            hbox.interline_penalty = self.interlinePenalty(para, line)
        return hbox

    def interlinePenalty(self, para, line):
        parser = self.parser
        penalty = parser.layout["interlinepenalty"]
        if line.line_no == 2:
            penalty += parser.layout["clubpenalty"]
        if line.line_no == para.line_count:
            penalty += parser.layout["widowpenalty"]
        if line.prev is not None and line.prev.hyphenated:
            penalty += parser.layout["brokenpenalty"]
        return penalty

    def updateDisplayState(self, para):
        parser = self.parser
        line_count = len(para._line_boxes or [])
        parser.globals["prevgraf"] = line_count
        displayindent, displaywidth = para.lineShape(parser, line_count + 1)
        para.line_count = line_count
        parser.volatile["displayindent"] = displayindent
        parser.volatile["displaywidth"] = displaywidth
        hbox = para._line_boxes[-1] if para._line_boxes else None
        if hbox is None:
            predisplaysize = Dimen(-16383.99999)
        else:
            predisplaysize = hbox.rightmost() + 2 * parser.parameters["currentfont"].param[5]
        parser.volatile["predisplaysize"] = predisplaysize

    def typeset(self, para, vlist):
        if len(para.list) == 0:
            para.line_count = 0
            para._line_boxes = []
            return
        hlist = para.list
        breaks = self.scanBreaks(para, hlist)
        hlist, lines = self.lineBreak(para, hlist, breaks)
        para.line_count = len(lines)
        para._line_boxes = []
        for line in lines:
            node = self._packLine(para, hlist, line)
            para._line_boxes.append(node)
            vlist.append(node)
            for extra in getattr(node, "migratory", ()):
                vlist.append(extra)

    def scanBreaks(self, para, nodes):
        return _scanBreaks(self.parser, nodes)

    def lineBreak(self, para, hlist, breaks=None):
        parser = self.parser
        pre_tolerance = parser.layout["pretolerance"]
        if pre_tolerance < 0:
            pre_tolerance = parser.layout["tolerance"]
        if breaks is None:
            breaks = self.scanBreaks(para, hlist)
        breaker = _LineBreaker(para, parser, hlist, breaks, pre_tolerance)
        lines = breaker.run()
        working_hlist = hlist
        working_breaks = breaks
        if lines is None or (
            parser.volatile["looseness"] != 0
            and breaker.actual_looseness != parser.volatile["looseness"]
        ):
            hyphenated = self.hyphenate(para, hlist, breaks)
            if hyphenated:
                working_hlist, working_breaks = hyphenated
                hyphen_breaker = _LineBreaker(
                    para,
                    parser,
                    working_hlist,
                    working_breaks,
                    parser.layout["tolerance"],
                )
                hyphen_lines = hyphen_breaker.run()
                if hyphen_lines is not None:
                    breaker = hyphen_breaker
                    lines = hyphen_lines
        if lines is None:
            breaker = _LineBreaker(
                para,
                parser,
                working_hlist,
                working_breaks,
                max(parser.layout["tolerance"], 10000),
                allow_overfull=True,
            )
            lines = breaker.run()
        para.actual_looseness = breaker.actual_looseness
        return working_hlist, lines

    def hyphenate(self, para, hlist=None, scan=None):
        if hlist is None or scan is None:
            hlist = para.list
            scan = self.scanBreaks(para, hlist)
        extras = self._hyphenBreakCandidates(hlist)
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
            _prepareCandidateStart(hlist, len(hlist), candidate)
        return hlist, hyphenated

    def typesetFragment(self, chars):
        packed = []
        helper = hmode.HList(self.parser, packed, raw=[])
        helper.open()
        helper._ligature_state["in_word"] = True
        helper._ligature_state["lig_base"] = None
        try:
            for node in chars:
                helper.append(node)
        finally:
            helper.close()
        return packed

    @staticmethod
    def virtualDisc(pre, post):
        return hmode.Disc(pre, post, [])

    @staticmethod
    def _hyphenItemLetters(node):
        if node.node_type == nd.NODE_TYPE.CHAR:
            return [node]
        if node.node_type == nd.NODE_TYPE.LIGATURE:
            source = getattr(node, "source", None) or []
            if all(c.node_type == nd.NODE_TYPE.CHAR for c in source):
                return list(source)
        return None

    def _hyphenSkipToStart(self, nodes, start, language):
        parser = self.parser
        j = start - 1
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
                lc = parser.lccode[char]
                if lc == 0:
                    continue
                if lc != char and not (parser.layout["uchyph"] > 0):
                    break
                found = True
                break
            if trial_type == nd.NODE_TYPE.LIGATURE:
                char = ord(trial.source[0].char)
                lc = parser.lccode[char]
                if lc == 0:
                    continue
                if lc != char and not (parser.layout["uchyph"] > 0):
                    break
                found = True
                break
            break
        hyphen = trial.font.hyphenChar() if found else None
        return j, hyphen, language

    def _hyphenCollectWord(self, nodes, start):
        font = nodes[start].font
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
                if letter.font != font or self.parser.lccode[ord(letter.char)] == 0:
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
        parser = self.parser
        if len(text) < max(1, parser.layout["lefthyphenmin"]) + max(1, parser.layout["righthyphenmin"]):
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

    def _iterHyphenWords(self, nodes):
        in_math = False
        current_language = self.parser.parameters["language"]
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
            j, hyphen, current_language = self._hyphenSkipToStart(nodes, i, current_language)
            if hyphen is None:
                i = j if j > i else i + 1
                continue
            tail, text, parts = self._hyphenCollectWord(nodes, j)
            if not self._hyphenWordValid(nodes, tail, text):
                i = tail
                continue
            yield current_language, hyphen, text, parts
            i = tail

    def _hyphenBreakCandidates(self, nodes):
        parser = self.parser
        lambda_ = max(1, parser.layout["lefthyphenmin"])
        rho = max(1, parser.layout["righthyphenmin"])
        extras = []
        for language, hyphen, text, parts in self._iterHyphenWords(nodes):
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
                        candidate.penalty = parser.layout["hyphenpenalty"]
                        candidate.hyphenated = True
                        if split == len(letters):
                            candidate.disc = self.virtualDisc([hyphen], [])
                            candidate.disc_skip = 0
                        else:
                            candidate.disc = self.virtualDisc(
                                self.typesetFragment(letters[:split]) + [hyphen],
                                self.typesetFragment(letters[split:]),
                            )
                            candidate.disc_skip = 1
                        extras.append(candidate)
                    total = next_total
        return extras


class Paragraph(nd.Node):
    """
    A paragraph.
    @param parser: the parser
    @param indent: whether to indent the paragraph
    """
    def __init__(self, parser, indent: bool):
        self.list = []
        self.raw = []
        self.indent = indent
        # \prevgraf for this paragraph (set by display-math machinery when needed).
        self.prevgraf = 0
        self.line_count = 0
        self.actual_looseness = 0
        # Display math opens a synthetic following paragraph that may remain empty.
        if indent:
            indent_box = bx.IndentBox(parser)
            self.raw.append(indent_box)
            self.list.append(indent_box)
        self._line_boxes = None

    # not a proper node
    node_type = None
    # This node will be typeset when appending to a vlist.
    typeset_to_vlist = True
    _migratory_node_types = (nd.NODE_TYPE.MARK, nd.NODE_TYPE.INS, nd.NODE_TYPE.ADJUST)

    def saveInfo(self):
        return {
                "indent": self.indent,
            }, {
                "disc": getattr(self, "disc", None),
                "list": self.list,
            }

    init_needs_parser = True
    
    def __repr__(self):
        return f'HList([{", ".join(repr(node) for node in self.list)}])'

    def meaning(self, parser):
        return "HList"

    @staticmethod
    def _lineShape(parshape, hsize, hangindent, hangafter, line_no):
        if parshape:
            i = line_no - 1
            if i >= len(parshape):
                i = len(parshape) - 1
            return parshape[i]
        hang = hangindent
        if hang == 0:
            return Dimen(), hsize
        after = hangafter
        if after >= 0:
            hanging = line_no > after
        else:
            hanging = line_no <= -after
        if not hanging:
            return Dimen(), hsize
        if hang > 0:
            return hang, hsize - abs(hang)
        return Dimen(), hsize - abs(hang)

    def lineShape(self, parser, line_no):
        return self._lineShape(
            parser.volatile["parshape"],
            parser.layout["hsize"],
            parser.volatile["hangindent"],
            parser.volatile["hangafter"],
            line_no,
        )

    def _interlinePenalty(self, parser, line):
        return parser.line_breaker.interlinePenalty(self, line)

    def updateDisplayState(self, parser):
        parser.line_breaker.updateDisplayState(self)

    def typeset(self, parser, vlist):
        parser.line_breaker.typeset(self, vlist)

    @staticmethod
    def _lineDisc(parser, disc, broken):
        rendered = disc.pre if broken else disc.replace
        out = hmode.Disc(disc.pre, disc.post, list(rendered))
        out.source = getattr(disc, "source", None)
        return out

    def _scanBreaks(self, parser, nodes):
        """
        Scan an already-typeset horizontal node list for legal breakpoints.
        """
        return parser.line_breaker.scanBreaks(self, nodes)

    def lineBreak(self, parser, hlist, breaks=None):
        return parser.line_breaker.lineBreak(self, hlist, breaks)

    def _hyphenate(self, parser, hlist=None, scan=None):
        return parser.line_breaker.hyphenate(self, hlist, scan)


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
        parser = breaker.parser
        layout = parser.layout
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
        line_glue = layout["leftskip"] + layout["rightskip"]
        _, measure = breaker.para.lineShape(parser, self.line_no)
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

        line = layout["linepenalty"] + badness
        demerits = line * line
        penalty = end.penalty
        if penalty >= 0:
            demerits += penalty * penalty
        elif penalty > -10000:
            demerits -= penalty * penalty

        if self.prev is not None:
            if abs(self.fitness - self.prev.fitness) > 1:
                demerits += layout["adjdemerits"]
            if self.prev.hyphenated and self.hyphenated:
                demerits += layout["doublehyphendemerits"]
            if last_line and self.prev.hyphenated:
                demerits += layout["finalhyphendemerits"]
            demerits += self.prev.demerits

        self.demerits = demerits


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


def _isDiscardable(node):
    return node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY)


def _prepareCandidateStart(nodes, end, candidate):
    if candidate.break_index >= end:
        candidate.line_start_index = end
        return

    if candidate.disc is not None:
        candidate.line_start_index = candidate.break_index + candidate.disc_skip
        return

    start = candidate.break_index + 1 if candidate.at_penalty else candidate.break_index
    while start < end and _isDiscardable(nodes[start]):
        start += 1
    candidate.line_start_index = start


def _scanBreaks(parser, nodes):
    items = nodes.list if hasattr(nodes, "list") else nodes
    candidates = _BreakCandidateChain()
    candidates.append(_BreakCandidate(0))
    in_math = False

    for i, node in enumerate(items):
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
            in_math = node.on
            continue

        if node_type == nd.NODE_TYPE.GLUE:
            if in_math or i == 0:
                continue
            prev = items[i - 1]
            prev_type = prev.node_type
            if prev_type == nd.NODE_TYPE.KERN:
                candidates.append(_BreakCandidate(i))
            elif prev_type == nd.NODE_TYPE.MATH and not prev.on:
                candidates.append(_BreakCandidate(i))
            elif not _isDiscardable(prev):
                candidates.append(_BreakCandidate(i))
            continue

        if node_type == nd.NODE_TYPE.PENALTY and node.penalty < 10000:
            candidate = candidates.append(_BreakCandidate(i))
            candidate.penalty = node.penalty
            candidate.at_penalty = True
            continue

        if node_type == nd.NODE_TYPE.DISC:
            candidate = candidates.append(_BreakCandidate(i))
            candidate.disc = node
            candidate.disc_skip = 1
            candidate.hyphenated = _discHyphenated(node)
            candidate.penalty = parser.layout["exhyphenpenalty"]

    end = len(items)
    if candidates.tail.break_index != end:
        end_candidate = _BreakCandidate(end)
        end_candidate.penalty = -10000
        candidates.append(end_candidate)
    for candidate in candidates:
        _prepareCandidateStart(items, end, candidate)
    return candidates


class _LineBreaker:
    """
    One line-breaking round based on expanded nodes and direct slice
    measurement between legal breakpoints.
    """
    def __init__(self, para, parser, nodes, breaks, tolerance, allow_overfull=False):
        self.para = para
        self.parser = parser
        self.nodes = nodes
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
                        if best is None or line.demerits <= best.demerits:
                            next_states[key] = self._State(end, line)
                    end = end.next
            if not next_states:
                break
            frontier = list(next_states.values())
            finals.extend([state for state in frontier if state.break_pos is self.last_break])

        if not finals:
            return None

        baseline, best = self._selectFinal(finals, self.parser.volatile["looseness"])
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


class PrevGraf(Accessor):
    target_type = VALUE_TYPE.INT
    value_type = VALUE_TYPE.INT

    def getTarget(self, parser):
        value = parser.globals["prevgraf"]
        if value is None:
            # when this is accessed here, we are in building a list. So we use
            # parser.paragraph_before_last_display_math if available by forcing the
            # last built paragraph to realize prevgraf.
            for vlist in reversed(parser.lists):
                if vlist.type == lists.LISTTYPE.VERTICAL:
                    break
            else:
                vlist = None
            if vlist is not None:
                for para in reversed(vlist):
                    if isinstance(para, Paragraph):
                        para.typeset(parser, [])
                        break
            if parser.globals["prevgraf"] is None:
                parser.globals["prevgraf"] = 0
        return super().getTarget(parser)


def init(parser):
    parser.line_breaker = LineBreaker(parser)


mod = Module("paragraph",
    init=init,
    commands={
        "setlanguage": SetLanguage(),
    },
    parameters={
        "prevgraf": {"value": 0, "accessor": PrevGraf, "domain": "globals"},
    },
)
