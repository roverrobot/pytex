"""
Allowlisted handlers for TeX-style `|command ...` input streams.
"""

import importlib
import re
import shlex


_PIPE_COMMANDS = {}
_PIPE_NAME_RE = re.compile(r"[A-Za-z0-9_-]+")


def registerPipeCommand(name, handler):
    """
    Register a process-wide pipe-command handler.

    The handler receives `(resolver, args)` and returns a text string, or
    `None` to indicate failure.
    """
    _PIPE_COMMANDS[name] = handler


def unregisterPipeCommand(name):
    """
    Remove a previously registered pipe-command handler.
    """
    _PIPE_COMMANDS.pop(name, None)


def parsePipeCommand(spec):
    """
    Parse a TeX-style `|command ...` file name.
    """
    if not spec.startswith("|"):
        return None
    text = spec[1:].strip()
    if not text:
        return None
    try:
        parts = shlex.split(text)
    except ValueError:
        return None
    if not parts:
        return None
    return parts[0], parts[1:]


def _loadPipeCommand(name):
    """
    Try to load a handler module for the given command name.
    """
    if not _PIPE_NAME_RE.fullmatch(name):
        return
    module = name.replace("-", "_")
    try:
        importlib.import_module(f"pytex.pipes.{module}")
    except ModuleNotFoundError as exc:
        if exc.name != f"pytex.pipes.{module}":
            raise


def openPipe(resolver, spec):
    """
    Execute an allowlisted pipe command through a registered handler.
    """
    parsed = parsePipeCommand(spec)
    if parsed is None:
        return None
    name, args = parsed
    handler = _PIPE_COMMANDS.get(name)
    if handler is None:
        _loadPipeCommand(name)
        handler = _PIPE_COMMANDS.get(name)
    if handler is None:
        return None
    return handler(resolver, args)
