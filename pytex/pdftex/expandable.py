"""
Macro expansions in PDFTeX.
"""

import datetime
import hashlib
import os
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
    if name.startswith("/"):
        if name.startswith("/dev/null."):
            return None
        if name == "/dev/null":
            return name if os.path.exists(name) else None
        raise ValueError("Absolute file name: " + name, parser.input.position())
    info = parser.resolver.getInfo(name, None)
    for ext in info["extensions"]:
        n = info["name"] + "." + ext
        if info.get("category") == "source":
            path = parser.resolver._sourcePath(n)
        else:
            path = os.path.realpath(n)
        if os.path.exists(path):
            return path
    return None


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
            file = parser.resolver.openIn(name)
            if file is None:
                return
            data = file.read()
            file.close()
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
        name = parser.readFileName()
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
        toks = parser.readGeneralText(expand=True)
        name = parser.toksToString(toks)
        path = _resolve_pdftex_file(parser, name)
        if path is None:
            return
        mod = _pdf_date_string(os.path.getmtime(path))
        parser.input.push(lexer.TokenListScanner(expandable.toToks(mod)))


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


mod = Module("pdftex.expandable",
    commands={
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
