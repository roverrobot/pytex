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
_DEST_RE = re.compile(r"^\s*pdf:\s*dest\s*\(([^()]*)\)", re.IGNORECASE)
_BEGINANN_RE = re.compile(r"^\s*pdf:\s*(?:beginann|bann|annotate|annot|ann)\b", re.IGNORECASE)
_ENDANN_RE = re.compile(r"^\s*pdf:\s*(?:endann|eann|eannot)\b", re.IGNORECASE)
_GOTO_RE = re.compile(r"/S\s*/GoTo\b.*?/D\s*\(([^()]*)\)", re.IGNORECASE | re.DOTALL)
_GOTOR_RE = re.compile(
    r"/S\s*/GoToR\b.*?/F\s*\(([^()]*)\)(?:.*?/D\s*\(([^()]*)\))?",
    re.IGNORECASE | re.DOTALL,
)
_DEFAULT_FONT_ROLE = {
    "family": "serif",
    "weight": "normal",
    "style": "normal",
    "variant": "normal",
}

_MATH_OPERATORS_MAP = {
    0x00: "Γ",
    0x01: "Δ",
    0x02: "Θ",
    0x03: "Λ",
    0x04: "Ξ",
    0x05: "Π",
    0x06: "Σ",
    0x07: "Υ",
    0x08: "Φ",
    0x09: "Ψ",
    0x0A: "Ω",
}

_MATH_LETTERS_MAP = {
    0x0B: "α",
    0x0C: "β",
    0x0D: "γ",
    0x0E: "δ",
    0x0F: "ε",
    0x10: "ζ",
    0x11: "η",
    0x12: "θ",
    0x13: "ι",
    0x14: "κ",
    0x15: "λ",
    0x16: "μ",
    0x17: "ν",
    0x18: "ξ",
    0x19: "π",
    0x1A: "ρ",
    0x1B: "σ",
    0x1C: "τ",
    0x1D: "υ",
    0x1E: "φ",
    0x1F: "χ",
    0x20: "ψ",
    0x21: "ω",
    0x22: "ε",
    0x23: "ϑ",
    0x24: "ϖ",
    0x25: "ϱ",
    0x26: "ς",
    0x27: "φ",
    0x40: "∂",
    0x60: "ℓ",
    0x7B: "ı",
    0x7C: "ȷ",
    0x7D: "℘",
}

_MATH_SYMBOLS_MAP = {
    0x00: "−",
    0x01: "·",
    0x02: "×",
    0x03: "*",
    0x04: "÷",
    0x06: "±",
    0x07: "∓",
    0x08: "⊕",
    0x09: "⊖",
    0x0A: "⊗",
    0x0B: "⊘",
    0x0C: "⊙",
    0x0D: "◯",
    0x0E: "∘",
    0x0F: "•",
    0x10: "≍",
    0x11: "≡",
    0x12: "⊆",
    0x13: "⊇",
    0x14: "≤",
    0x15: "≥",
    0x18: "∼",
    0x19: "≈",
    0x1A: "⊂",
    0x1B: "⊃",
    0x1C: "≪",
    0x1D: "≫",
    0x1E: "≺",
    0x1F: "≻",
    0x20: "←",
    0x21: "→",
    0x22: "↑",
    0x23: "↓",
    0x24: "↔",
    0x25: "↗",
    0x26: "↘",
    0x28: "⇐",
    0x29: "⇒",
    0x2A: "⇑",
    0x2B: "⇓",
    0x2C: "⇔",
    0x2D: "↖",
    0x2E: "↙",
    0x2F: "∝",
    0x30: "′",
    0x31: "∞",
    0x32: "∈",
    0x33: "∋",
    0x34: "△",
    0x35: "▽",
    0x38: "∀",
    0x39: "∃",
    0x3A: "¬",
    0x3B: "∅",
    0x3C: "ℜ",
    0x3D: "ℑ",
    0x3E: "⊤",
    0x3F: "⊥",
    0x40: "ℵ",
    0x5B: "∪",
    0x5C: "∩",
    0x5D: "⊎",
    0x5E: "∧",
    0x5F: "∨",
    0x60: "⊢",
    0x61: "⊣",
    0x62: "⌊",
    0x63: "⌋",
    0x64: "⌈",
    0x65: "⌉",
    0x66: "{",
    0x67: "}",
    0x68: "⟨",
    0x69: "⟩",
    0x6A: "|",
    0x6B: "∥",
    0x6E: "\\",
    0x71: "∐",
    0x72: "∇",
    0x73: "∫",
    0x74: "⊔",
    0x75: "⊓",
    0x76: "⊑",
    0x77: "⊒",
    0x78: "§",
    0x79: "†",
    0x7A: "‡",
    0x7B: "¶",
    0x7C: "♣",
    0x7D: "♢",
    0x7E: "♡",
    0x7F: "♠",
}

_MATH_LARGE_SYMBOLS_MAP = {
    0x46: "⨆",
    0x48: "∮",
    0x4A: "⨀",
    0x4C: "⨁",
    0x4E: "⨂",
    0x50: "∑",
    0x51: "∏",
    0x52: "∫",
    0x53: "⋃",
    0x54: "⋂",
    0x55: "⨄",
    0x56: "⋀",
    0x57: "⋁",
    0x60: "∐",
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

    @staticmethod
    def _printable_char(char):
        return isinstance(char, str) and len(char) == 1 and char.isprintable() and ord(char) >= 0x20

    def _math_symbol_text(self, symbol):
        if symbol is None:
            return None
        code = ord(symbol.char)
        if symbol.fam == 0:
            text = _MATH_OPERATORS_MAP.get(code)
            if text is not None:
                return text
        elif symbol.fam == 1:
            text = _MATH_LETTERS_MAP.get(code)
            if text is not None:
                return text
        elif symbol.fam == 2:
            text = _MATH_SYMBOLS_MAP.get(code)
            if text is not None:
                return text
        elif symbol.fam == 3:
            text = _MATH_LARGE_SYMBOLS_MAP.get(code)
            if text is not None:
                return text
        if self._printable_char(symbol.char):
            return symbol.char
        return None

    def _math_delim_text(self, delim):
        if delim is None or delim._isNull():
            return None
        text = self._math_symbol_text(delim.small)
        if text is not None:
            return text
        return self._math_symbol_text(delim.large)

    def _math_fragment(self, children, class_name=None):
        children = [child for child in children if child is not None and child != ""]
        if not children:
            return []
        if len(children) == 1 and class_name is None:
            return children
        return [element("span", children, class_=class_name)]

    def _render_math_field(self, field):
        if field is None:
            return []
        if isinstance(field, mmode.StyleNode):
            return []
        if isinstance(field, mmode.MathSymbol):
            text = self._math_symbol_text(field)
            if text is None:
                return []
            return [text]
        if isinstance(field, (mmode.MathListHolder, mmode.Subformula, mmode.InlineMathNode, mmode.DisplayMathNode)):
            return self._render_math_items(field.list)
        if isinstance(field, mmode.Over):
            num, den, _bar, _thickness = field.nucleus
            frac = element(
                "span",
                [
                    element("span", self._render_math_field(num), class_="math-num"),
                    "/",
                    element("span", self._render_math_field(den), class_="math-den"),
                ],
                class_="math-frac",
            )
            return self._render_math_scripts(field, [frac])
        if isinstance(field, mmode.Rad):
            children = ["√"]
            children.extend(self._render_math_field(field.oprand))
            return self._math_fragment(children, class_name="math-rad")
        if isinstance(field, mmode.Accent):
            children = []
            children.extend(self._render_math_field(field.base))
            accent = self._render_math_field(field.accent)
            if accent:
                children.append(element("sup", accent, class_="math-accent"))
            return self._render_math_scripts(field, children)
        if isinstance(field, mmode.Atom):
            children = []
            if field.left is not None:
                left = self._math_delim_text(field.left)
                if left is not None:
                    children.append(left)
            boundary = field._boundaryInfo()
            if boundary is not None:
                left_delim, right_delim, body_items = boundary
                left = self._math_delim_text(left_delim)
                right = self._math_delim_text(right_delim)
                if left is not None:
                    children.append(left)
                children.extend(self._render_math_items(body_items))
                if right is not None:
                    children.append(right)
            else:
                children.extend(self._render_math_field(getattr(field, "nucleus", None)))
            if field.right is not None:
                right = self._math_delim_text(field.right)
                if right is not None:
                    children.append(right)
            return self._render_math_scripts(field, children)
        if getattr(field, "node_type", None) == nd.NODE_TYPE.WHATSIT:
            text = self._special_text(field)
            if text is None:
                return []
            action = self._special_action(text)
            if action is None:
                return []
            if action["kind"] == "dest":
                return [element("span", id=action["target"], class_="tex-dest")]
            if action["kind"] == "marker":
                return [self._special_marker(action["text"])]
            return []
        raw = getattr(field, "raw", None)
        if raw is not None:
            return self._inline_children(raw)
        children = getattr(field, "list", None)
        if children is not None:
            return self._inline_children(children)
        if isinstance(field, str):
            return [field]
        return []

    def _render_math_items(self, items):
        children = []
        for item in items:
            children.extend(self._render_math_field(item))
        return children

    def _render_math_scripts(self, atom, base_children):
        children = list(base_children)
        if getattr(atom, "sub", None) is not None:
            children.append(element("sub", self._render_math_field(atom.sub)))
        if getattr(atom, "sup", None) is not None:
            children.append(element("sup", self._render_math_field(atom.sup)))
        return self._math_fragment(children, class_name="math-atom")

    def _raw_text_segments(self, nodes):
        segments = []
        for node in nodes:
            node_type = getattr(node, "node_type", None)
            if node_type == nd.NODE_TYPE.CHAR:
                segments.append(("text", node.font, node.char))
                continue
            if node_type == nd.NODE_TYPE.LIGATURE:
                source = getattr(node, "source", None) or []
                if source:
                    text = "".join(getattr(child, "char", "") for child in source)
                else:
                    text = node.char
                segments.append(("text", node.font, text))
                continue
            if node_type == nd.NODE_TYPE.GLUE:
                segments.append(("text", None, " "))
                continue
            if isinstance(node, mmode.InlineMathNode):
                segments.append(("math", node))
                continue
            if node_type in (
                nd.NODE_TYPE.KERN,
                nd.NODE_TYPE.MARK,
                nd.NODE_TYPE.INS,
                nd.NODE_TYPE.ADJUST,
            ):
                continue
            if node_type == nd.NODE_TYPE.PENALTY:
                if getattr(node, "penalty", None) is not None and node.penalty >= 10000:
                    segments.append(("break",))
                continue
            if node_type == nd.NODE_TYPE.WHATSIT:
                segments.append(("special", self._special_text(node)))
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
        for segment in segments:
            kind = segment[0]
            if kind in ("special", "math", "break"):
                if pending_space and started and kind != "break":
                    normalized.append(("text", None, " "))
                    pending_space = False
                normalized.append(segment)
                continue
            _kind, font, text = segment
            for char in text:
                if char.isspace():
                    if started:
                        pending_space = True
                    continue
                if pending_space:
                    normalized.append(("text", font, " "))
                    pending_space = False
                normalized.append(("text", font, char))
                started = True
        if not normalized:
            return []
        merged = []
        for segment in normalized:
            if segment[0] != "text":
                merged.append(segment)
                continue
            _kind, font, text = segment
            if (
                merged
                and merged[-1][0] == "text"
                and self._font_signature(merged[-1][1]) == self._font_signature(font)
            ):
                merged[-1] = ("text", merged[-1][1], merged[-1][2] + text)
                continue
            merged.append(("text", font, text))
        return merged

    def _special_marker(self, text):
        attrs = {
            "class_": "tex-special",
            "aria-hidden": "true",
            "data-tex-special": text,
        }
        return element("span", **attrs)

    def _special_action(self, text):
        if text is None:
            return None
        stripped = text.strip()
        if not stripped:
            return None
        match = _DEST_RE.match(stripped)
        if match is not None:
            return {"kind": "dest", "target": match.group(1)}
        match = _GOTO_RE.search(stripped)
        if match is not None and _BEGINANN_RE.match(stripped):
            return {"kind": "link-start", "href": f"#{match.group(1)}"}
        match = _GOTOR_RE.search(stripped)
        if match is not None and _BEGINANN_RE.match(stripped):
            href = match.group(1)
            if match.group(2):
                href = f"{href}#{match.group(2)}"
            return {"kind": "link-start", "href": href}
        if _ENDANN_RE.match(stripped):
            return {"kind": "link-end"}
        return {"kind": "marker", "text": stripped}

    def _inline_children(self, nodes, base_font=None):
        children = []
        link_stack = []
        pending_break = False

        def append(child):
            if child is None:
                return
            nonlocal pending_break
            if pending_break:
                target = link_stack[-1]["children"] if link_stack else children
                target.append(element("br"))
                pending_break = False
            if link_stack:
                link_stack[-1]["children"].append(child)
            else:
                children.append(child)

        for segment in self._normalize_segments(self._raw_text_segments(nodes)):
            kind = segment[0]
            if kind == "special":
                action = self._special_action(segment[1])
                if action is None:
                    continue
                if action["kind"] == "dest":
                    append(element("span", id=action["target"], class_="tex-dest"))
                    continue
                if action["kind"] == "link-start":
                    link_stack.append({"href": action["href"], "children": []})
                    continue
                if action["kind"] == "link-end":
                    if not link_stack:
                        continue
                    link = link_stack.pop()
                    append(element("a", link["children"], href=link["href"], class_="tex-link"))
                    continue
                append(self._special_marker(action["text"]))
                continue
            if kind == "break":
                pending_break = True
                continue
            if kind == "math":
                append(element("span", self._render_math_field(segment[1]), class_=["math", "inline-math"]))
                continue
            _kind, font, text = segment
            attrs = self._font_attrs(font, base_font)
            if attrs:
                append(element("span", text, **attrs))
            else:
                append(text)
        while link_stack:
            link = link_stack.pop(0)
            append(element("a", link["children"], href=link["href"], class_="tex-link"))
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

    @staticmethod
    def _owner_raw_nodes(owner):
        raw = getattr(owner, "raw", None)
        if raw is not None:
            return raw
        return getattr(owner, "list", ())

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
                raw_nodes = self._owner_raw_nodes(cell)
                attrs.update(self._font_attrs(dominant, self._body_font))
                cells.append(
                    element(
                        "td",
                        self._inline_children(raw_nodes, dominant),
                        **attrs,
                    )
                )
            if cells:
                rows.append(element("tr", cells))
        return rows

    def _display_math_children(self, owner):
        children = self._render_math_items(getattr(owner, "list", ()))
        eqno = getattr(owner, "eqno", None)
        if eqno is None:
            return children
        eqno_list, left = eqno
        eqno_children = self._render_math_items(getattr(eqno_list, "list", ()))
        if not eqno_children:
            return children
        label = element("span", eqno_children, class_="eqno")
        if left:
            return [label] + children
        return children + [label]

    def _render_owner(self, owner):
        if isinstance(owner, paragraph.Paragraph):
            dominant = self._dominant_font(owner.list)
            children = self._inline_children(self._owner_raw_nodes(owner), dominant)
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
            children = self._display_math_children(owner)
            if not children:
                return []
            return [element("div", children, class_="display-math")]
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
            children = self._render_math_items(getattr(owner, "list", ()))
            if not children:
                return []
            return [element("div", children, class_="display-math")]
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
        if node_type == nd.NODE_TYPE.WHATSIT:
            text = self._special_text(owner)
            if text is None:
                return []
            action = self._special_action(text)
            if action is None:
                return []
            if action["kind"] == "dest":
                return [element("span", id=action["target"], class_="tex-dest")]
            if action["kind"] == "marker":
                return [self._special_marker(action["text"])]
            return []
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
