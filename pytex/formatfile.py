"""
Helpers for pytex format-file containers.

The current container format is a deflated zip archive that stores:
- `manifest.json`: versioned metadata
- `state.json`: serialized parser state
- `hyphen/<language>.json`: one hyphenator payload per language

Using a zip container lets us keep format files inspectable while making it
easy to split hyphen data per language and defer loading until needed.
"""

import io
import json
import zipfile

from pytex import serialization


FORMAT_KIND = "pytex-format"
FORMAT_VERSION = 1


class ContainerFormatFile:
    """
    In-memory view of a loaded pytex format container.
    """
    def __init__(self, data: bytes):
        self.data = data
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.manifest = json.loads(archive.read("manifest.json"))
        if self.manifest.get("kind") != FORMAT_KIND:
            raise ValueError(f"unknown format container kind {self.manifest.get('kind')!r}")
        version = self.manifest.get("version")
        if version != FORMAT_VERSION:
            raise ValueError(f"unsupported format container version {version}")

    def readJSON(self, name):
        """
        Read one JSON entry from the container.
        """
        with zipfile.ZipFile(io.BytesIO(self.data)) as archive:
            return json.loads(archive.read(name))


def isContainer(data: bytes) -> bool:
    """
    Check whether the given bytes look like a supported format container.
    """
    if not isinstance(data, (bytes, bytearray)) or len(data) < 4:
        return False
    return zipfile.is_zipfile(io.BytesIO(data))


def dump(parser) -> bytes:
    """
    Dump the current parser state as a compressed zip container.

    Readers accept both compressed and historical stored containers. Deflating
    the JSON payload keeps bundled format files small enough for ordinary Git
    hosting while preserving their inspectable zip layout.
    """
    manifest = {
        "kind": FORMAT_KIND,
        "version": FORMAT_VERSION,
        "state": "state.json",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        state_data = serialization.serialize(parser.dumpState())
        archive.writestr("state.json", json.dumps(state_data))
        if hasattr(parser, "hyphenator"):
            entries = {}
            for language, data in parser.hyphenator.dumpLanguages():
                name = f"hyphen/{language}.json"
                entries[str(language)] = name
                archive.writestr(name, json.dumps(data))
            manifest["hyphenator"] = {
                "language": parser.hyphenator.language,
                "entries": entries,
            }
        archive.writestr("manifest.json", json.dumps(manifest))
    return buffer.getvalue()


def load(parser, data: bytes):
    """
    Load a parser state from a format container.
    """
    parser.formatfile = ContainerFormatFile(data)
    manifest = parser.formatfile.manifest
    state_name = manifest.get("state", "state.json")
    state_data = parser.formatfile.readJSON(state_name)
    parser.loadState(serialization.deserialize(parser, state_data))
    hyphen_data = manifest.get("hyphenator", None)
    if hyphen_data is not None and hasattr(parser, "hyphenator"):
        parser.hyphenator.load(hyphen_data)
