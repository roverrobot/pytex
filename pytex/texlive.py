"""
A FileResolver subclass that resolves files by searching in the texlive installation
"""


from pytex.resolver import FileResolver
from pytex.module import Module
import platform
import os


_directory_index_cache = {}


class TexliveResolver(FileResolver):
    """
    A file resolver that resolves files by searching in the texlive installation
    """

    def __init__(
        self,
        texlive_path: str=None,
        format: str="tex",
        project_dir: str=None,
        output_in_memory: bool=False,
        defer: bool=False,
    ):
        super().__init__(project_dir=project_dir, output_in_memory=output_in_memory)
        self.texlive_path = self.defaultTeXLivePath() if texlive_path is None else texlive_path
        self.paths = None
        self.format = format
        # Cache the first matching full path for each file name under a search root.
        # This is process-wide so separate resolver instances and parser-local clones
        # can reuse the same expensive directory walks.
        self._index = _directory_index_cache
        if not defer:
            self._configurePaths()

    def _configurePaths(self):
        """Validate the TeX Live root and record its searchable trees."""
        path = self.texlive_path
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

    def _ensurePaths(self):
        if self.paths is None:
            self._configurePaths()

    def clone(self, project_dir: str=None):
        cloned = super().clone(project_dir=project_dir)
        cloned.paths = None if self.paths is None else list(self.paths)
        # Share the expensive directory index across parser-local resolver clones while
        # keeping per-parser mutable state such as in-memory files isolated.
        cloned._index = self._index
        return cloned


    def searchPaths(self, info: dict):
        """
        Get the paths to search for the file
        """
        self._ensurePaths()
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
        # Parser construction should not prevent the CLI from selecting a
        # nonstandard TeX Live root with --texlive.
        "resolver": TexliveResolver(format="plain", defer=True),
    }
)
