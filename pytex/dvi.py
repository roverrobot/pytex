"""
Minimal DVI shipout support.
"""


import os

from pytex import node as nd
from pytex.dimen import Dimen, NEG_MAX_DIMEN
from pytex.module import Module
from pytex import page


class DVIShipout(page.Shipout):
    """
    Minimal DVI backend that writes shipped pages to a .dvi file.
    """

    NUM = 25400000
    DEN = 473628672
    ID = 2

    def __init__(self, parser, output=None):
        super().__init__(parser)
        self.parser = parser
        self.mag = parser.state.parameters["mag"]
        self.font_ids = {}
        self.current_font = None
        self.h = 0
        self.v = 0
        self.stack = []
        self.max_stack = 0
        self.last_bop = -1
        self.page_count = 0
        self.max_height = 0
        self.max_width = 0
        self.file = None
        self.open(output)
    
    def __enter__(self):
        if self.file is None:
            self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
    
    def open(self, output=None):
        if self.file is not None:
            return
        if output is None:
            output = self.parser.jobname
            if output is None:
                output = "texput"
        path = os.fspath(output)
        if not path.endswith(".dvi"):
            path += ".dvi"
        self.file = open(path, "wb")
        self._write_pre()

    def _write(self, data):
        self.file.write(data)

    def _write_byte(self, value):
        self._write(bytes((value & 0xFF,)))

    def _write_unsigned(self, value, size):
        self._write(int(value).to_bytes(size, "big", signed=False))

    def _write_signed(self, value, size):
        self._write(int(value).to_bytes(size, "big", signed=True))

    def _write_string(self, s):
        l = len(s)
        assert l < 256, "string too long"
        self._write_byte(l)
        self.file.write(s.encode())

    def _write_path(self, path):
        dir = os.path.dirname(path)
        a = len(dir)
        if a > 0:
            a += 1 # to include the /
        base = os.path.basename(path)
        l = len(base)
        assert a < 256 and l < 256, "path too long"
        self._write_byte(a)
        self._write_byte(l)
        self.file.write(path.encode())

    def _write_dimen(self, d):
        self._write_signed(d, 4)

    def _write_pre(self):
        comment = "PyTeX"
        self._write_byte(247)
        self._write_byte(self.ID)
        self._write_unsigned(self.NUM, 4)
        self._write_unsigned(self.DEN, 4)
        self._write_unsigned(self.mag, 4)
        self._write_string(comment)

    def _define_font(self, font):
        font_id = len(self.font_ids)
        self.font_ids[id(font)] = font_id
        self._write_byte(243)  # fnt_def1
        self._write_unsigned(font_id, 1)
        self._write_unsigned(font.tfm.header.checksum, 4)
        self._write_dimen(font.at)
        self._write_dimen(Dimen(font.tfm.header.size))
        self._write_path(font.tfm.name)
        return font_id

    def _set_font(self, font):
        if self.current_font == font:
            return
        self.current_font = font
        font_id = self.font_ids.get(id(font))
        if font_id is None:
            font_id = self._define_font(font)
        if font_id < 64:
            self._write_byte(171 + font_id)
        else:
            self._write_byte(235)  # fnt1
            self._write_unsigned(font_id, 1)

    def _push(self):
        self._write_byte(141)
        self.stack.append((self.h, self.v))
        if len(self.stack) > self.max_stack:
            self.max_stack = len(self.stack)

    def _pop(self):
        self._write_byte(142)
        self.h, self.v = self.stack.pop()

    def _move(self, dh, dv):
        if dh:
            self._write_byte(146)  # right4
            self._write_signed(dh, 4)
            self.h += dh
        if dv:
            self._write_byte(160)  # down4
            self._write_signed(dv, 4)
            self.v += dv

    def _move_to(self, h, v):
        dh = None if h is None else int(h) - self.h
        dv = None if v is None else int(v) - self.v
        self._move(dh, dv)

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

    def _set_glue(self, node, box, state=None):
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
        if box.node_type == nd.NODE_TYPE.HLIST:
            self._move(amount, None)
        else:
            self._move(None, amount)

    def _set_char(self, node):
        self._set_font(node.font)
        code = ord(node.char)
        if code < 128:
            self._write_byte(code)
        elif code < 256: # set 1
            self._write_byte(128)
            self._write_unsigned(code, 1)
        elif code < 65536: # set1
            self._write_byte(129)
            self._write_unsigned(code, 2)
        elif code < 16777216: # set 3
            self._write_byte(130)
            self._write_unsigned(code, 3)
        else:
            self._write_byte(131)
            self._write_unsigned(code, 4)
        self.h += int(node.width)

    def _ship_rule(self, node, box, move):
        def running(d):
            return int(d) <= int(NEG_MAX_DIMEN)
        if box.node_type == nd.NODE_TYPE.VLIST:
            w = int(box.width) if running(node.width) else int(node.width)
            h = int(node.height)
            d = int(node.depth)
            if move:
                self.v += h
        else:
            w = int(node.width)
            h = int(box.height) if running(node.height) else int(node.height)
            d = int(box.depth) if running(node.depth) else int(node.depth)
            if d:
                self._move(None, d)
        self._write_byte(132 if move else 137)
        self._write_signed(h + d, 4)
        self._write_signed(w, 4)
        if box.node_type == nd.NODE_TYPE.HLIST:
            if move:
                self.h += w
            if d:
                self._move(None, -d)

    def special(self, text):
        data = text.encode()
        if len(data) < 256:
            self._write_byte(239)  # xxx1
            self._write_unsigned(len(data), 1)
        else:
            self._write_byte(242)  # xxx4
            self._write_unsigned(len(data), 4)
        self._write(data)

    def _ship_box(self, box, parent):
        self._push()
        if parent.node_type == nd.NODE_TYPE.HLIST:
            if box.node_type == nd.NODE_TYPE.HLIST:
                self._move(None, int(box.shifted))
                self._ship_hlist(box)
            else:
                self._move(None, int(box.shifted) - int(box.height))
                self._ship_vlist(box)
            self._pop()
            self._move(int(box.width), None)
        else:
            if box.node_type == nd.NODE_TYPE.HLIST:
                self._move(int(box.shifted), int(box.height))
                self._ship_hlist(box)
            else:
                self._move(int(box.shifted), None)
                self._ship_vlist(box)
            self._pop()
            self._move(None, int(box.height+box.depth))

    def _ship_hlist(self, box):
        if getattr(box, "list", None) is None:
            return
        glue_state = self._glue_state(box)
        for node in box.list:
            node_type = node.node_type
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                self._set_char(node)
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._ship_box(node, box)
            elif node_type == nd.NODE_TYPE.RULE:
                self._ship_rule(node, box, True)
            elif node_type == nd.NODE_TYPE.GLUE:
                assert getattr(box, "glue_ratio", None) is not None, "discretionary node contains glue"
                self._set_glue(node, box, glue_state)
            elif node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.MATH):
                self._move(int(node.kern), None)
            elif node_type == nd.NODE_TYPE.DISC:
                self._ship_hlist(node)
            elif node_type == nd.NODE_TYPE.WHATSIT:
                node.output(self.parser, self)

    def _ship_vlist(self, box):
        glue_state = self._glue_state(box)
        for node in box.list:
            node_type = node.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                self._set_glue(node, box, glue_state)
            elif node_type == nd.NODE_TYPE.KERN:
                self._move(None, int(node.kern))
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._ship_box(node, box)
            elif node_type == nd.NODE_TYPE.RULE:
                self._ship_rule(node, box, False)
            elif node_type == nd.NODE_TYPE.WHATSIT:
                node.output(self.parser, self)

    def shipout(self, box):
        if self.file is None:
            raise ValueError("dvi file is not opened")
        if box.width is None:
            packed = []
            box.typeset(self.parser, packed)
            box = packed[-1]
        self.pages.append(box)
        bop = self.file.tell()
        self._write_byte(139)
        for i in range(10):
            self._write_signed(self.parser.state.count[i], 4)
        self._write_signed(self.last_bop, 4)
        self.last_bop = bop
        self.page_count += 1
        height = box.height + box.depth
        if height > self.max_height:
            self.max_height = int(height)
        if box.width > self.max_width:
            self.max_width = int(box.width)
        self.h = 0
        self.v = 0
        self.stack = []
        self.current_font = None
        # DVI coordinates already use TeX's page-origin convention; apply the
        # TeX offsets directly without an extra 1in translation.
        x = self.parser.state.layout["hoffset"]
        y = self.parser.state.layout["voffset"]
        self._move_to(x, y)
        self._ship_vlist(box)
        self._write_byte(140)

    def close(self):
        if not self.file:
            return
        post = self.file.tell()
        self._write_byte(248)
        self._write_unsigned(self.last_bop if self.last_bop >= 0 else 0, 4)
        self._write_unsigned(self.NUM, 4)
        self._write_unsigned(self.DEN, 4)
        self._write_unsigned(self.parser.state.parameters["mag"], 4)
        self._write_unsigned(self.max_height, 4)
        self._write_unsigned(self.max_width, 4)
        self._write_unsigned(self.max_stack, 2)
        self._write_unsigned(self.page_count, 2)
        self._write_byte(249)
        self._write_unsigned(post, 4)
        self._write_byte(self.ID)
        for _ in range(4):
            self._write_byte(223)
        while self.file.tell() % 4:
            self._write_byte(223)
        self.file.close()
        self.file = None


mod = Module(
    "dvi",
    attributes={
        "shipout_class": DVIShipout,
    }
)
