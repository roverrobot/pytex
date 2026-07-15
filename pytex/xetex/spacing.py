"""XeTeX interword-space shaping controls."""

from pytex.integer import IntegerArrayItemAccessor
from pytex.module import Module


mod = Module(
    "xetex.spacing",
    parameters={
        "XeTeXinterwordspaceshaping": {
            "value": 0,
            "accessor": IntegerArrayItemAccessor,
            "domain": "parameters",
        },
    },
)
