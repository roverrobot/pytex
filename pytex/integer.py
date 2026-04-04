"""
This module handles reading and processing integers.
"""


from pytex.token import CATCODE, Command
from pytex.module import Module
from pytex.serialization import Builtin
from pytex.state import Array
from pytex.accessor import Accessor, VALUE_TYPE, AttrTarget, ReadOnlyTarget, canReadAs
from pytex.define import registerdef


def readSigns(parser):
    """
    Read ooptional signs
    @param parser: the parser
    @return: 1 or -1
    """
    sign = 1
    # skips spaces
    while True:
        try:
            t = parser.skipSpaces()
        except EOFError:
            return sign
        if t.catcode != CATCODE.OTHER:
            parser.input.unread(t)
            return sign
        if t.name == "-":
            sign = -sign
        elif t.name != "+":
            parser.input.unread(t)
            return sign


def readInteger(parser):
    """
    Read an integer
    @param parser: the parser
    @return: the integer
    """
    # number = signs followed by unsigned number
    # read signs, which are optional See TeXbook p. 269
    return readSigns(parser) * readUnsigned(parser)


def readUnsigned(parser):
    """
    Read an unsigned integer
    @param parser: the parser
    @return: the unsigned integer
    """
    # an unsigned integer is an innternal integer (one with an intValue method),
    # or a coersed integer, or a normal integer
    # a coerced integer is either a dimension or a glue, both have an intValue method
    value = parser.readInternalValue(VALUE_TYPE.INT)
    if value is not None:
        return int(value)
    try:
        t = parser.token_expand()
    except EOFError:
        raise ValueError("expecting an integer", parser.input.position())
    # a normal integer is either a ` followed by a character, or a ' followed by
    # an octant number, or a " followed by a hex number, or a number
    if t.catcode != CATCODE.OTHER:
        raise ValueError(f"expecting an integer, got {t}", parser.input.position())
    if t.name == "`":
        t = parser.token()
        if t.name[0] == "\\" and len(t.name) == 2:
            value = ord(t.name[1])
        elif len(t.name) == 1:
            value =  ord(t.name)
        else:
            raise ValueError(f"expecting a character, got {t.name}", parser.input.position())
    elif t.name == "'":
        value = int(readDigits(parser, 8), 8)
    elif t.name == '"':
        value = int(readDigits(parser, 16), 16)
    else:
        parser.input.unread(t)
        value = int(readDigits(parser, 10), 10)
    # skip the optional space
    parser.skipSpaceExapnd()
    return value


def validDecimalDigit(c):
    """
    Check if the character is a decimal digit
    @param c: the character
    @return: True if the character is a decimal digit
    """
    return ord("0") <= ord(c) <= ord("9")


def validOctalDigit(c):
    """
    Check if the character is an octal digit
    @param c: the character
    @return: True if the character is an octal digit
    """
    return ord("0") <= ord(c) <= ord("7")


def validHexDigit(c):
    """
    Check if the character is a hex digit
    @param c: the character
    @return: True if the character is a hex digit
    """
    return validDecimalDigit(c) or ord("A") <= ord(c) <= ord("F") or ord("a") <= ord(c) <= ord("f") 


def readDigits(parser, base, optional=False):
    """
    Read a sequence of digits in the given base
    @param parser: the parser
    @param base: the base of the number
    @return: the integer
    """
    if base == 10:
        validDigit = validDecimalDigit
    elif base == 8:
        validDigit = validOctalDigit
    elif base == 16:
        validDigit = validHexDigit
    else:
        raise ValueError("invalid base", base)
    # have we started reading?
    read = False
    value = ""
    while True:
        try:
            t = parser.token_expand()
        except EOFError:
            break
        # commands do not have a catcode
        if (t.catcode != CATCODE.OTHER and t.catcode != CATCODE.LETTER) or not validDigit(t.name):
            parser.input.unread(t)
            break
        read = True
        value += t.name
    if not read and not optional:
        raise ValueError("expecting a number", parser.input.position())
    return value


IntegerArrayItemAccessor = lambda domain=None, key=None, builtin=True: Accessor(
    domain,
    key,
    builtin=builtin,
    value_type=VALUE_TYPE.INT,
    read_key=lambda parser: parser.readInteger(),
)


class RangedIntergerArrayItemAccessor(Accessor):
    value_type = VALUE_TYPE.INT

    def __init__(self, domain, key=None, range=None, builtin=True):
        super().__init__(domain, key, builtin)
        self.range = range

    def readKey(self, parser):
        return parser.readInteger()

    def checkRange(self, value, pos):
        """
        check if the value is in the range
        @param value the value to check
        @param pos the current position in input
        """
        range = self.range
        if (range[0] is not None and value < range[0]) or \
            (range[0] is not None and value > range[1]):
            raise ValueError(f"value {value} is not in the range {self.range}", pos)

    def set(self, parser, value):
        if self.range is not None:
            self.checkRange(value, parser.input.position())
        super().set(parser, value)

    def setGlobal(self, parser, value):
        if self.range is not None:
            self.checkRange(value, parser.input.position())
        super().setGlobal(parser, value)


class CatCode(Array):
    """
    The category code array \\catcode
    """
    def __init__(self, state):
        super().__init__("catcode", state, CATCODE.OTHER)
        # When INITEX begins, it knows nothing but T EX’s primitives. All 256 charac-
        # ters are initially of category 12, except that ⟨return⟩has category 5, ⟨space⟩
        # has category 10, ⟨null⟩has category 9, ⟨delete⟩has category 15, the 52 letters A...Zand
        # a...z have category 11, % and \ have the respective categories 14 and 0. It follows that
        # INITEX is initially incapable of carrying out some of T EX’s primitives that depend on
        # grouping; you can’t use \def or \hbox until there are characters of categories 1 and 2.        
        self[ord("\r")] = CATCODE.END_OF_LINE
        self[ord(" ")] = CATCODE.SPACE
        self[0] = CATCODE.IGNORE
        self[8] = CATCODE.INVALID
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = CATCODE.LETTER
            self[c + 32] = CATCODE.LETTER
        self[ord("%")] = CATCODE.COMMENT
        self[ord("\\")] = CATCODE.ESCAPE


class CatCodeArrayAccessor(RangedIntergerArrayItemAccessor):
    def __init__(self, domain, key=None, builtin=True):
        super().__init__(domain, key, range=(0, 15), builtin=builtin)


class LCCode(Array):
    """
    The lowercase code array \\lccode
    """
    def __init__(self, state):
        super().__init__("lccode", state, 0)
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = c + 32
            self[c+32] = c + 32


class UCCode(Array):
    """
    The uppercase code array \\uccode
    """
    def __init__(self, state):
        super().__init__("uccode", state, 0)
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = c
            self[c+32] = c


class SFCode(Array):
    """
    The space factor code array \\sfcode
    """
    def __init__(self, state):
        super().__init__("sfcode", state, 1000)
        # When INITEX creates a brand new TEX, all characters have a space factor code of 1000, 
        # except that the uppercase letters ‘A’ through ‘Z’ have code 999. 
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = 999
        

class MathCode(Array):
    """
    The math code array \\mathcode
    """
    def __init__(self, state):
        super().__init__("mathcode", state, 0)
        # \mathcode x = x for all characters x that are neither letters nor digits. The ten digits
        # have \mathcode x = x+ ̋7000; the 52 letters have \mathcode x = x+ ̋7100.
        for c in range(self.SIZE):
            self[c] = c
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = c + 0x7100
            self[c + 32] = c + 0x7120
        for c in range(ord("0"), ord("9") + 1):
            self[c] = c + 0x7000


class DelCode(Array):
    """
    The delimiter code array \\delcode
    """
    def __init__(self, state):
        super().__init__("delcode", state, -1)


class Count(Array):
    """
    The count registers \\count
    """
    def __init__(self, state):
        super().__init__("count", state, 0)


class FixedInteger(Command):
    """
    A command returns a read-only integer
    @param value the integer value
    """
    def __init__(self, value):
        self.value = value

    def fetchValue(self, parser, requested_type):
        if not canReadAs(VALUE_TYPE.INT, requested_type):
            return None, None
        return self.value, VALUE_TYPE.INT
    
    def execute(self, parser):
        raise ValueError(f"{self.name} cannot be executed, it is read-only", parser.input.position())


class InputLineNo(Command):
    """
    \\inputlineno, which returns the current line number in the source file
    """
    def fetchValue(self, parser, requested_type):
        if not canReadAs(VALUE_TYPE.INT, requested_type):
            return None, None
        return parser.input.position().line, VALUE_TYPE.INT

    def execute(self, parser):
        raise ValueError(f"{self.name} cannot be executed, it is read-only", parser.input.position())


module = Module("integer", 
    attributes={"readInteger": readInteger},
    parameters={
        # integer parameters
        "pretolerance": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "tolerance": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "hbadness": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "vbadness": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "linepenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "hyphenpenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "exhyphenpenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "binoppenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "relpenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "clubpenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "widowpenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "displaywidowpenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "brokenpenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "predisplaypenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "postdisplaypenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "interlinepenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "floatingpenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "outputpenalty": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "doublehyphendemerits": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "finalhyphendemerits": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "adjdemerits": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "uchyph": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "lefthyphenmin": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "righthyphenmin": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "mag": {"value": 1000, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "delimiterfactor": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        # escapechar is a layout parameter because \write may use it
        "escapechar": {"value": ord("\\"), "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        # control parameters
        "fam": {"value": -1, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "pausing": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "holdinginserts": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "language": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "globaldefs": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "endlinechar": {"value": ord("\r"), "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "newlinechar": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "maxdeadcycles": {"value": 25, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "showboxbreadth": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "showboxdepth": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "errorcontextlines": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "defaulthyphenchar": {"value": ord("-"), "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "defaultskewchar": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        # volatile parameters
        "time": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "volatile"},
        "day": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "volatile"},
        "month": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "volatile"},
        "year": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "volatile"},
        # these are reset at the end of every paragraph
        "looseness": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "volatile"},
        "hangafter": {"value": 1, "accessor": IntegerArrayItemAccessor, "domain": "volatile"},
        # global parameters
        "deadcycles": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "globals"},
        "insertpenalties": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "globals"},
    },
    domains={
        "catcode": {"generator": CatCode, "accessor": CatCodeArrayAccessor},
        "lccode": {"generator": LCCode, "accessor": IntegerArrayItemAccessor},
        "uccode": {"generator": UCCode, "accessor": IntegerArrayItemAccessor},
        "sfcode": {"generator": SFCode, "accessor": IntegerArrayItemAccessor},
        "delcode": {"generator": DelCode, "accessor": IntegerArrayItemAccessor},
        "mathcode": {"generator": MathCode, "accessor": IntegerArrayItemAccessor},
        "count": {"generator": Count, "accessor": IntegerArrayItemAccessor},
    },
    commands={
        "inputlineno": InputLineNo(),
        "countdef": registerdef("count", IntegerArrayItemAccessor),
    },
)
