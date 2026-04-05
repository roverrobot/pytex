"""HTML reflow backend driven by outer-vlist contributions."""

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


_SPACE_RE = re.compile(r"\s+")


class HTMLReflowBackend:
    """
    Collect semantic block owners from the outer vertical list and render them
    using the concrete owned nodes that exist before page breaking.
    """

    def __init__(self, parser, output=None):
        self.parser = parser
        self.output = output
        self.contrib = []
        self.file = None
        self.finished = False

    def open(self, output=None):
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
    def _collectible(node):
        if isinstance(
            node,
            (
                paragraph.Paragraph,
                mmode.DisplayMathNode,
                align.HAlignment,
                align.MAlignment,
            ),
        ):
            return True
        return node.node_type in (
            nd.NODE_TYPE.HLIST,
            nd.NODE_TYPE.VLIST,
            nd.NODE_TYPE.RULE,
            nd.NODE_TYPE.INS,
        )

    def contribute(self, pending, node):
        if not self._collectible(node):
            return
        self.contrib.append(node)

    def _owns(self, node, owner):
        if vmode.VList.isOwner(node, owner):
            return True
        if isinstance(owner, align.MAlignment):
            source = getattr(owner, "source", None)
            if source is not None and vmode.VList.isOwner(node, source):
                return True
        return False

    def _owned_slice(self, concrete, owner, start):
        while start < len(concrete) and not self._owns(concrete[start], owner):
            start += 1
        end = start
        while end < len(concrete) and self._owns(concrete[end], owner):
            end += 1
        return concrete[start:end], end

    @staticmethod
    def _normalize_text(text):
        return _SPACE_RE.sub(" ", text).strip()

    def _flatten_text(self, nodes):
        parts = []
        last_space = True
        for node in nodes:
            node_type = getattr(node, "node_type", None)
            if node_type in (nd.NODE_TYPE.CHAR,):
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
                if (not last_space) and parts:
                    parts.append(" ")
                    last_space = True
                continue
            if node_type in (nd.NODE_TYPE.KERN, nd.NODE_TYPE.PENALTY, nd.NODE_TYPE.MARK):
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

    def _paragraph_lines(self, owner, nodes):
        lines = []
        for node in nodes:
            if node.node_type != nd.NODE_TYPE.HLIST:
                continue
            if getattr(node, "source", None) is not owner:
                continue
            text = self._flatten_text(getattr(node, "list", ()))
            if text:
                lines.append(text)
        return self._normalize_text(" ".join(lines))

    def _alignment_rows(self, owner, nodes):
        rows = []
        source = owner if not isinstance(owner, align.MAlignment) else getattr(owner, "source", None)
        for node in nodes:
            if node.node_type != nd.NODE_TYPE.HLIST:
                continue
            if getattr(node, "source", None) is not source:
                continue
            cells = []
            for child in getattr(node, "list", ()):
                if not isinstance(child, nd.Box):
                    continue
                text = self._flatten_text(getattr(child, "list", ()))
                cells.append(element("td", text))
            if cells:
                rows.append(element("tr", cells))
        return rows

    def _render_block(self, owner, nodes):
        if isinstance(owner, paragraph.Paragraph):
            text = self._paragraph_lines(owner, nodes)
            if not text:
                return None
            return element(
                "p",
                text,
                class_=["paragraph", "indent" if owner.indent else "noindent"],
            )
        if isinstance(owner, mmode.DisplayMathNode):
            text = self._normalize_text(" ".join(self._flatten_text(getattr(node, "list", ())) for node in nodes))
            if not text:
                return None
            return element("div", element("code", text), class_="display-math")
        if isinstance(owner, (align.HAlignment, align.MAlignment)):
            rows = self._alignment_rows(owner, nodes)
            if not rows:
                return None
            return element("table", rows, class_="alignment")
        if owner.node_type == nd.NODE_TYPE.RULE:
            return element("hr", class_="separator")
        if owner.node_type == nd.NODE_TYPE.INS:
            text = self._flatten_text(getattr(owner, "list", ()))
            if not text:
                return None
            return element("aside", text, class_="note")
        if owner.node_type in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            text = self._flatten_text(getattr(owner, "list", ()))
            if not text:
                return None
            return element("div", text, class_="box")
        return None

    def _render_document(self, pending):
        concrete = pending.concreteNodes()
        blocks = []
        index = 0
        for owner in self.contrib:
            nodes, index = self._owned_slice(concrete, owner, index)
            block = self._render_block(owner, nodes)
            if block is not None:
                blocks.append(block)
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

    def finish(self, pending):
        if self.finished:
            return
        self.open()
        self.file.write(self._render_document(pending))
        self.finished = True

    def close(self):
        if self.file is None:
            return
        self.file.close()
        self.file = None


def init(parser):
    parser.reflow = HTMLReflowBackend(parser)


mod = Module(
    "html_reflow",
    init=init,
    attributes={},
)
