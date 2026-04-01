"""Minimal DVI backend support."""


import os

from pytex.dimen import Dimen, NEG_MAX_DIMEN
from pytex.module import Module
from pytex.typeset.dvipdfm import serialize_annotate, serialize_setColor, serialize_xObject
from pytex.typeset.shipout import Shipout


class DVIBackend(Shipout):
    """
    Minimal DVI backend that implements the shipout IR and writes a .dvi file.
    """

    NUM = 25400000
    DEN = 473628672
    ID = 2

    def __init__(self, parser, output=None):
        super().__init__(parser, output)
        self.mag = parser.parameters["mag"]
        self.font_ids = {}
        self.fonts = []
        self.current_font = None
        self.dvi_h = 0
        self.dvi_v = 0
        self.last_bop = -1
        self.page_count = 0
        self.max_height = 0
        self.max_width = 0
        self.max_stack = 0
        self.file = None

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
            output = self.output
        if output is None:
            output = self.parser.jobname
            if output is None:
                output = "texput"
        if hasattr(output, "write"):
            self.file = output
            self._write_pre()
            return
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
            a += 1  # to include the /
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

    def _write_font_def(self, font_id, font):
        backend = font.backend
        if backend.dvi_name is None:
            raise ValueError(
                f"DVI shipout does not support backend {backend.kind} font {backend.name} without a DVI font name"
            )
        self._write_byte(243)  # fnt_def1
        self._write_unsigned(font_id, 1)
        self._write_unsigned(backend.checksum, 4)
        self._write_dimen(font.at)
        self._write_dimen(Dimen(backend.design_size))
        self._write_path(backend.dvi_name)

    def begin_page(self, box):
        if self.file is None:
            self.open()
        bop = self.file.tell()
        self._write_byte(139)
        for i in range(10):
            self._write_signed(self.parser.count[i], 4)
        self._write_signed(self.last_bop, 4)
        self.last_bop = bop
        self.page_count += 1
        height = box.height + box.depth
        if height > self.max_height:
            self.max_height = int(height)
        if box.width > self.max_width:
            self.max_width = int(box.width)
        self.current_font = None
        self.dvi_h = 0
        self.dvi_v = 0

    def end_page(self, box):
        self._write_byte(140)

    def define_font(self, font):
        font_id = len(self.fonts)
        self.font_ids[id(font)] = font_id
        self.fonts.append(font)
        self._write_font_def(font_id, font)

    def select_font(self, font):
        if self.current_font == font:
            return
        self.current_font = font
        font_id = self.font_ids.get(id(font))
        if font_id is None:
            self.define_font(font)
            font_id = self.font_ids[id(font)]
        if font_id < 64:
            self._write_byte(171 + font_id)
        else:
            self._write_byte(235)  # fnt1
            self._write_unsigned(font_id, 1)

    def move_to(self, h, v):
        dh = None if h is None else int(h) - self.dvi_h
        dv = None if v is None else int(v) - self.dvi_v
        if dh:
            self._write_byte(146)  # right4
            self._write_signed(dh, 4)
            self.dvi_h += dh
        if dv:
            self._write_byte(160)  # down4
            self._write_signed(dv, 4)
            self.dvi_v += dv

    def set_char(self, node):
        code = ord(node.char)
        if code < 128:
            self._write_byte(code)
        elif code < 256:  # set1
            self._write_byte(128)
            self._write_unsigned(code, 1)
        elif code < 65536:  # set2
            self._write_byte(129)
            self._write_unsigned(code, 2)
        elif code < 16777216:  # set3
            self._write_byte(130)
            self._write_unsigned(code, 3)
        else:
            self._write_byte(131)
            self._write_unsigned(code, 4)
        self.dvi_h += int(node.width)

    def set_rule(self, node, box, move):
        def running(d):
            return int(d) <= int(NEG_MAX_DIMEN)

        if box.node_type.name == "VLIST":
            w = int(box.width) if running(node.width) else int(node.width)
            h = int(node.height)
            d = int(node.depth)
            if move:
                self.dvi_v += h
        else:
            w = int(node.width)
            h = int(box.height) if running(node.height) else int(node.height)
            d = int(box.depth) if running(node.depth) else int(node.depth)
        self._write_byte(132 if move else 137)
        self._write_signed(h + d, 4)
        self._write_signed(w, 4)
        if box.node_type.name == "HLIST" and move:
            self.dvi_h += w

    def rawSpecial(self, text):
        data = text.encode()
        if len(data) < 256:
            self._write_byte(239)  # xxx1
            self._write_unsigned(len(data), 1)
        else:
            self._write_byte(242)  # xxx4
            self._write_unsigned(len(data), 4)
        self._write(data)

    def setColor(self, mode, space=None, values=None):
        self.rawSpecial(serialize_setColor(mode, space, values))

    def annotate(self, kind, name=None, dimensions=None, payload=None):
        self.rawSpecial(serialize_annotate(kind, name=name, dimensions=dimensions, payload=payload))

    def xObject(self, kind, name=None, options=None, source=None):
        self.rawSpecial(serialize_xObject(kind, name=name, options=options, source=source))

    def close(self):
        if not self.file:
            return
        post = self.file.tell()
        self._write_byte(248)
        self._write_unsigned(self.last_bop if self.last_bop >= 0 else 0, 4)
        self._write_unsigned(self.NUM, 4)
        self._write_unsigned(self.DEN, 4)
        self._write_unsigned(self.parser.parameters["mag"], 4)
        self._write_unsigned(self.max_height, 4)
        self._write_unsigned(self.max_width, 4)
        self._write_unsigned(self.max_stack, 2)
        self._write_unsigned(self.page_count, 2)
        for font_id, font in enumerate(self.fonts):
            self._write_font_def(font_id, font)
        self._write_byte(249)
        self._write_unsigned(post, 4)
        self._write_byte(self.ID)
        for _ in range(4):
            self._write_byte(223)
        while self.file.tell() % 4:
            self._write_byte(223)
        self.file.close()
        self.file = None


def init(parser):
    parser.shipout = DVIBackend(parser)


mod = Module(
    "dvi",
    init=init,
    attributes={}
)
