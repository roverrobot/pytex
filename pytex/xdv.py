"""Minimal XDV backend support."""


import os

from pytex.dvi import DVIBackend
from pytex.module import Module


class XDVBackend(DVIBackend):
    """
    Minimal XDV backend.

    XDV is DVI with a different preamble id, native font definition opcodes
    for OpenType/TrueType fonts, and glyph-id character setting for those
    native fonts. This backend keeps DVI movement, rules, and specials from
    ``DVIBackend``.
    """

    ID = 7
    NATIVE_FONT_DEF = 252
    XDV_GLYPHS = 253

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
        if os.path.isabs(path):
            if not path.endswith(".xdv"):
                path += ".xdv"
            self.file = open(path, "wb")
        else:
            self.file = self.parser.resolver.openOut(path, "shipout/xdv")
        self._write_pre()

    @staticmethod
    def _native_font_name(font):
        backend = font.backend
        path = getattr(backend, "path", None)
        return path if path else backend.name

    def _write_native_string(self, value):
        data = os.fsencode(value)
        if len(data) >= 256:
            raise ValueError(f"XDV native font string is too long: {value}")
        self._write_byte(len(data))
        self._write(data)

    def _write_native_font_def(self, font_id, font):
        self._write_byte(self.NATIVE_FONT_DEF)
        self._write_unsigned(font_id, 4)
        self._write_dimen(font.at)
        self._write_unsigned(0, 2)  # flags: no vertical/color/variation fields.
        self._write_native_string(self._native_font_name(font))
        self._write_native_string("")
        self._write_native_string("")
        self._write_unsigned(getattr(font.backend, "font_number", 0), 2)

    def _write_font_def(self, font_id, font):
        if getattr(font.backend, "kind", None) == "opentype":
            self._write_native_font_def(font_id, font)
            return
        super()._write_font_def(font_id, font)

    def _native_glyph_id(self, node):
        glyph_id = getattr(node.font.backend, "glyphId", lambda _char: 0)(node.char)
        return 0 if glyph_id is None else glyph_id

    def set_char(self, node):
        if getattr(node.font.backend, "kind", None) != "opentype":
            super().set_char(node)
            return
        width = int(node.width)
        self._write_byte(self.XDV_GLYPHS)
        self._write_unsigned(width, 4)
        self._write_unsigned(1, 2)
        self._write_signed(0, 4)
        self._write_signed(0, 4)
        self._write_unsigned(self._native_glyph_id(node), 2)
        self.dvi_h += width


def init(parser):
    parser.shipout = XDVBackend(parser)


mod = Module(
    "xdv",
    init=init,
    attributes={}
)
