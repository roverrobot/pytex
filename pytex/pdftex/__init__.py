"""
This module implements the pdftex extensions to TeX.

Currently, we will implement the minimum set of extensions to support latex.
"""

# pdftex depends on etex
from pytex import etex
from pytex.pdftex import expandable
from pytex.pdftex import sys
from pytex.module import Module
from pytex.integer import IntegerParameterAccessor
from pytex import dimen

version = "140.24"

mod = Module("pdftex", 
    parameters={
        # integers
        "pdftexversion": {"value": 140, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pdfdraftmode": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pdfoutput": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pdfmajorversion": {"value": 1, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pdfminorversion": {"value": 4, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pdfcompresslevel": {"value": 9, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pdfobjcompresslevel": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pdfdecimaldigits": {"value": 4, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pdfpkresolution": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        # dimensions
        "pdfpagewidth": {"value": dimen.Dimen(), "accessor": dimen.DimenParameterAccessor, "domain": "parameters"},
        "pdfpageheight": {"value": dimen.Dimen(), "accessor": dimen.DimenParameterAccessor, "domain": "parameters"},
        "pdfhorigin": {"value": dimen.Dimen(72.27), "accessor": dimen.DimenParameterAccessor, "domain": "parameters"},
        "pdfvorigin": {"value": dimen.Dimen(72.27), "accessor": dimen.DimenParameterAccessor, "domain": "parameters"},
    },
    commands={
        "pdftexversion": etex.FixedInteger(int(version.split(".")[0])),
        "pdftexrevision": etex.StringCommand(version.split(".")[1]),
    }
)
