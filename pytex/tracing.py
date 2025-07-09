from pytex.module import Module
from pytex import toks
from pytex import integer
from pytex.state import Dict, NamedEntry, NamedSavedValue


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
    if parser.tracingcommands > 1 and t.definition is not None:
        meaning = str(t.definition)
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
    parser.state.tracing = Dict(parser)
    parser.state.tracing.parser = parser


mod = Module("tracing",
    parameters = {
        # tex tracing facilities
        "tracingonline": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        "tracingmacros": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        "tracingstats": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        "tracingparagraphs": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        "tracingpages": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        "tracingoutput": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        "tracinglostchars": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        "tracingcommands": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        "tracingrestores": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        # pytex tracing facilities
        # the source file to trace, pytex extension, a string containing the file name
        "tracingsource": {"value": "", "accessor": toks.ToksAccessor, "domain": "tracing"},
        # the line number to start tracing, an integer
        "tracinglinebegin": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        # the line number to stop tracing, an integer
        "tracinglineend": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
        # whether to stop tracing, an integer (0 is False, nonzero is True)
        "tracingquitatend": {"value": 0, "accessor": integer.IntegerAccessor, "domain": "tracing"},
    },
    attributes = {
        "checkRange": checkRange,
        "trace": trace,
    },
    init = init,
)
