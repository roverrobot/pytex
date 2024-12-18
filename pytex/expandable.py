"""
This module implements various expandable commands.
"""


from pytex.token import Command, CATCODE, CommandToken
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


class EndCSName(Command):
    """
    The \\endcsname command.
    """
    def execute(self, parser):
        """
        Expand the command. The endcsname command expands the next token as a control sequence name.
        @param parser: the parser
        @return: the expanded command
        """
        raise ValueError("unexpected \\endcsname")


endcsname = EndCSName()


class CSName(Command):
    """
    The \\csname command.
    """
    def expand(self, parser):
        """
        Expand the command. The csname command expands the tokens until the endcsname command.
        and returns the control sequence name.
        @param parser: the parser
        @return: the expanded command
        """
        name = "\\"
        while True:
            t = parser.token_expand()
            if t is None:
                raise ValueError("expecting \\endcsname")
            if t.is_command:
                if t == endcsname:
                    break
                else:
                    raise ValueError("expecting \\endcsname")
            name += t.name
        c = parser.lookup(name)
        if c is not None:
            return c.expand(parser)
        c = Command()
        parser.state.domains["equitable"][name] = c
        return c


mod = Module("expandable",
    commands={
        "noexpand": NoExpand(),
        "expandafter": ExpandAfter(),
        "csname": CSName(),
        "endcsname": endcsname,
    }
)