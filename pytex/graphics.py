"""Backend-neutral graphics IR shared by shipout backends."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GraphicSpec:
    kind: str
    source: str
    name: str = None
    options: tuple = field(default_factory=tuple)
    format: str = None

    @classmethod
    def from_dvipdfm(cls, kind, name=None, options=None, source=None):
        source = "" if source is None else source
        suffix = source.rsplit(".", 1)
        format = "pdf" if kind == "epdf" else None
        if kind == "image" and len(suffix) == 2:
            format = suffix[1].lower()
        return cls(
            kind=kind,
            name=name,
            source=source,
            options=tuple(options or ()),
            format=format,
        )

    @property
    def option_map(self):
        return {key: value for key, value in self.options}
