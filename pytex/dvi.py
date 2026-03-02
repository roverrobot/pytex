"""
Minimal DVI shipout support.
"""


import os

from pytex import node as nd
from pytex.dimen import Dimen
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
        font_id = self.font_ids.get(id(font))
        if font_id is None:
            font_id = self._define_font(font)
        if self.current_font == font_id:
            return
        if font_id < 64:
            self._write_byte(171 + font_id)
        else:
            self._write_byte(235)  # fnt1
            self._write_unsigned(font_id, 1)
        self.current_font = font_id

    def _push(self):
        self._write_byte(141)
        self.stack.append((self.h, self.v))
        if len(self.stack) > self.max_stack:
            self.max_stack = len(self.stack)

    def _pop(self):
        self._write_byte(142)
        self.h, self.v = self.stack.pop()

    def _move_to(self, h, v):
        dh = int(h) - self.h
        dv = int(v) - self.v
        if dh:
            self._write_byte(146)  # right4
            self._write_signed(dh, 4)
            self.h += dh
        if dv:
            self._write_byte(160)  # down4
            self._write_signed(dv, 4)
            self.v += dv

    @staticmethod
    def _glue_amount(node, box):
        amount = node.glue.dimen
        ratio = box.glue_ratio
        if ratio > 0:
            stretch = node.glue.stretch
            if stretch.order == box.natural.stretch.order:
                amount += stretch.factor * ratio
        elif ratio < 0:
            shrink = node.glue.shrink
            if shrink.order == box.natural.shrink.order:
                amount += shrink.factor * ratio
        return amount

    def _set_char(self, char):
        code = ord(char)
        if code < 128:
            self._write_byte(code)
        else:
            self._write_byte(128)  # set1
            self._write_unsigned(code, 1)

    def _put_rule(self, height, width, move):
        self._write_byte(132 if move else 137)
        self._write_signed(int(height), 4)
        self._write_signed(int(width), 4)
        if move:
            self.h += int(width)

    def special(self, text):
        data = text.encode("utf-8")
        if len(data) < 256:
            self._write_byte(239)  # xxx1
            self._write_unsigned(len(data), 1)
        else:
            self._write_byte(242)  # xxx4
            self._write_unsigned(len(data), 4)
        self._write(data)

    def _ship_box(self, box, x, y):
        if getattr(box, "list", None) is None:
            return
        if box.node_type == nd.NODE_TYPE.HLIST:
            self._ship_hlist(box, x, y)
        else:
            self._ship_vlist(box, x, y)

    def _ship_hlist(self, box, x, y):
        cur = x
        for node in box.list:
            node_type = node.node_type
            if node_type in (nd.NODE_TYPE.CHAR, nd.NODE_TYPE.LIGATURE):
                self._set_font(node.font)
                self._move_to(cur, y)
                self._set_char(node.char)
                cur += node.width
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._push()
                child_y = y + node.shifted
                self._move_to(cur, child_y)
                self._ship_box(node, cur, child_y)
                self._pop()
                cur += node.width
            elif node_type == nd.NODE_TYPE.RULE:
                self._move_to(cur, y - node.height)
                self._put_rule(node.height + node.depth, node.width, True)
                cur += node.width
            elif node_type == nd.NODE_TYPE.GLUE:
                cur += self._glue_amount(node, box)
            elif node_type == nd.NODE_TYPE.KERN:
                cur += node.kern
            elif node_type == nd.NODE_TYPE.DISC:
                self._push()
                self._move_to(cur, y)
                self._ship_hlist(_DiscList(node.list, box), cur, y)
                self._pop()
                cur += node.replace_width
            elif node_type == nd.NODE_TYPE.MATH:
                cur += node.kern
            elif node_type == nd.NODE_TYPE.WHATSIT:
                node.output(self.parser, self)

    def _ship_vlist(self, box, x, y):
        cur = y - box.height
        for node in box.list:
            node_type = node.node_type
            if node_type == nd.NODE_TYPE.GLUE:
                cur += self._glue_amount(node, box)
            elif node_type == nd.NODE_TYPE.KERN:
                cur += node.kern
            elif node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                self._push()
                child_x = x + node.shifted
                child_y = cur + node.height
                self._move_to(child_x, child_y)
                self._ship_box(node, child_x, child_y)
                self._pop()
                cur += node.height + node.depth
            elif node_type == nd.NODE_TYPE.RULE:
                self._move_to(x, cur)
                self._put_rule(node.height + node.depth, node.width, False)
                cur += node.height + node.depth
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
        y = self.parser.state.layout["voffset"] + box.height
        self._move_to(x, y)
        self._ship_vlist(box, x, y)
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


class _DiscList:
    """
    Lightweight adapter so a rendered discretionary branch can reuse _ship_hlist.
    """

    def __init__(self, nodes, parent):
        self.list = nodes
        self.glue_ratio = Dimen()
        self.natural = parent.natural

    node_type = nd.NODE_TYPE.HLIST


mod = Module(
    "dvi",
    attributes={
        "shipout_class": DVIShipout,
    }
)
