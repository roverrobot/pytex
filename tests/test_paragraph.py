import pytest
from pytex import paragraph
from pytex import lists
from pytex import node as nd
from pytex import texlive


def test_discretionaary(cmr10):
    cmr10.parse("a-b")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 6
    disc = top[4]
    assert isinstance(disc, nd.Disc)


def test_language(cmr10):
    cmr10.parse("a\\language 1 b")
    top = cmr10.lists[-1]
    assert top.type == lists.LISTTYPE.HORIZONTAL
    assert len(top) == 5
    lang = top[2]
    assert isinstance(lang, paragraph.Language)
    assert lang.language == 1
