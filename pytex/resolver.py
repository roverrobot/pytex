"""
This module implements file name handling

The basic idea is to provide a generic interface to find files by their name.
"""


from pytex.token import CATCODE
from pytex.module import Module
from io import BytesIO, StringIO
from types import MethodType
from typing import Tuple
import copy
from importlib import resources
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
            if f == self.writer:
                self.writer = None
            StringIO.close(f)
        s.close = MethodType(close, s)
        if not for_read:
            self.writer = s
        else:
            self.readers.append(s)
        return s


class InMemoryBinaryFile:
    """
    An in memory binary file
    """
    def __init__(self, content: bytes=b""):
        self.content = content
        self.readers = []
        self.writer = None

    def open(self, for_read: bool=True):
        """
        Open the content as a binary file.
        """
        if for_read and self.writer is not None:
            raise ValueError("file already opened for writing")
        if not for_read and (self.readers or self.writer):
            raise ValueError("file already opened for reading")
        s = BytesIO(self.content)
        def close(f):
            self.content = f.getvalue()
            if f in self.readers:
                self.readers.remove(f)
            if f == self.writer:
                self.writer = None
            BytesIO.close(f)
        s.close = MethodType(close, s)
        if not for_read:
            self.writer = s
        else:
            self.readers.append(s)
        return s


class PipeTextFile(StringIO):
    """
    A read-only text stream produced by an allowlisted pipe command handler.
    """
    def __init__(self, content: str, name: str):
        super().__init__(content)
        self.name = name


class FileResolver:
    """
    The base class for all file resolvers

    The actual resolution of the file name is done by a subclass of FileInfo
    """
    def __init__(self, project_dir: str=None, output_in_memory: bool=False):
        self.in_memory_files = {}
        self.output_in_memory = output_in_memory
        self.typeinfo = {
            "fonts": {
                "tfm": {
                    "extensions": ["tfm"], 
                    "binary": True,
                },
                "afm": {
                    "extensions": ["afm"],
                    "binary": False,
                },
                "type1": {
                    "extensions": ["pfb"],
                    "binary": True,
                },
                "opentype": {
                    "extensions": ["otf"],
                    "binary": True,
                },
                "truetype": {
                    "extensions": ["ttf"],
                    "binary": True,
                },
            },
            "dump": {
                "pfmt": {
                    "extensions": ["pfmt"],
                    "binary": True,
                },
            },
            "shipout": {
                "dvi": {
                    "extensions": ["dvi"],
                    "binary": True,
                },
                "xdv": {
                    "extensions": ["xdv"],
                    "binary": True,
                },
                "pdf": {
                    "extensions": ["pdf"],
                    "binary": True,
                },
                "docx": {
                    "extensions": ["docx"],
                    "binary": True,
                },
                "html": {
                    "extensions": ["htm", "html"],
                    "binary": False,
                },
            },
            "source": {
                "tex": {
                    "extensions": ["tex"], 
                    "binary": False,
                },
                "ini": {
                    "extensions": ["ini"], 
                    "binary": False,
                },
            },
        }
        self.project_dir = None
        self.setProjectDir(os.getcwd() if project_dir is None else project_dir)

    def clone(self, project_dir: str=None):
        """
        Create a per-parser copy of the resolver.

        The module registry stores resolver instances on the module object, but parsers should
        not share mutable resolver state such as in-memory files or the project directory.
        """
        cloned = copy.copy(self)
        cloned.in_memory_files = {}
        cloned.typeinfo = copy.deepcopy(self.typeinfo)
        cloned.setProjectDir(os.getcwd() if project_dir is None else project_dir)
        return cloned

    def setProjectDir(self, project_dir: str):
        """
        Set the directory that source files may be read from.
        """
        path = os.path.realpath(os.path.abspath(project_dir))
        if not os.path.isdir(path):
            raise ValueError(f"project directory does not exist: {project_dir}")
        self.project_dir = path

    def _sourcePath(self, name: str):
        """
        Resolve a source path relative to the project directory and reject escapes.
        """
        if os.path.isabs(name):
            path = os.path.realpath(name)
        else:
            path = os.path.realpath(os.path.join(self.project_dir, name))
        try:
            allowed = os.path.commonpath([self.project_dir, path]) == self.project_dir
        except ValueError:
            allowed = False
        if not allowed:
            raise ValueError(f"path outside project directory not allowed: {name}")
        return path

    def _outputPath(self, name: str):
        """
        Resolve an output path under the project directory.
        """
        if os.path.isabs(name):
            raise ValueError(f"absolute output paths not allowed: {name}")
        path = os.path.realpath(os.path.join(self.project_dir, name))
        try:
            allowed = os.path.commonpath([self.project_dir, path]) == self.project_dir
        except ValueError:
            allowed = False
        if not allowed:
            raise ValueError(f"path outside project directory not allowed: {name}")
        return path

    @staticmethod
    def _hasExplicitDirectory(name: str):
        """
        Check whether the user supplied a path component rather than a bare file name.
        """
        return os.path.dirname(name) != ""

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

    def categories(self):
        """
        get the supported categories
        @return: the list of categories
        """
        return self.typeinfo.keys()
    
    def getSubcatogories(self, category: str):
        """
        get the subcategories of a category
        @param category: the category
        @return: the list of subcategories
        """
        if category in self.typeinfo:
            return self.typeinfo[category].keys()
        return []

    def getInfo(self, name: str, type: str) -> Tuple[str, dict]:
        """
        get the file information
        @param name: the file name
        @param type: the file type
        @return: a dictionary containing the type information

        The file type may be a catogory, such as "font", "source", "dump", as returned by
        the categories() method. The type may also be None, in which case the file type is
        inferred from the file extension. 
        
        The file type may also be category/subcategory, such as font/tfm or source/tex etc,
        the supportd subcategories for each category are returned by the 
        getSubcategories(category) method.

        The manditory fields of the returned type info include "name", "category", "subcategory",
        "extensions" and "binary". The "name" is the file name without extension. The
        "category" and "subcategory" are their literal meanings, The "extensions"
        is a list of file extensions. The "binary" key is a boolean indicating whether the file is
        binary or text. If the file extension is provided, the extensions
        contains only the provided one.
        """
        # split the extension from the path and normalise it to lowercase
        ext = os.path.splitext(name)[-1]
        # removing extension
        if ext:
            name = name[:-len(ext)]
            ext = ext[1:].lower()
        if not type:
            if ext == "" or ext == ".":
                raise ValueError("no file type specified")
            # check if we know the type
            for cat, cat_info in self.typeinfo.items():
                for sub, typeinfo in cat_info.items():
                    if ext in typeinfo["extensions"]:
                        return typeinfo | {"name": name, "category": cat, "subcategory": sub, "extensions": [ext]}
            # if we reach here, the type was not found
            return {"name": name, "extensions": [ext], "binary": False}
        # split the type into category and subcategory
        parts = type.split("/")
        cat = parts[0]
        if cat not in self.typeinfo:
            raise ValueError("unknown category: "+cat)
        cat_info = self.typeinfo[cat]
        if len(parts) == 1:
            # we do not know the subcategory
            # if the ext is provided, we search for the subcategory. Otherwise,
            # the preferred subcategory is returned. For example, for source files, the preferred
            # subcategory is "tex"
            key = None
            if ext:
                for key, info in cat_info.items():
                    if ext in info["extensions"]:
                        break
            if key is None:
                key = next(iter(cat_info))
        else:
            key = parts[1]
            if key not in cat_info:
                raise ValueError(f"unknown subcategory {key} in category {cat}")
        info = {"name": name, "category": cat, "subcategory": key}
        if ext:
            info["extensions"] = [ext]
        return cat_info[key] | info

    def resolve(self, info: dict):
        """
        Resolve the file name
        @param info: the file type information
        @return: the file path, or None if the file does not exist

        Before reaching this function, the file has been searched among in-memory files and
        direct filesystem paths. This function is responsible for searching the file was
        not found in the previous steps.
        """
        return None

    def openBundled(self, info: dict):
        """
        Open a bundled read-only resource for this file type, if one exists.

        Standard format files are package data rather than TeX Live inputs, so
        they are searched after a project-local file but before resolver
        backends such as TeX Live.
        """
        if info.get("category") != "dump":
            return None
        for ext in info["extensions"]:
            filename = f'{info["name"]}.{ext}'
            resource = resources.files("pytex").joinpath(
                "data", "formats", filename
            )
            if resource.is_file():
                return resource.open("rb")
        return None

    def openPipeIn(self, name: str):
        """
        Open an allowlisted pipe command for reading.

        Pipe commands are not arbitrary shell invocations. They are parsed and
        dispatched through the global pipe-command registry.
        """
        if not name.startswith("|"):
            return None
        from pytex import pipes
        content = pipes.openPipe(self, name)
        if content is None:
            return None
        return PipeTextFile(content, name)

    def openIn(self, name: str, type: str=None):
        """
        Resolve the file name for reading
        @param name: the file name
        @param type: the file type. If None, the file type is inferred from the file extension
        @return: the file object

        The file type can be a category or a category/subcategory. Please see the getInfo method
        for more details.
        """
        pipe = self.openPipeIn(name)
        if pipe is not None or name.startswith("|"):
            return pipe
        info = self.getInfo(name, type)
        for ext in info["extensions"]:
            n = info["name"] + "." + ext
            f = self.resolveInMemory(n)
            if f is not None:
                return f.open()
        mode = "rb" if info["binary"] else "r"
        if info.get("category") == "source":
            for ext in info["extensions"]:
                n = info["name"] + "." + ext
                try:
                    return open(self._sourcePath(n), mode)
                except FileNotFoundError:
                    pass
            if self._hasExplicitDirectory(info["name"]):
                return None
        else:
            # next, we search in the current working directory
            for ext in info["extensions"]:
                n = info["name"] + "." + ext
                try:
                    return open(n, mode)
                except FileNotFoundError:
                    pass
            # explicit paths are not searched via resolver backends
            if self._hasExplicitDirectory(info["name"]):
                return None
        # Next, look for package data such as the bundled standard formats.
        bundled = self.openBundled(info)
        if bundled is not None:
            return bundled
        # At last, resolve the file name through the configured backend.
        f = self.resolve(info)
        if f is not None:
            return open(f, mode)
        return None

    def openOut(self, name: str, type: str):
        """
        Resolve the file name for writing

        The output file is written under the project directory.
        @param name: the file name
        @param type: the file type. If None, the file type is inferred from the file extension
        @param shipout: whether the file is an output file
        @return: the file object

        The file type can be a category or a category/subcategory. Please see the getInfo method
        for more details.
        """
        if name.startswith("./"):
            return self.openOut(name[2:], type)
        info = self.getInfo(name, type)
        n = info["name"] + "." + info["extensions"][0]
        if self.output_in_memory:
            existing = self.resolveInMemory(n)
            if existing is not None:
                return existing.open(for_read=False)
            if info["binary"]:
                file = InMemoryBinaryFile()
            else:
                file = InMemoryTextFile()
            self.in_memory_files[n] = file
            return file.open(for_read=False)
        mode = "wb" if info["binary"] else "w"
        return open(self._outputPath(n), mode)


def readFileName(parser) -> str:
    """
    Read a file name fromt he input stack
    @param parser: the parser
    @return: the file name as a string
    """
    name = ""
    parser.skipFiller()
    toks = []
    t = parser.token_expand()
    if t is None:
        raise ValueError("expecting a file name")
    if t.catcode == CATCODE.OTHER and t.name == '"':
        # the file name is enclosed by double quotes
        while True:
            t = parser.token_expand()
            if t is None:
                raise ValueError("unterminated file name")
            if t.catcode == CATCODE.OTHER and t.name == '"':
                break
            name += t.name
        # skip an optional space
        parser.skipSpaceExapnd()
    elif t.catcode == CATCODE.BEGIN_GROUP:
        toks, _end = parser.readTo(CATCODE.END_GROUP, expand=True)
    else:
        # the file name is deliminated by a space or a control sequence
        toks = [t]
        while True:
            t = parser.token_expand()
            if t is None or t.isSpace(True):
                break
            if t.catcode is None or t.catcode == CATCODE.END_GROUP:
                parser.input.unread(t)
                break
            toks.append(t)
            if t.catcode == CATCODE.BEGIN_GROUP:
                toks, end = parser.readTo(CATCODE.END_GROUP, toks, expand=True)
                toks.append(end)
    for t in toks:
        name += t.name
    return name


mod = Module("resolver", 
    attributes={
        "readFileName": readFileName,
        "resolver": FileResolver(),
    },
)
