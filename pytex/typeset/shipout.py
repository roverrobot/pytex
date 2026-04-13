"""Backend-neutral shipout walker and minimal IR hooks."""

from pytex import node as nd
from pytex.dimen import Dimen, NEG_MAX_DIMEN
from pytex.typeset.dvipdfm import DVIPDFmSpecialParser


class Shipout:
    """
    Default shipout collector and backend-neutral page walker.

    The base class owns the traversal of shipped boxes and reduces them to a
    small backend IR consisting of page boundaries, positioning, font
    selection/definition, rules, characters, and specials. Concrete backends
    implement the IR methods below.
    """

    def __init__(self, parser, output=None):
        self.parser = parser
        self.output = output
        self.pages = []
        self.h = 0
        self.v = 0
        self._position_stack = []
        self._defined_fonts = set()
        self._dvipdfm = DVIPDFmSpecialParser(self)

    def shipout(self, box):
        self.open()
        self.pages.append(box)
        self.begin_page(box)
        h = int(self.parser.layout["hoffset"])
        v = int(self.parser.layout["voffset"])
        self._position_stack = []
        self.move_to(h, v)
        if box.node_type == nd.NODE_TYPE.VLIST:
            self.move_to(h, v)
            self._ship_vlist(box)
        else:
            self.move_to(h, v + box.height)
            self._ship_hlist(box)       
        self.end_page(box)

    def _glue_state(self, box):
        ratio = getattr(box, "glue_ratio", None)
        if isinstance(ratio, tuple):
            sign, num, den = ratio
            sign = int(sign)
            num = int(num)
            den = int(den)
            if sign > 0 and num > 0 and den > 0:
                return {
                    "num": num,
                    "den": den,
                    "order": box.natural.stretch.order,
                    "shrink": False,
                    "factor_sum": 0,
                    "applied": 0,
                }
            if sign < 0 and num > 0 and den > 0:
                return {
                    "num": -num,
                    "den": den,
                    "order": box.natural.shrink.order,
                    "shrink": True,
                    "factor_sum": 0,
                    "applied": 0,
                }
            return None

        spread = int(getattr(box, "spread", Dimen()))
        if spread > 0 and int(box.natural.stretch.factor) != 0:
            return {
                "num": spread,
                "den": int(box.natural.stretch.factor),
                "order": box.natural.stretch.order,
                "shrink": False,
                "factor_sum": 0,
                "applied": 0,
            }
        if spread < 0 and int(box.natural.shrink.factor) != 0:
            return {
                "num": spread,
                "den": int(box.natural.shrink.factor),
                "order": box.natural.shrink.order,
                "shrink": True,
                "factor_sum": 0,
                "applied": 0,
            }
        return None

    def _glue_amount(self, node, box, state=None):
        amount = int(node.glue.dimen)
        if state is not None:
            part = node.glue.shrink if state["shrink"] else node.glue.stretch
            if part.order == state["order"]:
                state["factor_sum"] += int(part.factor)
                target = Dimen._round_div(state["factor_sum"] * state["num"], state["den"])
                amount += target - state["applied"]
                state["applied"] = target
        else:
            ratio = box.glue_ratio
            if isinstance(ratio, tuple):
                ratio = type(box).ratioDimen(ratio)
            if ratio > 0:
                stretch = node.glue.stretch
                if stretch.order == box.natural.stretch.order:
                    amount += int(stretch.factor * ratio)
            elif ratio < 0:
                shrink = node.glue.shrink
                if shrink.order == box.natural.shrink.order:
                    amount += int(shrink.factor * ratio)
        return amount

    def _push_position(self):
        self._position_stack.append((self.h, self.v))
        if hasattr(self, "max_stack") and len(self._position_stack) > self.max_stack:
            self.max_stack = len(self._position_stack)

    def _pop_position(self):
        self.h, self.v = self._position_stack.pop()

    def _ensure_font(self, font):
        key = id(font)
        if key not in self._defined_fonts:
            self.define_font(font)
            self._defined_fonts.add(key)
        self.select_font(font)

    def _emit_whatsit(self, node):
        self.move_to(self.h, self.v)
        node.output(self.parser, self)

    def _ship_char(self, node):
        self.move_to(self.h, self.v)
        self._ensure_font(node.font)
        self.set_char(node)
        self.h += int(node.width)

    def _ship_rule(self, node, box, move):
        # Preserve the current DVI-compatible rule placement semantics. In
        # horizontal lists, the current point for a rule is lowered by its
        # depth; in vertical lists, the current point is used as-is.
        orig_h = self.h
        orig_v = self.v
        if box.node_type == nd.NODE_TYPE.HLIST:
            depth = int(box.depth) if int(node.depth) <= int(NEG_MAX_DIMEN) else int(node.depth)
            self.move_to(orig_h, orig_v + depth)
        else:
            self.move_to(orig_h, orig_v)
        self.set_rule(node, box, move)
        self.h = orig_h
        self.v = orig_v
        if box.node_type == nd.NODE_TYPE.HLIST:
            if move:
                self.h += int(node.width)
        else:
            if move:
                self.v += int(node.height)

    def _ship_box(self, box, parent):
        self._push_position()
        if parent.node_type == nd.NODE_TYPE.HLIST:
            if box.node_type == nd.NODE_TYPE.HLIST:
                self.v += int(box.shifted)
                self.move_to(self.h, self.v)
                self._ship_hlist(box)
            else:
                self.v += int(box.shifted) - int(box.height)
                self.move_to(self.h, self.v)
                self._ship_vlist(box)
            self._pop_position()
            self.h += int(box.width)
        else:
            if box.node_type == nd.NODE_TYPE.HLIST:
                self.h += int(box.shifted)
                self.v += int(box.height)
                self.move_to(self.h, self.v)
                self._ship_hlist(box)
            else:
                self.h += int(box.shifted)
                self.move_to(self.h, self.v)
                self._ship_vlist(box)
            self._pop_position()
            self.v += int(box.height + box.depth)

    def _ship_hlist(self, box):
        items = getattr(box, "list", None)
        if items is None:
            return
        glue_state = self._glue_state(box)
        for node in items:
            node_type = node.node_type
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                self._ship_char(node)
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._ship_box(node, box)
            elif node_type == nd.NODE_TYPE.RULE:
                self._ship_rule(node, box, True)
            elif node_type == nd.NODE_TYPE.GLUE:
                assert getattr(box, "glue_ratio", None) is not None, "discretionary node contains glue"
                self.h += self._glue_amount(node, box, glue_state)
            elif node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                self.h += int(node.kern)
            elif node_type == nd.NODE_TYPE.DISC:
                self._ship_hlist(node)
            elif node_type == nd.NODE_TYPE.WHATSIT:
                self._emit_whatsit(node)

    def _ship_vlist(self, box):
        items = getattr(box, "list", None)
        if items is None:
            return
        glue_state = self._glue_state(box)
        for node in items:
            node_type = node.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                self.v += self._glue_amount(node, box, glue_state)
            elif node_type == nd.NODE_TYPE.KERN:
                self.v += int(node.kern)
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._ship_box(node, box)
            elif node_type == nd.NODE_TYPE.RULE:
                self._ship_rule(node, box, False)
            elif node_type == nd.NODE_TYPE.WHATSIT:
                self._emit_whatsit(node)

    def begin_page(self, box):
        pass

    def end_page(self, box):
        pass

    def define_font(self, font):
        pass

    def select_font(self, font):
        pass

    def move_to(self, h, v):
        pass

    def set_char(self, node):
        pass

    def set_rule(self, node, box, move):
        pass

    def special(self, text):
        if not self._dvipdfm.emit(text):
            self.rawSpecial(text)

    def rawSpecial(self, text):
        pass

    def setColor(self, mode, space=None, values=None):
        pass

    def annotate(self, kind, name=None, dimensions=None, payload=None):
        pass

    def xObject(self, kind, name=None, options=None, source=None):
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
