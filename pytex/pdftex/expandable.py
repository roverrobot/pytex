"""
Macro expansions in PDFTeX.
"""

import os
from pytex import expandable
from pytex import token
from pytex import lexer
from pytex.module import Module
import os

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
            size = 0
        else:
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
        s1 = expandable.toksToString(parser, l1, space_after_command=True)
        s2 = expandable.toksToString(parser, l2, space_after_command=True)
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
        "expanded": Expanded(),
        "pdfstrcmp": PDFStrcmp(),
    },
)
