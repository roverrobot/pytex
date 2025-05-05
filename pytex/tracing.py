from pytex.module import Module
from pytex import toks
from pytex import integer


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


class Proxy(dict):
    """
    A proxy to change other objects
    """
    def __init__(self):
        self.obj = None

    def attach(self, obj):
        """
        attacht to an object
        """
        self.obj = obj
        if obj is not None:
            for key, value in self.items():
                setattr(obj, key,value)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if self.obj is not None:
            setattr(self.obj, key, value)


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
    domains = {
        "tracing": {"generator": Proxy, "accessor": None},
    },
)
