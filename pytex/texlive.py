"""
A FileResolver subclass that resolves files by searching in the texlive installation
"""


from pytex.resolver import FileResolver
from pytex.module import Module
import platform
import os

class TexliveResolver(FileResolver):
    """
    A file resolver that resolves files by searching in the texlive installation
    """

    def __init__(self, texlive_path: str=None, format: str="tex", project_dir: str=None):
        super().__init__(project_dir=project_dir)
        path = self.defaultTeXLivePath() if texlive_path is None else texlive_path
        if not os.path.exists(path):
            raise ValueError("texlive path does not exist: ", path)
        # iterate over all the directories in the texlive path to search for the latest year
        years = []
        for d in os.listdir(path):
            if d.isdigit():
                years.append(int(d))
        if len(years) == 0:
            raise ValueError("no texlive installation found in: ", path)
        self.paths = [os.path.join(path, str(max(years)), "texmf-dist")]
        texmf_local = os.path.join(path, "texmf-local")
        if os.path.exists(texmf_local):
            self.paths.append(texmf_local)
        self.format = format
        # Cache the first matching full path for each file name under a search root.
        # latex.ltx parsing resolves hundreds of files from the same few TeX Live
        # subtrees, so indexing each subtree once avoids repeated os.walk/scandir.
        self._index = {}

    def clone(self, project_dir: str=None):
        cloned = super().clone(project_dir=project_dir)
        cloned.paths = list(self.paths)
        cloned._index = {}
        return cloned


    def searchPaths(self, info: dict):
        """
        Get the paths to search for the file
        """
        if info["category"] == "source":
            subdirs = [self.format, "generic"]
            if self.format != "plain":
                subdirs.append("plain")
            paths = [os.path.join("tex", d) for d in subdirs]
        else:
            paths = [os.path.join(info["category"], info["subcategory"])]
        for p in self.paths:
            for path in paths:
                yield os.path.join(p, path)

    def find(self, names, path):
        """
        Find the file in the directory
        @param names: the file names to search for
        @param path: the path to search
        @return: the file path or None if the file does not exist
        """
        if path not in self._index:
            index = {}
            for root, dirs, files in os.walk(path):
                for name in files:
                    if name not in index:
                        index[name] = os.path.join(root, name)
            self._index[path] = index
        index = self._index[path]
        for name in names:
            if name in index:
                return index[name]
        return None

    def resolve(self, info):
        """
        Resolve the file
        @param info: the file type information, a dictionary returned by the getInfo method
        @return: the file path or None if the file does not exist
        """
        names = [info["name"] + "." + ext for ext in info["extensions"]]
        for p in self.searchPaths(info):
            f = self.find(names, p)
            if f is not None:
                return f
        return None

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


mod = Module("texlive", 
    attributes={
        "resolver": TexliveResolver(format="plain"),
    }
)
