"""Minimal dvipdfm special parsing and serialization helpers."""


from pytex.graphics import GraphicSpec


_PDF_STRING_ESCAPES = {
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "b": "\b",
    "f": "\f",
    "\\": "\\",
    "(": "(",
    ")": ")",
}


_COLOR_COMMANDS = {
    "setcolor": "set",
    "scolor": "set",
    "sc": "set",
    "begincolor": "push",
    "bcolor": "push",
    "bc": "push",
    "endcolor": "pop",
    "ecolor": "pop",
    "ec": "pop",
    "bgcolor": "background",
    "bbc": "background",
    "bgc": "background",
}

_ANNOTATE_COMMANDS = {
    "annotate": "fixed",
    "annot": "fixed",
    "ann": "fixed",
    "beginann": "begin",
    "bann": "begin",
    "bannot": "begin",
    "endann": "end",
    "eann": "end",
    "eannot": "end",
}

_XOBJECT_COMMANDS = {
    "beginxobj": "begin",
    "bxobj": "begin",
    "endxobj": "end",
    "exobj": "end",
    "usexobj": "use",
    "uxobj": "use",
    "image": "image",
    "epdf": "epdf",
}

_DIMENSION_KEYS = {"width", "height", "depth"}
_XOBJECT_OPTION_KEYS = _DIMENSION_KEYS | {"scale", "xscale", "yscale", "rotate", "bbox", "page", "pagebox", "clip"}


def _skip_spaces(text, index):
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _read_word(text, index):
    index = _skip_spaces(text, index)
    start = index
    while index < len(text) and not text[index].isspace():
        index += 1
    if start == index:
        return None, index
    return text[start:index], index


def _read_pdf_string(text, index):
    if index >= len(text) or text[index] != "(":
        raise ValueError("pdf string expected")
    start = index
    index += 1
    depth = 1
    escaped = False
    while index < len(text):
        ch = text[index]
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:index + 1], index + 1
        index += 1
    raise ValueError("unterminated pdf string")


def _read_token(text, index):
    index = _skip_spaces(text, index)
    if index >= len(text):
        raise ValueError("token expected")
    if text[index] == "(":
        return _read_pdf_string(text, index)
    start = index
    while index < len(text) and not text[index].isspace():
        index += 1
    return text[start:index], index


def _parse_color_arg(arg):
    arg = arg.strip()
    if not arg:
        raise ValueError("color argument expected")
    if arg[0] == "[" and arg[-1] == "]":
        values = tuple(arg[1:-1].split())
    else:
        values = (arg,)
    if len(values) == 1:
        return "gray", values
    if len(values) == 3:
        return "rgb", values
    if len(values) == 4:
        return "cmyk", values
    raise ValueError("unsupported color")


def _decode_pdf_string(token):
    if len(token) < 2 or token[0] != "(" or token[-1] != ")":
        return token
    out = []
    i = 1
    while i < len(token) - 1:
        ch = token[i]
        if ch == "\\" and i + 1 < len(token) - 1:
            i += 1
            esc = token[i]
            out.append(_PDF_STRING_ESCAPES.get(esc, esc))
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _encode_pdf_string(text):
    return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def _serialize_color_arg(space, values):
    if space == "gray":
        return values[0]
    return "[ " + " ".join(values) + " ]"


def serialize_setColor(mode, space=None, values=None):
    command = {
        "set": "sc",
        "push": "bc",
        "pop": "ec",
        "background": "bgc",
    }[mode]
    if mode == "pop":
        return f"pdf: {command}"
    return f"pdf: {command} {_serialize_color_arg(space, values)}"


def serialize_target(name):
    return f"pdf: dest {_encode_pdf_string(name)} [@thispage/XYZ @xpos @ypos null]"


def serialize_annotate(kind, name=None, dimensions=None, payload=None):
    if kind == "end":
        return "pdf: endann"
    if kind == "begin":
        return f"pdf: beginann {payload}"
    parts = ["pdf: ann"]
    if name is not None:
        parts.append(name)
    for key, value in dimensions or ():
        parts.extend((key, value))
    if payload is not None:
        parts.append(payload)
    return " ".join(parts)


def serialize_xObject(kind, name=None, options=None, source=None):
    if kind == "end":
        return "pdf: endxobj"
    if kind == "use":
        return f"pdf: uxobj {name}"
    command = {
        "begin": "beginxobj",
        "image": "image",
        "epdf": "epdf",
    }[kind]
    parts = [f"pdf: {command}"]
    if name is not None:
        parts.append(name)
    for key, value in options or ():
        parts.append(key)
        if isinstance(value, tuple):
            parts.extend(value)
        else:
            parts.append(value)
    if source is not None:
        parts.append(source)
    return " ".join(parts)


def serialize_graphic(spec: GraphicSpec):
    return serialize_xObject(spec.kind, name=spec.name, options=spec.options, source=_encode_pdf_string(spec.source))


class DVIPDFmSpecialParser:
    """Parse a small dvipdfm special subset and emit backend IR ops."""

    def __init__(self, device):
        self.device = device

    def emit(self, text):
        index = _skip_spaces(text, 0)
        if not text.startswith("pdf:", index):
            return False
        index = _skip_spaces(text, index + 4)
        command, index = _read_word(text, index)
        if command is None:
            return False
        command = command.lower()
        try:
            if command in _COLOR_COMMANDS:
                return self._emit_color(_COLOR_COMMANDS[command], text, index)
            if command == "dest":
                return self._emit_target(text, index)
            if command in _ANNOTATE_COMMANDS:
                return self._emit_annotate(_ANNOTATE_COMMANDS[command], text, index)
            if command in _XOBJECT_COMMANDS:
                return self._emit_xobject(_XOBJECT_COMMANDS[command], text, index)
        except ValueError:
            return False
        return False

    def _emit_color(self, mode, text, index):
        arg = text[index:].strip()
        if mode == "pop":
            if arg:
                raise ValueError("endcolor takes no argument")
            self.device.setColor(mode)
            return True
        space, values = _parse_color_arg(arg)
        self.device.setColor(mode, space, values)
        return True

    def _emit_target(self, text, index):
        name, index = _read_token(text, index)
        self.device.setTarget(_decode_pdf_string(name))
        return True

    def _emit_annotate(self, kind, text, index):
        if kind == "end":
            if text[index:].strip():
                raise ValueError("endann takes no argument")
            self.device.annotate(kind)
            return True
        name = None
        word, peek = _read_word(text, index)
        if word is not None and word.startswith("@"):
            name = word
            index = peek
        dimensions = []
        while True:
            key, peek = _read_word(text, index)
            if key not in _DIMENSION_KEYS:
                break
            value, index = _read_token(text, peek)
            dimensions.append((key, value))
        payload = text[index:].strip()
        if kind == "fixed" and not dimensions:
            raise ValueError("annotation dimensions required")
        if payload == "":
            raise ValueError("annotation payload required")
        self.device.annotate(kind, name=name, dimensions=dimensions, payload=payload)
        return True

    def _emit_xobject(self, kind, text, index):
        if kind == "end":
            if text[index:].strip():
                raise ValueError("endxobj takes no argument")
            self.device.xObject(kind)
            return True
        if kind == "use":
            name, index = _read_token(text, index)
            if text[index:].strip():
                raise ValueError("usexobj takes only a name")
            self.device.xObject(kind, name=name)
            return True
        name = None
        word, peek = _read_word(text, index)
        if word is not None and word.startswith("@"):
            name = word
            index = peek
        options = []
        while True:
            key, peek = _read_word(text, index)
            if key not in _XOBJECT_OPTION_KEYS:
                break
            index = peek
            if key == "bbox":
                bbox = []
                for _ in range(4):
                    value, index = _read_token(text, index)
                    bbox.append(value)
                options.append((key, tuple(bbox)))
            else:
                value, index = _read_token(text, index)
                options.append((key, value))
        source = None
        if kind in ("image", "epdf"):
            source = text[index:].strip()
            if source == "":
                raise ValueError("xobject source required")
        elif text[index:].strip():
            raise ValueError("unexpected trailing xobject text")
        if kind in ("image", "epdf"):
            spec = GraphicSpec.from_dvipdfm(
                kind,
                name=name,
                options=options,
                source=_decode_pdf_string(source),
            )
            self.device.graphic(spec)
            return True
        self.device.xObject(kind, name=name, options=options, source=source)
        return True
