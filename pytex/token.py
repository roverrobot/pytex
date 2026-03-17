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

    def saveInfo(self):
        """
        save the command information. This is used to serialize the command.
        @return: a dictionary with the command information
        """
        return {"init": {"name": self.name}}

    @classmethod
    def new(cls, parser, **kargs):
        """
        create a new command from the dictionary
        @param parser: the parser
        @param init: the command information
        @return: the command
        """
        name = kargs.get("name")
        if name:
            return parser.builtin[name]
        if cls.init_needs_parser:
            return cls(parser, **kargs)
        return cls(**kargs)

   
    def __eq__(self, other):
        """
        compare the command with another command.
        @param other: the other command
        @return: True if the commands are the same object, False otherwise
        """
        return self is other

    def execute(self, parser):
        """
        execute the command.
        @param parser: the parser
        """
        pass

    def meaning(self, parser):
        """
        return a string representation of the command.
        @param parser: the parser
        @return: the string representation of the command
        """
        if self.name is None:
            return None
        return parser.formatName(self.name)
    
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
    
    # not expandable by default
    expand = None

    def __eq__(self, other):
        return isinstance(other, Token) and self.name == other.name and self.catcode == other.catcode

    def execute(self, parser):
        """
        execute the token. The default behavior is to raise an error.
        @param parser: the parser
        """
        raise ValueError(f"invalid token: {self.meaning(parser)}", parser.input.position())
    
    def saveInfo(self):
        return {"init": {"name": self.name, "catcode": self.catcode}}
    
    @classmethod
    def new(cls, parser, **kargs):
        return cls(**kargs)

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

    
    def meaning(self, parser):
        """
        return a string representation of the token.
        @return: the string representation of the token

        This is used by \\meaning
        """
        return NotImplementedError("Must be implemented in subclasses")


class BeginGroupToken(Token):
    """ a token that represents the beginning of a group {"""
    def execute(self, parser):
        parser.beginGroup(parser.input.position())

    def meaning(self, parser):
        return f"begin-group character {self.name}"


class EndGroupToken(Token):
    """ a token that represents the end of a group {"""
    def execute(self, parser):
        parser.endGroup(parser.input.position())

    def meaning(self, parser):
        return f"end-group character {self.name}"


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

    @classmethod
    def new(cls, parser, **kargs):
        """
        create a new command from the dictionary
        @param parser: the parser
        @param init: the command information
        @return: the command
        """
        name = kargs["name"]
        if name is None:
            raise ValueError("command name is required")
        t = cls(name)
        t.entry = parser.state.equitable.entry(name)
        return t

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
    
    def meaning(self, parser):
        """
        Get the meaning of the command.
        @param parser: the parser
        @return: the meaning of the command
        """
        definition = self.entry.value
        return "undefined" if definition is None else definition.meaning(parser)
    
    def __eq__(self, other):
        """
        compare the command with another command.
        @param other: the other command
        @return: True if the commands are equal, False otherwise
        """
        return isinstance(other, CommandToken) and self.entry == other.entry


class ActiveToken(CommandToken):
    """ an active token """
    def __init__(self, name: str, catcode: int=CATCODE.ACTIVE):
        super().__init__(name)
        self.catcode = CATCODE.ACTIVE

    @classmethod
    def new(cls, parser, **kargs):
        """
        create a new command from the dictionary
        @param parser: the parser
        @param init: the command information
        @return: the command
        """
        name = kargs["name"]
        if name is None:
            raise ValueError("active token name is required")
        t = cls(name, kargs.get("catcode", CATCODE.ACTIVE))
        t.entry = parser.state.equitable.entry(name)
        return t
    
    def charValue(self, parser):
        """ 
        An active token is a character token, so it has a char value.
        @param parser: the parser
        @return: the char value
        """
        return self.name


class AlignmentTabToken(Token):
    """ 
    a token that represents an alignment tab &.
    This is used in tabular environments.
    """
    def meaning(self, parser):
        return f"alignment tab character {self.name}"
    
    def execute(self, parser):
        """
        Execute the alignment tab token. 
        @param parser: the parser

        This command can only appear in alignment.
        """
        if parser.alignments.currentCell() is None:
            raise ValueError("unexpected &", parser.input.position())
        parser.endCell(is_last=False)


class ParameterToken(Token):
    """
    represent the # token in a macro definition
    """
    # the parameter number
    parameter = None

    def saveInfo(self):
        return super().saveInfo() | {"extra": {"parameter": self.parameter}}

    def execute(self, parser):
        raise ValueError("unexpected #", parser.input.position())
    
    def meaning(self, parser):
        """
        return a string representation of the token.
        @param parser: the parser
        @return: the string representation of the token
        """
        return f"macro parameter character {self.name}"

    def toString(self, parser):
        if self.parameter is None:
            return "##"
        return "#" + str(self.parameter+1)


class SpaceToken(Token):
    """
    represent a space (including tabs and newlines)
    the name is always " "
    """
    def __init__(self, name: str=" ", catcode=CATCODE.SPACE):
        super().__init__(name, catcode)

    def execute(self, parser):
        parser.addSpace()

    def meaning(self, parser):
        return "blank space"
    
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
    
    def meaning(self, parser):
        if self.token == CATCODE.LETTER:
            return f"the letter {self.name}"
        return f"the character {self.name}"
    

class MathShiftToken(Token):
    """ a token that represents a math shift $ """
    def execute(self, parser):
        parser.mathShift()

    def meaning(self, parser):
        return f"math shift character {self.name}"


class SuperscriptToken(Token):
    """ a token that represents a superscript ^ """
    def execute(self, parser):
        parser.superscript()

    def meaning(self, parser):
        return f"superscript character {self.name}"


class SubscriptToken(Token):
    """ a token that represents a subscript _ """
    def execute(self, parser):
        parser.subscript()

    def meaning(self, parser):
        return f"subscript character {self.name}"


# the token generators for each category code
Token.generators = [
    None,  # ESCAPE
    BeginGroupToken,  # BEGIN_GROUP = 1
    EndGroupToken,  # END_GROUP = 2
    MathShiftToken,  # MATH_SHIFT = 3
    AlignmentTabToken,  # ALIGNMENT_TAB = 4
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
