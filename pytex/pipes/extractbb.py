"""
Allowlisted `extractbb` pipe command.
"""

import math
import os

from pypdf import PdfReader

from pytex import resolver as rs
from pytex.pipes import registerPipeCommand


_BOX_GETTERS = {
    "mediabox": lambda page: page.mediabox,
    "cropbox": lambda page: page.cropbox,
    "bleedbox": lambda page: page.bleedbox,
    "trimbox": lambda page: page.trimbox,
    "artbox": lambda page: page.artbox,
}


def _parse_args(args):
    page_number = 1
    page_box = "cropbox"
    filename = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-p" and i + 1 < len(args):
            page_number = int(args[i + 1])
            i += 2
            continue
        if arg == "-B" and i + 1 < len(args):
            page_box = args[i + 1].lower()
            i += 2
            continue
        if arg == "-O" and i + 1 < len(args):
            filename = args[i + 1]
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        filename = arg
        i += 1
    return filename, page_number, page_box


def _open_pdf_stream(resolver, filename):
    in_memory = resolver.resolveInMemory(filename)
    if in_memory is not None:
        if isinstance(in_memory, rs.InMemoryBinaryFile):
            return in_memory.open()
        if isinstance(in_memory, rs.InMemoryTextFile):
            return None
    try:
        path = resolver._sourcePath(filename)
    except ValueError:
        return None
    if not os.path.exists(path):
        return None
    return open(path, "rb")


def _box_values(page, page_box):
    getter = _BOX_GETTERS.get(page_box, _BOX_GETTERS["cropbox"])
    box = getter(page)
    return tuple(map(float, box))


def _pdf_version(reader):
    header = getattr(reader, "pdf_header", "%PDF-1.0")
    if header.startswith("%PDF-"):
        return header[5:]
    return "1.0"


def extractbb(resolver, args):
    filename, page_number, page_box = _parse_args(args)
    if not filename or page_number <= 0:
        return None
    stream = _open_pdf_stream(resolver, filename)
    if stream is None:
        return None
    try:
        reader = PdfReader(stream)
        if page_number > len(reader.pages):
            return None
        page = reader.pages[page_number - 1]
        llx, lly, urx, ury = _box_values(page, page_box)
        bbox = (
            math.floor(llx),
            math.floor(lly),
            math.ceil(urx),
            math.ceil(ury),
        )
        return (
            f"%%Title: {filename}\n"
            "%%Creator: pytex extractbb\n"
            f"%%BoundingBox: {bbox[0]} {bbox[1]} {bbox[2]} {bbox[3]}\n"
            f"%%HiResBoundingBox: {llx:.6f} {lly:.6f} {urx:.6f} {ury:.6f}\n"
            f"%%PDFVersion: {_pdf_version(reader)}\n"
            f"%%Pages: {len(reader.pages)}\n"
        )
    finally:
        stream.close()


registerPipeCommand("extractbb", extractbb)
