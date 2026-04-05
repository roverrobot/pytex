"""HTML reflow backend driven by the outer-vlist raw history."""

from __future__ import annotations

from collections import Counter
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
_EPDF_RE = re.compile(r"pdf:epdf\b.*\(([^()]+)\)")
_DEFAULT_FONT_ROLE = {
    "family": "serif",
    "weight": "normal",
    "style": "normal",
    "variant": "normal",
}


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
        self._body_font = None
        self._pending_media_blocks = []

    def shipout(self, box):
        if box.width is None:
            packed = []
            box.typeset(self.parser, packed)
            box = packed[-1]
        self.pages.append(box)
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
        return self._normalize_text(self._flatten_text_raw(nodes))

    def _flatten_text_raw(self, nodes):
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
                text = self._flatten_text_raw(node.replace)
                if text:
                    parts.append(text)
                    last_space = text.endswith(" ")
                continue
            children = getattr(node, "list", None)
            if children is not None:
                text = self._flatten_text_raw(children)
                if text:
                    parts.append(text)
                    last_space = text.endswith(" ")
        return "".join(parts)

    @staticmethod
    def _font_signature(font):
        if font is None:
            return None
        backend = getattr(font, "backend", None)
        name = None if backend is None else getattr(backend, "name", None)
        at = getattr(font, "at", None)
        size = None if at is None else round(float(at), 2)
        return name, size

    def _fonts(self, nodes):
        fonts = []
        for node in nodes:
            font = getattr(node, "font", None)
            if font is not None:
                fonts.append(font)
            children = getattr(node, "list", None)
            if children is not None:
                fonts.extend(self._fonts(children))
        return fonts

    def _dominant_font(self, nodes):
        fonts = self._fonts(nodes)
        if not fonts:
            return None
        counts = Counter()
        sample = {}
        for font in fonts:
            key = self._font_signature(font)
            counts[key] += 1
            sample.setdefault(key, font)
        return sample[counts.most_common(1)[0][0]]

    def _infer_body_font(self, owners):
        counts = Counter()
        sample = {}
        for owner in owners:
            if not isinstance(owner, paragraph.Paragraph):
                continue
            for font in self._fonts(owner.list):
                key = self._font_signature(font)
                counts[key] += 1
                sample.setdefault(key, font)
        if not counts:
            return None
        return sample[counts.most_common(1)[0][0]]

    @staticmethod
    def _font_role(font):
        if font is None:
            return dict(_DEFAULT_FONT_ROLE)
        name = getattr(getattr(font, "backend", None), "name", "") or ""
        lower = name.lower()
        role = dict(_DEFAULT_FONT_ROLE)
        if "tt" in lower:
            role["family"] = "monospace"
        elif "ss" in lower:
            role["family"] = "sans-serif"
        if "bx" in lower or lower.startswith("cmb") or "bold" in lower:
            role["weight"] = "bold"
        if "it" in lower or "ti" in lower or "sl" in lower:
            role["style"] = "italic"
        if "csc" in lower:
            role["variant"] = "small-caps"
        return role

    def _font_attrs(self, font, base_font=None):
        if font is None:
            return {}
        attrs = {}
        key = self._font_signature(font)
        role = self._font_role(font)
        base_role = self._font_role(base_font)
        style = []
        at = getattr(font, "at", None)
        base_at = getattr(base_font, "at", None)
        if at is not None and base_at is not None:
            size = round(float(at), 2)
            base_size = round(float(base_at), 2)
            if size != base_size:
                style.append(f"font-size:{size / base_size:.2f}em")
        elif at is not None and base_font is None and self._body_font is not None:
            size = round(float(at), 2)
            body_size = round(float(self._body_font.at), 2)
            if size != body_size:
                style.append(f"font-size:{size / body_size:.2f}em")
        for css_key, role_key in (
            ("font-family", "family"),
            ("font-weight", "weight"),
            ("font-style", "style"),
            ("font-variant", "variant"),
        ):
            value = role.get(role_key)
            if value != base_role.get(role_key):
                style.append(f"{css_key}:{value}")
        if key != self._font_signature(base_font) and (style or base_font is not None):
            attrs["data-tex-font"] = getattr(getattr(font, "backend", None), "name", None)
        if style:
            attrs["style"] = ";".join(style)
        return attrs

    def _raw_text_segments(self, nodes):
        segments = []
        for node in nodes:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.CHAR:
                segments.append((node.font, node.char))
                continue
            if node_type == nd.NODE_TYPE.LIGATURE:
                source = getattr(node, "source", None) or []
                if source:
                    text = "".join(getattr(child, "char", "") for child in source)
                else:
                    text = node.char
                segments.append((node.font, text))
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                segments.append((None, " "))
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
                segments.extend(self._raw_text_segments(node.replace))
                continue
            children = getattr(node, "list", None)
            if children is not None:
                segments.extend(self._raw_text_segments(children))
        return segments

    def _normalize_segments(self, segments):
        normalized = []
        pending_space = False
        started = False
        for font, text in segments:
            for char in text:
                if char.isspace():
                    if started:
                        pending_space = True
                    continue
                if pending_space:
                    normalized.append((font, " "))
                    pending_space = False
                normalized.append((font, char))
                started = True
        if not normalized:
            return []
        merged = []
        for font, text in normalized:
            key = self._font_signature(font)
            if merged and merged[-1][0] == key:
                merged[-1][2] += text
                continue
            merged.append([key, font, text])
        return [(font, text) for _key, font, text in merged]

    def _inline_children(self, nodes, base_font=None):
        children = []
        segments = self._normalize_segments(self._raw_text_segments(nodes))
        for font, text in segments:
            attrs = self._font_attrs(font, base_font)
            if attrs:
                children.append(element("span", text, **attrs))
            else:
                children.append(text)
        return children

    def _special_text(self, node):
        text = getattr(node, "text", None)
        if text is None:
            return None
        if isinstance(text, list):
            return self.parser.expandedToksToString(text)
        return text

    def _contains_epdf(self, node):
        if getattr(node, "node_type", None) == nd.NODE_TYPE.WHATSIT:
            text = self._special_text(node)
            return bool(text and _EPDF_RE.search(text))
        for child in getattr(node, "list", ()) or ():
            if self._contains_epdf(child):
                return True
        return False

    def _extract_epdf_path(self, node):
        if getattr(node, "node_type", None) == nd.NODE_TYPE.WHATSIT:
            text = self._special_text(node)
            if text is None:
                return None
            match = _EPDF_RE.search(text)
            return None if match is None else match.group(1)
        for child in getattr(node, "list", ()) or ():
            path = self._extract_epdf_path(child)
            if path is not None:
                return path
        return None

    def _is_media_container(self, node):
        node_type = getattr(node, "node_type", None)
        if node_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
            return False
        if not self._contains_epdf(node):
            return False
        for child in getattr(node, "list", ()) or ():
            child_type = getattr(child, "node_type", None)
            if child_type not in (nd.NODE_TYPE.HLIST, nd.NODE_TYPE.VLIST):
                continue
            if self._contains_epdf(child) and self._flatten_text(getattr(child, "list", ())) != "":
                return False
        return True

    def _render_media_container(self, node):
        path = self._extract_epdf_path(node)
        if path is None:
            return None
        caption = self._flatten_text(getattr(node, "list", ()))
        media = element(
            "object",
            element("a", os.path.basename(path), href=path),
            data=path,
            type="application/pdf",
            class_="media-object",
        )
        children = [media]
        if caption:
            children.append(element("figcaption", caption))
        return element("figure", children, class_="media-block")

    def _collect_media_blocks(self):
        blocks = []

        def walk(node):
            if self._is_media_container(node):
                block = self._render_media_container(node)
                if block is not None:
                    blocks.append(block)
                return
            for child in getattr(node, "list", ()) or ():
                walk(child)

        for page in self.pages:
            walk(page)
        return blocks

    def _alignment_rows(self, owner):
        rows = []
        for row in getattr(owner, "rows", ()):
            cells = []
            for cell in getattr(row, "cells", ()):
                attrs = {}
                span = getattr(cell, "span", 1)
                if span > 1:
                    attrs["colspan"] = span
                dominant = self._dominant_font(getattr(cell, "list", ()))
                attrs.update(self._font_attrs(dominant, self._body_font))
                cells.append(
                    element(
                        "td",
                        self._inline_children(getattr(cell, "list", ()), dominant),
                        **attrs,
                    )
                )
            if cells:
                rows.append(element("tr", cells))
        return rows

    def _render_owner(self, owner):
        if isinstance(owner, paragraph.Paragraph):
            dominant = self._dominant_font(owner.list)
            children = self._inline_children(owner.list, dominant)
            if not children:
                return []
            attrs = {
                "class_": ["paragraph", "indent" if owner.indent else "noindent"],
            }
            attrs.update(self._font_attrs(dominant, self._body_font))
            return [
                element(
                    "p",
                    children,
                    **attrs,
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
            if (
                len(getattr(owner, "list", ())) == 0
                and getattr(owner, "source", None) is not None
                and self._pending_media_blocks
            ):
                return [self._pending_media_blocks.pop(0)]
            text = self._flatten_text(getattr(owner, "list", ()))
            if not text:
                return []
            return [element("div", text, class_="box")]
        return []

    def _render_document(self, owners):
        self._body_font = self._infer_body_font(owners)
        self._pending_media_blocks = self._collect_media_blocks()
        blocks = []
        for owner in owners:
            blocks.extend(self._render_owner(owner))
        if self._pending_media_blocks:
            blocks.extend(self._pending_media_blocks)
            self._pending_media_blocks = []
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
