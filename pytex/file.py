"""
File operations
"""

from pytex import serialization
from pytex import node as nd
from pytex.accessor import Accessor
from pytex.lexer import TokenListScanner, StringScanner, Tokenizer
from pytex import token
from pytex import macro
from pytex.module import Module
from pytex import conditional
from pytex import toks


class EndFileScanToken(token.Token):
    """
    Internal token that terminates a temporary file-token scan.
    """

    def __init__(self):
        super().__init__("\\endfilescan", None)

    def execute(self, parser):
        raise RuntimeError("unexpected file scan terminator")


class EndFileScanScanner(TokenListScanner):
    def __init__(self):
        super().__init__([EndFileScanToken()])


class _LocalFileLineScanner:
    """
    Minimal scanner stub used by local line tokenizers for \\read.
    """
    def end(self):
        pass


def _readFileLineTokenizer(parser, file):
    """
    Build a local Tokenizer for the next physical input line.

    This mirrors Scanner.feed() enough for \\read, but avoids pushing a
    temporary StringScanner through parser.input for every line.
    """
    line = next(file, None)
    if line is None:
        return None
    line_number = getattr(file, "_pytex_line_number", 0)
    file._pytex_line_number = line_number + 1
    if line.endswith("\n"):
        line = line[:-1]
    eol = parser.endlinechar.value
    if 0 <= eol < 256:
        line += chr(eol)
    name = getattr(file, "name", None)
    return Tokenizer(line, parser, _LocalFileLineScanner(), name, line_number)


def pushFileScan(parser, scanner):
    """
    Push a temporary scanner that should stop before resuming the normal input stack.
    """
    parser.input.push(EndFileScanScanner())
    parser.input.push(scanner)


def popFileScan(parser):
    """
    Pop a temporary file scan, including any active line tokenizer layer.
    """
    while parser.input.top is not None:
        top = parser.input.top
        parser.input.pop()
        if isinstance(top, EndFileScanScanner):
            break


class OpenOp(Accessor):
    """
    Open a file
    @param file_array: the file array
    @param file_id: the file number to operate on
    @param filename: the file name
    """
    def __init__(self, array, file_id, filename):
        super().__init__(array, file_id, builtin=False)
        self.filename = filename

    @classmethod
    def new(cls, parser, **kargs):
        files = parser.globals["openin" if kargs["input"] else "openout"]
        return cls(files, kargs["file_id"], kargs["filename"])

    def readEq(self, parser):
        # the = sign has been read in the command itself.
        pass

    def saveInfo(self):
        return {"input": isinstance(self, OpenInOp), "file_id": self.key, "filename": self.filename}, None

    
class OpenInOp(OpenOp):
    def readValue(self, parser):
        return parser.resolver.openIn(self.filename, "source")


class OpenOutOp(OpenOp):
    def readValue(self, parser):
        return parser.resolver.openOut(self.filename, "source")


class FileOp(serialization.Serializable):
    """
    The base class of file operations
    @param input: whether the file is an input file
    @param file: the file number to operate on
    """
    def __init__(self, input: bool, file_id: int):
        self.files = "openin" if input else "openout"
        self.file_id = file_id

    def saveInfo(self):
        return {"input": self.files == "openin", "file_id": self.file_id}, None
    
    def execute(self, parser):
        """
        Perform the operation
        """
        raise NotImplementedError("should be implemented in subclass")

    def file(self, parser):
        """
        Get the file object
        """
        files = parser.globals[self.files]
        return files[self.file_id] if 0 < self.file_id < len(files) else None


class CloseOp(FileOp):
    """
    Close a file
    @param files: the file array
    @param file: the file number to operate on
    """
    def execute(self, parser):
        files = parser.globals[self.files]
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
    
    def saveInfo(self):
        return {"file_id": self.file_id, "tokens": self.tokens}, None
    
    def execute(self, parser):
        pushFileScan(parser, TokenListScanner(self.tokens))
        file = self.file(parser)
        expander = toks.ExpandBuilder(parser)
        while True:
            t = parser.token()
            if isinstance(t, EndFileScanToken):
                popFileScan(parser)
                break
            expander.append(t)
        s = parser.expandedToksToString(expander.toks)
        if file is None:
            print(s, file=parser.log)
            if self.file_id >= 0:
                print(s, file=parser.console)
        else:
            print(s, file=file)
        


class ReadOp(Accessor):
    """
    Read from a file
    @param file: the file number to operate on
    """
    def __init__(self, domain, index, file_id: int):
        super().__init__(domain, index, builtin=False)
        self.file_id = file_id
    
    # an immediate operation like read should not be serialized
    def saveInfo(self):
        raise NotImplementedError("should not be serialized")

    def readEq(self, parser):
        pass

    def readValue(self, parser):
        tokens = []
        level = 0
        file = parser.globals["openin"][self.file_id]
        if file is None or file.closed:
            raise FileNotFoundError(f"file {self.file_id} is not open")
        done = False
        reached_eof = False
        while True:
            tokenizer = _readFileLineTokenizer(parser, file)
            if tokenizer is None:
                reached_eof = True
                break
            while True:
                t = tokenizer.read()
                if t is None:
                    done = level == 0
                    break
                if t.catcode == token.CATCODE.BEGIN_GROUP:
                    level += 1
                elif t.catcode == token.CATCODE.END_GROUP:
                    if level == 0:
                        done = True
                        break
                    level -= 1
                tokens.append(t)
            if done:
                break
        if level > 0:
            raise ValueError(f"unbalanced curly braces in file id {self.file_id}", parser.input.position())
        # The file reached eof. We close the file.
        if reached_eof and not done:
            file.close()
            parser.globals["openin"][self.file_id] = None
        m = macro.Macro([], tokens)
        m.name = self.key
        return m


class FileOpNode(nd.WhatsIt):
    """
    A file operation.
    @param op: the operation to perform
    """
    def __init__(self, op):
        self.op = op

    def saveInfo(self):
        return {"op": self.op}, None

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
        if file_id < 0 or file_id >= 16:
            raise ValueError(f"file number out of range: {file_id}", parser.input.position())
        parser.skipEq()
        filename = parser.readFileName()
        if self.input:
            return OpenInOp(parser.globals["openin"], file_id, filename)
        return OpenOutOp(parser.globals["openout"], file_id, filename)


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
        if file_id < 0 or file_id >= len(parser.globals["openin"]):
            raise ValueError(f"\\read does not support reading from console", parser.input.position())
        to = parser.readKeyword(["to"])
        if to is None:
            raise ValueError("Expected 'to' keyword")
        t = parser.skipSpacesNoExpand()
        if t.entry is None:
            raise ValueError(f"Expected a control sequence, got {t}")
        return ReadOp(parser.equitable, t.name, file_id)
    

class Immediate(token.Command):
    """
    \\immediate
    """
    def execute(self, parser):
        t = parser.token_expand().definition
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
        parser.message(s)

    def execute(self, parser):
        tokens = parser.readGeneralText(expand=True)
        self.write(parser, parser.expandedToksToString(tokens))
        if self.error:
            help = parser.parameters["errhelp"]
            if len(help) > 0:
                self.write(parser, parser.expandedToksToString(help))


class IfEof(conditional.Conditional):
    """
    \\ifeof
    """
    def condition(self, parser):
        file_id = parser.readInteger()
        files = parser.globals["openin"]
        file = files[file_id] if 0 <= file_id < len(files) else None
        # in python, it is not quite obvious how to check a file for EOF
        return 0 if (file is None) or file.closed else 1
    

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
        "ifeof": IfEof(),
    },
    parameters={
        "openin": {"value": [None] * 16, "accessor": None, "domain": "globals"},
        "openout": {"value": [None] * 16, "accessor": None, "domain": "globals"},
    },
)
