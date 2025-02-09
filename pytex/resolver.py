"""
This module implements file name handling

The basic idea is to provide a generic interface to find files by their name.
"""


from pytex.token import CATCODE
from pytex.module import Module
from io import StringIO
from types import MethodType
from typing import Tuple
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


class FileResolver:
    """
    The base class for all file resolvers

    The actual resolution of the file name is done by a subclass of FileInfo
    """
    def __init__(self):
        self.in_memory_files = {}
        self.typeinfo = {
            "fonts": {
                "tfm": {
                    "extensions": ["tfm"], 
                    "binary": True,
                },
            },
            "dump": {
                "json": {
                    "extensions": ["json"], 
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

    def resolve(self, name: str, typeinfo: dict):
        """
        Resolve the file name
        @param name: the file name without extension
        @param typeinfo: the file type information
        @return: the file path, or None if the file does not exist

        Before reaching this function, the file has been searched among in-memory files and
        the current working directory. This function is responsible for searching the file was
        not found in the previous steps.
        """
        return None

    def openIn(self, name: str, type: str=None):
        """
        Resolve the file name for reading
        @param name: the file name
        @param type: the file type. If None, the file type is inferred from the file extension
        @return: the file object

        The file type can be a category or a category/subcategory. Please see the getInfo method
        for more details.
        """
        if name[0] == "/":
            raise ValueError("absolute path not allowed")
        info = self.getInfo(name, type)
        for ext in info["extensions"]:
            n = info["name"] + "." + ext
            f = self.resolveInMemory(n)
            if f is not None:
                return f.open()
        mode = "rb" if info["binary"] else "r"
        # next, we search in the working directories
        for ext in info["extensions"]:
            n = info["name"] + "." + ext
            try:
                return open(n, mode)
            except FileNotFoundError:
                pass
        # relative path is only search in the working directory
        p = os.path.split(name)
        if p[0] != "":
            return None
        # at last, we resolve the file name
        f = self.resolve(info)
        if f is not None:
            return open(f, mode)
        return None

    def openOut(self, name: str, type: str):
        """
        Resolve the file name for writing

        The output file cannot be an absolute path. The file is created in memory.
        Note that shipout files are not opened by this method.

        @param name: the file name
        @param type: the file type. If None, the file type is inferred from the file extension
        @param shipout: whether the file is an output file
        @return: the file object

        The file type can be a category or a category/subcategory. Please see the getInfo method
        for more details.
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
