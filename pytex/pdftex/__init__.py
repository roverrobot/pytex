"""
This module implements the pdftex extensions to TeX.

Currently, we will implement the minimum set of extensions to support latex.
"""

# pdftex depends on etex
from pytex import etex
from pytex.pdftex import expandable
from pytex.pdftex import sys
from pytex.module import Module
from pytex.integer import IntegerAccessor
from pytex import dimen

version = "140.24"

mod = Module("pdftex", 
    parameters={
        # integers
        "pdftexversion": {"value": 140, "accessor": IntegerAccessor, "domain": "parameters"},
        "pdfdraftmode": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "pdfoutput": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "pdfmajorversion": {"value": 1, "accessor": IntegerAccessor, "domain": "parameters"},
        "pdfminorversion": {"value": 4, "accessor": IntegerAccessor, "domain": "parameters"},
        "pdfcompresslevel": {"value": 9, "accessor": IntegerAccessor, "domain": "parameters"},
        "pdfobjcompresslevel": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "pdfdecimaldigits": {"value": 4, "accessor": IntegerAccessor, "domain": "parameters"},
        "pdfpkresolution": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        # dimensions
        "pdfpagewidth": {"value": dimen.Dimen(), "accessor": dimen.DimenAccessor, "domain": "parameters"},
        "pdfpageheight": {"value": dimen.Dimen(), "accessor": dimen.DimenAccessor, "domain": "parameters"},
        "pdfhorigin": {"value": dimen.Dimen(72.27), "accessor": dimen.DimenAccessor, "domain": "parameters"},
        "pdfvorigin": {"value": dimen.Dimen(72.27), "accessor": dimen.DimenAccessor, "domain": "parameters"},
    },
    commands={
        "pdftexversion": etex.FixedInteger(int(version.split(".")[0])),
        "pdftexrevision": etex.StringCommand(version.split(".")[1]),
    }
)
