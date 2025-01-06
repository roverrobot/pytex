"""
Module level fixtures
"""


import pytest
from pytex.parser import Parser


@pytest.fixture()
def parser():
    return Parser()
