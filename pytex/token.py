"""
Tokens are the product of lexers, and the input to the parser. The tokens are
classified by its catcode, which is a number between 0 and 15. A token is a command, and 
a command can either be expanded into a sequence of other tokens, or be executed by the
parser to produce a result.
"""


import enum
import typing


class CATCODE:
    """
    The category codes of the tokens. The category codes are used to classify the 
    tokens into different types. The category codes are used to determine the behavior
    of the tokens in the parser, and are defined in the TeXbook (p. 39).
    """
    ESCAPE = 0
    BEGIN_GROUP = 1
    END_GROUP = 2
    MATH_SHIFT = 3
    ALIGNMENT_TAB = 4
    END_OF_LINE = 5
    PARAMETER = 6
    SUPERSCRIPT = 7
    SUBSCRIPT = 8
    IGNORE = 9
    SPACE = 10
    LETTER = 11
    OTHER = 12
    ACTIVE = 13
    COMMENT = 14
    INVALID = 15
    # these are constants that should not be changed
    __slots__ = ()


class Command:
    """ 
    a command represents a tex functionality. It could represent a sequence of tokens
    to be expanded to, such as a macro, or a primitive command that is executed by the
    parser.
    """
    # a command is a special type of token that has no name and category code
    name = None
    catcode = None
    def execute(self, parser):
        """
        execute the command.
        @param parser: the parser
        """
        pass

    def expand(self, parser):
        """
        if the command is not expandable, the command should return itself.
        otherwise, it should put the expanded tokens in the input stack.
        Here, by default, it is not expandable.
        @param parser: the parser 
        """
        return self


class Token(Command):
    """
    A token is the smallest unit of a tex document, the key properties that a token has
    are its name and category code.
    @param name: the name of the token
    @param catcode: the category code of the token
    """
    def __init__(self, name: str, catcode: typing.Optional[int]):
        self.name = name
        self.catcode = catcode
        self.meaning = None

    def __str__(self):
        name = "\\r" if self.name == "\r" else self.name
        cat = "" if self.catcode is None else " (%d)" % self.catcode
        return name + cat

    def __repr__(self):
        return str(self)

    def execute(self, parser):
        """
        execute the token. The default behavior is to raise an error.
        @param parser: the parser
        """
        raise ValueError("invalid token: " + str(self))

    # the token generators for each category code
    generators = None

    @classmethod
    def token(cls, name: str, catcode: int):
        """ 
        generate a token according to the category code 
        @param name: the name of the token
        @param catcode: the category code of the token
        @return: the token
        """
        factory = cls.generators[catcode]
        if factory is None:
            raise ValueError("invalid category code: %d" % catcode)
        return factory(name, catcode)

class BeginGroupToken(Token):
    """ a token that represents the beginning of a group {"""
    def execute(self, parser):
        parser.beginGroup(parser.input.position())


class EndGroupToken(Token):
    """ a token that represents the end of a group {"""
    def execute(self, parser):
        parser.state.endGroup(parser.input.position())


class CommandToken(Token):
    """ 
    represent a command sequence
    the catcode is None.
    The no expand flag is used to prevent the command from being expanded in certain
    contexts.
    @param name: the name of the command
    """
    def __init__(self, name: str):
        super().__init__(name, None)
        # the no expand flag
        self.noexpand = False

    def expand(self, parser):
        """
        expand the command. If the command is not expandable, the command should return
        itself. Otherwise, it should put the expanded tokens in the input stack.
        @param parser: the parser
        @return: the expanded command
        """
        if self.noexpand:
            return self
        command = parser.lookup(self.name)
        if command is None:
            return self
        return command

    def execute(self, parser):
        """
        Execute the command. The default behavior is to raise an error.
        @param parser: the parser
        """
        raise ValueError("command not defined: ", self.name)

    def charValue(self, parser):
        """ 
        A command tokens does not represent a character. So they do not have a char value.
        @param parser: the parser
        @return: None
        """
        return None

class ParameterToken(Token):
    """
    represent the # token in a macro definition
    """
    def execute(self, parser):
        raise ValueError("unexpected #")


class SpaceToken(Token):
    """
    represent a space (including tabs and newlines)
    the name is always " "
    """
    def __init__(self):
        super().__init__(" ", CATCODE.SPACE)

    def execute(self, parser):
        parser.addSpace()


class CharToken(Token):
    """ a letter or other character """
    def execute(self, parser):
        parser.addChar(self.name)
    

class MathShiftToken(Token):
    """ a token that represents a math shift $ """
    def execute(self, parser):
        parser.mathShift(self)


class SuperscriptToken(Token):
    """ a token that represents a superscript ^ """
    def execute(self, parser):
        parser.superscript(self)


class SubscriptToken(Token):
    """ a token that represents a subscript _ """
    def execute(self, parser):
        parser.subscript(self)

# the token generators for each category code
Token.generators = [
    None,  # ESCAPE
    BeginGroupToken,  # BEGIN_GROUP = 1
    EndGroupToken,  # END_GROUP = 2
    MathShiftToken,  # MATH_SHIFT = 3
    Token,  # ALIGNMENT_TAB = 5
    None,  # END_OF_LINE = 5
    ParameterToken,  # PARAMETER = 6
    SuperscriptToken,  # SUPERSCRIPT = 7
    SubscriptToken,  # SUBSCRIPT = 8
    None,  # IGNORE = 9
    SpaceToken,  # SPACE = 10
    CharToken,  # LETTER = 11
    CharToken,  # OTHER = 12
    None,  # ACTIVE = 13
    None,  # COMMENT = 14
    None,  # INVALID = 15
]
