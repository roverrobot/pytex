"""
Assignment commands are commands that assign values to registers or parameters

Most assignments also access the value of the register or parameter. For example,
the \\count command assigns a value to a count register and also returns the value
of the count register. Such a commands us called an Accessor. An Accessor points to 
a specific value, could be an item in an array, or a parameter. The latter is also
an item int heequitable. So the Accessor class denote the value that it poitns to by
a domain and an index. 

There are two main methods in the Accessor class: getValue and assign. When the command
is executed, it is an assignment.  On the other hand, the command may be read by other 
commands. In this case, the command is not an assignment, but the getValue() method is called.

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
    t = parser.skipSpaces(expand)
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


class KeyTarget:
    """
    A target backed by ``domain[key]``.
    """
    __slots__ = ("domain", "key", "value_type", "supports_global", "readable", "writable")

    def __init__(self, domain, key, value_type=VALUE_TYPE.UNKNOWN, supports_global=None,
                 readable=True, writable=True):
        self.domain = domain
        self.key = key
        self.value_type = value_type
        if supports_global is None:
            supports_global = hasattr(domain, "setGlobal")
        self.supports_global = supports_global
        self.readable = readable
        self.writable = writable

    def get(self):
        if not self.readable:
            raise ValueError("target is not readable")
        return self.domain[self.key]

    def set(self, value, global_scope=False):
        if not self.writable:
            raise ValueError("target is not writable")
        if global_scope and self.supports_global:
            self.domain.setGlobal(self.key, value)
        else:
            self.domain[self.key] = value
        return value


class AttrTarget:
    """
    A target backed by ``getattr(obj, attr)`` / ``setattr(obj, attr, value)``.
    """
    __slots__ = ("domain", "key", "value_type", "readable", "writable")

    def __init__(self, obj, attr, value_type=VALUE_TYPE.UNKNOWN, readable=True, writable=True):
        self.domain = obj
        self.key = attr
        self.value_type = value_type
        self.readable = readable
        self.writable = writable

    def get(self):
        if not self.readable:
            raise ValueError("target is not readable")
        return getattr(self.domain, self.key)

    def set(self, value, global_scope=False):
        if not self.writable:
            raise ValueError("target is not writable")
        setattr(self.domain, self.key, value)
        return value


def makeTarget(domain, key, value_type=VALUE_TYPE.UNKNOWN, **kwargs):
    return KeyTarget(domain, key, value_type, **kwargs)

class Accessor(token.Command):
    """
    access a value in a domain
    @param domain: the domain of the assignment
    @param key: the key of the assignment. None means the key is read from input.
    @param builtin: whether the accessor is a builtin command for serialization
    """
    _MISSING_KEY = object()
    target_type = VALUE_TYPE.UNKNOWN

    def __init__(self, domain=None, key=None, builtin=True):
        self.domain = domain
        self.key = key
        self.builtin = builtin

    def className(self):
        return Builtin.className(self) if self.builtin else Serializable.className(self)

    def saveInfo(self):
        if self.builtin:
            return Builtin.saveInfo(self)
        return {"domain": self.domain.name, "key": self.key}, None

    init_needs_parser = True

    @classmethod
    def new(cls, parser, **kargs):
        """
        create a non-builtin accessor from serialized data
        """
        return cls(getattr(parser, kargs["domain"]), kargs["key"], builtin=False)

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
        return type(self).readKey is not Accessor.readKey

    def canBindInternalValue(self):
        """
        whether this accessor can safely bind itself for parser.readInternalValue()
        """
        return self.key is not None or not self.needsKey()

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
        return KeyTarget(self.domain, self.currentKey(parser), self.target_type)

    def readTarget(self, parser):
        """
        compatibility alias for older target-reading call sites
        """
        return self.getTarget(parser)

    def readValue(self, parser):
        """
        read the value from the input stack
        @param parser: the parser
        """
        raise NotImplementedError("readValue method must be implemented in a subclass")

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

    def assign(self, parser, prefixes):
        """
        assign the value to the index
        @param parser: the parser
        @param prefixes: the prefixes to the assignment
        """
        if self.key is None and self.needsKey():
            return self.bindKey(self.readKey(parser)).assign(parser, prefixes)
        target = self.getTarget(parser)
        self.readEq(parser)
        value = self.readValue(parser)
        globally = False
        try:
            for p in prefixes:
                value, globally = p.modify(value, globally)
        except ValueError as e:
            e.args = (e.args[0], parser.input.position())
            raise e
        globally = parser.resolveGlobalScope(globally)
        target.set(value, global_scope=globally)
        parser.afterAssignment()

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
        self.assign(parser, prefixes=[])

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
    
    def assign(self, parser, prefixes):
        """
        execute the prefix. It reads an assignment from the input stack
        then calls the its assign method.
        @param parser: the parser
        """
        prefixes.append(self)
        parser.skipFiller()
        t = parser.token()
        if t is None:
            raise ValueError("expecting an assignment", parser.input.position())
        assign = getattr(t.definition, "assign", None)
        if assign is None:
            raise ValueError("expecting an assignment", parser.input.position())
        if parser.tracingcommands > 0:
            parser.trace(t, "execute")
        assign(parser, prefixes)

    def execute(self, parser):
        """
        execute the prefix
        @param parser: the parser
        """
        self.assign(parser, [])


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
