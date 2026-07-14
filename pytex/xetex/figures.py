"""XeTeX PDF and image file primitives."""

import os
from dataclasses import dataclass

from pytex import box as bx
from pytex import lists
from pytex import node as nd
from pytex import token
from pytex.dimen import Dimen, UNITS
from pytex.glue import Glue
from pytex.module import Module
from pytex.typeset.dvipdfm import _encode_pdf_string, serialize_xObject


PDF_FILE_FALLBACK_SIZE = Dimen(1)
PDF_FILE_PAGEBOX_KEYWORDS = {
    "media": "mediabox",
    "crop": "cropbox",
    "bleed": "bleedbox",
    "trim": "trimbox",
    "art": "artbox",
}


def _dimen_option(value):
    return f"{repr(Dimen(value))}pt"


def _number_option(value):
    value = float(value)
    if value.is_integer():
        return str(int(value))
    return repr(value)


def _special_tokens(text):
    return [
        token.Token.token(" ", token.CATCODE.SPACE)
        if ch.isspace()
        else token.Token.token(ch, token.CATCODE.OTHER)
        for ch in text
    ]


def _read_option_word(parser):
    try:
        first = parser.skipSpaces()
    except EOFError:
        raise ValueError("expecting an option value", parser.input.position())
    toks = [first]
    while True:
        try:
            t = parser.token_expand()
        except EOFError:
            break
        if t.isSpace(True):
            break
        if t.catcode is None or t.catcode in (
            token.CATCODE.BEGIN_GROUP,
            token.CATCODE.END_GROUP,
        ):
            parser.input.unread(t)
            break
        toks.append(t)
    return parser.expandedToksToString(toks)


def _bp_to_dimen(value):
    num, den = UNITS["bp"]
    scaled = round(float(value) * 1000000)
    return Dimen(
        integer=Dimen._trunc_div(
            scaled * num * Dimen.scale,
            den * 1000000,
        )
    )


def _read_pdf_page_box(parser, filename, page_number, pagebox="cropbox"):
    try:
        path = parser.resolver._sourcePath(filename)
    except ValueError:
        return None
    if not os.path.exists(path):
        return None
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        page = reader.pages[page_number - 1]
        box = getattr(page, pagebox, page.cropbox)
        llx, lly, urx, ury = tuple(map(float, box))
    except Exception:
        return None
    width = _bp_to_dimen(urx - llx)
    height = _bp_to_dimen(ury - lly)
    bbox = tuple(_number_option(v) for v in (llx, lly, urx, ury))
    return width, height, bbox


def _bbox_size(bbox):
    try:
        llx, lly, urx, ury = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return None
    return _bp_to_dimen(urx - llx), _bp_to_dimen(ury - lly)


def _bbox_ratio(bbox):
    try:
        llx, lly, urx, ury = (float(value) for value in bbox)
    except (TypeError, ValueError):
        return None
    return urx - llx, ury - lly


class XeTeXGraphicFileBox(bx.HBox):
    """
    Pre-packed box used by XeTeX graphic file primitives.

    The contained WHATSIT performs the later shipout work; this box exists only
    to reserve TeX layout space while keeping the primitive backend-neutral.
    """

    def copy(self, content=None):
        box = super().copy(content)
        if content is None and self._packed is self:
            box._packed = box
        return box


def _new_graphic_file_box(parser, width, height, depth, special):
    node = nd.Special(_special_tokens(special))
    box = XeTeXGraphicFileBox(parser, width, Dimen())
    box.width = Dimen(width)
    box.height = Dimen(height)
    box.depth = Dimen(depth)
    box.natural = Glue(width)
    box.list = [node]
    box.raw = [node]
    box._packed = box
    return box


def _read_image_size(parser, filename):
    try:
        path = parser.resolver._sourcePath(filename)
    except ValueError:
        return None
    if not os.path.exists(path):
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            width, height = image.size
    except Exception:
        return None
    bbox = tuple(_number_option(v) for v in (0, 0, width, height))
    return Dimen(width), Dimen(height), bbox


@dataclass
class XeTeXGraphicSpec:
    filename: str
    kind: str
    page_number: object = 1
    pagebox: object = None
    bbox: object = None
    scale: object = 1.0
    xscale: object = 1.0
    yscale: object = 1.0
    rotate: object = None
    width: object = None
    height: object = None
    depth: object = None


class XeTeXGraphicFile(lists.ModeDependentCommand):
    r"""Base class for XeTeX graphic file primitives."""

    kind = None
    primitive = None
    default_pagebox = None
    keyword_spec = {
        "width": ("width", "_read_dimen"),
        "height": ("height", "_read_dimen"),
        "scaled": ("scale", "_read_scaled"),
        "xscaled": ("xscale", "_read_scaled"),
        "yscaled": ("yscale", "_read_scaled"),
        "rotated": ("rotate", "_read_word"),
    }

    def _read_options(self, parser, spec):
        keywords = set(self.keyword_spec)
        while True:
            keyword = parser.readKeyword(keywords)
            if keyword is None:
                break
            attr, reader_name = self.keyword_spec[keyword]
            setattr(spec, attr, getattr(self, reader_name)(parser, keyword))

    def _read_dimen(self, parser, keyword):
        return parser.readDimen()

    def _read_integer(self, parser, keyword):
        return parser.readInteger()

    def _read_scaled(self, parser, keyword):
        return parser.readInteger() / 1000

    def _read_word(self, parser, keyword):
        return _read_option_word(parser)

    def _read_bbox(self, parser, keyword):
        return tuple(_read_option_word(parser) for _ in range(4))

    def _read_pagebox(self, parser, keyword):
        return PDF_FILE_PAGEBOX_KEYWORDS[keyword]

    def _natural_size(self, parser, spec):
        return None

    def _complete_size(self, parser, spec):
        natural = self._natural_size(parser, spec)
        if natural is not None:
            natural_width, natural_height, bbox = natural
            if spec.bbox is None:
                spec.bbox = bbox
            bbox_ratio = _bbox_ratio(spec.bbox)
            if spec.width is None and spec.height is None:
                spec.width = natural_width
                spec.height = natural_height
            elif spec.width is None and bbox_ratio is not None and bbox_ratio[1] != 0:
                spec.width = spec.height * (bbox_ratio[0] / bbox_ratio[1])
            elif spec.width is None and natural_height != 0:
                spec.width = natural_width * (
                    float(spec.height) / float(natural_height)
                )
            elif spec.height is None and bbox_ratio is not None and bbox_ratio[0] != 0:
                spec.height = spec.width * (bbox_ratio[1] / bbox_ratio[0])
            elif spec.height is None and natural_width != 0:
                spec.height = natural_height * (
                    float(spec.width) / float(natural_width)
                )

        if spec.width is None:
            spec.width = PDF_FILE_FALLBACK_SIZE
        if spec.height is None:
            spec.height = PDF_FILE_FALLBACK_SIZE
        if spec.depth is None:
            spec.depth = Dimen()

        spec.width = spec.width * (spec.scale * spec.xscale)
        spec.height = spec.height * (spec.scale * spec.yscale)
        spec.depth = spec.depth * (spec.scale * spec.yscale)

    def _special_options(self, spec):
        options = [
            ("width", _dimen_option(spec.width)),
            ("height", _dimen_option(spec.height)),
        ]
        if spec.depth is not None and int(spec.depth) != 0:
            options.append(("depth", _dimen_option(spec.depth)))
        if spec.rotate is not None:
            options.append(("rotate", spec.rotate))
        return options

    def _serialize_special(self, spec):
        return serialize_xObject(
            spec.kind,
            options=self._special_options(spec),
            source=_encode_pdf_string(spec.filename),
        )

    def readGraphicFileBox(self, parser):
        spec = XeTeXGraphicSpec(
            filename=parser.readFileName(),
            kind=self.kind,
            pagebox=self.default_pagebox,
        )
        self._read_options(parser, spec)
        self._complete_size(parser, spec)
        return _new_graphic_file_box(
            parser,
            spec.width,
            spec.height,
            spec.depth or Dimen(),
            self._serialize_special(spec),
        )

    def _append(self, parser, state):
        state.append(self.readGraphicFileBox(parser))

    def horizontal(self, parser, hlist):
        self._append(parser, hlist)

    def vertical(self, parser, vlist):
        self._append(parser, vlist)


class XeTeXPDFFile(XeTeXGraphicFile):
    r"""
    \XeTeXpdffile <filename> [page <integer>] [crop|media|bleed|trim|art] [scaled <integer>]
    [xscaled <integer>] [yscaled <integer>] [rotated <number>] [width <dimen>] [height <dimen>]
    [depth <dimen>].
    """

    kind = "epdf"
    primitive = "\\XeTeXpdffile"
    default_pagebox = "cropbox"
    keyword_spec = {
        **XeTeXGraphicFile.keyword_spec,
        "page": ("page_number", "_read_integer"),
        "depth": ("depth", "_read_dimen"),
        "bbox": ("bbox", "_read_bbox"),
        **{
            keyword: ("pagebox", "_read_pagebox")
            for keyword in PDF_FILE_PAGEBOX_KEYWORDS
        },
    }

    def _natural_size(self, parser, spec):
        if spec.page_number < 1:
            raise ValueError(
                f"{self.primitive} page number must be positive",
                parser.input.position(),
            )
        if spec.bbox is not None:
            size = _bbox_size(spec.bbox)
            if size is not None:
                return (*size, spec.bbox)
        return _read_pdf_page_box(
            parser,
            spec.filename,
            spec.page_number,
            spec.pagebox,
        )

    def _special_options(self, spec):
        options = []
        if spec.page_number != 1:
            options.append(("page", str(spec.page_number)))
        if spec.pagebox is not None:
            options.append(("pagebox", spec.pagebox))
        if spec.bbox is not None:
            options.append(("bbox", spec.bbox))
        options.extend(super()._special_options(spec))
        return options

    def readPDFFileBox(self, parser):
        return self.readGraphicFileBox(parser)


class XeTeXPicFile(XeTeXGraphicFile):
    r"""
    \XeTeXpicfile <filename> [scaled <integer>] [xscaled <integer>] [yscaled <integer>]
    [rotated <number>] [width <dimen>] [height <dimen>].
    """

    kind = "image"
    primitive = "\\XeTeXpicfile"

    def _natural_size(self, parser, spec):
        return _read_image_size(parser, spec.filename)

    def _special_options(self, spec):
        options = [
            ("width", _dimen_option(spec.width)),
            ("height", _dimen_option(spec.height)),
        ]
        if spec.rotate is not None:
            options.append(("rotate", spec.rotate))
        if spec.bbox is not None:
            options.append(("bbox", spec.bbox))
        return options


mod = Module(
    "xetex.figures",
    commands={
        "XeTeXpdffile": XeTeXPDFFile(),
        "XeTeXpicfile": XeTeXPicFile(),
    },
)
