"""
Macro expansions in PDFTeX.
"""

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
        # latex searches for /dev/null to check for system type
        if name[0] == "/":
            if name.startswith("/dev/null."):
                return
            if name == "/dev/null":
                if os.path.exists(name):
                    parser.input.unread(token.Token("0", token.CATCODE.OTHER))
                return
            raise ValueError("Absolute file name: " + name, parser.input.position())
        file = parser.resolver.openIn(name, "source")
        if file is None:
            return
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.close()
        parser.input.push(lexer.TokenListScanner(expandable.toToks(str(size))))


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
        "pdfmdfivesum": PDFMDfiveSum(),
        "mdfivesum": PDFMDfiveSum(),
        "expanded": Expanded(),
        "pdfstrcmp": PDFStrcmp(),
    },
)
