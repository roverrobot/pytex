"""
Tokens are the product of lexers, and the input to the parser. The tokens are
classified by its catcode, which is a number between 0 and 15. A token is a command, and 
a command can either be expanded into a sequence of other tokens, or be executed by the
parser to produce a result.

However, commands are not tokens. This is demonstrated by the following example:
\\write-1{\\count0=0}. This writes the literal string "\\count0=0" to the output file, not the
primitive command that \\count points to. This means that, when expanding tokens, control
sequences that points to non-expandable commands are not expanded. On the other hand, the 
expandable commands are expanded. Thus, when expanding a control sequence token, we put the 
command that it points to into a instance variable named meaning. In addition, the expand
method takes the original token as an argument, in addition to the parser. Non-expandable 
commands returns the original token. Executing the token, or examining its value, is done 
by calling the execute method of the meaning command. 
"""


import typing
from pytex.module import Module
from pytex import serialization


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


class Command(serialization.Serializable):
    """ 
    a command represents a tex functionality. It could represent a sequence of tokens
    to be expanded to, such as a macro, or a primitive command that is executed by the
    parser.
    """
    name = None
    catcode = None
    protected = False

    # the command is not expandable by default
    # expandable commands have a expand method defined
    expand = None

    # this variable is used to identify \\the and \\unexpanded commands, which defines 
    # the expanded method.
    expanded = None

    @classmethod
    def showmeaning(cls, command):
        """
        return a string representation of the meaning of the command. 
        @param token: the command
        @return: the meaning of the command
        
        This is used to define the \\meaning command
        """
        if command:
            return command.name if command.name else "noname"
        return "undefined"

    def meaning(self):
        """
        get the meaning of the command.
        @return the class, and the representation values

        The is used to implement both \meaning and \ifx (for comparison).
        For \ifx, if both tokens return the same meaning, then they are the same.
        """
        return Command, self

    def execute(self, parser):
        """
        execute the command.
        @param parser: the parser
        """
        pass

    def __repr__(self):
        """
        return a string representation of the command.
        @return: the string representation of the command
        """
        cls, value = self.meaning()
        return cls.showmeaning(value)
    
    def __eq__(self, other):
        """
        compare the command with another command.
        @param other: the other command
        @return: True if the commands are equal, False otherwise
        """
        return self is other


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
        self.definition = None

    # the token is not a command
    is_command = False

    @classmethod
    def showmeaning(cls, token):
        """
        get the meaning of the command. This is used to define the \\meaning command
        @param token: the command
        @return: the meaning of the command
        """
        name, catcode = token
        return f"{name}({catcode})"
    
    # not expandable by default
    expand = None

    def meaning(self):
        return Token, (self.name, self.catcode)
    
    def __eq__(self, other):
        return self.meaning() == other.meaning()

    def execute(self, parser):
        """
        execute the token. The default behavior is to raise an error.
        @param parser: the parser
        """
        raise ValueError("invalid token: " + str(self))
    
    def saveInfo(self):
        return {"init": {"name": self.name, "catcode": self.catcode}}

    def isSpace(self, expand):
        """ 
        Check if the token is a space token.
        @param expand: bool indicating if the token should be expanded
        @return: bool
        """
        return False

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
        parser.endGroup(parser.input.position())


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
        self.noexpand = False

    def saveInfo(self):
        return {"init": {"name": self.name}}

    # Command tokens represent commands
    is_command = True

    def execute(self, parser):
        """
        Execute the command. 
        @param parser: the parser
        """
        # up to this point, the meaning has been found
        if self.definition is not None:
            self.definition.execute(parser)

    def isSpace(self, expand):
        """ 
        Check if the command is a space command.
        @param expand: bool indicating if the command should be expanded
        @return: bool
        """
        return expand and isinstance(self.definition, Token) and self.definition.isSpace(True)

    def charValue(self, parser):
        """ 
        A command tokens does not represent a character. So they do not have a char value.
        @param parser: the parser
        @return: None
        """
        return None
    
    def meaning(self):
        """
        Get the meaning of the command.
        @param parser: the parser
        @return: the meaning of the command
        """
        if self.definition is None:
            return Command, None
        return self.definition.meaning()


class ActiveToken(CommandToken):
    """ an active token """
    def __init__(self, name: str, catcode: int=CATCODE.ACTIVE):
        super().__init__(name)
        self.catcode = CATCODE.ACTIVE

    def charValue(self, parser):
        """ 
        An active token is a character token, so it has a char value.
        @param parser: the parser
        @return: the char value
        """
        return self.name

    def meaning(self):
        """
        Get the meaning of the command.
        @param parser: the parser
        @return: the meaning of the command
        """
        if self.noexpand:
            return Token, (self.name, self.catcode)
        return super().meaning()


class ParameterToken(Token):
    """
    represent the # token in a macro definition
    """
    # the parameter number
    parameter = None
    def execute(self, parser):
        raise ValueError("unexpected #")


class SpaceToken(Token):
    """
    represent a space (including tabs and newlines)
    the name is always " "
    """
    def __init__(self, name: str=" ", catcode=CATCODE.SPACE):
        super().__init__(name, catcode)

    def execute(self, parser):
        parser.addSpace()

    def __repr__(self):
        return " "
    
    def saveInfo(self):
        return {}
    
    def isSpace(self, expand):
        """ 
        Check if the token is a space token.
        @param expand: bool indicating if the token should be expanded
        @return: bool
        """
        return True


class CharToken(Token):
    """ a letter or other character """
    def execute(self, parser):
        parser.addChar(self.name)
    
    def __repr__(self):
        return self.name
    

class MathShiftToken(Token):
    """ a token that represents a math shift $ """
    def execute(self, parser):
        parser.mathShift()


class SuperscriptToken(Token):
    """ a token that represents a superscript ^ """
    def execute(self, parser):
        parser.superscript()


class SubscriptToken(Token):
    """ a token that represents a subscript _ """
    def execute(self, parser):
        parser.subscript()


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
    ActiveToken,  # ACTIVE = 13
    None,  # COMMENT = 14
    None,  # INVALID = 15
]


relax = Command()


mod = Module("token",
    commands = {
        "relax": relax,
    },
)
