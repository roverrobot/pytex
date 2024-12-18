"""
This module implements various expandable commands.
"""


from pytex.token import Command, CATCODE
from pytex.module import Module


class NoExpand(Command):
    """
    The \\noexpand command.
    """
    def expand(self, parser):
        """
        Expand the command. The noexpand command prevents the next token from being expanded.
        @param parser: the parser
        @return: the expanded command
        """
        return parser.token()


class ExpandAfter(Command):
    """
    The \\expandafter command.
    """
    def expand(self, parser):
        """
        Expand the command. The expandafter command expands the next token after the next token.
        @param parser: the parser
        @return: the expanded command
        """
        t = parser.token()
        if t is None:
            return None
        t1 = parser.token_expand()
        if t1 is not None:
            parser.input.unread(t1)
        parser.input.unread(t)


mod = Module("expandable",
    commands={
        "noexpand": NoExpand(),
        "expandafter": ExpandAfter()
    }
)