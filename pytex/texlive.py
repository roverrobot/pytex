"""
A FileResolver subclass that resolves files by searching in the texlive installation
"""


from pytex.resolver import FileResolver, TypeInfo
from pytex.module import Module
import platform
import os


class TexliveTypeInfo(TypeInfo):
    """
    A file info class that resolves files by searching in the texlive installation
    """
    def __init__(self, extensions, binary, paths, formats):
        super().__init__(extensions, binary)
        self.paths = []
        for p in paths:
            for f in formats:
                self.paths.append(os.path.join(p, f))

    def find(self, names, path):
        """
        Find the file in the directory
        @param names: the file names to search for
        @param path: the path to search
        @return: the file path or None if the file does not exist
        """
        for root, dirs, files in os.walk(path):
            for name in names:
                if name in files:
                    return os.path.join(root, name)
        return None

    def resolve(self, name):
        """
        Resolve the file
        @return: the file path or None if the file does not exist
        """
        names = [name + "." + ext for ext in self.extensions]
        for p in self.paths:
            f = self.find(names, p)
            if f is not None:
                return f
        return None


class TexliveResolver(FileResolver):
    """
    A file resolver that resolves files by searching in the texlive installation
    """

    def __init__(self, texlive_path: str=None, format: str="tex"):
        super().__init__()
        path = self.defaultTeXLivePath() if texlive_path is None else texlive_path
        if not os.path.exists(path):
            raise ValueError("texlive path does not exist: ", path)
        # iterate over all the directories in the texlive path to search for the latest year
        years = []
        for d in os.listdir(path):
            if d.isdigit():
                years.append(d)
        if len(years) == 0:
            raise ValueError("no texlive installation found in: ", path)
        self.paths = [os.path.join(path, str(max(years)), "texmf-dist")]
        texmf_local = os.path.join(path, "texmf-local")
        if os.path.exists(texmf_local):
            self.paths.append(texmf_local)
        self.typeinfo = {
            "tfm": TexliveTypeInfo(["tfm"], True, self.paths, ["fonts/tfm"]),
        }
        self.format = format
    
    def sourceTypeInfo(self, exts):
        """
        Get the type information
        """
        return TexliveTypeInfo(exts, False, self.paths, [
            os.path.join("tex", self.format),
            "tex/generic",
        ])

    @staticmethod
    def defaultTeXLivePath():
        """
        Get the default texlive path
        @return: the texlive path
        """
        sys = platform.system()
        if sys == "Windows":
            return "C:\\texlive"
        elif sys == "Darwin":
            return "/usr/local/texlive"
        else:
            return "/usr/share/texlive"

    def resolveRead(self, name: str, exts: list):
        """
        Resolve a file for reading
        @param name: the file name
        @param exts: the file extensions
        @return: the file path or None if the file does not exist
        """
        for p in self.paths:
            f = os.path.join(p, name)
            if os.path.exists(f):
                return f
        return None


mod = Module("texlive", 
    attributes={
        "resolver": TexliveResolver(format="plain"),
    }
)
