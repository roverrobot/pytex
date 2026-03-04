"""
This module implements keyword parsing
"""


from pytex.token import CATCODE
from pytex.module import Module


def filter(keywords: set, t, i):
    """
    filter the keywords to exclude nonmatching ones
    @param keywords: the keywords
    @param t: the token
    @param i: the current index in the keyword
    @return: the keywords excluding the unmatched ones, and a bool
    indicating whether the keyword is found
    """
    for k in keywords.copy():
        if t.name.lower() == k[i]:
            if len(k) == i + 1:
                return k, True
        else:
            keywords.remove(k)
    return keywords, False

def readKeyword(parser, keywords: set):
    """
    read a keyword from the input
    @param parser: the parser
    @param keywords: the valid keywords, in lower case
    @param optional: if the keyword is optional
    @return: the keyword or None
    """
    keywords = set(keywords)
    t = parser.skipSpaces()
    if t is None:
        return None
    read = [t]
    # the current location in the string
    i = 0
    # exclude nonmatching keywords
    while True:
        keywords, found = filter(keywords, t, i)
        if found:
            return keywords
        if not keywords:
            break
        i += 1
        t = parser.token_expand()
        if t is None:
            break
        read.append(t)
    for t in reversed(read):
        parser.input.unread(t)
    return None


mod = Module("keyword",
    attributes = {
        "readKeyword": readKeyword,
    }
)
