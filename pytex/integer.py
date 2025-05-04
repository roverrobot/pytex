"""
This module handles reading and processing integers.
"""


import typing
from pytex.token import CATCODE, Command
from pytex.module import Module
from pytex.state import Array
from pytex.accessor import Accessor, ArrayAccessor


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


class IntegerCommand:
    """
    an integer command
    """
    def readValue(self, parser):
        value = parser.readInteger()
        if self.range is not None:
            min, max = self.range
            if (min is not None and value < min) or (max is not None and value > max):
                if min is None:
                    range = f"at least {max}"
                elif max is None:
                    range = f"at most {min}"
                else:
                    range = f"between {min} and {max}"
                raise ValueError(f"value out of range: {value} must be {range}")
        return value

    def intValue(self, parser):
        return self.getValue(parser)


class IntegerAccessor(IntegerCommand, Accessor):
    """
    integer accessor common functions
    """
    def __init__(self, domain, index, range=None):
        super().__init__(domain, index)
        self.range = range

    def saveInfo(self):
        init = super().saveInfo()
        if self.range is not None:
            init["range"] = self.range
        return init
    
    def checkRange(self, value, pos):
        """
        check if the value is in the range
        @param value the value to check
        @param pos the current position in input
        """
        range = self.range
        if range is not None:
            if (range[0] is not None and value < range[0]) or \
                (range[0] is not None and value > range[1]):
                raise ValueError(f"value {value} is not in the range {self.range}", pos)

    def setValue(self, parser, value, globally):
        if self.range is not None:
            self.checkRange(value, parser.input.position())
        super().setValue(parser, value, globally)


class IntegerArrayAccessor(IntegerCommand, ArrayAccessor):
    """
    integer array accessor
    """
    def __init__(self, domain, range=None):
        super().__init__(domain)
        self.range = range

    def saveInfo(self):
        return super().saveInfo() | {"init": {"domain": self.domain, "range": self.range}}

    def newItemAccessor(self, index):
        return IntegerAccessor(self.domain, index, self.range)


class CatCode(Array):
    """
    The category code array \\catcode
    """
    def __init__(self, size: typing.Optional[int]=None):
        super().__init__(CATCODE.OTHER, size)
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = CATCODE.LETTER
            self[c + 32] = CATCODE.LETTER
        self[ord("\\")] = CATCODE.ESCAPE
        self[ord("\r")] = CATCODE.END_OF_LINE
        self[ord(" ")] = CATCODE.SPACE
        self[ord("%")] = CATCODE.COMMENT
        self[8] = CATCODE.INVALID


class CatCodeArrayAccessor(IntegerArrayAccessor):
    def __init__(self, domain="catcode"):
        super().__init__(domain, range=(0, 15))

    def saveInfo(self):
        return {"init": {"domain": "catcode"}}


class LCCode(Array):
    """
    The lowercase code array \\lccode
    """
    def __init__(self, size: typing.Optional[int]=None):
        super().__init__(0, size)
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = c + 32
            self[c+32] = c + 32


class UCCode(Array):
    """
    The uppercase code array \\uccode
    """
    def __init__(self, size: typing.Optional[int]=None):
        super().__init__(0, size)
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = c
            self[c+32] = c


class SFCode(Array):
    """
    The space factor code array \\sfcode
    """
    
    def __init__(self, size: typing.Optional[int]=None):
        super().__init__(1000, size)
        # When INITEX creates a brand new TEX, all characters have a space factor code of 1000, 
        # except that the uppercase letters ‘A’ through ‘Z’ have code 999. 
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = 999
        

class MathCode(Array):
    """
    The math code array \\mathcode
    """
    def __init__(self, size: typing.Optional[int]=None):
        super().__init__(0, size)
        # \mathcode x = x for all characters x that are neither letters nor digits. The ten digits
        # have \mathcode x = x+ ̋7000; the 52 letters have \mathcode x = x+ ̋7100.
        for c in range(self.SIZE):
            self[c] = c
        for c in range(ord("A"), ord("Z") + 1):
            self[c] = c + 0x7100
            self[c + 32] = c + 0x7120
        for c in range(ord("0"), ord("9") + 1):
            self[c] = c + 0x7000


class ReadOnlyInteger(Command, IntegerCommand):
    """
    The base class that returns an integer
    """
    def execute(self, parser):
        raise ValueError(f"improper use of {self.name}")


class FixedInteger(ReadOnlyInteger):
    """
    A command returns a read-only integer
    @param value the integer value
    """
    def __init__(self, value):
        self.value = value

    def saveInfo(self):
        return {"init": {"value": self.value}}
    
    def getValue(self, parser):
        return self.value


class InputLineNo(ReadOnlyInteger):
    """
    \inputlineno, which returns the current line number in the soruce file
    """
    def getValue(self, parser):
        # the line number is the current line number
        pos = parser.input.position()
        return pos.line


module = Module("integer", 
    attributes={"readInteger": readInteger},
    parameters={
        # integer parameters
        "pretolerance": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "tolerance": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "hbadness": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "vbadness": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "linepenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "hyphenpenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "exhyphenpenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "binoppenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "relpenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "clubpenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "widowpenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "displaywidowpenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "brokenpenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "predisplaypenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "postdisplaypenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "interlinepenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "floatingpenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "outputpenalty": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "doublehyphendemerits": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "finalhyphendemerits": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "adjdemerits": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "looseness": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "uchyph": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "lefthyphenmin": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "righthyphenmin": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "hangafter": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "mag": {"value": 1000, "accessor": IntegerAccessor, "domain": "layout"},
        "delimiterfactor": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        # escapechar is a layout parameter because \write may use it
        "escapechar": {"value": ord("\\"), "accessor": IntegerAccessor, "domain": "layout"},
        # control parameters
        "fam": {"value": -1, "accessor": IntegerAccessor, "domain": "parameters"},
        "pausing": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "holdinginserts": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "language": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "globaldefs": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "endlinechar": {"value": ord("\r"), "accessor": IntegerAccessor, "domain": "parameters"},
        "newlinechar": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "maxdeadcycles": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "showboxbreadth": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "showboxdepth": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "errorcontextlines": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "defaulthyphenchar": {"value": ord("-"), "accessor": IntegerAccessor, "domain": "parameters"},
        "defaultskewchar": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        # volatile parameters
        "time": {"value": 0, "accessor": IntegerAccessor, "domain": "volatile"},
        "day": {"value": 0, "accessor": IntegerAccessor, "domain": "volatile"},
        "month": {"value": 0, "accessor": IntegerAccessor, "domain": "volatile"},
        "year": {"value": 0, "accessor": IntegerAccessor, "domain": "volatile"},
        # global parameters
        "spacefactor": {"value": 1000, "accessor": IntegerAccessor, "domain": "globals"},
        "prevgraf": {"value": 0, "accessor": IntegerAccessor, "domain": "globals"},
        "deadcycles": {"value": 0, "accessor": IntegerAccessor, "domain": "globals"},
        "insertpenalties": {"value": 0, "accessor": IntegerAccessor, "domain": "globals"},
    },
    domains={
        "catcode": {"generator": CatCode, "accessor": CatCodeArrayAccessor},
        "lccode": {"generator": LCCode, "accessor": IntegerArrayAccessor},
        "uccode": {"generator": UCCode, "accessor": IntegerArrayAccessor},
        "sfcode": {"generator": SFCode, "accessor": IntegerArrayAccessor},
        "delcode": {"generator": lambda: Array(-1), "accessor": IntegerArrayAccessor},
        "mathcode": {"generator": MathCode, "accessor": IntegerArrayAccessor},
        "count": {"generator": lambda: Array(0), "accessor": IntegerArrayAccessor},
    },
    commands={
        "inputlineno": InputLineNo(),
    },
)
