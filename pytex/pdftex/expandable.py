"""
Macro expansions in PDFTeX.
"""

import datetime
import hashlib
import os
from pytex import accessor
from pytex import conditional
from pytex import expandable
from pytex import token
from pytex import lexer
from pytex.module import Module


def _string_to_bytes(value: str) -> bytes:
    try:
        return value.encode("latin1")
    except UnicodeEncodeError:
        return value.encode("utf-8")


def _resolve_pdftex_file(parser, name: str):
    # latex probes /dev/null to detect host capabilities
    lower = name.lower()
    if name.startswith("/"):
        if lower.startswith("/dev/null."):
            return None
        if lower == "/dev/null":
            return name if os.path.exists(name) else None
        raise ValueError("Absolute file name: " + name, parser.input.position())
    if lower in {"nul", "nul:"}:
        return os.devnull if os.name == "nt" else None
    file = parser.resolver.openIn(name, "source")
    if file is None:
        return None
    path = getattr(file, "name", None)
    file.close()
    return path


def _open_pdftex_source(parser, name: str):
    lower = name.lower()
    if name.startswith("/"):
        if lower.startswith("/dev/null."):
            return None
        if lower == "/dev/null":
            return open(name, "rb") if os.path.exists(name) else None
        raise ValueError("Absolute file name: " + name, parser.input.position())
    if lower in {"nul", "nul:"}:
        return open(os.devnull, "rb") if os.name == "nt" else None
    return parser.resolver.openIn(name, "source")


def _read_pdftex_file_name(parser) -> str:
    toks = parser.readGeneralText(expand=True)
    return parser.toksToString(toks)


def _read_control_sequence(parser):
    t = parser.token()
    if t is None or t.entry is None or t.catcode is not None:
        raise ValueError("expecting a control sequence", parser.input.position())
    return t


def _primitive_token(name: str, definition):
    t = token.CommandToken(name)
    t.definition = definition
    return t


def _read_primitive(parser):
    t = _read_control_sequence(parser)
    return t.name, parser.builtin.get(t.name)


def _pdf_date_string(timestamp: float) -> str:
    if os.environ.get("SOURCE_DATE_EPOCH") is not None and os.environ.get("FORCE_SOURCE_DATE") is not None:
        dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    else:
        dt = datetime.datetime.fromtimestamp(timestamp).astimezone()
    s = dt.strftime("D:%Y%m%d%H%M%S")
    offset = dt.utcoffset()
    if offset is None:
        return s
    seconds = int(offset.total_seconds())
    if seconds == 0:
        return s + "Z"
    sign = "+" if seconds >= 0 else "-"
    seconds = abs(seconds)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    return f"{s}{sign}{hours:02d}'{minutes:02d}'"


class PDFMDfiveSum(token.Command):
    r"""
    \pdfmdfivesum <general text> or \pdfmdfivesum file <file name>.
    """

    def _push_hash(self, parser, data):
        digest = hashlib.md5(data).hexdigest().upper()
        parser.input.push(lexer.TokenListScanner(expandable.toToks(digest)))

    def expand(self, parser):
        if parser.readKeyword({"file"}):
            toks = parser.readGeneralText(expand=True)
            name = parser.toksToString(toks)
            file = _open_pdftex_source(parser, name)
            if file is None:
                return
            with file:
                data = file.read()
            if isinstance(data, str):
                data = _string_to_bytes(data)
            self._push_hash(parser, data)
            return
        toks = parser.readGeneralText(expand=True)
        self._push_hash(parser, _string_to_bytes(parser.toksToString(toks)))

class PDFFileSize(token.Command):
    """
    The PDF file size
    """
    def expand(self, parser):
        name = _read_pdftex_file_name(parser)
        path = _resolve_pdftex_file(parser, name)
        if path is None:
            return
        size = os.path.getsize(path)
        parser.input.push(lexer.TokenListScanner(expandable.toToks(str(size))))


class PDFFileModDate(token.Command):
    r"""
    \pdffilemoddate <file name>.
    """

    def expand(self, parser):
        name = _read_pdftex_file_name(parser)
        path = _resolve_pdftex_file(parser, name)
        if path is None:
            return
        mod = _pdf_date_string(os.path.getmtime(path))
        parser.input.push(lexer.TokenListScanner(expandable.toToks(mod)))


class PDFFileDump(token.Command):
    r"""
    \pdffiledump [offset <integer>] [length <integer>] <general text>.
    """

    def expand(self, parser):
        offset = 0
        length = 0
        if parser.readKeyword({"offset"}):
            offset = parser.readInteger()
        if parser.readKeyword({"length"}):
            length = parser.readInteger()
        if offset < 0 or length < 0:
            raise ValueError("\\pdffiledump offset and length must be nonnegative", parser.input.position())
        name = _read_pdftex_file_name(parser)
        path = _resolve_pdftex_file(parser, name)
        if path is None or length == 0:
            return
        with open(path, "rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
        if data:
            parser.input.push(lexer.TokenListScanner(expandable.toToks(data.hex().upper())))


class Expanded(token.Command):
    """
    \\expanded <general text> which expands the tokens in exactly the same way as \\message
    """
    def expand(self, parser):
        toks = parser.readGeneralText(expand=True)
        parser.input.push(lexer.TokenListScanner(toks))


class PDFStrcmp(token.Command):
    """
    \\strcmp <string1> <string2> compares two strings.
    """
    def expand(self, parser):
        l1 = parser.readGeneralText(expand=True)
        l2 = parser.readGeneralText(expand=True)
        s1 = parser.toksToString(l1)
        s2 = parser.toksToString(l2)
        if s1 == s2:
            s = "0"
        elif s1 < s2:
            s = "-1"
        else:
            s = "1"
        parser.input.push(lexer.TokenListScanner(expandable.toToks(s)))


class IfInCSName(conditional.Conditional):
    r"""
    \ifincsname is true while scanning a \csname ... \endcsname name.
    """

    def condition(self, parser):
        return 0 if getattr(parser, "incsname_depth", 0) > 0 else 1


class IfPDFPrimitive(conditional.Conditional):
    r"""
    \ifpdfprimitive <control sequence> is true if the control sequence still has
    its original primitive meaning.
    """

    def condition(self, parser):
        t = _read_control_sequence(parser)
        builtin = parser.builtin.get(t.name)
        return 0 if builtin is not None and t.definition == builtin else 1


class PDFPrimitive(token.Command):
    r"""
    \pdfprimitive <control sequence> executes or expands the primitive meaning of
    the control sequence, regardless of its current definition.
    """

    def getTarget(self, parser):
        name, builtin = _read_primitive(parser)
        if builtin is None:
            return accessor.ReadOnlyTarget(None, accessor.VALUE_TYPE.UNKNOWN)
        get_target = getattr(builtin, "getTarget", None)
        if get_target is None:
            return accessor.ReadOnlyTarget(None, accessor.VALUE_TYPE.UNKNOWN)
        return get_target(parser)

    def execute(self, parser):
        name, builtin = _read_primitive(parser)
        if builtin is None:
            return
        primitive = _primitive_token(name, builtin)
        parser.current_token = primitive
        if builtin.expand is not None:
            if parser.tracingcommands > 0:
                parser.trace(primitive, "expand")
            expanded = builtin.expand(parser)
            if expanded is not None:
                parser.input.unread(expanded)
            return
        if parser.tracingcommands > 0:
            parser.trace(primitive, "execute")
        return builtin.execute(parser)


mod = Module("pdftex.expandable",
    commands={
        "ifincsname": IfInCSName(),
        "ifpdfprimitive": IfPDFPrimitive(),
        "pdfprimitive": PDFPrimitive(),
        "pdffiledump": PDFFileDump(),
        "pdffilesize": PDFFileSize(),
        "filesize": PDFFileSize(),
        "pdffilemoddate": PDFFileModDate(),
        "pdfmdfivesum": PDFMDfiveSum(),
        "mdfivesum": PDFMDfiveSum(),
        "expanded": Expanded(),
        "pdfstrcmp": PDFStrcmp(),
        "strcmp": PDFStrcmp(),
    },
)
