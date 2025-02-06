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


import enum
import typing
from pytex.module import Module


def serialize(obj):
    """
    serialize the object into a dictionary
    """
    if isinstance(obj, Serializable):
        return obj.serialize()
    elif hasattr(obj, "items"):
        for key, value in obj.items():
            obj[key] = serialize(value)
    elif isinstance(obj, enum.Enum):
        return obj.value
    return obj


def getClass(module, name):
    """
    get the class from the module
    """
    # check if module has the form pytex.module
    if module.startswith("pytex."):
        module = module[6:]
        mod = getattr(__import__("pytex"), module)
    else:
        mod = __import__(module)
    return getattr(mod, name)


def deserialize(parser, data):
    """
    deserialize the object from a dictionary or a list
    """
    if isinstance(data, list):
        items = enumerate(data)
    elif isinstance(data, dict):
        items = data.items()
    else:
        items = None
    if items is not None:
        for key, value in items:
            data[key] = deserialize(parser, value)
    if isinstance(data, dict) and "serializable" in data and data["serializable"]:
        cls = getClass(data["module"], data["classname"])
        data = cls.deserialize(parser, data)
    return data


class Serializable:
    """
    The base class for all serializable objects. The serialization will be used to dump
    the parser state into a dump file
    """
    def saveInfo(self):
        """
        save the information of the command into a dictionary

        One component of the information is argument needed to construct the command, which
        is stored in the "init" element. The other component is the extra attributed,
        which is stored in the "extra" element. If either is empty, the element is not
        included in the dictionary.
        """
        return {}

    def serialize(self):
        info = serialize(self.saveInfo())
        info["classname"] = self.__class__.__name__
        info["module"] = self.__module__
        info["serializable"] = True
        return info

    @classmethod
    def new(cls, parser, **kwargs):
        """
        create a new object from the dictionary
        """
        return cls(**kwargs)

    @classmethod
    def deserialize(cls, parser, data):
        """
        deserialize the object from a string
        """
        init = deserialize(parser, data["init"]) if "init" in data else {}
        cls = getClass(data["module"], data["classname"])
        obj = cls.new(parser, **init)
        if "extra" in data:
            for key, value in data["extra"].items():
                if isinstance(value, dict) and "serializable" in value:
                    cls = getClass(value["module"], value["classname"])
                    value = cls.deserialize(parser, value)
                setattr(obj, key, value)
        return obj


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


class Command(Serializable):
    """ 
    a command represents a tex functionality. It could represent a sequence of tokens
    to be expanded to, such as a macro, or a primitive command that is executed by the
    parser.
    """
    # a command is a special type of token that has no name and category code
    name = None
    catcode = None
    # the command is protected from expansion when constructing an expended token list
    protected = False
    def execute(self, parser):
        """
        execute the command.
        @param parser: the parser
        """
        pass

    def expand(self, parser, token):
        """
        if the command is not expandable, the command should return itself.
        otherwise, it should put the expanded tokens in the input stack.
        Here, by default, it is not expandable.
        @param parser: the parser 
        @param token: the command token
        """
        return token


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

    def isCommand(self):
        """ 
        A token is not a command. 
        @return: False
        """
        return self.catcode is None or self.catcode == CATCODE.ACTIVE
    
    def __repr__(self):
        return f"{self.name}({self.catcode})"

    def execute(self, parser):
        """
        execute the token. The default behavior is to raise an error.
        @param parser: the parser
        """
        raise ValueError("invalid token: " + str(self))
    
    def expand(self, parser, token):
        """
        expand the token. The default behavior is to return itself.
        @param parser: the parser
        @param token: the token
        @return: the expanded token
        """
        return self

    def saveInfo(self):
        return {"init": {"name": self.name, "catcode": self.catcode}}

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

    def saveInfo(self):
        return {"init": {"name": self.name}}

    def expand(self, parser, token):
        """
        expand the command. If the command is not expandable, the command should return
        itself. Otherwise, it should put the expanded tokens in the input stack.
        @param parser: the parser
        @param token: the token that represents the command
        @return: the expanded command
        """
        command = parser.lookup(self.name)
        if command is None:
            return self
        self.meaning = command
        return command.expand(parser, self)

    def execute(self, parser):
        """
        Execute the command. The default behavior is to raise an error.
        @param parser: the parser
        """
        if self.meaning is not None:
            self.meaning.execute(parser)
        else:
            raise ValueError(f"command not defined: {self.name}")

    def charValue(self, parser):
        """ 
        A command tokens does not represent a character. So they do not have a char value.
        @param parser: the parser
        @return: None
        """
        return None

    def __repr__(self):
        return f"{self.name} "


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

    def __repr__(self):
        return " "
    
    def saveInfo(self):
        return {}


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
