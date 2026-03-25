import inspect

from pytex.module import Module
from pytex import toks
from pytex import integer
from pytex import lists
from pytex.state import Dict, NamedEntry
from pytex.accessor import Accessor
from pytex.token import Command
from pytex.expandable import toksToString, tokenToString


def _diag(parser, lines):
    for line in lines:
        parser.message(line, console=parser.tracingonline > 0)


def _show_limit(value):
    return None if value <= 0 else value


def _normalize_trace_nodes(node, expanded):
    if expanded is None:
        return []
    if isinstance(expanded, list):
        nodes = expanded
    else:
        try:
            nodes = list(expanded)
        except TypeError:
            nodes = [expanded]
    for item in nodes:
        if item is node:
            continue
        if getattr(item, "source", None) is None:
            item.source = node
    return nodes


def _trace_expand_node(parser, node):
    typeset = getattr(node, "typeset", None)
    if typeset is None:
        return None
    try:
        params = list(inspect.signature(typeset).parameters.values())
    except (TypeError, ValueError):
        return None
    positional = [
        p for p in params
        if p.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    ]
    has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
    if (not has_varargs) and len(positional) != 2:
        return None
    packed = []
    typeset(parser, packed)
    return _normalize_trace_nodes(node, packed)


def _trace_label(node):
    label = getattr(node, "list_type_name", None)
    if label is not None:
        return label
    return type(node).__name__


def _show_items(parser, lines, items, prefix, depth):
    if depth is not None and depth < 0:
        lines.append(prefix + "...")
        return
    breadth = _show_limit(parser.state.parameters["showboxbreadth"])
    shown = items if breadth is None else items[:breadth]
    child_depth = None if depth is None else depth - 1
    for node in shown:
        _show_node(parser, lines, node, prefix, child_depth)
    if breadth is not None and len(items) > breadth:
        lines.append(prefix + "etc.")


def _show_node(parser, lines, node, prefix="", depth=None):
    meaning = getattr(node, "meaning", None)
    if meaning is None:
        expanded = _trace_expand_node(parser, node)
        if expanded is not None:
            _show_items(parser, lines, expanded, prefix, depth)
            return
        lines.append(prefix + _trace_label(node))
    else:
        lines.append(prefix + meaning(parser))
    items = getattr(node, "list", None)
    if items:
        _show_items(parser, lines, items, prefix + ".", depth)


def _show_box(parser, box):
    if box is None:
        return ["void"]
    lines = [box.meaning(parser)]
    depth = _show_limit(parser.state.parameters["showboxdepth"])
    items = getattr(box, "list", None)
    if items:
        _show_items(parser, lines, items, ".", depth)
    return lines


def _show_list(parser, current):
    is_main_vlist = (
        getattr(current, "type", None) == lists.LISTTYPE.VERTICAL
        and not getattr(current, "inner", True)
    )
    lines = [] if is_main_vlist else [current.list_type_name]
    depth = _show_limit(parser.state.parameters["showboxdepth"])
    nodes = current.concreteNodes() if hasattr(current, "concreteNodes") else list(current)
    _show_items(parser, lines, nodes, "" if is_main_vlist else ".", depth)
    return lines


def _format_shipout_number(parser):
    values = [int(parser.state.count[index]) for index in range(10)]
    last = 0
    for index in range(9, 0, -1):
        if values[index] != 0:
            last = index
            break
    return ".".join(str(value) for value in values[: last + 1])


def traceOutputPage(parser, box):
    if parser.tracingoutput <= 0:
        return
    lines = [f"Completed box being shipped out [{_format_shipout_number(parser)}]"]
    lines.extend(_show_box(parser, box))
    _diag(parser, lines)


def checkRange(parser):
    """
    check whether the current input stack is in the tracing range
    @return: True if the current input stack is in the tracing range, False otherwise    
    The tracing range is specified by tracingsource, tracinglinebegin, tracinglineend, tracingquitatend
    """
    pos = parser.input.position()
    if parser.tracingsource and parser.tracingsource != pos.file:
        return False
    if parser.tracinglinebegin > 0 and parser.tracinglinebegin > pos.line:
        return False
    if parser.tracinglineend > 0 and parser.tracinglineend < pos.line:
        if parser.tracingquitatend > 0:
            parser.run = False
            # clear the ifstack
            parser.ifstack = []
        return False
    return True


def trace(parser, t, mode: str):
    """
    trace the commands being expanded or executed
    @param t: the token being expanded
    @param mode: "expand" or "execute"
    """
    if not parser.checkRange():
        return
    if parser.tracingcommands and t.definition is not None:
        meaning = t.meaning(parser)
    else:
        meaning = ""
    parser.message(f"{mode} {t.name} at {parser.input.position()}: {meaning}\n")


class TracingEntry(NamedEntry):
    """
    A tracing entry that can be used to trace the commands being expanded or executed.
    It is a NamedEntry, so it has a name and a value.
    """
    def __init__(self, state, domain, name):
        self.state = state
        self.domain = domain
        self.name = name
        self.parser = state.tracing.parser
        self.value = getattr(self.parser, name)

    def saveInfo(self):
        return {"domain": self.domain.name, "name": self.name}, None

    @classmethod
    def new(cls, parser, **kargs):
        """
        create a new accessor from the dictionary
        @param parser: the parser
        @param kargs: the keyword arguments
        @return: the command
        """
        domain = kargs["domain"]
        name = kargs["name"]
        return cls(getattr(parser.state, domain), name)

    def set(self, value):
        """
        set the value of the entry
        @param value: the value to be set
        """
        super().set(value)
        setattr(self.parser, self.name, value)

    def setGlobal(self, value):
        """
        set the value of the entry globally
        @param value: the value to be set
        """
        super().setGlobal(value)
        setattr(self.parser, self.name, value)

    def __eq__(self, other):
        """
        check if the entry is equal to another entry or value
        @param other: the other entry or value
        @return: True if the entry is equal to the other, False otherwise
        """
        return other == self.value
    
    def __repr__(self):
        return repr(self.value)


class Tracing(Dict):
    """
    A dictionary that contains the tracing parameters.
    It is a Dict, so it can be used to access the tracing parameters.
    """
    def __init__(self, parser):
        super().__init__("tracing", parser.state)
        self.parser = parser

    def entry(self, key):
        """
        get the entry of the domain at the index
        @param key: the index of the value
        @return: the NamedEntry object at the index
        """
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            entry = TracingEntry(self.state, self.name, key)
            dict.__setitem__(self, key, entry)
            return entry

    def __getitem__(self, key):
        """
        get the value of the domain at the index
        @param key: the index of the value
        @return: the value at the index
        """
        try:
            return dict.__getitem__(self, key).value
        except KeyError:
            dict.__setitem__(self, key, TracingEntry(self.state, self.name, key))
            return None
    
    def __setitem__(self, key, value):
        """
        set the value of the domain at the index
        @param key: the index of the value
        @param: the value
        """
        try:
            dict.__getitem__(self, key).set(value)
        except KeyError:
            dict.__setitem__(self, key,  TracingEntry(self.state, self.name, key, value))


class TracingSource(Accessor):
    """
    The \\tracingsource command.
    It sets the source file for tracing.
    """
    def readValue(self, parser):
        return toksToString(parser, toks.readGeneralText(parser))
    
    def set(self, parser, value):
        parser.tracingsource = value

    def setGlobal(self, parser, value):
        parser.tracingsource = value


class Show(Command):
    """
    The \\show command.
    """
    def execute(self, parser):
        t = parser.skipSpaces(False)
        if t is None:
            raise ValueError("missing token after \\show", parser.input.position())
        _diag(parser, [f"> {tokenToString(parser, t)}={t.meaning(parser)}", "OK."])


class ShowThe(Command):
    """
    The \\showthe command.
    """
    def execute(self, parser):
        tokens = parser.builtin["\\the"].expanded(parser)
        _diag(parser, [f"> {toksToString(parser, tokens)}", "OK."])


class ShowBox(Command):
    """
    The \\showbox command.
    """
    def execute(self, parser):
        index = parser.readInteger()
        box = parser.state.box[index]
        lines = [f"> \\box{index}="]
        lines.extend(_show_box(parser, box))
        lines.append("OK.")
        _diag(parser, lines)


class ShowLists(Command):
    """
    The \\showlists command.
    """
    def execute(self, parser):
        lines = ["> \\showlists"]
        for level, current in enumerate(reversed(parser.lists)):
            is_main_vlist = (
                getattr(current, "type", None) == lists.LISTTYPE.VERTICAL
                and not getattr(current, "inner", True)
            )
            if not is_main_vlist:
                lines.append(f"### list {level}")
            lines.extend(_show_list(parser, current))
        lines.append("OK.")
        _diag(parser, lines)


def init(parser):
    """
    initialize the tracing module
    @param parser: the parser
    """
    # set the initial values for the tracing parameters
    parser.tracingonline = 0
    parser.tracingmacros = 0
    parser.tracingstats = 0
    parser.tracingparagraphs = 0
    parser.tracingpages = 0
    parser.tracingoutput = 0
    parser.tracinglostchars = 0
    parser.tracingcommands = 0
    parser.tracingrestores = 0
    # set the initial values for the pytex tracing parameters
    parser.tracingsource = ""
    parser.tracinglinebegin = 0
    parser.tracinglineend = 0
    parser.tracingquitatend = 0
    parser.state.tracing = Tracing(parser)


mod = Module("tracing",
    parameters = {
        # tex tracing facilities
        "tracingonline": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        "tracingmacros": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        "tracingstats": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        "tracingparagraphs": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        "tracingpages": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        "tracingoutput": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        "tracinglostchars": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        "tracingcommands": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        "tracingrestores": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        # pytex tracing facilities
        # the line number to start tracing, an integer
        "tracinglinebegin": {"value": 0, "accessor": toks.ToksParameterAccessor, "domain": "tracing"},
        # the line number to stop tracing, an integer
        "tracinglineend": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
        # whether to stop tracing, an integer (0 is False, nonzero is True)
        "tracingquitatend": {"value": 0, "accessor": integer.IntegerParameterAccessor, "domain": "tracing"},
    },
    attributes = {
        "checkRange": checkRange,
        "trace": trace,
        "traceOutputPage": traceOutputPage,
    },
    commands = {
        "tracingsource": TracingSource(),
        "show": Show(),
        "showthe": ShowThe(),
        "showbox": ShowBox(),
        "showlists": ShowLists(),
    },
    init = init,
)
