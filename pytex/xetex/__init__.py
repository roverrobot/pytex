"""XeTeX engine extensions."""

from pytex import etex  # registers the e-TeX layer
from pytex.etex import StringCommand
from pytex.integer import FixedInteger
from pytex.module import Module
from pytex.pdftex import expandable as pdftex_expandable
from pytex.pdftex import sys as pdftex_sys

# Import the XeTeX feature modules before registering the engine wrapper.  Each
# feature module owns its commands and parser state.
from .figures import (
    PDF_FILE_FALLBACK_SIZE,
    PDF_FILE_PAGEBOX_KEYWORDS,
    XeTeXGraphicFile,
    XeTeXGraphicFileBox,
    XeTeXGraphicSpec,
    XeTeXPDFFile,
    XeTeXPicFile,
)
from .font import COLLECTION_FONT_RE, XeTeXFontType, parseFontName
from .interchar import (
    INTERCHAR_CLASS_MAX,
    XeTeXCharClassAccessor,
    XeTeXCharClassArray,
    XeTeXIntercharToksAccessor,
    XeTeXIntercharToksDict,
)
from .math import (
    UDelCode,
    UDelCodeArray,
    UMathChar,
    UMathCharDef,
    UMathCharNum,
    UMathCharNumDef,
    UMathCharValue,
    UMathCode,
    UMathCodeArray,
    UMathCodeNum,
    UMathSymbol,
)
from . import spacing as _spacing  # registers interword-space shaping state
from .unicode import (
    UCHARCAT_CATCODES,
    UNICODE_MAX,
    UChar,
    UCharCat,
)


version = "0.999995"


def init(parser):
    parser.registerEngine(
        "xetex",
        {
            "XeTeXversion": FixedInteger(int(version.split(".")[0])),
            "XeTeXrevision": StringCommand(
                "." + ".".join(version.split(".")[1:])
            ),
        },
    )


mod = Module(
    "xetex",
    init=init,
    commands={
        # XeTeX spells these pdfTeX-derived utilities without the "pdf" prefix.
        "ifprimitive": pdftex_expandable.IfPDFPrimitive(),
        "primitive": pdftex_expandable.PDFPrimitive(),
        "filedump": pdftex_expandable.PDFFileDump(),
        "filemoddate": pdftex_expandable.PDFFileModDate(),
        "filesize": pdftex_expandable.PDFFileSize(),
        "mdfivesum": pdftex_expandable.PDFMDfiveSum(),
        "strcmp": pdftex_expandable.PDFStrcmp(),
        "elapsedtime": pdftex_sys.PDFElapsedtime(),
        "resettimer": pdftex_sys.PDFResettimer(),
        "shellescape": FixedInteger(0),
    },
)
