"""Minimal dvips graphic-special parsing."""

import shlex

from pytex.graphics import GraphicSpec


def _bp_tenths(value):
    return f"{float(value) / 10:g}bp"


class DVIPSSpecialParser:
    def __init__(self, device):
        self.device = device

    def emit(self, text):
        try:
            fields = shlex.split(text, posix=True)
        except ValueError:
            return False
        if not fields or not fields[0].lower().startswith("psfile="):
            return False

        values = {}
        flags = set()
        for field in fields:
            if "=" in field:
                key, value = field.split("=", 1)
                values[key.lower()] = value
            else:
                flags.add(field.lower())
        source = values.get("psfile")
        if not source:
            return False

        options = []
        bbox_keys = ("llx", "lly", "urx", "ury")
        if all(key in values for key in bbox_keys):
            options.append(("bbox", tuple(values[key] for key in bbox_keys)))
        if "rwi" in values:
            options.append(("width", _bp_tenths(values["rwi"])))
        if "rhi" in values:
            options.append(("height", _bp_tenths(values["rhi"])))
        if "angle" in values:
            options.append(("rotate", values["angle"]))
        if "clip" in flags:
            options.append(("clip", "true"))

        self.device.graphic(
            GraphicSpec.from_dvipdfm(
                "image",
                options=options,
                source=source,
            )
        )
        return True
