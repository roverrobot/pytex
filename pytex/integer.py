"""
This module handles reading and processing integers.
"""


from pytex.token import CATCODE, Command
from pytex.module import Module
from pytex.state import Array
from pytex.accessor import ParameterAccessor, ArrayAccessor, ArrayItemAccessor
from pytex.define import Define


def readSigns(parser):
    """
    Read ooptional signs
    @param parser: the parser
    @return: 1 or -1
    """
    sign = 1
    # skips spaces
    while True:
        t = parser.skipSpaces()
        if t is None:
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
    t = parser.token_expand()
    if t is None:
        raise ValueError("expecting an integer", parser.input.position())
    try:
        return t.definition.intValue(parser)
    except AttributeError:
        pass
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
            raise ValueError("expecting a character", parser.input.position())
    elif t.name == "'":
        value = int(readDigits(parser, 8), 8)
    elif t.name == '"':
        value = int(readDigits(parser, 16), 16)
    else:
        parser.input.unread(t)
        value = int(readDigits(parser, 10), 10)
    # skip the optional space
    parser.skipSpace()
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
        t = parser.token_expand()
        if t is None:
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


class IntegerArrayItemAccessor(ArrayItemAccessor):
    """
    integer accessor common functions
    """
    def readValue(self, parser):
        return parser.readInteger()

    def intValue(self, parser):
        return self.domain[self.index]


class RangedIntergerArrayItemAccessor(IntegerArrayItemAccessor):
    def __init__(self, domain, index, range=None):
        super().__init__(domain, index)
        self.range = range

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
        if range is not None:
            self.checkRange(value, parser.input.position())
        super().set(parser, value)

    def setGlobal(self, parser, value):
        if self.range is not None:
            self.checkRange(value, parser.input.position())
        super().setGlobal(parser, value)


class IntegerArrayAccessor(ArrayAccessor):
    """
    integer array accessor
    """
    def getItemAccessor(self, parser):
        return IntegerArrayItemAccessor(self.domain, parser.readInteger())
        
    def intValue(self, parser):
        """
        get the integer value of the array item
        @param parser: the parser
        @return: the integer value
        """
        return self.domain[parser.readInteger()]


class RangedIntegerArrayAccessor(IntegerArrayAccessor):
    """
    An integer array accessor with a range
    """
    def __init__(self, domain, range=None):
        super().__init__(domain)
        self.range = range

    def getItemAccessor(self, parser):
        return RangedIntergerArrayItemAccessor(self.domain, parser.readInteger(), self.range)


class CatCode(Array):
    """
    The category code array \\catcode
    """
    def __init__(self, state):
        super().__init__("catcode", state, CATCODE.OTHER)
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = CATCODE.LETTER
            self[c + 32] = CATCODE.LETTER
        self[ord("\\")] = CATCODE.ESCAPE
        self[ord("\r")] = CATCODE.END_OF_LINE
        self[ord(" ")] = CATCODE.SPACE
        self[ord("%")] = CATCODE.COMMENT
        self[8] = CATCODE.INVALID


class CatCodeArrayAccessor(RangedIntegerArrayAccessor):
    def __init__(self, domain="catcode"):
        super().__init__(domain, range=(0, 15))


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

    def intValue(self, parser):
        return self.value
    
    def execute(self, parser):
        raise ValueError(f"{self.name} cannot be executed, it is read-only", parser.input.position())


class InputLineNo(Command):
    """
    \inputlineno, which returns the current line number in the source file
    """
    def intValue(self, parser):
        # the line number is the current line number
        return parser.input.position().line

    def execute(self, parser):
        raise ValueError(f"{self.name} cannot be executed, it is read-only", parser.input.position())


class IntegerParameterAccessor(ParameterAccessor):
    """
    An accessor for an integer parameter
    """
    def readValue(self, parser):
        return parser.readInteger()

    def intValue(self, parser):
        return self.entry.value


class CountDefAccessor(ParameterAccessor):
    """
    An accessor for \\countdef
    """
    def readValue(self, parser):
        return IntegerArrayItemAccessor(parser.state.count, parser.readInteger())


countdef = Define(CountDefAccessor)


module = Module("integer", 
    attributes={"readInteger": readInteger},
    parameters={
        # integer parameters
        "pretolerance": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "tolerance": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "hbadness": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "vbadness": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "linepenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "hyphenpenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "exhyphenpenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "binoppenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "relpenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "clubpenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "widowpenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "displaywidowpenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "brokenpenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "predisplaypenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "postdisplaypenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "interlinepenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "floatingpenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "outputpenalty": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "doublehyphendemerits": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "finalhyphendemerits": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "adjdemerits": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "looseness": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "uchyph": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "lefthyphenmin": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "righthyphenmin": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "hangafter": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "mag": {"value": 1000, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "delimiterfactor": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        # escapechar is a layout parameter because \write may use it
        "escapechar": {"value": ord("\\"), "accessor": IntegerParameterAccessor, "domain": "layout"},
        # control parameters
        "fam": {"value": -1, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pausing": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "holdinginserts": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "language": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "globaldefs": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "endlinechar": {"value": ord("\r"), "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "newlinechar": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "maxdeadcycles": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "showboxbreadth": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "showboxdepth": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "errorcontextlines": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "defaulthyphenchar": {"value": ord("-"), "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "defaultskewchar": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        # volatile parameters
        "time": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "volatile"},
        "day": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "volatile"},
        "month": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "volatile"},
        "year": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "volatile"},
        # global parameters
        "spacefactor": {"value": 1000, "accessor": IntegerArrayItemAccessor, "domain": "globals"},
        "prevgraf": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "globals"},
        "deadcycles": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "globals"},
        "insertpenalties": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "globals"},
    },
    domains={
        "catcode": {"generator": CatCode, "accessor": CatCodeArrayAccessor},
        "lccode": {"generator": LCCode, "accessor": IntegerArrayAccessor},
        "uccode": {"generator": UCCode, "accessor": IntegerArrayAccessor},
        "sfcode": {"generator": SFCode, "accessor": IntegerArrayAccessor},
        "delcode": {"generator": DelCode, "accessor": IntegerArrayAccessor},
        "mathcode": {"generator": MathCode, "accessor": IntegerArrayAccessor},
        "count": {"generator": Count, "accessor": IntegerArrayAccessor},
    },
    commands={
        "inputlineno": InputLineNo(),
        "countdef": countdef,
    },
)
