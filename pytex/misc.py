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


class InteractionMode(token.Command):
    """
    A no-op interaction mode command that remains distinct from \\relax.
    """
    def __init__(self, mode):
        self.mode = mode

    def execute(self, parser):
        parser.globals["interactionmode"] = self.mode


mod = Module("misc",
    commands={
        "dump": Dump(),
        "batchmode": InteractionMode(0),
        "nonstopmode": InteractionMode(1),
        "scrollmode": InteractionMode(2),
        "errorstopmode": InteractionMode(3),
    },
)
