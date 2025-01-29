"""
This module handles reading and processing integers.
"""


import typing
from pytex.token import Token, CATCODE
from pytex.module import Module
from pytex.state import Array
from pytex.accessor import ValuePointer, ParameterAccessor, GlobalParameterAccessor, ArrayAccessor


def readSigns(parser):
    """
    Read ooptional signs
    @param parser: the parser
    @return: 1 or -1
    """
    sign = 1
    pos = parser.input.position()
    # skips spaces
    while True:
        parser.skipSpaces()
        t = parser.token_expand()
        if t is None:
            break
        if t.catcode != CATCODE.OTHER:
            parser.input.unread(t)
            break
        if t.name == "-":
            sign = -sign
        elif t.name != "+":
            parser.input.unread(t)
            break
    parser.skipSpaces()
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
    pos = parser.input.position()
    t = parser.token_expand()
    if t is None:
        raise ValueError("expecting an integer", pos)
    try:
        return t.intValue(parser)
    except AttributeError:
        pass
    # a normal integer is either a ` followed by a character, or a ' followed by
    # an octant number, or a " followed by a hex number, or a number
    if t.catcode != CATCODE.OTHER:
        raise ValueError("expecting an integer", pos)
    if t.name == "`":
        t = parser.token()
        if t.is_command:
            if t.name[0] == "\\" and len(t.name) == 2:
                value = ord(t.name[1])
            elif len(t.name) == 1:
                value =  ord(t.name)
            else:
                raise ValueError("expecting a character", pos)
        else:
            value = ord(t.name)
    elif t.name == "'":
        value = int(readDigits(parser, 8), 8)
    elif t.name == '"':
        value = int(readDigits(parser, 16), 16)
    else:
        parser.input.unread(t)
        value = int(readDigits(parser, 10), 10)
    # read the optional space
    t = parser.token_expand()
    if t is not None and t.catcode != CATCODE.SPACE:
        parser.input.unread(t)
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
    pos = parser.input.position()
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
        raise ValueError("expecting a number", pos)
    return value


class IntegerValueAccessor:
    def intValue(self, parser):
        """
        get the integer value of the parameter
        @param parser: the parser
        """
        return self.getValue(parser)


class IntegerValuePointer(ValuePointer, IntegerValueAccessor):
    """
    integer accessor common functions
    """
    def readValue(self, parser):
        return parser.readInteger()


class IntegerCommand(IntegerValueAccessor):
    """
    accessing the pointer integer command
    """
    def __init__(self, min, max, accessor):
        self.range = None if min is None and max is None else (min, max)
        self.accessor = accessor


    def pointer(self, parser):
        """
        get the pointer to the item
        @param parser: the parser
        """
        p = self.accessor.pointer(self, parser)
        p.range = self.range
        return p


    def getValue(self, parser):
        """
        get the integer value
        @param parser: the parser
        """
        return self.pointer(parser).getValue(parser)


class IntegerArrayAccessor(IntegerCommand, ArrayAccessor):
    """
    integer array accessor
    @param domain: the domain
    @param min: the minimum value
    @param max: the maximum value
    """
    def __init__(self, domain, min=None, max=None):
        IntegerCommand.__init__(self, min, max, ArrayAccessor)
        ArrayAccessor.__init__(self, domain, IntegerValuePointer)


class IntegerParameterAccessor(IntegerCommand, ParameterAccessor):
    """
    integer parameter accessor
    """
    def __init__(self, domain, name, min=None, max=None):
        IntegerCommand.__init__(self, min, max, ParameterAccessor)
        ParameterAccessor.__init__(self, domain, name, IntegerValuePointer)


class GlobalIntegerParameterAccessor(IntegerCommand, GlobalParameterAccessor):
    """
    global integer parameter accessor
    """
    def __init__(self, domain, name, min=None, max=None):
        IntegerCommand.__init__(self, min, max, GlobalParameterAccessor)
        GlobalParameterAccessor.__init__(self, domain, name, IntegerValuePointer)


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
        self[ord("{")] = CATCODE.BEGIN_GROUP
        self[ord("}")] = CATCODE.END_GROUP
        self[ord("\r")] = CATCODE.END_OF_LINE
        self[ord(" ")] = CATCODE.SPACE
        self[ord("\t")] = CATCODE.SPACE
        self[ord("^")] = CATCODE.SUPERSCRIPT
        self[ord("_")] = CATCODE.SUBSCRIPT
        self[ord("$")] = CATCODE.MATH_SHIFT
        self[ord("#")] = CATCODE.PARAMETER
        self[ord("&")] = CATCODE.ALIGNMENT_TAB
        self[ord("%")] = CATCODE.COMMENT
        self[ord("@")] = CATCODE.ACTIVE
        self[8] = CATCODE.INVALID


class CatCodeArrayAccessor(IntegerArrayAccessor):
    def __init__(self, domain):
        super().__init__(domain, 0, CATCODE.INVALID)


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
        "language": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "uchyph": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "lefthyphenmin": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "righthyphenmin": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "defaulthyphenchar": {"value": ord("-"), "accessor": IntegerParameterAccessor, "domain": "layout"},
        "defaultskewchar": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "hangafter": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "mag": {"value": 1000, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "delimiterfactor": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        # escapechar is a layout parameter because \write may use it
        "escapechar": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        # control parameters
        "fam": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "pausing": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "holdinginserts": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingonline": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingmacros": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingstats": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingparagraphs": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingpages": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingoutput": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracinglostchars": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingcommands": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingrestores": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "globaldefs": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "endlinechar": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "newlinechar": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "maxdeadcycles": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "time": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "day": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "month": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "year": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "showboxbreadth": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "showboxdepth": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "errorcontextlines": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        # global parameters
        "spacefactor": {"value": 1000, "accessor": GlobalIntegerParameterAccessor, "domain": "globals"},
        "prevgraf": {"value": 0, "accessor": GlobalIntegerParameterAccessor, "domain": "globals"},
        "deadcycles": {"value": 0, "accessor": GlobalIntegerParameterAccessor, "domain": "globals"},
        "insertpenalties": {"value": 0, "accessor": GlobalIntegerParameterAccessor, "domain": "globals"},
    },
    domains={
        "catcode": {"generator": CatCode, "accessor": CatCodeArrayAccessor},
        "lccode": {"generator": LCCode, "accessor": IntegerArrayAccessor},
        "uccode": {"generator": UCCode, "accessor": IntegerArrayAccessor},
        "sfcode": {"generator": SFCode, "accessor": IntegerArrayAccessor},
        "mathcode": {"generator": MathCode, "accessor": IntegerArrayAccessor},
        "count": {"generator": lambda: Array(0), "accessor": IntegerArrayAccessor},
    }
)
