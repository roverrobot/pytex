"""
This module implements command definition, such as \\let etc.
"""


from pytex import accessor
from pytex.module import Module
from pytex.integer import IntegerValuePointer
from pytex.dimen import DimenValuePointer
from pytex.glue import GlueValuePointer, MuGlueValuePointer
from pytex.accessor import ParameterAccessor
from pytex.toks import ToksValuePointer, relax
from pytex import token


class Define(accessor.ArrayAccessor):
    """
    the base class for defining commands
    @param pointer_generator: the generator for the pointer to the equitable item
    """
    def __init__(self, pointer_generator, eq: bool = True):
        super().__init__("equitable", pointer_generator, eq)

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


class LetItem(accessor.ValuePointer):
    """
    an item in the equitable.
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return parser.token()


class Let(Define):
    """
    the \\let command
    """
    def __init__(self):
        super().__init__(LetItem)


class FutureLetItem(LetItem):
    """
    an item in the equitable.
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
    def __init__(self):
        super().__init__(FutureLetItem)


class IntegerHolder:
    """
    a holder for an integer
    """
    def __init__(self, value):
        self.value = value

    def intValue(self, parser):
        """
        get the integer value
        """
        return self.value


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
        parser.addChar(token.CharToken(chr(self.value), token.CATCODE.OTHER))
    
    def pointer(self, parser):
        """
        get the integer value
        """
        return IntegerHolder(self.value)


class CharDefItem(accessor.ValuePointer):
    """
    an item in the equitable.
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
    def __init__(self):
        super().__init__(CharDefItem)


class RegisterItem(accessor.ValuePointer):
    """
    an item in \\count.
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return ParameterAccessor(self.register, parser.readInteger(), self.item_generator)


class RegisterDef(Define):
    """
    commands such as \\countdef \\skipdef etc.
    @param register: the name of the register
    @param item_generator: the generator for the register item
    """
    def __init__(self, register: str, item_generator):
        super().__init__(RegisterItem)
        self.register = register
        self.item_generator = item_generator

    def pointer(self, parser):
        """
        get the value pointer
        @param parser: the parser
        @return: the value pointer and possible prefixes
        """
        p = super().pointer(parser)
        p.register = self.register
        p.item_generator = self.item_generator
        return p


mod = Module("define",
    commands = {
        "let": Let(),
        "futurelet": FutureLet(),
        "chardef": CharDef(),
        "countdef": RegisterDef("count", IntegerValuePointer),
        "dimendef": RegisterDef("dimen", DimenValuePointer),
        "skipdef": RegisterDef("skip", GlueValuePointer),
        "muskipdef": RegisterDef("muskip", MuGlueValuePointer),
        "toksdef": RegisterDef("toks", ToksValuePointer)
    }
)