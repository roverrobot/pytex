"""
This module implements file name handling

The basic idea is to provide a generic interface to find files by their name.
"""


from pytex.token import CATCODE
from pytex.module import Module
from io import StringIO
from types import MethodType
import os


class InMemoryTextFile:
    """
    An in memory text file
    """
    def __init__(self, content: str=""):
        self.content = content
        # currently opened readers
        self.readers = []
        # currently opened writer
        self.writer = None

    def open(self, for_read: bool=True):
        """
        Open the content as a file

        The file is opened in text mode. Multiple readers may coexist. But if it is opened
        for writing, then no writer or readers are allowed.
        @param for_read: whether the file is opened for reading
        """
        if for_read and self.writer is not None:
            raise ValueError("file already opened for writing")
        if not for_read and (self.readers or self.writer):
            raise ValueError("file already opened for reading")
        s = StringIO(self.content)
        def close(f):
            self.content = f.getvalue()
            if f in self.readers:
                self.readers.remove(f)
        s.close = MethodType(close, s)
        if not for_read:
            self.writer = s
        else:
            self.readers.append(s)
        return s


class TypeInfo:
    """
    A class that holds information about file types
    @param extensions: the list of extensions
    @param binary: whether the file is binary
    """
    def __init__(self, extensions: list, binary: bool):
        self.extensions = extensions
        self.binary = binary

    def resolve(self, name: str):
        """
        Resolve the file name
        @param name: the file name
        @return: the file name
        """
        return None


class FileResolver:
    """
    The base class for all file resolvers

    The actual resolution of the file name is done by a subclass of FileInfo
    """
    def __init__(self):
        self.in_memory_files = {}
        self.typeinfo = {
            "tfm": TypeInfo(["tfm"], binary=True),
        }

    def sourceTypeInfo(self, exts):
        """
        Get the type information
        """
        return TypeInfo(exts, binary=False)

    def resolveInMemory(self, name: str):
        """
        Resolve an in memory file
        @param name: the file name
        @return: the file object
        """
        try:
            return self.in_memory_files[name]
        except KeyError:
            return None

    def getInfo(self, name: str, type: str) -> (str, list, bool):
        """
        get the file information
        @param name: the file name
        @return: the file name and the typeinfo
        """
        if type is None:
            # split the extension from the path and normalise it to lowercase
            ext = os.path.splitext(name)[-1]
            if ext == "" or ext == ".":
                raise ValueError("no file type specified")
            # removing extension
            name = name[:-len(ext)]
            ext = ext[1:].lower()
            # check if we know the type
            for t in self.typeinfo:
                if ext in self.typeinfo[t].extensions:
                    return name, self.typeinfo[t]
            return name, self.sourceTypeInfo([ext])
        if type == "source":
            info = self.sourceTypeInfo(["tex"])
        elif type in self.typeinfo:
            info = self.typeinfo[type]
        else:
            raise ValueError("unknown file type: ", type)
        for e in info.extensions:
            if name.endswith("." + e):
                name = name[:-len(e) - 1]
                break
        return name, info

    def openIn(self, name: str, type: str=None):
        """
        Resolve the file name for reading
        @param name: the file name
        @param type: the file type. If None, the file type is inferred from the file extension
        @return: the file object
        """
        if name[0] == "/":
            raise ValueError("absolute path not allowed")
        name, info= self.getInfo(name, type)
        # we first resolve in memory files
        for t in info.extensions:
            n = name + "." + t
            f = self.resolveInMemory(n)
            if f is not None:
                return f.open()
        mode = "rb" if info.binary else "r"
        # next, we search in the working directories
        for t in info.extensions:
            try:
                return open(name + "." + t, mode)
            except FileNotFoundError:
                pass
        # relative path is only search in the working directory
        p = os.path.split(name)
        if p[0] != "":
            return None
        # at last, we resolve the file name
        f = info.resolve(name)
        if f is not None:
            return open(f, mode)
        return None

    def openOut(self, name: str, type: str):
        """
        Resolve the file name for writing

        The output file cannot be an absolute path. The file is created in memory.
        Note that shipout files are not opened by this method.

        @param name: the file name
        @param type: the file type. 
        @param shipout: whether the file is an output file
        @return: the file object
        """
        if name[0] == "/":
            raise ValueError("absolute path not allowed")
        name, info = self.getInfo(name, type)
        if info.binary:
            raise ValueError("binary files not allowed for writing")
        # it must be an in memory file
        for t in info.extensions:
            n = name + "." + t
            if n in self.in_memory_files:
                return self.in_memory_files[n].open(for_read=False)
        n = name + "." + info.extensions[0]
        f = InMemoryTextFile()
        self.in_memory_files[n] = f
        return f.open(for_read=False)


def readFileName(parser) -> str:
    """
    Read a file name fromt he input stack
    @param parser: the parser
    @return: the file name as a string
    """
    name = ""
    parser.skipFiller()
    while True:
        t = parser.token()
        if t is None:
            break
        if t.catcode == CATCODE.BEGIN_GROUP or t.catcode == CATCODE.END_GROUP:
            parser.input.unread(t)
            break
        if t.catcode == CATCODE.SPACE:
            break
        name += t.name
    return name


mod = Module("resolver", 
    attributes={
        "readFileName": readFileName,
        "resolver": FileResolver(),
    },
)
