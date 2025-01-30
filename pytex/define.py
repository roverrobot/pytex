"""
This module implements command definition, such as \\let etc.
"""


from pytex import accessor
from pytex.module import Module
from pytex.integer import IntegerArrayAccessor
from pytex.dimen import DimenArrayAccessor
from pytex.glue import GlueArrayAccessor, MuGlueArrayAccessor
from pytex.toks import ToksArrayAccessor
from pytex import token


class Define(accessor.ArrayAccessor):
    """
    the base class for defining commands
    @param pointer_generator: the generator for the pointer to the equitable item
    """
    def __init__(self):
        super().__init__("equitable")

    def getIndex(self, parser):
        """
        get the index of the command
        @param parser: the parser
        """
        t = parser.token()
        if t is None or not t.is_command:
            raise ValueError("command name expected")
        # command t is going to be redefined. We make it relax
        parser.state.equitable[t.name] = None
        return t.name


class LetAccessor(accessor.Accessor):
    """
    An accessor for the \\let command
    """
    def readValue(self, parser):
        t = parser.token()
        if t is None:
            raise ValueError("a token is expected")
        return t


class Let(Define):
    """
    the \\let command
    """
    def newItemAccessor(self, index):
        return LetAccessor(self.domain, index)


class FutureLetAccessor(accessor.Accessor):
    """
    An accessor for the \\futurelet command
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        t1 = parser.token()
        if t1 is None:
            raise ValueError("a token is expected")    
        t2 = parser.token()
        if t2 is None:
            raise ValueError("\\futurelet expects two tokens")
        parser.input.unread(t1)
        return t2


class FutureLet(Define):
    """
    the \\futurelet command
    """
    def newItemAccessor(self, index):
        return FutureLetAccessor(self.domain, index)


class CharDefValue(token.Command):
    """
    the value of the \\chardef command
    """
    def __init__(self, value):
        self.value = value
    
    def __str__(self):
        return chr(self.value)

    def execute(self, parser):
        """
        execute the command
        @param parser: the parser
        """
        parser.addChar(self.charValue(parser))
    
    def intValue(self, parser):
        """
        get the integer value
        """
        return self.value

    def charValue(self, parser):
        """
        get the character value
        """
        return chr(self.value)


class CharDefAccessor(accessor.Accessor):
    """
    An accessor for the \\chardef command
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return CharDefValue(parser.readInteger())


class CharDef(Define):
    """
    the \\chardef command
    """
    def newItemAccessor(self, index):
        return CharDefAccessor(self.domain, index)


class RegisterDefAccessor(accessor.Accessor):
    """
    An accessor for the register definition commands
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        index = parser.readInteger()
        return self.value_type.getItemAccessor(parser, index)


class RegisterDef(Define):
    """
    commands such as \\countdef \\skipdef etc.
    @param register: the name of the register
    @param value_type: the generator for the register item
    """
    def __init__(self, register: str, value_type):
        super().__init__()
        self.value_type = value_type(register)

    def getItemAccessor(self, parser, index):
        """
        read the value from the input stack
        @param parser: the parser
        """
        p = RegisterDefAccessor(self.domain, self.getIndex(parser), eq=True)
        p.value_type = self.value_type
        return p


mod = Module("define",
    commands = {
        "let": Let(),
        "futurelet": FutureLet(),
        "chardef": CharDef(),
        "countdef": RegisterDef("count", IntegerArrayAccessor),
        "dimendef": RegisterDef("dimen", DimenArrayAccessor),
        "skipdef": RegisterDef("skip", GlueArrayAccessor),
        "muskipdef": RegisterDef("muskip", MuGlueArrayAccessor),
        "toksdef": RegisterDef("toks", ToksArrayAccessor),
    }
)