"""
This module implements keyword parsing
"""


from pytex.token import CATCODE
from pytex.module import Module


def readKeyword(parser, keywords: set):
    """
    read a keyword from the input
    @param parser: the parser
    @param keywords: the valid keywords, in lower case
    @param optional: if the keyword is optional
    @return: the keyword or None
    """
    parser.skipSpaces()
    # the current location in the string
    i = 0
    read = []
    while True:
        t = parser.token_expand()
        if t is None:
            break
        read.append(t)
        if t.catcode != CATCODE.LETTER:
            break
        for k in keywords.copy():
            if t.name.lower() == k[i]:
                if len(k) == i + 1:
                    parser.skipSpaces()
                    return k
            else:
                keywords.remove(k)
        if not keywords:
            break
        i += 1
    for t in reversed(read):
        parser.input.unread(t)
    return None


mod = Module("keyword",
    attributes = {
        "readKeyword": readKeyword,
    }
)
