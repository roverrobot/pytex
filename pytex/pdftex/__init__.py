"""
This module implements the pdftex extensions to TeX.

Currently, we will implement the minimum set of extensions to support latex.
"""

# pdftex depends on etex
from pytex import etex
from pytex.pdftex import expandable
from pytex.pdftex import sys
from pytex.module import Module
from pytex.integer import IntegerArrayItemAccessor
from pytex import dimen

version = "140.24"


def init(parser):
    parser.registerEngine("pdftex", {
        "pdftexversion": etex.FixedInteger(int(version.split(".")[0])),
        "pdftexrevision": etex.StringCommand(version.split(".")[1]),
    })


mod = Module("pdftex", 
    init=init,
    parameters={
        # integers
        "pdfdraftmode": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "pdfoutput": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "pdfmajorversion": {"value": 1, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "pdfminorversion": {"value": 4, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "pdfcompresslevel": {"value": 9, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "pdfobjcompresslevel": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "pdfdecimaldigits": {"value": 4, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "pdfpkresolution": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        # dimensions
        "pdfpagewidth": {"value": dimen.Dimen(), "accessor": dimen.DimenArrayItemAccessor, "domain": "parameters"},
        "pdfpageheight": {"value": dimen.Dimen(), "accessor": dimen.DimenArrayItemAccessor, "domain": "parameters"},
        "pdfhorigin": {"value": dimen.Dimen(72.27), "accessor": dimen.DimenArrayItemAccessor, "domain": "parameters"},
        "pdfvorigin": {"value": dimen.Dimen(72.27), "accessor": dimen.DimenArrayItemAccessor, "domain": "parameters"},
    },
)
