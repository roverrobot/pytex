"""
Assignment commands are commands that assign values to registers or parameters

Most assignments also access the value of the register or parameter. For example,
the \\count command assigns a value to a count register and also returns the value
of the count register. Such a commands us called an Accessor. An Accessor points to 
a specific value, could be an item in an array, or a parameter. The latter is also
an item int heequitable. So the Accessor class denote the value that it poitns to by
a domain and an index. 

There are two main methods in the Accessor class: readValue and getAssignment. When the
command is executed, it is an assignment. On the other hand, the command may be read by
other commands. In this case, the command is not an assignment, but readValue() is called.

"""

import copy
import enum
from pytex import token
from pytex.module import Module
from pytex.serialization import Serializable, Builtin


def skipEq(parser, expand: bool=True):
    """
    read the equal sign from the input stack
    @param parser: the parser
    """
    t = parser.skipSpaces() if expand else parser.skipSpacesNoExpand()
    if t is None:
        return
    # read the equal sign
    if t.catcode != token.CATCODE.OTHER or t.name != "=":
        parser.input.unread(t)


class VALUE_TYPE(enum.IntEnum):
    UNKNOWN = 0
    INT = 1
    DIMEN = 2
    GLUE = 3
    MUGLUE = 4
    BOX = 5
    TOKS = 6
    FONT = 7
    MEANING = 8


def canReadAs(source_type, requested_type):
    """
    Whether a value of ``source_type`` can satisfy ``requested_type``.
    """
    if requested_type == VALUE_TYPE.UNKNOWN:
        return True
    compatible_targets = {
        VALUE_TYPE.INT: {VALUE_TYPE.INT},
        VALUE_TYPE.DIMEN: {VALUE_TYPE.INT, VALUE_TYPE.DIMEN},
        VALUE_TYPE.GLUE: {VALUE_TYPE.INT, VALUE_TYPE.DIMEN, VALUE_TYPE.GLUE},
        VALUE_TYPE.MUGLUE: {VALUE_TYPE.INT, VALUE_TYPE.DIMEN, VALUE_TYPE.MUGLUE},
        VALUE_TYPE.BOX: {VALUE_TYPE.BOX},
        VALUE_TYPE.TOKS: {VALUE_TYPE.TOKS},
        VALUE_TYPE.FONT: {VALUE_TYPE.FONT},
        VALUE_TYPE.MEANING: {VALUE_TYPE.MEANING},
    }
    return requested_type in compatible_targets.get(source_type, set())


class KeyTarget:
    """
    A target backed by ``domain[key]``.
    """
    __slots__ = ("domain", "key", "value_type", "supports_global", "readable")

    def __init__(self, domain, key, value_type=VALUE_TYPE.UNKNOWN, supports_global=None,
                 readable=True):
        self.domain = domain
        self.key = key
        self.value_type = value_type
        if supports_global is None:
            supports_global = hasattr(domain, "setGlobal")
        self.supports_global = supports_global
        self.readable = readable

    def get(self):
        if not self.readable:
            raise ValueError("target is not readable")
        return self.domain[self.key]

    def set(self, value, global_scope=False):
        if global_scope and self.supports_global:
            self.domain.setGlobal(self.key, value)
        else:
            self.domain[self.key] = value
        return value


class AttrTarget:
    """
    A target backed by ``getattr(obj, attr)`` / ``setattr(obj, attr, value)``.
    """
    __slots__ = ("domain", "key", "value_type", "readable")

    def __init__(self, obj, attr, value_type=VALUE_TYPE.UNKNOWN, readable=True):
        self.domain = obj
        self.key = attr
        self.value_type = value_type
        self.readable = readable

    def get(self):
        if not self.readable:
            raise ValueError("target is not readable")
        return getattr(self.domain, self.key)

    def set(self, value, global_scope=False):
        setattr(self.domain, self.key, value)
        return value


class ReadOnlyTarget:
    """
    A target that simply stores a readable value.
    """
    __slots__ = ("value", "value_type", "readable")

    def __init__(self, value, value_type=VALUE_TYPE.UNKNOWN):
        self.value = value
        self.value_type = value_type
        self.readable = True

    def get(self):
        return self.value

    def set(self, value, global_scope=False):
        raise ValueError("target is not writable")


def makeTarget(domain, key, value_type=VALUE_TYPE.UNKNOWN, **kwargs):
    return KeyTarget(domain, key, value_type, **kwargs)


class Assignment:
    """
    A parsed assignment occurrence.
    """
    __slots__ = ("target", "value", "global_scope")

    def __init__(self, target, value, global_scope=False):
        self.target = target
        self.value = value
        self.global_scope = global_scope

    def apply(self, parser):
        globally = parser.resolveGlobalScope(self.global_scope)
        self.target.set(self.value, global_scope=globally)
        parser.afterAssignment()
        return self.value

class Accessor(token.Command):
    """
    access a value in a domain
    @param domain: the domain of the assignment
    @param key: the key of the assignment. None means the key is read from input.
    @param builtin: whether the accessor is a builtin command for serialization
    """
    _MISSING_KEY = object()
    value_type = VALUE_TYPE.UNKNOWN

    def __init__(self, domain=None, key=None, builtin=True, *, value_type=None, read_key=None):
        self.domain = domain
        self.key = key
        self.builtin = builtin
        self.value_type = self.__class__.value_type if value_type is None else value_type
        self._read_key = read_key

    def className(self):
        return Builtin.className(self) if self.builtin else Serializable.className(self)

    def saveInfo(self):
        if self.builtin:
            return Builtin.saveInfo(self)
        info = {"domain": self.domain.name, "key": self.key}
        if type(self) is Accessor:
            info["value_type"] = int(self.value_type)
        return info, None

    init_needs_parser = True

    @classmethod
    def new(cls, parser, **kargs):
        """
        create a non-builtin accessor from serialized data
        """
        return cls(
            getattr(parser, kargs["domain"]),
            kargs["key"],
            builtin=False,
            value_type=VALUE_TYPE(kargs.get("value_type", kargs.get("target_type", cls.value_type))),
        )

    def bindKey(self, key):
        """
        create a fixed-key accessor of the same kind
        """
        bound = copy.copy(self)
        bound.key = key
        return bound

    def needsKey(self):
        """
        whether this accessor reads a key from input when it is not fixed
        """
        return self._read_key is not None or type(self).readKey is not Accessor.readKey

    def canBindInternalValue(self):
        """
        whether this accessor can safely bind itself for parser.readInternalValue()
        """
        return True

    def readEq(self, parser):
        """
        read the equal sign from the input stack
        @param parser: the parser
        """
        return parser.skipEq(expand=True)

    def readKey(self, parser):
        """
        read the key from the input stack when this accessor is not bound to one
        """
        if self._read_key is not None:
            return self._read_key(parser)
        raise NotImplementedError("readKey method must be implemented when key is not fixed")

    def currentKey(self, parser):
        """
        return the active key for this accessor
        """
        if self.key is not None:
            return self.key
        if self.needsKey():
            return self.readKey(parser)
        return None

    def getTarget(self, parser):
        """
        return the bound target for this accessor occurrence
        """
        return KeyTarget(self.domain, self.currentKey(parser), self.value_type)

    def readAssignmentValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        return parser.readValue(self.value_type)

    def readValue(self, parser, requested_type):
        if not self.canBindInternalValue():
            return None, None
        if not canReadAs(self.value_type, requested_type):
            return None, None
        target = self.getTarget(parser)
        if not getattr(target, "readable", True):
            return None, None
        try:
            value = target.get()
        except (IndexError, KeyError, TypeError, ValueError):
            return None, None
        return value, target.value_type

    def set(self, parser, value):
        """
        set the value in the domain.
        @param parser: the parser
        @param value: the value
        """
        target = self.getTarget(parser)
        try:
            target.set(value, global_scope=False)
        except IndexError:
            domain, key = target.domain, target.key
            name = getattr(domain, "name", domain)
            raise ValueError(f"index {key} out of range for domain {name}", parser.input.position())
    
    def setGlobal(self, parser, value):
        """
        set the value in the domain globally.
        @param parser: the parser
        @param value: the value
        """
        self.getTarget(parser).set(value, global_scope=True)

    def getAssignment(self, parser):
        if self.key is None and self.needsKey():
            return self.bindKey(self.readKey(parser)).getAssignment(parser)
        target = self.getTarget(parser)
        self.readEq(parser)
        value = self.readAssignmentValue(parser)
        return Assignment(target, value)

    def meaning(self, parser):
        key = self.key
        if key is None:
            return parser.formatName(self.name) if self.name is not None else None
        name = getattr(self.domain, "name", None)
        return f"{name if name is not None else self.domain}{key}"
    
    def execute(self, parser):
        """
        execute the assignment command. The default behavior is to raise an error.
        @param parser: the parser
        """
        self.getAssignment(parser).apply(parser)

class Prefix(token.Command):
    """
    A prefix to an assignment
    """    
    def modify(self, value, globally: bool):
        """
        modify the value
        @param value: the value
        @param globally: whether the assignment is global
        @return: the modified value and whether the assignment is global
        """
        raise ValueError("prefix not defined")

    def modifyAssignment(self, parser, assignment):
        value, globally = self.modify(assignment.value, assignment.global_scope)
        assignment.value = value
        assignment.global_scope = globally
        return assignment

    def getAssignment(self, parser):
        parser.skipFiller()
        t = parser.token()
        if t is None:
            raise ValueError("expecting an assignment", parser.input.position())
        meaning = t.definition
        if meaning is None:
            raise ValueError("expecting an assignment", parser.input.position())
        if parser.tracingcommands > 0:
            parser.trace(t, "execute")
        getter = getattr(meaning, "getAssignment", None)
        assignment = None if getter is None else getter(parser)
        if assignment is None:
            raise ValueError("expecting an assignment", parser.input.position())
        return self.modifyAssignment(parser, assignment)

    def execute(self, parser):
        """
        execute the prefix
        @param parser: the parser
        """
        self.getAssignment(parser).apply(parser)


class GlobalPrefix(Prefix):
    """
    The global prefix
    """
    def modify(self, value, globally: bool):
        return value, True


class AfterAssignment(token.Command):
    """
    the \\afterassignment command

    It reads the next (unexpanded) token and stores it in the afterassignment parameter.
    """
    def execute(self, parser):
        """
        execute the command
        @param parser: the parser
        """
        t = parser.token()
        if t is None:
            raise ValueError("expecting a token")
        parser.globals["afterassignment"] = t


module = Module("assignment", 
    commands = {
        "global": GlobalPrefix(),
        "afterassignment": AfterAssignment(),
    },
    parameters= {
        # this token should not have any accessor, because users only interact
        # with it via the afterassignment command.
        "afterassignment": {"value": None, "accessor": None, "domain": "globals"},
    },
    attributes={
        "skipEq": skipEq
    }
)
