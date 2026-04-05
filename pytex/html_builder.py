"""Minimal internal HTML builder for reflow-style output."""

from __future__ import annotations

import html as _html


_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class Fragment:
    def __init__(self, children=()):
        self.children = list(_iter_children(children))


class Element:
    def __init__(self, name, attrs=None, children=()):
        self.name = name
        self.attrs = {} if attrs is None else dict(attrs)
        self.children = list(_iter_children(children))


def fragment(*children):
    return Fragment(children)


def element(name, *children, **attrs):
    return Element(name, _normalize_attrs(attrs), children)


def render(node):
    out = []
    _render(node, out)
    return "".join(out)


def _iter_children(children):
    for child in children:
        if child is None:
            continue
        if isinstance(child, (str, Fragment, Element)):
            yield child
            continue
        if isinstance(child, (list, tuple)):
            for nested in _iter_children(child):
                yield nested
            continue
        yield str(child)


def _normalize_attrs(attrs):
    normalized = {}
    for key, value in attrs.items():
        key = key[:-1] if key.endswith("_") else key
        if value is None or value is False:
            continue
        if isinstance(value, dict):
            parts = [str(name) for name, enabled in value.items() if enabled]
            if not parts:
                continue
            value = " ".join(parts)
        elif isinstance(value, (list, tuple, set)):
            parts = [str(part) for part in value if part]
            if not parts:
                continue
            value = " ".join(parts)
        normalized[key] = value
    return normalized


def _render(node, out):
    if isinstance(node, Fragment):
        for child in node.children:
            _render(child, out)
        return
    if isinstance(node, Element):
        out.append("<")
        out.append(node.name)
        for key, value in node.attrs.items():
            if value is True:
                out.append(f" {key}")
                continue
            escaped = _html.escape(str(value), quote=True)
            out.append(f' {key}="{escaped}"')
        out.append(">")
        if node.name not in _VOID_ELEMENTS:
            for child in node.children:
                _render(child, out)
            out.append(f"</{node.name}>")
        return
    out.append(_html.escape(str(node), quote=False))
