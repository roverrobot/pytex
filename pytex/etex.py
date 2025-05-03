"""
This module implements the e-TeX

Note that this module is not automatically loaded by the parser. 
Like the texlive module, users need to explicitly loading the module
by importing it.
"""

from pytex import token as tk
from pytex.module import Module
from pytex.lists import ModeDependentCommand
from pytex.integer import IntegerCommand, IntegerAccessor
from pytex.dimen import DimenCommand, Dimen
from pytex.glue import GlueCommand
from pytex.toks import ToksAccessor, The
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
        
    def getValue(self, parser):
        return self.readExpr(parser, False)
    

class NumExpr(Expr, IntegerCommand):
    """
    The \\numexpr command
    """
    def readValue(self, parser):
        return parser.readInteger()
    
    def divide(self, x, y):
        d = int(abs(x) / abs(y) + 0.5)
        return -d if x < 0 < y or y < 0 < x else d
    

class DimExpr(Expr, DimenCommand):
    """
    The \\dimexpr command
    """
    def readValue(self, parser):
        return parser.readDimen()


class GlueExpr(Expr, GlueCommand):
    """
    The \\glueexpr command
    """
    def readValue(self, parser):
        return parser.readGlue()


class MuExpr(Expr, GlueCommand):
    """
    The \\muexpr command
    """
    def readValue(self, parser):
        return parser.readGlue(mu=True)


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


class IntegerValuedCommand(token.Command, IntegerCommand):
    """
    An integer valued command
    """
    def execute(self, parser):
        raise ValueError(f"improper use of {self.name}")
    
    def getValue(self, parser):
        raise NotImplementedError("this method should be implemented by subclasses")
    

class ETeXVersion(IntegerValuedCommand):
    """
    The \\eTeXversion command
    """
    def getValue(self, parser):
        return int(version.split(".")[0])


class ETeXRevision:
    """
    The \\eTeXrevision command
    """
    def expand(self, parser):
        s = "."+".".join(version.split(".")[1:])
        toks = expandable.toToks(s)
        parser.input.push(lexer.TokenListScanner(toks))

class LastNodeType(IntegerValuedCommand):
    """
    The \\lastnodetype command
    """
    def getValue(self, parser):
        top = parser.lists[-1]
        if len(top) == 0:
            return -1
        return top[-1].node_type
    

class CurrentGroupType(IntegerValuedCommand):
    """
    The \\currentgrouptype command
    """
    def getValue(self, parser):
        groups = parser.state.groups
        if len(groups) == 0:
            return -1
        return groups[-1].group_type
    

class CurrentGroupLevel(IntegerValuedCommand):
    """
    The \\currentgrouplevel command
    """
    def getValue(self, parser):
        return len(parser.state.groups)


class CurrentIfLevel(IntegerValuedCommand):
    """
    The \\currentiflevel command
    """
    def getValue(self, parser):
        return len(parser.state.ifs)
    

class CurrentIfType(IntegerValuedCommand):
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
    def getValue(self, parser):
        if len(parser.state.ifs) == 0:
            return -1
        return self.if_types.index(parser.state.ifs[-1].name[1:])


class CurrentIfBranch(IntegerValuedCommand):
    """
    The \\currentifbranch command
    """
    def getValue(self, parser):
        raise NotImplementedError()
    

class GlueOrder(IntegerValuedCommand):
    """
    The \\gluestretchorder and \\glueshrinkorder commands
    """
    def __init__(self, field):
        self.field = field

    def saveInfo(self):
        return {"init": {"field": self.field}}

    def getValue(self, parser):
        glue = parser.readGlue()
        return getattr(glue, self.field).order


class Penalties(IntegerValuedCommand):
    """
    the \\interlinepenalties etc commands
    """
    def __init__(self, penalties):
        self.penalties = penalties
    
    def saveInfo(self):
        return {"init": {"penalties": self.penalties}}

    def getValue(self, parser):
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


class DimenValuedCommand(token.Command, DimenCommand):
    """
    A dimen valued command
    """
    def execute(self, parser):
        raise ValueError(f"improper use of {self.name}")
    
    def getValue(self, parser):
        raise NotImplementedError("this method should be implemented by subclasses")
    

class ParShapeDimen(DimenValuedCommand):
    """
    The \\parshapeindent and \\parshapelength and \\parshapedimen commands
    @param index: the index of the parshape dimen for a specific line

    Note that if index < 0, it is \\parshapedimen
    """
    def __init__(self, index):
        self.index = index

    def saveInfo(self):
        return {"init": {"index": self.index}}

    def getValue(self, parser):
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


class GlueStrechness(DimenValuedCommand):
    """
    The \\gluestretch and \\glueshrink command
    """
    def __init__(self, field):
        self.field = field

    def saveInfo(self):
        return {"init": {"field": self.field}}

    def getValue(self, parser):
        glue = parser.readGlue()
        return Dimen(getattr(glue, self.field).factor)
    

class FontCharDimen(DimenValuedCommand):
    """
    The \\fontcharwd, \\fontcharht, and \\fontchardp commands
    """
    def __init__(self, field):
        self.field = field

    def saveInfo(self):
        return {"init": {"field": self.field}}

    def getValue(self, parser):
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
        return 0 if t.definition is not None else 1


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
        endlinechar = parser.state.parameters["endlinechar"]
        if line and line[-1] == "\n":
            line = line[:-1]
        if 0 <= endlinechar <= 255:
            line = line + chr(endlinechar)
        toks = expandable.toToks(line)
        return macro.Macro([[]], toks)


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
        if not isinstance(t, token.CommandToken):
            raise ValueError(f"Expected a control sequence, got {t}")
        return ReadlineOp(t.name, file_id)


mod = Module("etex",
    commands={
        "numexpr": NumExpr(),
        "dimexpr": DimExpr(),
        "glueexpr": GlueExpr(),
        "muexpr": MuExpr(),
        "marks": Marks(),
        "mark": Mark(),
        "eTeXversion": ETeXVersion(),
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
        "interactionmode": {"value": 0, "accessor": IntegerAccessor, "domain": "globals"},
        "TeXXeTstate": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "tracingassigns": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "tracinggroups": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "tracingifs": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "tracingscantokens": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "tracingnesting": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "predisplaydirection": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "lastlinefit": {"value": 0, "accessor": IntegerAccessor, "domain": "layout"},
        "savingvdiscards": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "savinghyphcodes": {"value": 0, "accessor": IntegerAccessor, "domain": "parameters"},
        "everyeof": {"value": [], "accessor": ToksAccessor, "domain": "parameters"},
    },
)
