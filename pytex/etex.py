"""
This module implements the e-TeX

Note that this module is not automatically loaded by the parser. 
Like the texlive module, users need to explicitly loading the module
by importing it.
"""

from pytex import token as tk
from pytex.module import Module
from pytex.lists import ModeDependentCommand
from pytex.integer import FixedInteger, IntegerArrayItemAccessor
from pytex.dimen import Dimen
from pytex.toks import The, ToksAccessor
from pytex import token
from pytex import expandable
from pytex import lexer
from pytex import conditional
from pytex import macro
from pytex import font
from pytex import accessor
from pytex import file


# e-TeX version
version = "2.6"


def newMarkRegister():
    return [[]]


class MarksValue(token.Command):
    """
    Expand to the mark text for a given class.
    """
    def __init__(self, key):
        self.key = key

    value_type = accessor.VALUE_TYPE.TOKS

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(self.value_type, requested_type):
            return None, None
        index = parser.readInteger()
        if index < 0:
            raise ValueError("mark class must be non-negative", parser.input.position())
        register = parser.globals[self.key]
        if index >= len(register):
            return [], self.value_type
        return register[index], self.value_type

    def expand(self, parser):
        toks, _ = self.fetchValue(parser, self.value_type)
        if toks:
            parser.input.pushTokenList(toks)


class Expr(ModeDependentCommand):
    """
    The \\numexpr etc commands
    """
    def readTermValue(self, parser):
        """
        Read a value from the input stack
        @param parser: the parser
        @return: the value

        Note that \\numexpr etc should implement this method
        """
        raise NotImplementedError("this method should be implemented by subclasses")
    
    def readOp(self, parser, allowed: str):
        """
        Read an operator from the input stack
        @param parser: the parser
        @param allowed: the allowed operators
        @return: the operator as a character
        """
        t = parser.skipSpaces()
        if t is not None:
            if t.catcode == tk.CATCODE.OTHER and t.name in allowed:
                return t.name
            parser.input.unread(t)
        return None
        
    def readExpr(self, parser, integer: bool = False):
        """
        Read an expression from the input stack
        @param parser: the parser
        @param integer: whether the expression should be an integer
        @return: the value of the expression
        """
        term = self.readTerm(parser, integer)
        while True:
            op = self.readOp(parser, "+-")
            if op is None:
                # skip spaces and an optional \relax
                t = parser.skipSpaces()
                if t is not None and t.definition != token.relax:
                    parser.input.unread(t)
                return term
            oprand = self.readTerm(parser, integer)
            if op == "+":
                term += oprand
            else:
                term -= oprand

    def divide(self, x, y):
        """
        Divide two numbers
        @param x: the dividend
        @param y: the divisor
        @return: the quotient

        \\numexpr should overload and return an integer
        """
        return x / y

    def readTerm(self, parser, integer: bool = False):
        """
        Read a term from the input stack
        @param parser: the parser
        @param integer: whether the term should be an integer
        @return: the value of the term
        """
        factor = self.readFactor(parser, integer)
        while True:
            op = self.readOp(parser, "*/")
            if op is None:
                return factor
            oprand = self.readFactor(parser, True)
            if op == "*":
                factor *= oprand
            else:
                factor = self.divide(factor, oprand)

    def readFactor(self, parser, integer: bool = False):
        """
        Read a factor from the input stack
        @param parser: the parser
        @param integer: whether the factor should be an integer
        @return: the value of the factor
        """
        left_paren = self.readOp(parser, "(")
        if left_paren is not None:
            value = self.readExpr(parser, integer)
            right_paren = self.readOp(parser, ")")
            if right_paren is None:
                raise ValueError("missing )", parser.input.position())
            return value
        if integer:
            return parser.readInteger()
        return self.readTermValue(parser)
    

class NumExpr(Expr):
    """
    The \\numexpr command
    """
    def readTermValue(self, parser):
        return parser.readInteger()
    
    def divide(self, x, y):
        d = int(abs(x) / abs(y) + 0.5)
        return -d if x < 0 < y or y < 0 < x else d

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        return self.readExpr(parser, False), accessor.VALUE_TYPE.INT
    

class DimExpr(Expr):
    """
    The \\dimexpr command
    """
    def readTermValue(self, parser):
        return parser.readDimen()

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.DIMEN, requested_type):
            return None, None
        return self.readExpr(parser, False), accessor.VALUE_TYPE.DIMEN


class GlueExpr(Expr):
    """
    The \\glueexpr command
    """
    def readTermValue(self, parser):
        return parser.readGlue()

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.GLUE, requested_type):
            return None, None
        return self.readExpr(parser, False), accessor.VALUE_TYPE.GLUE


class MuExpr(Expr):
    """
    The \\muexpr command
    """
    def readTermValue(self, parser):
        return parser.readGlue(mu=True)

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.MUGLUE, requested_type):
            return None, None
        return self.readExpr(parser, False), accessor.VALUE_TYPE.MUGLUE


class Marks(token.Command):
    """
    The \\marks command
    """
    def getIndex(self, parser):
        return parser.readInteger()

    def execute(self, parser):
        from pytex import vmode

        index = self.getIndex(parser)
        text = parser.readGeneralText(expand=True)
        node = vmode.Mark(text)
        node.index = index
        parser.lists[-1].append(node)


class Mark(Marks):
    """
    The \\mark command
    """
    def getIndex(self, parser):
        return 0


class StringCommand(token.Command):
    """
    A command that expands to a list of tokens in a string
    @param s the string to expand to
    """
    def __init__(self, s):
        self.toks = expandable.toToks(s)

    def expand(self, parser):
        parser.input.pushTokenList(self.toks)


class LastNodeType(tk.Command):
    """
    The \\lastnodetype command
    """
    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        top = parser.lists[-1]
        value = -1 if len(top) == 0 else top[-1].node_type
        return value, accessor.VALUE_TYPE.INT
    

class CurrentGroupType(tk.Command):
    """
    The \\currentgrouptype command
    """
    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        groups = parser.groups
        value = -1 if len(groups) == 0 else groups[-1].group_type
        return value, accessor.VALUE_TYPE.INT
    

class CurrentGroupLevel(tk.Command):
    """
    The \\currentgrouplevel command
    """
    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        return len(parser.groups), accessor.VALUE_TYPE.INT


class CurrentIfLevel(tk.Command):
    """
    The \\currentiflevel command
    """
    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        return len(parser.ifstack), accessor.VALUE_TYPE.INT
    

class CurrentIfType(tk.Command):
    """
    The \\currentiftype command
    """

    if_types = [
        "if", # 0
        "ifcat", 
        "ifnum", 
        "ifdim", 
        "ifodd", 
        "ifvmode", #5
        "ifhmode", 
        "ifmmode", 
        "ifinner", 
        "ifvoid", 
        "ifhbox", # 10
        "ifvbox",
        "ifx", 
        "ifeof", 
        "iftrue", #15 
        "iffalse", 
        "ifcase",
        "ifdefined",
        "ifcsname",
        "iffontchar", #20
    ]
    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        value = -1 if len(parser.ifstack) == 0 else self.if_types.index(parser.ifstack[-1][0].name[1:])
        return value, accessor.VALUE_TYPE.INT


class CurrentIfBranch(tk.Command):
    """
    The \\currentifbranch command
    """
    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        b = parser.ifstack[-1][2]
        return 1 if b == 0 else -1, accessor.VALUE_TYPE.INT
    

class GlueOrder(tk.Command):
    """
    The \\gluestretchorder and \\glueshrinkorder commands
    """
    def __init__(self, field):
        self.field = field

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        glue = parser.readGlue()
        return getattr(glue, self.field).order, accessor.VALUE_TYPE.INT


class Penalties(tk.Command):
    """
    the \\interlinepenalties etc commands
    """
    def __init__(self, penalties):
        self.penalties = penalties

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.INT, requested_type):
            return None, None
        index = parser.readInteger()
        if index < 0:
            return 0, accessor.VALUE_TYPE.INT
        penalties = parser.layout[self.penalties]
        value = len(penalties) if index == 0 else penalties[index - 1]
        return value, accessor.VALUE_TYPE.INT

    def execute(self, parser):
        # read a length n followed by n penalties
        n = parser.readInteger()
        penalties = []
        for i in range(n):
            penalties.append(parser.readInteger())
        parser.layout[self.penalties] = penalties


class ParShapeDimen(tk.Command):
    """
    The \\parshapeindent and \\parshapelength and \\parshapedimen commands
    @param index: the index of the parshape dimen for a specific line

    Note that if index < 0, it is \\parshapedimen
    """
    def __init__(self, index):
        self.index = index

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.DIMEN, requested_type):
            return None, None
        row = parser.readInteger()
        if row < 0:
            return Dimen(), accessor.VALUE_TYPE.DIMEN
        parshape = parser.volatile["parshape"]
        if self.index < 0:
            # \\parshapedimen
            index = row % 2
            row = row >> 1
        else:
            index = self.index
        if row >= len(parshape):
            row = len(parshape) - 1
        return parshape[row][index], accessor.VALUE_TYPE.DIMEN


class GlueStrechness(tk.Command):
    """
    The \\gluestretch and \\glueshrink command
    """
    def __init__(self, field):
        self.field = field

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.DIMEN, requested_type):
            return None, None
        glue = parser.readGlue()
        return Dimen(getattr(glue, self.field).factor), accessor.VALUE_TYPE.DIMEN
    

class FontCharDimen(tk.Command):
    """
    The \\fontcharwd, \\fontcharht, and \\fontchardp commands
    """
    def __init__(self, field):
        self.field = field

    def fetchValue(self, parser, requested_type):
        if not accessor.canReadAs(accessor.VALUE_TYPE.DIMEN, requested_type):
            return None, None
        f = font.readFont(parser)
        char = parser.readInteger()
        box = f[chr(char)]
        return getattr(box, self.field), accessor.VALUE_TYPE.DIMEN


class Middle(ModeDependentCommand):
    """
    The \\middle command
    """
    def math(self, parser, mlist):
        raise NotImplementedError()


class IfDefined(conditional.Conditional):
    """
    The \\ifdefined command
    """
    def condition(self, parser):
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token, but reached end of input", parser.input.position())
        return 0 if t.entry is None or t.definition is not None else 1


class IfFontChar(conditional.Conditional):
    """
    The \\iffontchar command
    """
    def condition(self, parser):
        f = font.readFont(parser)
        char = parser.readInteger()
        return 0 if f.hasCharCode(char) else 1


class IfCSName(conditional.Conditional):
    """
    The \\ifcsname command
    """
    def condition(self, parser):
        t = expandable.readCSName(parser)
        return 0 if t.entry.value is not None else 1


class UnlessConditional(conditional.Conditional):
    """
    The actual work of \\unless
    This is to prevent unless being treated s a conditional
    """
    def __init__(self, command):
        self.command = command
    
    def condition(self, parser):
        return 1 - self.command.condition(parser)


class Unless(token.Command):
    def expand(self, parser):
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token, but reached end of input", parser.input.position())
        c = t.definition
        if isinstance(c, conditional.Conditional) and not isinstance(c, conditional.IfCase):
            if parser.tracingcommands > 0:
                parser.trace(t, "expand")
            unless = UnlessConditional(c)
            unless.expand(parser)
            return
        raise ValueError(f"You cannot use \\unless in front of {t.name}", parser.input.position())

class Protected(accessor.Prefix):
    """
    The \\protected command
    """
    def modify(self, value, globally):
        value.protected = True
        return value, globally


class Detokenize(token.Command):
    """
    The \\detokenize command
    """
    def expand(self, parser):
        toks = parser.readGeneralText(expand=False)
        s = expandable.toksToString(parser, toks)
        parser.input.pushTokenList(expandable.toToks(s))


class _ScanTokensSource:
    """
    Minimal source object for a single-line \\scantokens tokenizer.
    """
    def end(self):
        pass


class ScanTokens(token.Command):
    """
    The \\scantokens command
    """
    def expand(self, parser):
        toks = parser.readGeneralText(expand=False)
        s = expandable.toksToString(parser, toks)
        eol = parser.endlinechar.value
        if 0 <= eol < 256:
            s += chr(eol)
        parser.input.push(lexer.Tokenizer(s, parser, _ScanTokensSource()))


class Unexpanded(The):
    """
    The \\unexpanded command
    """
    def expanded(self, parser):
        return parser.readGeneralText(expand=False)
    

class ReadlineOp(file.ReadOp):
    """
    Read a line from a file, and assignit as a parameterless macro
    """    
    def readAssignmentValue(self, parser):
        tokens = []
        level = 0
        file = parser.globals["openin"][self.file_id]
        if file is None or file.closed:
            raise FileNotFoundError(f"file {self.file_id} is not open")
        try:
            line = next(file)
        except StopIteration:
            file.close()
            line = ""
        endlinechar = parser.endlinechar.value
        if line and line[-1] == "\n":
            line = line[:-1]
        if 0 <= endlinechar <= 255:
            line = line + chr(endlinechar)
        toks = expandable.toToks(line)
        m = macro.Macro([], toks)
        m.name = self.key
        return m


class Readline(file.FileCommand):
    """
    The \\readline command
    """
    def __init__(self):
        super().__init__(immediate=True)

    def fileOp(self, parser, file_id):
        if file_id < 0 or file_id >= len(parser.globals["openin"]):
            raise ValueError(f"\\read does not support reading from console", parser.input.position())
        to = parser.readKeyword(["to"])
        if to is None:
            raise ValueError("Expected 'to' keyword")
        t = parser.skipSpacesNoExpand()
        if t.entry is None:
            raise ValueError(f"Expected a control sequence, got {t}")
        return ReadlineOp(parser.equitable, t.name, file_id)


mod = Module("etex",
    commands={
        "numexpr": NumExpr(),
        "dimexpr": DimExpr(),
        "glueexpr": GlueExpr(),
        "muexpr": MuExpr(),
        "marks": Marks(),
        "mark": Mark(),
        "eTeXversion": FixedInteger(int(version.split(".")[0])),
        "eTexrevision": StringCommand("."+".".join(version.split(".")[1:])),
        "lastnodetype": LastNodeType(),
        "currentgrouptype": CurrentGroupType(),
        "currentgrouplevel": CurrentGroupLevel(),
        "currentiflevel": CurrentIfLevel(),
        "currentiftype": CurrentIfType(),
        "currentifbranch": CurrentIfBranch(),
        "gluestretchorder": GlueOrder("stretch"),
        "glueshrinkorder": GlueOrder("shrink"),
        "interlinepenalties": Penalties("interlinepenalties"),
        "clubpenalties": Penalties("clubpenalties"),
        "widowpenalties": Penalties("widowpenalties"),
        "displaywidowpenalties": Penalties("displaywidowpenalties"),
        "parshapeindent": ParShapeDimen(0),
        "parshapelength": ParShapeDimen(1),
        "parshapedimen": ParShapeDimen(-1),
        "gluestretch": GlueStrechness("stretch"),
        "glueshrink": GlueStrechness("shrink"),
        "fontcharwd": FontCharDimen("width"),
        "fontcharht": FontCharDimen("height"),
        "fontchardp": FontCharDimen("depth"),
        "middle": Middle(),
        "topmarks": MarksValue("topmarks"),
        "firstmarks": MarksValue("firstmarks"),
        "botmarks": MarksValue("botmarks"),
        "splitfirstmarks": MarksValue("splitfirstmarks"),
        "splitbotmarks": MarksValue("splitbotmarks"),
        "ifdefined": IfDefined(),
        "iffontchar": IfFontChar(),
        "ifcsname": IfCSName(),
        "unless": Unless(),
        "protected": Protected(),
        "detokenize": Detokenize(),
        "scantokens": ScanTokens(),
        "unexpanded": Unexpanded(),
        "readline": Readline(),
    },
    parameters={
        "interactionmode": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "globals"},
        "TeXXeTstate": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "tracingassigns": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "tracinggroups": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "tracingifs": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "tracingscantokens": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "tracingnesting": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "predisplaydirection": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "lastlinefit": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "layout"},
        "savingvdiscards": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "savinghyphcodes": {"value": 0, "accessor": IntegerArrayItemAccessor, "domain": "parameters"},
        "everyeof": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
        "topmarks": {"value": newMarkRegister, "accessor": None, "domain": "globals"},
        "botmarks": {"value": newMarkRegister, "accessor": None, "domain": "globals"},
        "firstmarks": {"value": newMarkRegister, "accessor": None, "domain": "globals"},
        "splitfirstmarks": {"value": newMarkRegister, "accessor": None, "domain": "globals"},
        "splitbotmarks": {"value": newMarkRegister, "accessor": None, "domain": "globals"},
    },
)
