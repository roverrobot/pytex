"""
This module implements commands for interactive modes, such as \\scrollmode etc, and other
things such as dump.

In this implementation, we do not handle user interactions as classic TeX82 does. Right now, 
the parser stops whenever it encounters an error. So the commands like \\scrollmode etc is 
meaningless here. They are just no-ops now.
"""

from pytex.module import Module
from pytex import token


class Dump(token.Command):
    """
    Dump the current parser state as a format file.
    """
    def execute(self, parser):
        parser.end()
        if parser.dumper is None:
            raise ValueError("no dumper is available", parser.input.position())
        parser.dumper(parser.dump())


mod = Module("misc",
    commands={
        "dump": Dump(),
        "scrollmode": token.relax,
        "nonstopmode": token.relax,
        "batchmode": token.relax,
        "errorstopmode": token.relax,
    },
)
