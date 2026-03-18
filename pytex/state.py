"""
This file defines facilities to implement versioned values and groups.
"""


import typing
from pytex import serialization
from pytex.module import Module
from pytex.token import Command
import enum

class GROUP_TYPE(enum.IntEnum):
    """
    the type of a group, as specified in e-TeX manual.
    """
    BOTTOM = 0 # no group
    SIMPLE = 1 # started by {, ended by }
    HBOX = 2
    ADJUSTED_HBOX = 3
    VBOX = 4
    VTOP = 5
    ALIGN = 6
    NO_ALIGN = 7
    OUTPUT = 8
    MATH = 9
    DISC = 10
    INSERT = 11
    VCENTER = 12
    MATH_CHOICE = 13
    SEMI_SIMPLE = 14 # started by \begingroup, ended by \endgroup
    MATH_SHIFT = 15
    MATH_LEFT = 16


class Group:
    """
    a group is a collection of values that are bound to a certain scope.
    To implement a group, we store old values in the group, while the new values
    are stored in situ. When the group is closed, the old values are restored.
    @param position: the position of the token starting the group
    @param group_type: the type of the group
    @param to_end: callback executed before local values are restored
    @param ended: callback executed after the group is closed
    """
    def __init__(self, position, group_type: GROUP_TYPE, to_end=None, ended=None):
        self.group_type = group_type
        self.position = position
        self.to_end = to_end
        self.ended = ended
        # the aftergroup tokens
        self.aftergroup = []
        # values holds the saved values, where the key is the name of a domain, e.g., "catcode", 
        # "equitable" etc, and the value is a tuple, which first value is the domain, and 
        # the second is a dict that maps the index to the saved value.
        self.values = {}

    def store(self, domain, index):
        """
        return the store to save a value in the group.
        @param domain: the domain
        @param index: the index of the value
        """
        if domain not in self.values:
            store = {}
            self.values[domain] = store
        else:
            store = self.values[domain]
        return None if index in store else store

    def match(self, group_type: GROUP_TYPE):
        """
        check if the group type matches the group type of the group
        @param group_type: the group type
        @return: True if the group type matches, False otherwise
        """
        if group_type == self.group_type:
            return True
        if self.group_type == GROUP_TYPE.SEMI_SIMPLE or self.group_type == GROUP_TYPE.MATH_SHIFT:
            return False
        return group_type ==  GROUP_TYPE.SIMPLE

    def end(self, position, group_type: GROUP_TYPE):
        """
        end the group, and restore the old values. This is valid only if the group_type
        matches the type that started the group.
        @param group_type: the type of the group
        @param position: the position of the token ending the group
        """
        if not self.match(group_type):
            raise ValueError(f"mismatched group type starting at {self.position} and ending at {position}")
        for store in self.values.values():
            for saved in store.values():
                saved.restore()

    def remove(self, domain, index):
        """
        remove a value from the group.
        @param domain: the domain of the value
        @param index: the index of the value
        """
        if domain not in self.values:
            return
        store = self.values[domain]
        if index in store:
            del store[index]
        

class NamedSavedValue:
    """
    a saved value in the group for a Dict.
    @param value: the Entry holding the value
    """
    def __init__(self, domain, name, value):
        self.domain = domain
        self.index = name
        self.entry = value
        self.value = value.value

    def restore(self):
        """
        restore the value at the index in the domain
        """
        self.entry.value = self.value


class Domain:
    """
    an interface for a domain that holds values.
    """
    def store(self, index, value):
        """
        return a stored value in the group.
        @param index: the index of the value
        @param value: the value to be saved
        @return: a SaveValue object that holds the saved value
        """
        pass

    def setGlobal(self, index, value):
        """
        set the value of the domain at the index globally
        @param index: the index of the value
        @param: the value

        This is like __setitem__, but also should clear the saved values in the group stack.
        """
        pass

    def load(self, data):
        """
        restore the domain from a dump
        @param data: the data to restore the domain
        """
        pass

    def dump(self):
        """
        dump the domain
        @return: a dict that contains the values of the domain
        """
        pass


class NamedEntry:
    """
    a named value in a domain.
    @param state: the a State object for parser state
    @param domain: the name of the domain
    @param name: the name of the command
    @param value: the value of the command, None meaning undefined.
    """
    def __init__(self, state, domain, name, value=None):
        self.state = state
        self.domain = domain
        self.name = name
        self.value = value

    def set(self, value):
        """
        set the value of the entry
        @param value: the value to be set
        """
        if self.state:
            top = self.state.current_group
            if top:
                store = top.store(self.domain, self.name)
                if store is not None:
                    store[self.name] = NamedSavedValue(self.domain, self.name, self)
        self.value = value

    def setGlobal(self, value):
        """
        set the value of the entry globally
        @param value: the value to be set
        """
        if self.state:
            self.state.remove(self.domain, self.name)
        self.value = value

    def __eq__(self, other):
        """
        check if the entry is equal to another entry or value
        @param other: the other entry or value
        @return: True if the entry is equal to the other, False otherwise
        """
        return other == self.value
    
    def __repr__(self):
        return repr(self.value)

class Dict(dict):
    """
    a domain that is a dict, and respects groups.
    @param name: the name of the domain
    @param values: the values in the domain
    @param state: the a State object for parser state
    """
    def __init__(self, name: str, state=None):
        dict.__init__(self)
        self.name = name
        self.state = state
    
    def entry(self, key):
        """
        get the entry of the domain at the index
        @param key: the index of the value
        @return: the NamedEntry object at the index
        """
        try:
            return dict.__getitem__(self, key)
        except KeyError:
            entry = NamedEntry(self.state, self.name, key)
            dict.__setitem__(self, key, entry)
            return entry

    def __getitem__(self, key):
        """
        get the value of the domain at the index
        @param key: the index of the value
        @return: the value at the index
        """
        return self.entry(key).value
    
    def __setitem__(self, key, value):
        """
        set the value of the domain at the index
        @param key: the index of the value
        @param: the value
        """
        self.entry(key).set(value)

    def __delitem__(self, index):
        """
        delete the value at the index in the domain
        @param index: the index of the value
        """
        raise NotImplementedError("deleting an entry is not supported")

    def load(self, data):
        """
        restore the domain from a dump
        @param data: the data to restore the domain
        """
        for i, v in data.items():
            self.setGlobal(i, v)

    def dump(self):
        data = {}
        for i, v in self.items():
            if v.value is not None:
                data[i] = v.value
        return data

    def setGlobal(self, key, value):
        """
        set the value of the domain at the index globally
        @param key: the index of the value
        @param: the value

        This is like __setitem__, but also should clear the saved values in group_stack.
        """
        if key not in self:
            entry = NamedEntry(self.state, self.name, key)
            dict.__setitem__(self, key, entry)
        else:
            entry = dict.__getitem__(self, key)
        entry.setGlobal(value)
        if self.state:
            self.state.remove(self.name, key)
    

class ArraySavedValue:
    """
    a saved value in the group for an Array.
    @param domain: the domain of the value
    @param index: the index of the value
    @param value: the vEntry holding the value
    """
    def __init__(self, domain, index):
        self.domain = domain.name
        self.array = domain
        self.index = index
        try:
            self.value = domain[index]
        except IndexError:
            raise ValueError(f"index {index} out of range for array {domain.name}")

    def restore(self):
        """
        restore the value at the index in the domain
        """
        self.array._set(self.index, self.value)


class Array:
    SIZE = 256
    """
    an array of values
    """
    def __init__(self, name: str, state=None, default=None):
        self.default = default() if callable(default) else default
        self.list = [self.default for i in range(self.SIZE)]
        self.dict = {}
        self.state = state
        self.name = name
    
    def __setitem__(self, index, value):
        if self.state:
            top = self.state.current_group
            if top:
                store = top.store(self.name, index)
                if store is not None:
                    store[index] = ArraySavedValue(self, index)
        self._set(index, value)

    def _set(self, index, value):
        if index < self.SIZE:
            self.list[index] = value
        else:
            self.dict[index] = value

    def __getitem__(self, index):
        return self.list[index] if index < self.SIZE else self.dict.get(index, self.default)

    def setGlobal(self, index, value):
        """
        set the value of the array at the index globally
        @param index: the index of the value
        @param: the value

        This is like __setitem__, but also should clear the saved values in group_stack.
        """
        if self.state:
            self.state.remove(self.name, index)
        self._set(index, value)

    def load(self, data):
        """
        restore the array from a dump
        @param data: the data to restore the array
        """
        for i, v in data.items():
            self._set(int(i), v)

    def dump(self):
        """
        dump the array
        @return: a dict that contains the array values
        """
        values = {}
        default = self.default
        for i, v in enumerate(self.list):
            if v != default:
                values[i] = v
        return values | self.dict
    

class Globals(dict):
    """
    a dict that holds the global variables, which are not subject to groups.
    """
    def __init__(self):
        dict.__init__(self)
        self.name = "globals"

    def setGlobal(self, key, value):
        self[key] = value


class State:
    """
    stores the state of the parser, including the local and global parameters and registers.
    """
    def __init__(self):
        self.groups = [] # group stack
        self.current_group = None
        self.globals = Globals() # the global variables, which are not subject to groups
        self.volatile = Dict("volatile", self)  # the volatile domain, which will not be dumped
        self.parameters = Dict("parameters", self)  # the parameters domain
        self.equitable = Dict("equitable", self)  # the equitable domain
        self.layout = Dict("layout", self)  # the layout domain
        self.arrays = {}  # a dict of arrays, where the key is the name of the array, and the value is the Array object

    def dump(self):
        """
        dump the state
        @return: a dict that represents the state
        """
        data = {
            "equitable": self.equitable.dump(),
            "parameters": self.parameters.dump(),
            "layout": self.layout.dump(),
        }
        for name, array in self.arrays.items():
            data[name] = array.dump()
        return data
    
    def load(self, data):
        """
        restore the state from a dump
        @param data: a previously dumped data
        """
        # Globals are runtime state and are intentionally not loaded from dumps.
        self.equitable.load(data.get("equitable", {}))
        self.parameters.load(data.get("parameters", {}))
        self.layout.load(data.get("layout", {}))
        for name, array in self.arrays.items():
            if name in data:
                array.load(data[name])

    def remove(self, domain: Domain, index):
        """
        remove a value from the group.
        @param domain: the domain of the value
        @param index: the index of the value
        """
        if self.current_group:
            self.current_group.remove(domain, index)
            for group in self.groups:
                group.remove(domain, index)

    def beginGroup(self, position, group_type: GROUP_TYPE, to_end=None, ended=None):
        """
        begin a group, and push it to the group stack.
        @param position: the position of the token starting the group
        @param group_type: the type of the group
        @param to_end: called before the group values are restored
        @param ended: called after the group is closed
        """
        if self.current_group:
            self.groups.append(self.current_group)
        self.current_group = Group(position, group_type, to_end=to_end, ended=ended)

    def endGroup(self, position, group_type: GROUP_TYPE):
        """
        end the group, and pop it from the group stack.
        @param position: the position of the token ending the group
        @param group_type: the type of the group
        @return the aftergroup tokens
        """
        if not self.current_group:
            raise ValueError("no current group")
        group = self.current_group
        aftergroup = group.aftergroup
        to_end = group.to_end
        ended = group.ended
        if not group.match(group_type):
            raise ValueError(f"mismatched group type starting at {group.position} and ending at {position}")
        if to_end:
            to_end()
        group.end(position, group_type)
        if self.groups:
            self.current_group = self.groups.pop()
        else:
            self.current_group = None
        if ended:
            ended()
        return aftergroup
        

class BeginGroup(Command):
    """
    the \\begingroup command
    """
    def execute(self, parser):
        pos = parser.input.position()
        parser.beginGroup(pos, GROUP_TYPE.SEMI_SIMPLE)


class EndGroup(Command):
    """
    the \\endgroup command
    """
    def execute(self, parser):
        pos = parser.input.position()
        parser.endGroup(pos, GROUP_TYPE.SEMI_SIMPLE)


mod = Module("state",
    commands={
        "begingroup": BeginGroup(),
        "endgroup": EndGroup(),
    }
)
