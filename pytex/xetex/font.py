"""XeTeX extended font-name parsing."""

import re

from pytex import accessor
from pytex import font as font_data
from pytex.font_backend import FontSpec
from pytex.integer import IntegerArrayItemAccessor
from pytex.module import Module
from pytex.token import Command


COLLECTION_FONT_RE = re.compile(r"^(.+\.(?:otc|ttc|dfont)):(\d+)$", re.IGNORECASE)


def _split_font_suffix(value, leading_option: bool = False):
    option_pos = value.find("/") if leading_option else value.find("/", 1)
    feature_pos = value.find(":")
    stops = [pos for pos in (option_pos, feature_pos) if pos >= 0]
    if not stops:
        return value, "", ""
    stop = min(stops)
    name = value[:stop]
    suffix = value[stop:]
    options = ""
    features = ""
    if suffix.startswith("/"):
        feature_start = suffix.find(":")
        if feature_start >= 0:
            options = suffix[:feature_start]
            features = suffix[feature_start + 1:]
        else:
            options = suffix
    else:
        features = suffix[1:]
    return name, options, features


def _split_collection_index(value):
    match = COLLECTION_FONT_RE.match(value)
    if match is None:
        return value, 0
    return match.group(1), int(match.group(2))


def parseFontName(parser, name):
    """
    Parse XeTeX's extended quoted font-name syntax.

    Bracketed names force file lookup; unbracketed names use the classic
    auto path after stripping XeTeX options/features for lookup.
    """
    if not isinstance(name, str):
        return name
    if name.startswith("file:"):
        lookup_name, font_number = _split_collection_index(name[5:])
        return FontSpec(lookup_name, lookup="file", font_number=font_number)
    if name.startswith("name:"):
        return FontSpec(name[5:], lookup="system")
    if name.startswith("["):
        end = name.find("]")
        if end >= 0:
            lookup_name, font_number = _split_collection_index(name[1:end])
            _suffix, options, features = _split_font_suffix(
                name[end + 1:],
                leading_option=True,
            )
            return FontSpec(
                lookup_name,
                lookup="file",
                font_number=font_number,
                options=options,
                features=features,
            )
    lookup_name, options, features = _split_font_suffix(name)
    if lookup_name != name:
        return FontSpec(
            lookup_name,
            lookup="auto",
            options=options,
            features=features,
        )
    return FontSpec(name, lookup="auto")


class XeTeXFontType(Command):
    r"""Read the XeTeX layout-engine type of a font."""

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        font = font_data.readFont(parser)
        value = getattr(font.backend, "xetex_font_type", 0)
        return value, accessor.VALUE_TYPE.INT

    def execute(self, parser):
        raise ValueError(
            f"{self.name} cannot be executed, it is read-only",
            parser.input.position(),
        )


mod = Module(
    "xetex.font",
    attributes={
        "parseFontName": parseFontName,
    },
    commands={
        "XeTeXfonttype": XeTeXFontType(),
    },
    parameters={
        "suppressfontnotfounderror": {
            "value": 0,
            "accessor": IntegerArrayItemAccessor,
            "domain": "parameters",
        },
    },
)
