"""Parser-owned math translation pipeline."""

from pytex import box
from pytex import mmode as mm
from pytex import node as nd
from pytex.dimen import Dimen
from pytex.hmode import Ligature
from pytex.mmode import InlineMathNode, DisplayMathNode
from pytex.ligature import run_ligature_program

Style = mm.Style
MATH_STYLE = mm.MATH_STYLE
ATOM_TYPE = mm.ATOM_TYPE
StyleNode = mm.StyleNode
ChoiceNode = mm.ChoiceNode
Atom = mm.Atom
MathSymbol = mm.MathSymbol
MathListHolder = mm.MathListHolder
Subformula = mm.Subformula
Delim = mm.Delim
Accent = mm.Accent
mathfont = mm.mathfont
mathsigma = mm.mathsigma
mathlayout = mm.mathlayout
_drop_redundant_wrapper = mm._drop_redundant_wrapper
AtomState = mm.AtomState


def _coerceAtomState(parser, context):
    if isinstance(context, AtomState):
        return context
    return AtomState(
        parser,
        prev_atom_type=getattr(context, "prev_atom_type", None),
        atom_type=getattr(context, "atom_type", None),
        text_symbol=getattr(context, "text_symbol", False),
    )


class _AtomWrapper:
    """
    Temporary math-atom record produced in MList.typesetNodes pass 1.

    It proxies to the wrapped atom for regular atom fields/methods while
    carrying pass-1 metadata:
    - node_type: normalized effective atom class for spacing
    - style: style snapshot for pass-2 emission
    - text_symbol: Rule 14 text-symbol mark for Rule 17 italic handling
    """
    def __init__(self, atom, node_type, style, text_symbol=False):
        self._atom = atom
        self.node_type = node_type
        self.style = style
        self.text_symbol = text_symbol

    @property
    def atom(self):
        return self._atom

    def __getattr__(self, name):
        return getattr(self._atom, name)


class MathTypesetter:
    """
    Parser-owned math translation pipeline.
    """
    def __init__(self, parser):
        self.parser = parser

    def _extendExpanded(self, source, collected, expanded):
        if not expanded:
            collected.append(source)
            return
        for n in expanded:
            if n is source:
                continue
            if getattr(n, "source", None) is None:
                n.source = source
        collected.extend(expanded)

    def _pass1Collect(self, holder, context, style):
        parser = self.parser
        if not isinstance(style, Style):
            style = Style(style)
        pass_through = {
            nd.NODE_TYPE.RULE,
            nd.NODE_TYPE.DISC,
            nd.NODE_TYPE.PENALTY,
            nd.NODE_TYPE.WHATSIT,
            nd.NODE_TYPE.ADJUST,
            nd.NODE_TYPE.MARK,
            nd.NODE_TYPE.INS,
        }
        collected = []
        current = iter(holder.list)
        stack = []
        while current is not None:
            node = next(current, None)
            if node is None:
                if not stack:
                    break
                current, style = stack.pop()
                continue
            if node.node_type in pass_through:
                collected.append(node)
                continue
            if node.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
                if getattr(node, "nonscript", False):
                    if style.style <= MATH_STYLE.S:
                        nxt = next(current, None)
                        while nxt is None and stack:
                            current, style = stack.pop()
                            nxt = next(current, None)
                        if nxt is None:
                            break
                        if nxt.node_type in (nd.NODE_TYPE.GLUE, nd.NODE_TYPE.KERN):
                            continue
                        node = nxt
                    else:
                        continue
                elif getattr(node, "mu", False):
                    expanded = []
                    node.typeset(parser, expanded, context, style)
                    for n in expanded:
                        if n is node:
                            continue
                        if getattr(n, "source", None) is None:
                            n.source = node
                    collected.extend(expanded)
                    continue
                else:
                    collected.append(node)
                    continue
            if isinstance(node, StyleNode):
                style = node.style
                continue
            if isinstance(node, ChoiceNode):
                branch = node.branch(style)
                if branch is not None:
                    stack.append((current, style))
                    current = iter(branch)
                continue
            if isinstance(node, Atom):
                s = Style(style.style, style.cramped)
                collected.append(_AtomWrapper(node, node.atom_type, s))
                continue
            if isinstance(node, (MathListHolder, Subformula)):
                expanded = []
                self.typesetHolder(node, expanded, context, style)
                self._extendExpanded(node, collected, expanded)
                continue
            typeset = getattr(node, "typeset", None)
            if typeset is None:
                collected.append(node)
                continue
            expanded = []
            typeset(parser, expanded, context, style)
            self._extendExpanded(node, collected, expanded)
        return collected

    def _pass1AdjustAtoms(self, context, collected):
        parser = self.parser
        prev_types_for_rule5 = (ATOM_TYPE.BIN, ATOM_TYPE.OP, ATOM_TYPE.REL, ATOM_TYPE.OPEN, ATOM_TYPE.PUNCT)
        rule6_types = (ATOM_TYPE.REL, ATOM_TYPE.CLOSE, ATOM_TYPE.PUNCT)

        def previous_atom(index):
            j = index - 1
            while j >= 0:
                item = collected[j]
                if isinstance(item, _AtomWrapper):
                    return item
                j -= 1
            return None

        i = 0
        prev = None
        while i < len(collected):
            cur = collected[i]
            if not isinstance(cur, _AtomWrapper):
                i += 1
                continue
            if cur.node_type in (ATOM_TYPE.VCENT, ATOM_TYPE.OVER, ATOM_TYPE.UNDER, ATOM_TYPE.ACC, ATOM_TYPE.RAD):
                cur.node_type = ATOM_TYPE.ORD
            try_rule14 = False
            if cur.node_type == ATOM_TYPE.BIN:
                if prev is None or prev.node_type in prev_types_for_rule5:
                    cur.node_type = ATOM_TYPE.ORD
                    try_rule14 = True
            else:
                if cur.node_type in rule6_types and prev is not None and prev.node_type == ATOM_TYPE.BIN:
                    prev.node_type = ATOM_TYPE.ORD
                try_rule14 = cur.node_type == ATOM_TYPE.ORD
            if try_rule14 and i < len(collected) - 1:
                nxt = collected[i + 1]
                if isinstance(nxt, _AtomWrapper) and cur.node_type == ATOM_TYPE.ORD and nxt.node_type in (
                    ATOM_TYPE.ORD,
                    ATOM_TYPE.OP,
                    ATOM_TYPE.BIN,
                    ATOM_TYPE.REL,
                    ATOM_TYPE.OPEN,
                    ATOM_TYPE.CLOSE,
                    ATOM_TYPE.PUNCT,
                ):
                    if getattr(cur, "sub", None) is None and getattr(cur, "sup", None) is None:
                        n1 = getattr(cur, "nucleus", None)
                        n2 = getattr(nxt, "nucleus", None)
                        if isinstance(n1, MathSymbol) and isinstance(n2, MathSymbol) and n1.fam == n2.fam:
                            cur.text_symbol = True
                            font = mathfont(parser, cur.style, n1.fam)
                            c1 = font[n1.char]
                            c2 = font[n2.char]
                            working = run_ligature_program(
                                [c1, c2],
                                make_ligature=lambda insert_char, replaced, step, base, after: Ligature(insert_char, replaced),
                                make_kern=lambda step, base, after: nd.Kern(step.kern * base.font.at, automatic=True),
                                source_nodes=lambda n: list(n.source) if isinstance(n, Ligature) else [n],
                            )
                            if len(working) == 1 and isinstance(working[0], Ligature):
                                lig = Atom(ATOM_TYPE.ORD)
                                lig.nucleus = MathSymbol(
                                    (ATOM_TYPE.ORD.value << 12) | (n1.fam << 8) | ord(working[0].char),
                                    -1,
                                )
                                lig.source = [cur.atom, nxt.atom]
                                collected[i:i + 2] = [
                                    _AtomWrapper(
                                        lig,
                                        ATOM_TYPE.ORD,
                                        Style(cur.style.style, cur.style.cramped),
                                        text_symbol=True,
                                    )
                                ]
                                i = max(i - 1, 0)
                                prev = previous_atom(i)
                                continue
                            if len(working) == 3 and isinstance(working[1], nd.Kern):
                                k = nd.Kern(working[1].kern, automatic=True)
                                k.source = [cur.atom, nxt.atom]
                                collected.insert(i + 1, k)
                                prev = cur
                                i += 2
                                continue
            prev = cur
            i += 1
        if prev is not None and prev.node_type == ATOM_TYPE.BIN:
            prev.node_type = ATOM_TYPE.ORD

    def emitMathSymbol(self, symbol, packed, context, style, include_italic=True):
        font = mathfont(self.parser, style, symbol.fam)
        node = font[symbol.char]
        packed.append(node)
        if include_italic and int(node.italic) != 0:
            packed.append(nd.Kern(node.italic, automatic=True))
        return packed

    def _delimiterFontSearchOrder(self, style, family):
        level = style.style if isinstance(style, Style) else style
        fonts = []
        seen = set()

        def add(f):
            if f is None:
                return
            key = id(f)
            if key in seen:
                return
            seen.add(key)
            fonts.append(f)

        if family < 0 or family >= 16:
            return fonts
        parser = self.parser
        if level >= MATH_STYLE.SS:
            add(parser.scriptscriptfont[family])
        if level >= MATH_STYLE.S:
            add(parser.scriptfont[family])
        add(parser.textfont[family])
        return fonts

    def _lookupDelimiterChar(self, font, code):
        if font is None:
            return None, None
        try:
            char = chr(code)
        except ValueError:
            return None, None
        info = font.glyphInfo(char)
        if info is None:
            return None, None
        return info, font[char]

    def _scanDelimiterSymbol(self, symbol, style, minimum, best):
        if Delim._symbolIsNull(symbol):
            return None, best
        code0 = ord(symbol.char)
        for font in self._delimiterFontSearchOrder(style, symbol.fam):
            code = code0
            visited = set()
            while code not in visited:
                visited.add(code)
                info, node = self._lookupDelimiterChar(font, code)
                if info is None:
                    break
                total = node.height + node.depth
                if best is None or total > best["total"]:
                    best = {
                        "node": node,
                        "info": info,
                        "font": font,
                        "total": total,
                        "extensible": info.assembly is not None,
                    }
                if total >= minimum or info.assembly is not None:
                    return {
                        "node": node,
                        "info": info,
                        "font": font,
                        "total": total,
                        "extensible": info.assembly is not None,
                    }, best
                if info.next_larger is None:
                    break
                code = ord(info.next_larger)
        return None, best

    def _delimiterBoxWithItalic(self, node):
        b = box.HBox(self.parser, None, 0)
        b.list.append(node)
        italic = getattr(node, "italic", None)
        if italic is not None and int(italic) != 0:
            b.list.append(nd.Kern(italic, automatic=True))
        return b.typeset(self.parser)

    def _buildExtensibleDelimiter(self, chosen, minimum):
        info = chosen["info"]
        ext = info.assembly
        if ext is None:
            return self._delimiterBoxWithItalic(chosen["node"])

        def piece(code):
            if code == 0:
                return None
            _, n = self._lookupDelimiterChar(chosen["font"], code)
            b = box.HBox(self.parser, None, 0)
            b.list.append(n)
            return b.typeset(self.parser)

        top = piece(ext.top)
        mid = piece(ext.middle)
        bot = piece(ext.bottom)
        rep = piece(ext.repeat)
        if rep is None:
            return self._delimiterBoxWithItalic(chosen["node"])

        def total(n):
            return n.height + n.depth if n is not None else Dimen()

        top_total = total(top)
        mid_total = total(mid)
        bot_total = total(bot)
        rep_total = total(rep)
        if int(rep_total) <= 0:
            return self._delimiterBoxWithItalic(chosen["node"])

        base = top_total + mid_total + bot_total
        need = minimum - base
        if mid is not None:
            unit = 2 * rep_total
            repeat = 0 if need <= 0 else max(0, (int(need) + int(unit) - 1) // int(unit))
        else:
            unit = rep_total
            repeat = 0 if need <= 0 else max(0, (int(need) + int(unit) - 1) // int(unit))
        repeat = max(repeat, 1)

        parts = []
        if top is not None:
            parts.append(top)
        if mid is not None:
            for _ in range(repeat):
                parts.append(rep)
            parts.append(mid)
            for _ in range(repeat):
                parts.append(rep)
        else:
            for _ in range(repeat):
                parts.append(rep)
        if bot is not None:
            parts.append(bot)
        if not parts:
            parts.append(rep)

        v = box.VTop(self.parser, None, 0)
        v.list.extend(parts)
        v.expanded = list(parts)
        v = v.typeset(self.parser)
        v.width = rep.width
        return v

    def typesetDelimiter(self, delim, total, context, style, axis=None):
        if axis is None:
            axis = Dimen(mathsigma(self.parser, style)[21])
        if delim._isNull():
            b = box.HBox(self.parser, mathlayout(self.parser, "nulldelimiterspace"), None)
            b = b.typeset(self.parser)
            b.shifted = (b.height - b.depth) / 2 - axis
            return b
        minimum = Dimen(total)
        best = None
        chosen, best = self._scanDelimiterSymbol(delim.small, style, minimum, best)
        if chosen is None:
            chosen, best = self._scanDelimiterSymbol(delim.large, style, minimum, best)
        if chosen is None:
            chosen = best
        if chosen is None:
            b = box.HBox(self.parser, mathlayout(self.parser, "nulldelimiterspace"), None)
            return b.typeset(self.parser)
        if chosen["extensible"]:
            out = self._buildExtensibleDelimiter(chosen, minimum)
        else:
            out = self._delimiterBoxWithItalic(chosen["node"])
        out.shifted = (out.height - out.depth) / 2 - axis
        return out

    def typesetAccentNucleus(self, accent, packed, context, style):
        accent._attach_scripts = True
        base_symbol = accent._rule12SingleBaseSymbol(accent.nucleus)
        x = accent._typesetField(self.parser, accent.nucleus, context, Style(style.style, cramped=True))
        u = x.width
        y_char, accent_font = accent._rule12AccentNode(self.parser, context, style, u)
        if y_char is None:
            return super(Accent, accent).typesetNucleus(self.parser, packed, context, style)
        s = accent._rule12Skew(self.parser, base_symbol, context, style) if base_symbol is not None else Dimen()
        delta = x.height
        xh = Dimen(accent_font.param[4])
        if delta > xh:
            delta = xh
        if base_symbol is not None:
            old_h = x.height
            base_atom = Atom(ATOM_TYPE.ORD)
            base_atom.nucleus = base_symbol
            base_atom.sub = accent.sub
            base_atom.sup = accent.sup
            x = base_atom.assemble(self.parser, context, style)
            delta += x.height - old_h
            accent._attach_scripts = False
        y = box.HBox(self.parser, None, 0)
        y.list.append(y_char)
        if int(y_char.italic) != 0:
            y.list.append(nd.Kern(y_char.italic, automatic=True))
        y = y.typeset(self.parser)
        y.shifted = s + (u - y.width) / 2
        z = box.VBox(self.parser, None, 0)
        z.list[:] = [y, nd.Kern(-delta), x]
        z = z.typeset(self.parser)
        if z.height < x.height:
            k = x.height - z.height
            z.list.insert(0, nd.Kern(k))
            z.natural.dimen += k
        z.width = x.width
        packed.append(z)
        return Dimen()

    def _rule21Penalty(self, paragraph_math, current_item, next_item):
        if not paragraph_math or next_item is None or not isinstance(current_item, _AtomWrapper):
            return None
        atom_type = current_item.node_type
        if atom_type not in (ATOM_TYPE.BIN, ATOM_TYPE.REL):
            return None
        if isinstance(next_item, nd.Penalty):
            return None
        if atom_type == ATOM_TYPE.REL and isinstance(next_item, _AtomWrapper) and next_item.node_type == ATOM_TYPE.REL:
            return None
        layout = self.parser.layout
        penalty = layout["binoppenalty"] if atom_type == ATOM_TYPE.BIN else layout["relpenalty"]
        if penalty >= 10000:
            return None
        p = nd.Penalty(penalty)
        p.source = current_item.atom
        return p

    def _pass2Emit(self, holder, packed, context, collected):
        if packed is None:
            packed = []
        previous = {}
        for name in ("prev_atom_type", "atom_type", "text_symbol"):
            if hasattr(context, name):
                previous[name] = (True, getattr(context, name))
            else:
                previous[name] = (False, None)
        prev_atom_type = None
        items = iter(collected)
        item = next(items, None)
        try:
            while item is not None:
                nxt = next(items, None)
                if isinstance(item, _AtomWrapper):
                    context.prev_atom_type = prev_atom_type
                    context.atom_type = item.node_type
                    context.text_symbol = item.text_symbol
                    self.typesetAtom(
                        item.atom,
                        packed,
                        context,
                        item.style,
                        atom_type=item.node_type,
                        text_symbol=item.text_symbol,
                    )
                    prev_atom_type = context.prev_atom_type
                else:
                    packed.append(item)
                p = self._rule21Penalty(holder.paragraph_math, item, nxt)
                if p is not None:
                    packed.append(p)
                item = nxt
        finally:
            for name, (had_attr, value) in previous.items():
                if had_attr:
                    setattr(context, name, value)
                elif hasattr(context, name):
                    delattr(context, name)
        return packed

    def typesetNodes(self, holder, packed, context, style):
        collected = self._pass1Collect(holder, context, style)
        self._pass1AdjustAtoms(context, collected)
        atom_state = _coerceAtomState(self.parser, context)
        return self._pass2Emit(holder, packed, atom_state, collected)

    def typesetAtom(self, atom, packed, context=None, style=None, atom_type=None, text_symbol=None):
        if packed is None:
            packed = []
        if context is None:
            packed.append(atom)
            return packed
        if atom_type is None:
            atom_type = getattr(context, "atom_type", atom.atom_type)
        if text_symbol is not None:
            context.text_symbol = text_symbol
        context.atom_type = atom_type
        boundary_info = atom._boundaryInfo()
        if boundary_info is not None:
            atom.typsetSpace(self.parser, packed, context, style, atom_type)
            left_delim, right_delim, body_items = boundary_info
            packed.append(atom._typesetBoundaryInner(self.parser, context, style, left_delim, right_delim, body_items))
            context.prev_atom_type = atom_type
            return packed
        b = atom.assemble(self.parser, context, style)
        sigma = mathsigma(self.parser, style)
        axis = Dimen(sigma[21])
        total = b.height + b.depth
        if atom.left is not None and atom.right is not None:
            delta_up = b.height - axis
            delta_down = b.depth + axis
            delta = delta_up if delta_up >= delta_down else delta_down
            f = mathlayout(self.parser, "delimiterfactor")
            l = mathlayout(self.parser, "delimitershortfall")
            rule19 = Dimen(integer=(int(delta) // 500) * f)
            short = 2 * delta - l
            total = rule19 if rule19 >= short else short
        if atom.left:
            left = atom.left.typeset(self.parser, total, context, style, axis)
            atom.typsetSpace(self.parser, packed, context, style, ATOM_TYPE.OPEN)
            packed.append(left)
            context.prev_atom_type = ATOM_TYPE.OPEN
            atom.typsetSpace(self.parser, packed, context, style, atom_type)
        else:
            atom.typsetSpace(self.parser, packed, context, style, atom_type)
        if atom.left is not None or atom.right is not None:
            if getattr(b, "source", None) is None:
                b.source = atom
            packed.append(b)
        else:
            for n in b.list:
                packed.append(n)
        context.prev_atom_type = atom_type
        if atom.right:
            right = atom.right.typeset(self.parser, total, context, style, axis)
            atom.typsetSpace(self.parser, packed, context, style, ATOM_TYPE.CLOSE)
            packed.append(right)
            context.prev_atom_type = ATOM_TYPE.CLOSE
        return packed

    def typesetField(self, field, packed, context, style):
        if field is None:
            return packed
        if isinstance(field, (MathListHolder, Subformula)):
            self.typesetHolder(field, packed, context, style)
            return packed
        typeset = getattr(field, "typeset", None)
        if typeset is None:
            packed.append(field)
            return packed
        typeset(self.parser, packed, context, style)
        return packed

    def typesetHolder(self, holder, packed, context, style):
        hbox = box.HBox(self.parser, None, None)
        self.typesetNodes(holder, hbox.list, context, style)
        packed.append(_drop_redundant_wrapper(hbox.typeset(self.parser), allow_char=True))

    def typesetSubformula(self, holder, packed, context, style):
        self.typesetHolder(holder, packed, context, style)

    def pretypesetInlineMath(self, holder):
        if holder._typeset_cache is not None:
            return
        cache = []
        math_shift = nd.MathShift(True)
        math_shift.source = holder
        math_shift.kern = Dimen(self.parser.layout["mathsurround"])
        cache.append(math_shift)
        self.typesetNodes(holder, cache, holder, Style(MATH_STYLE.T))
        math_shift = nd.MathShift(False)
        math_shift.kern = Dimen(self.parser.layout["mathsurround"])
        cache.append(math_shift)
        for node in cache:
            if getattr(node, "source", None) is None:
                node.source = holder
        holder._typeset_cache = cache

    def typesetInlineMath(self, holder, packed):
        self.pretypesetInlineMath(holder)
        packed.extend(holder._typeset_cache)

    def appendToHList(self, node, packed):
        if not isinstance(node, InlineMathNode):
            return False
        start = len(packed)
        self.typesetInlineMath(node, packed)
        for concrete in packed[start:]:
            if getattr(concrete, "source", None) is None:
                concrete.source = node
        return True

    def typesetDisplayMath(self, holder, packed):
        parser = self.parser
        cache = []
        volatile = parser.volatile
        displaywidth = volatile["displaywidth"]
        displayindent = volatile["displayindent"]
        predisplaysize = volatile["predisplaysize"]
        if holder.eqno is not None:
            eqno, left = holder.eqno
            a = box.HBox(parser, None, 0)
            self.typesetNodes(eqno, a.list, holder, Style(MATH_STYLE.T))
            a = a.typeset(parser)
            e = a.width
            q = e + mathfont(parser, Style(MATH_STYLE.T), 2).param[5]
        else:
            q = Dimen()
            e = Dimen()
            eqno = None
            left = None
        h = self.typesetNodes(holder, None, holder, Style(MATH_STYLE.D))
        b = box.HBox(parser, None, 0)
        b.list[:] = h
        b = b.typeset(parser)
        w0 = b.width
        z = displaywidth
        s = displayindent
        p = predisplaysize
        if w0 + q > z:
            if e != 0:
                b = box.HBox(parser, to=z-q, spread=None)
                b.list[:] = h
                b = b.typeset(parser)
                ratio = b.glue_ratio
                if isinstance(ratio, tuple):
                    sign, num, den = ratio
                    over_shrink_ratio = int(sign) < 0 and int(num) > int(den)
                else:
                    over_shrink_ratio = ratio < -1
                not_enough_shrink = (
                    b.spread < 0
                    and (
                        int(b.natural.shrink.factor) == 0
                        or over_shrink_ratio
                    )
                )
                if not_enough_shrink:
                    e = Dimen()
            if e == 0:
                b = box.HBox(parser, to=min(w0, z), spread=None)
                b.list[:] = h
                b = b.typeset(parser)
        w = b.width
        d = (z - w) / 2
        if e > 0 and d < 2 * e:
            begins_with_glue = len(h) > 0 and h[0].node_type == nd.NODE_TYPE.GLUE
            d = Dimen() if begins_with_glue else (z - w - e) / 2
        cache.append(nd.Penalty(parser.layout["predisplaypenalty"]))
        if d + s <= p or left is True:
            ga = nd.Glue(parser.layout["abovedisplayskip"], "\\abovedisplayskip")
            gb = nd.Glue(parser.layout["belowdisplayskip"], "\\belowdisplayskip")
        else:
            ga = nd.Glue(parser.layout["abovedisplayshortskip"], "\\abovedisplayshortskip")
            gb = nd.Glue(parser.layout["belowdisplayshortskip"], "\\belowdisplayshortskip")
        if e == 0 and left is True:
            a.shifted = Dimen(s)
            cache.append(a)
            cache.append(nd.Penalty(10000))
        else:
            cache.append(ga)
        if e != 0:
            line = box.HBox(parser, None, None)
            k = nd.Kern(z - w - e - d)
            if left:
                line.list.append(a)
                line.list.append(k)
                line.list.append(b)
                d = 0
            else:
                line.list.append(b)
                line.list.append(k)
                line.list.append(a)
            b = line.typeset(parser)
        b.shifted = Dimen(s + d)
        b.display = True
        cache.append(b)
        if e == 0 and left is False:
            cache.append(nd.Penalty(10000))
            a.shifted = Dimen(s + z) - a.width
            a.interline_glue = nd.Glue(None, None)
            cache.append(a)
            cache.append(nd.Penalty(parser.layout["postdisplaypenalty"]))
        else:
            cache.append(nd.Penalty(parser.layout["postdisplaypenalty"]))
            cache.append(gb)
        for n in cache:
            n.source = holder
        packed.extend(cache)

    def appendToVList(self, node, packed):
        if not isinstance(node, DisplayMathNode):
            return False
        self.typesetDisplayMath(node, packed)
        return True


