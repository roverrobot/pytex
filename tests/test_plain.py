import pytest
from pytex import texlive

def test_plain(parser):
    plain = parser.resolver.openIn('plain', "source")
    assert plain is not None
    parser.parse(
    """
        \\def\\patterns#1{}
        \\def\\hyphenation#1{}
    """)
    parser.parse(plain)
