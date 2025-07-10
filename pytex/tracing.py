from pytex.module import Module
from pytex import toks
from pytex import integer
from pytex.state import Dict, NamedEntry
from pytex.accessor import Accessor
from pytex.expandable import toksToString


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

    def saveInfo(self):
        return {"init": {"domain": self.domain.name, "name": self.name}}

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
    parser.state.tracing.parser = parser


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
    },
    commands = {
        "tracingsource": TracingSource(),
    },
    init = init,
)
