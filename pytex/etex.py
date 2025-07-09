"""
This module implements the e-TeX

Note that this module is not automatically loaded by the parser. 
Like the texlive module, users need to explicitly loading the module
by importing it.
"""

from pytex import token as tk
from pytex.module import Module
from pytex.lists import ModeDependentCommand
from pytex.integer import FixedInteger, IntegerParameterAccessor, IntegerArrayItemAccessor
from pytex.dimen import Dimen, DimenCommand
from pytex.glue import GlueCommand, MuGlueCommand
from pytex.toks import The, ToksParameterAccessor
from pytex import token
from pytex import node as nd
from pytex import expandable
from pytex import lexer
from pytex import conditional
from pytex import macro
from pytex import font
from pytex import accessor
from pytex import file


# e-TeX version
version = "2.6"


class Expr(ModeDependentCommand):
    """
    The \\numexpr etc commands
    """
    def readValue(self, parser):
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
        return self.readValue(parser)
    

class NumExpr(Expr):
    """
    The \\numexpr command
    """
    def readValue(self, parser):
        return parser.readInteger()
    
    def divide(self, x, y):
        d = int(abs(x) / abs(y) + 0.5)
        return -d if x < 0 < y or y < 0 < x else d
    
    def intValue(self, parser):
        """
        Get the integer value of the expression
        @param parser: the parser
        @return: the integer value of the expression
        """
        return self.readExpr(parser, False)
    

class DimExpr(Expr, DimenCommand):
    """
    The \\dimexpr command
    """
    def readValue(self, parser):
        return parser.readDimen()
    
    def dimenValue(self, parser):
        """
        Get the dimension value of the expression
        @param parser: the parser
        @return: the dimension value of the expression
        """
        return self.readExpr(parser, False)


class GlueExpr(Expr, GlueCommand):
    """
    The \\glueexpr command
    """
    def readValue(self, parser):
        return parser.readGlue()
    
    def glueValue(self, parser):
        """
        Get the glue value of the expression
        @param parser: the parser
        @return: the glue value of the expression
        """
        return self.readExpr(parser, False)


class MuExpr(Expr, MuGlueCommand):
    """
    The \\muexpr command
    """
    def readValue(self, parser):
        return parser.readGlue(mu=True)
    
    def muglueValue(self, parser):
        """
        Get the mu glue value of the expression
        @param parser: the parser
        @return: the mu glue value of the expression
        """
        return self.readExpr(parser, False)


class Marks(token.Command):
    """
    The \\marks command
    """
    def getIndex(self, parser):
        return parser.readInteger()

    def execute(self, parser):
        index = self.getIndex(parser)
        text = parser.readGeneralText(expand=True)
        node = nd.Mark(text)
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
        parser.input.push(lexer.TokenListScanner(self.toks))


class LastNodeType(tk.Command):
    """
    The \\lastnodetype command
    """
    def intValue(self, parser):
        top = parser.lists[-1]
        if len(top) == 0:
            return -1
        return top[-1].node_type
    

class CurrentGroupType(tk.Command):
    """
    The \\currentgrouptype command
    """
    def intValue(self, parser):
        groups = parser.state.groups
        if len(groups) == 0:
            return -1
        return groups[-1].group_type
    

class CurrentGroupLevel(tk.Command):
    """
    The \\currentgrouplevel command
    """
    def intValue(self, parser):
        return len(parser.state.groups)


class CurrentIfLevel(tk.Command):
    """
    The \\currentiflevel command
    """
    def intValue(self, parser):
        return len(parser.state.ifs)
    

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
    def intValue(self, parser):
        if len(parser.state.ifs) == 0:
            return -1
        return self.if_types.index(parser.state.ifs[-1].name[1:])


class CurrentIfBranch(tk.Command):
    """
    The \\currentifbranch command
    """
    def intValue(self, parser):
        b = parser.ifstack[-1][2]
        return 1 if b == 0 else -1
    

class GlueOrder(tk.Command):
    """
    The \\gluestretchorder and \\glueshrinkorder commands
    """
    def __init__(self, field):
        self.field = field

    def intValue(self, parser):
        glue = parser.readGlue()
        return getattr(glue, self.field).order


class Penalties(tk.Command):
    """
    the \\interlinepenalties etc commands
    """
    def __init__(self, penalties):
        self.penalties = penalties

    def intValue(self, parser):
        index = parser.readInteger()
        if index < 0:
            return 0
        penalties = parser.state.layout[self.penalties]
        if index == 0:
            return len(penalties)
        return penalties[index - 1]

    def execute(self, parser):
        # read a length n followed by n penalties
        n = parser.readInteger()
        penalties = []
        for i in range(n):
            penalties.append(parser.readInteger())
        parser.state.layout[self.penalties] = penalties


class ParShapeDimen(tk.Command, DimenCommand):
    """
    The \\parshapeindent and \\parshapelength and \\parshapedimen commands
    @param index: the index of the parshape dimen for a specific line

    Note that if index < 0, it is \\parshapedimen
    """
    def __init__(self, index):
        self.index = index

    def dimenValue(self, parser):
        row = parser.readInteger()
        if row < 0:
            return Dimen()
        parshape = parser.state.layout["parshape"]
        if self.index < 0:
            # \\parshapedimen
            index = row % 2
            row = row >> 1
        else:
            index = self.index
        if row >= len(parshape):
            row = len(parshape) - 1
        return parshape[row][index]


class GlueStrechness(tk.Command, DimenCommand):
    """
    The \\gluestretch and \\glueshrink command
    """
    def __init__(self, field):
        self.field = field

    def dimenValue(self, parser):
        glue = parser.readGlue()
        return Dimen(getattr(glue, self.field).factor)
    

class FontCharDimen(tk.Command, DimenCommand):
    """
    The \\fontcharwd, \\fontcharht, and \\fontchardp commands
    """
    def __init__(self, field):
        self.field = field

    def dimenValue(self, parser):
        f = font.readFont(parser)
        char = parser.readInteger()
        box = f[chr(char)]
        return getattr(box, self.field)


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
        return 0 if t.is_command and t.definition is not None else 1


class IfFontChar(conditional.Conditional):
    """
    The \\iffontchar command
    """
    def condition(self, parser):
        f = font.readFont(parser)
        char = parser.readInteger()
        return 0 if f.bc <= char <= f.ec else 1


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
        if t.is_command:
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
        parser.input.push(lexer.TokenListScanner(expandable.toToks(s)))


class ScanTokens(token.Command):
    """
    The \\scantokens command
    """
    def expand(self, parser):
        toks = parser.readGeneralText(expand=False)
        s = expandable.toksToString(parser, toks)
        parser.input.push(lexer.StringScanner((s, " ")))


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
    def readValue(self, parser):
        tokens = []
        level = 0
        file = parser.state.globals["openin"][self.file_id]
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
        m = macro.Macro([[]], toks)
        m.name = self.entry.name
        return m


class Readline(file.FileCommand):
    """
    The \\readline command
    """
    def __init__(self):
        super().__init__(immediate=True)

    def fileOp(self, parser, file_id):
        if file_id < 0 or file_id >= len(parser.state.globals["openin"]):
            raise ValueError(f"\\read does not support reading from console", parser.input.position())
        to = parser.readKeyword(["to"])
        if to is None:
            raise ValueError("Expected 'to' keyword")
        t = parser.skipSpaces(expand=False)
        if not t.is_command:
            raise ValueError(f"Expected a control sequence, got {t}")
        return ReadlineOp(t.entry, file_id)


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
        "TeXXeTstate": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "tracingassigns": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracinggroups": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingifs": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingscantokens": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "tracingnesting": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "predisplaydirection": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "lastlinefit": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "layout"},
        "savingvdiscards": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "savinghyphcodes": {"value": 0, "accessor": IntegerParameterAccessor, "domain": "parameters"},
        "everyeof": {"value": [], "accessor": ToksParameterAccessor, "domain": "parameters"},
    },
)
