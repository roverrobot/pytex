"""
This module implements command definition, such as \\let etc.
"""


from pytex import accessor
from pytex.module import Module
from pytex.token import relax, Command
from pytex.serialization import Serializable


class EquitableAccessor(accessor.Accessor):
    """
    An accessor whose target key is a control sequence in the equitable domain.
    """
    target_type = accessor.VALUE_TYPE.MEANING

    def readKey(self, parser):
        t = parser.token()
        if t is None or t.entry is None:
            raise ValueError(f"command name expected, got {t}", parser.input.position())
        self.setDefault(t)
        return t.name

    def setDefault(self, t):
        if t.definition is None:
            t.entry.value = t.definition = relax


class Define(accessor.ArrayAccessor):
    """
    the base class for defining commands
    @param accessor_generator: the generator for the accessor to the equitable item
    """
    def __init__(self, accessor_generator=accessor.Accessor):
        # provide a default value for the command before the assignment.
        # Typically this is \\relax. However, in font assignment. For example, in
        # \\font\\f=cmr10 \\fontname\\f
        # the \\fontname is expanded before the assignment because the \\font command
        # is looking for a keyword "scale" or "to". However, at this stage the assignmnt
        # for \\f has not happended yet as pytex is still reading the font specification.
        # Thus, \\f should recive a default value of \\nullfont, as in TeX82.
        self.accessor_generator = accessor_generator

    def getItemAccessor(self, parser):
        """
        get the index of the command
        @param parser: the parser
        """
        return self.accessor_generator(parser.equitable, builtin=False)


class LetAccessor(EquitableAccessor):
    """
    An accessor for the \\let command
    """
    def readEq(self, parser):
        parser.skipEq(expand=False)
        parser.skipSpace(expand=False)

    def readValue(self, parser):
        t = parser.token()
        if t is None:
            raise ValueError("a token is expected")
        return t.definition if t.entry is not None else t


let = Define(LetAccessor)


class FutureLetAccessor(EquitableAccessor):
    """
    An accessor for the \\futurelet command
    """
    def readEq(self, parser):
        """
        has no equal sign
        """
        pass

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
        parser.input.unread(t2)
        parser.input.unread(t1)
        return t2.definition if t2.entry is not None else t2


futurelet = Define(FutureLetAccessor)


class CharDefValue(Command):
    """
    the value of the \\chardef command
    """
    def __init__(self, value):
        self.value = value

    def className(self):
        return Serializable.className(self)
    
    def saveInfo(self):
        return {"value": self.value}, None
    
    @classmethod
    def new(cls, parser, **kargs):
        return cls(**kargs)

    def execute(self, parser):
        return parser.addChar(self.charValue(parser))
    
    def charValue(self, parser):
        """
        get the character value
        """
        return chr(self.value)

    def intValue(self, parser):
        """
        get the integer value
        """
        return self.value
    
    def meaning(self, parser):
        """
        return the meaning of the command
        """
        name = parser.formatName('\\char')
        return f"{name}\"{self.value:X}"
    
    def __eq__(self, other):
        return isinstance(other, CharDefValue) and self.value == other.value


class CharDefAccessor(EquitableAccessor):
    """
    An accessor for the \\chardef command
    """
    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return CharDefValue(parser.readInteger())


chardef = Define(CharDefAccessor)


class RegisterDefAccessor(EquitableAccessor):
    """
    An accessor for commands such as \\countdef, \\dimendef etc
    @param entry: the entry of the equitable for the command name
    @param register: the register name, such as "count", "dimen", etc.
    @param accessor_generator: the generator for the accessor to the register item
    """
    def __init__(self, domain, key=None, register=None, accessor_generator=None, builtin=False):
        super().__init__(domain, key, builtin)
        self.register = register
        self.accessor_generator = accessor_generator

    def readValue(self, parser):
        i = parser.readInteger()
        register = getattr(parser, self.register)
        c = self.accessor_generator(register, i, builtin=False)
        c.name = parser.formatName(f"\\{self.register}{i}")
        return c


def registerdef(register, accessor_generator): 
    generator = lambda domain, key=None, builtin=False: RegisterDefAccessor(domain, key, register, accessor_generator, builtin=builtin)
    return Define(generator)


mod = Module("define",
    commands = {
        "let": let,
        "futurelet": futurelet,
        "chardef": chardef,
    }
)
