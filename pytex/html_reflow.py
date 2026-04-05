"""HTML reflow backend driven by the outer-vlist raw history."""

from __future__ import annotations

import os
import re

from pytex import align
from pytex import mmode
from pytex import node as nd
from pytex import paragraph
from pytex import vmode
from pytex.html_builder import element, render
from pytex.module import Module
from pytex.typeset.shipout import Shipout


_SPACE_RE = re.compile(r"\s+")


class HTMLReflowBackend(Shipout):
    """
    Null shipout backend for reflow mode.

    We still let TeX/LaTeX run the normal page builder and output routine so
    deferred writes, aux replay, and shipout hooks behave normally. The backend
    itself only executes shipped whatsits; the final HTML is emitted once at
    close from the main vertical list's raw ownership history.
    """

    def __init__(self, parser, output=None):
        super().__init__(parser, output)
        self.file = None
        self.finished = False

    def shipout(self, box):
        if box.width is None:
            packed = []
            box.typeset(self.parser, packed)
            box = packed[-1]
        self._emit_whatsits(box)

    def _emit_whatsits(self, node):
        if getattr(node, "node_type", None) == nd.NODE_TYPE.WHATSIT:
            node.output(self.parser, self)
            return
        items = getattr(node, "list", None)
        if items is None:
            return
        for child in items:
            self._emit_whatsits(child)

    def open(self):
        # Runtime shipout is intentionally side-effect free for HTML reflow.
        return

    def _open_output(self, output=None):
        if self.file is not None:
            return
        if output is None:
            output = self.output
        if output is None:
            output = self.parser.jobname or "texput"
        if hasattr(output, "write"):
            self.file = output
            return
        path = os.fspath(output)
        if os.path.isabs(path):
            if not path.endswith(".html"):
                path += ".html"
            self.file = open(path, "w")
            return
        if not path.endswith(".html"):
            path += ".html"
        self.file = self.parser.resolver.openOut(path, None)

    @staticmethod
    def _normalize_text(text):
        return _SPACE_RE.sub(" ", text).strip()

    def _flatten_text(self, nodes):
        parts = []
        last_space = True
        for node in nodes:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.CHAR:
                parts.append(node.char)
                last_space = False
                continue
            if node_type == nd.NODE_TYPE.LIGATURE:
                source = getattr(node, "source", None) or []
                if source:
                    parts.append("".join(getattr(child, "char", "") for child in source))
                else:
                    parts.append(node.char)
                last_space = False
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                if parts and not last_space:
                    parts.append(" ")
                    last_space = True
                continue
            if node_type in (
                nd.NODE_TYPE.KERN,
                nd.NODE_TYPE.PENALTY,
                nd.NODE_TYPE.MARK,
                nd.NODE_TYPE.INS,
                nd.NODE_TYPE.ADJUST,
                nd.NODE_TYPE.WHATSIT,
            ):
                continue
            if node_type == nd.NODE_TYPE.DISC:
                text = self._flatten_text(node.replace)
                if text:
                    parts.append(text)
                    last_space = text.endswith(" ")
                continue
            children = getattr(node, "list", None)
            if children is not None:
                text = self._flatten_text(children)
                if text:
                    parts.append(text)
                    last_space = text.endswith(" ")
        return self._normalize_text("".join(parts))

    def _alignment_rows(self, owner):
        rows = []
        for row in getattr(owner, "rows", ()):
            cells = []
            for cell in getattr(row, "cells", ()):
                attrs = {}
                span = getattr(cell, "span", 1)
                if span > 1:
                    attrs["colspan"] = span
                cells.append(element("td", self._flatten_text(getattr(cell, "list", ())), **attrs))
            if cells:
                rows.append(element("tr", cells))
        return rows

    def _render_owner(self, owner):
        if isinstance(owner, paragraph.Paragraph):
            text = self._flatten_text(owner.list)
            if not text:
                return []
            return [
                element(
                    "p",
                    text,
                    class_=["paragraph", "indent" if owner.indent else "noindent"],
                )
            ]
        if isinstance(owner, mmode.DisplayMathNode):
            text = self._flatten_text(owner.list)
            if not text:
                return []
            return [element("div", element("code", text), class_="display-math")]
        if isinstance(owner, align.HAlignment):
            rows = self._alignment_rows(owner)
            if not rows:
                return []
            return [element("table", rows, class_="alignment")]
        if isinstance(owner, align.MAlignment):
            source = getattr(owner, "source", None)
            if isinstance(source, align.HAlignment):
                rows = self._alignment_rows(source)
                if rows:
                    return [element("table", rows, class_=["alignment", "display-math"])]
            text = self._flatten_text(getattr(owner, "list", ()))
            if not text:
                return []
            return [element("div", element("code", text), class_="display-math")]
        if isinstance(owner, vmode.VAdjust):
            blocks = []
            for child in getattr(owner, "list", ()):
                blocks.extend(self._render_owner(child))
            return blocks
        node_type = getattr(owner, "node_type", None)
        if node_type == nd.NODE_TYPE.RULE:
            return [element("hr", class_="separator")]
        if node_type == nd.NODE_TYPE.INS:
            text = self._flatten_text(getattr(owner, "list", ()))
            if not text:
                return []
            return [element("aside", text, class_="note")]
        if node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            text = self._flatten_text(getattr(owner, "list", ()))
            if not text:
                return []
            return [element("div", text, class_="box")]
        return []

    def _render_document(self, owners):
        blocks = []
        for owner in owners:
            blocks.extend(self._render_owner(owner))
        title = os.path.basename(os.fspath(self.parser.jobname or "texput"))
        doc = element(
            "html",
            element(
                "head",
                element("meta", charset="utf-8"),
                element("title", title),
            ),
            element(
                "body",
                element("main", blocks, class_="pytex-reflow"),
            ),
            lang="en",
        )
        return "<!doctype html>\n" + render(doc) + "\n"

    def close(self):
        if self.finished or not getattr(self.parser, "ended", False):
            return
        if not self.parser.lists:
            return
        main = self.parser.lists[0]
        owners = main.rawNodes() if hasattr(main, "rawNodes") else list(getattr(main, "raw", ()))
        self._open_output()
        self.file.write(self._render_document(owners))
        self.finished = True
        self.file.close()
        self.file = None


mod = Module(
    "html_reflow",
    attributes={},
)
