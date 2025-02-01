"""
File operations
"""


from pytex import node as nd
from pytex.accessor import Accessor, ArrayAccessor
from pytex.lexer import TokenListScanner, StringScanner
from pytex import token
from pytex import macro
from pytex.module import Module
from pytex.expandable import toksToString


class OpenOp(Accessor):
    """
    Open a file
    @param file_array: the file array
    @param file_id: the file number to operate on
    @param filename: the file name
    """
    def __init__(self, input: bool, file_id, filename):
        super().__init__(None, file_id, eq=True, allow_global=False)
        if file_id < 0 or file_id >= 16:
            raise ValueError("file number out of range: {file_id}")
        self.file_array = "openin" if input else "openout"
        self.filename = filename

    def setValue(self, parser, value, prefixes):
        parser.state.globals[self.file_array][self.index] = value

    
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
        files = parser.state.globals[self.files]
        return files[self.file_id] if 0 < self.file_id < len(files) else None


class CloseOp(FileOp):
    """
    Close a file
    @param files: the file array
    @param file: the file number to operate on
    """
    def execute(self, parser):
        files = parser.state.globals[self.files]
        if 0 <= self.file_id < len(files) and files[self.file_id] is not None:
            files[self.file_id].close()
            files[self.file_id] = None


class WriteOp(FileOp):
    """
    Write to a file
    @param file_array: the file array
    @param file_id: the file number to operate on
    """
    def __init__(self, file_id, tokens):
        FileOp.__init__(self, input=False, file_id=file_id)
        self.tokens = tokens
    
    def execute(self, parser):
        scanner = TokenListScanner(self.tokens)
        scanner.terminate = True
        parser.input.push(scanner)
        file = self.file(parser)
        tokens = []
        while True:
            t = parser.token_expand()
            if t is None:
                break
            tokens.append(t)
        s = toksToString(parser, tokens)
        print(s, file=file)


class ReadOp(Accessor):
    """
    Read from a file
    @param file: the file number to operate on
    """
    def __init__(self, command):
        super().__init__("equitable", command, eq=False)

    def readEq(self, parser):
        parser.readKeyword(["to"])

    def readValue(self, parser):
        tokens = []
        level = 0
        file = self.file
        if file is None:
            raise FileNotFoundError(f"file {self.index} is not open")
        for s in file:
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
        raise ValueError("unblanced curly braces")


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
            return OpenInOp(True, file_id, filename)  
        return OpenOutOp(False, file_id, filename)


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


class Read(FileCommand):
    """
    \\read
    """
    def __init__(self):
        FileCommand.__init__(self, immediate=True)

    def fileOp(self, parser, file_id):
        to = parser.readKeyword(["to"])
        if to is None:
            raise ValueError("Expected 'to' keyword")
        parser.skipSpaces(expand=False)
        t = parser.token()
        if not isinstance(t, token.CommandToken):
            raise ValueError(f"Expected a control sequence, got {t}")
        op = ReadOp(t.name)
        op.file = parser.state.globals["openin"][file_id]
        return op
    

class Immediate(token.Command):
    """
    \\immediate
    """
    def execute(self, parser):
        t = parser.token_expand().meaning
        if isinstance(t, FileCommand):
            t.execute(parser, immediate=True)
        else:
            raise ValueError(f"Expected a file operation")


class Message(token.Command):
    """
    \\message
    """
    def __init__(self, error: bool):
        self.error = error
    
    def write(self, parser, s):
        parser.log.write(s)
        print(s)

    def execute(self, parser):
        tokens = parser.readGeneralText(expand=True)
        self.write(parser, toksToString(parser, tokens))
        if self.error:
            help = parser.state.parameters["errhelp"]
            if len(help) > 0:
                self.write(parser, toksToString(parser, help))


mod = Module("file",
    commands={
        "openin": Open(input=True),
        "openout": Open(input=False),
        "closein": CloseIn(immediate=True),
        "closeout": CloseOut(immediate=False),
        "write": Write(immediate=False),
        "read": Read(),
        "immediate": Immediate(),
        "message": Message(error=False),
        "errmessage": Message(error=True),
    },
    parameters={
        "openin": {"value": [None] * 16, "accessor": None, "domain": "globals"},
        "openout": {"value": [None] * 16, "accessor": None, "domain": "globals"},
    },
)
