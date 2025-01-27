"""
File operations
"""


from pytex import node as nd
from pytex.accessor import ValuePointer, Accessor
from pytex.lexer import TokenListScanner, StringScanner
from pytex import token
from pytex import macro
from pytex.module import Module


class OpenOp(ValuePointer):
    """
    Open a file
    @param file_array: the file array
    @param file_id: the file number to operate on
    @param filename: the file name
    """
    def __init__(self, file_array, file_id, filename, input: bool):
        FileOp.__init__(self, input=True, file_id=file_id)
        self.file_array = file_array
        self.filename = filename
        ValuePointer.__init__(self, file_array, file_id, eq=True)
    
    allow_global = False 

    def execute(self, parser):
        ValuePointer.execute(self, parser)


class OpenInOp(OpenOp):
    def readValue(self, parser):
        file = parser.resolver.openIn(self.filename, "source")
        if file is None:
            raise FileNotFoundError(self.filename)
        return file


class OpenOutOp(OpenOp):
    def readValue(self, parser):
        file = parser.resolver.openOut(self.filename, "source")
        if file is None:
            raise FileNotFoundError(self.filename)
        return file


class FileOp:
    """
    The base class of file operations
    @param input: whether the file is an input file
    @param file: the file number to operate on
    """
    def __init__(self, input: bool, file_id: int):
        self.files = "openin" if input else "openout"
        self.file_id = file_id

    def execute(self, parser):
        """
        Perform the operation
        """
        raise NotImplementedError("should be implemented in subclass")

    def file(self, parser):
        """
        Get the file object
        """
        return parser.state.globals[self.files][self.file_id]


class CloseOp(FileOp):
    """
    Close a file
    @param files: the file array
    @param file: the file number to operate on
    """
    def execute(self, parser):
        parser.state.globals[self.files][self.file_id].close()
        parser.state.globals[self.files][self.file_id] = None


class WriteOp(FileOp):
    """
    Write to a file
    @param file_array: the file array
    @param file_id: the file number to operate on
    """
    def __init__(self, file_id, tokens):
        FileOp.__init__(self, input=False, file_id=abs(file_id))
        self.print = file_id >= 0
        self.tokens = tokens
    
    def execute(self, parser):
        scanner = TokenListScanner(self.tokens)
        scanner.terminate = True
        parser.input.push(scanner)
        file = self.file(parser)
        s = ""
        while True:
            t = parser.token_expand()
            if t is None:
                break
            if isinstance(t, token.CommandToken):
                raise ValueError(f"Undefined control sequence {t.name}")
            elif isinstance(t, token.Command):
                if len(t.name) > 1:
                    s += chr(parser.state.layout["escapechar"])
                    s += t.name[1:]
                    continue
                s += t.name
            elif isinstance(t, token.CharToken):
                s += t.name
            else:
                raise ValueError(f"Unexpected token {t}")
        file.write(s)
        if self.print:
            print(s)


class ReadOp(FileOp, ValuePointer):
    """
    Read from a file
    @param file: the file number to operate on
    """
    def __init__(self, file_id, domain, command):
        FileOp.__init__(self, input=True, file_id=file_id)
        ValuePointer.__init__(self, domain, command, eq=False)

    def readValue(self, parser):
        tokens = []
        level = 0
        file = self.file(parser)
        while True:
            s = file.readline()
            scanner = StringScanner(parser.state.catcode, s)
            scanner.terminate = True
            parser.input.push(scanner)
            while True:
                pos = parser.input.position()
                t = parser.token()
                if t is None:
                    break
                if t.catcode == token.CATCODE.BEGIN_GROUP:
                    level += 1
                elif t.catcode == token.CATCODE.END_GROUP:
                    if level == 0:
                        return macro.Macro([], tokens)
                    level -= 1
                tokens.append(t)
    
    def execute(self, parser):
        return ValuePointer.execute(self, parser)

class FileOpNode(nd.WhatsIt):
    """
    A file operation.
    @param op: the operation to perform
    """
    def __init__(self, op):
        self.op = op

    def output(self, parser, device):
        self.op.execute(parser)
    

class FileCommand(token.Command):
    """
    The base class of file commands
    """
    def __init__(self, immediate):
        self.immediate = immediate
    
    def fileOp(self, parser, file_id):
        """
        Get the file operation
        """
        raise NotImplementedError("should be implemented in subclass")

    def execute(self, parser, immediate=False):
        file_id = parser.readInteger()
        op = self.fileOp(parser, file_id)
        if immediate or self.immediate:
            op.execute(parser)
        else:
            parser.lists[-1].append(FileOpNode(op))


class Open(FileCommand):
    """
    Open a file for reading
    """
    def __init__(self, input: bool):
        super().__init__(immediate=input)
        self.input = input

    def fileOp(self, parser, file_id):
        parser.skipEq()
        filename = parser.readFileName()
        if self.input:
            return OpenInOp(parser.state.globals["openin"], file_id, filename, input=True)  
        return OpenOutOp(parser.state.globals["openout"], file_id, filename, input=True)


class CloseIn(FileCommand):
    """
    \\closein
    """
    def fileOp(self, parser, file_id):
        return CloseOp(True, file_id)
    

class CloseOut(FileCommand):
    """
    \\closeout
    """
    def fileOp(self, parser, file_id):
        return CloseOp(False, file_id)


class Write(FileCommand):
    """
    \\write
    """
    def fileOp(self, parser, file_id):
        tokens = parser.readGeneralText(expand=False)
        return WriteOp(file_id, tokens)


class Read(FileCommand, Accessor):
    """
    \\read
    """
    def __init__(self):
        FileCommand.__init__(self, immediate=True)
        Accessor.__init__(self, "equitable", ReadOp, eq=True)

    def fileOp(self, parser, file_id):
        to = parser.readKeyword(["to"])
        if to is None:
            raise ValueError("Expected 'to' keyword")
        parser.skipSpaces(expand=False)
        t = parser.token()
        if not isinstance(t, token.CommandToken):
            raise ValueError(f"Expected a control sequence, got {t}")
        return ReadOp(file_id, parser.state.equitable, t.name)
    
    def pointer(self, parser):
        file_id = parser.readInteger()
        return self.fileOp(parser, file_id)




class Immediate(token.Command):
    """
    \\immediate
    """
    def execute(self, parser):
        t = parser.token_expand()
        if isinstance(t, FileCommand):
            t.execute(parser, immediate=True)
        else:
            raise ValueError(f"Expected a file operation, got {t}")


mod = Module("file",
    commands={
        "openin": Open(input=True),
        "openout": Open(input=False),
        "closein": CloseIn(immediate=True),
        "closeout": CloseOut(immediate=False),
        "write": Write(immediate=False),
        "read": Read(),
        "immediate": Immediate()
    },
    parameters={
        "openin": {"value": [None] * 16, "accessor": None, "domain": "globals"},
        "openout": {"value": [None] * 16, "accessor": None, "domain": "globals"},
    },
)
