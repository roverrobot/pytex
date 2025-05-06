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
    @param callback: a callback to be called when the group
    """
    def __init__(self, position, group_type: GROUP_TYPE, callback=None):
        self.group_type = group_type
        self.position = position
        self.callback = callback
        # the aftergroup tokens
        self.aftergroup = []
        # values holds the saved values, where the key is the name of a domain, e.g., "catcode", 
        # "equitable" etc, and the value is a tuple, which first value is the domain, and 
        # the second is a dict that maps the index to the saved value.
        self.values = {}

    def store(self, domain, index):
        """
        store a value in the group.
        @param domain: the domain of the value
        @param index: the index of the value
        @param value: the value
        """
        if isinstance(domain.values, dict) and index not in domain.values:
            save = None
        else:
            save = domain[index]
        if domain.name not in self.values:
            store = [domain, {}]
            self.values[domain.name] = store
        else:
            store = self.values[domain.name]
        if index not in store[1]:
            store[1][index] = save

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
        for key, item in self.values.items():
            domain, store = item
            for index, value in store.items():
                domain.restore(index, value)
        if self.callback:
            self.callback()

    def remove(self, domain, index):
        """
        remove a value from the group.
        @param domain: the domain of the value
        @param index: the index of the value
        """
        if domain.name not in self.values:
            return
        item = self.values[domain.name]
        store = item[1]
        if index in store:
            del store[index]


class GroupStack:
    """
    a stack of groups.
    """
    def __init__(self):
        self.groups = []

    
    def begin(self, position, group_type: GROUP_TYPE, callback=None):
        """
        begin a new group
        @param position: the position of the token starting the group
        @param group_type: the type of the group
        @param callback: a callback to be called when the group is closed
        """
        group = Group(position, group_type, callback)
        self.groups.append(group)

    def end(self, position, group_type: GROUP_TYPE):
        """
        end the current group and return its aftergroup token list
        @param group_type: the type of the group
        @param position: the position of the token ending the group
        @return: the aftergroup token list
        """
        if self.groups:
            group = self.groups.pop()
            group.end(position, group_type)
            return group.aftergroup
        raise ValueError("no group to end")

    def remove(self, domain, index):
        """
        remove a value from all groups. This is to implement \\global
        @param domain: the domain of the value
        @param index: the index of the value
        """
        for group in self.groups:
            group.remove(domain, index)

    def aftergroup(self, tok):
        """
        add a token to the aftergroup list
        @param tok: the token to add
        """
        if self.groups:
            self.groups[-1].aftergroup.append(tok)

    def top(self):
        """
        return the top group
        @return: the top group
        """
        return self.groups[-1] if self.groups else None


class Domain:
    """
    a Domamin is a dict or list that respect groups.
    @param name: the name of the domain
    @param values: the values in the domain
    @param group_stack: the group stack to store the values
    @param volatile: whether the domain is volatile, i.e., shold be dumped in a format file
    """
    def __init__(self, name: str, values, group_stack=None, volatile=False):
        self.name = name
        self.values = values
        self.group_stack = group_stack
        self.changed = None if volatile else {}

    def __getitem__(self, index):
        return self.values[index]

    def __setitem__(self, index, value):
        """
        set the value of the domain at the index
        @param index: the index of the value
        @param: the value
        """
        if self.group_stack:
            top = self.group_stack.top()
            if top:
                top.store(self, index)
        if self.changed is not None:
            self.changed[index] = value
        self.values[index] = value
        
    def __delitem__(self, index):
        if self.group_stack:
            top = self.group_stack.top()
            if top:
                top.store(self, index)
        del self.values[index]
        del self.changed[index]

    def setGlobal(self, index, value):
        """
        set the value of the domain at the index globally
        @param index: the index of the value
        @param: the value

        This is like __setitem__, but also should clear the saved values in group_stack.
        """
        self[index] = value
        if self.group_stack:
            self.group_stack.remove(self, index)

    def restore(self, index, value):
        """
        restore the value of the domain at the index
        @param index: the index of the value
        @param: the value
        """
        if value is None:
            del self.values[index]
            if self.changed is not None:
                del self.changed[index]
        else:
            self.values[index] = value
            if self.changed is not None:
                self.changed[index] = value
            
    def dump(self):
        """
        dump the object
        @return: a dict that represents the object
        """
        changed = self.changed
        if self.changed is not None:
            self.changed = {}
        return changed

    def load(self, data):
        """
        restore the domain from a dump
        @param data: the data to restore the domain
        """
        if self.changed is None:
            raise ValueError("cannot load a volatile domain")
        is_array = isinstance(self.values, list)
        for i, v in data.items():
            if is_array:
                i = int(i)
            self[i] = v
        
    def __repr__(self):
        return self.values.__repr__()


class GlobalDomain(Domain):
    """
    the global domain if not subject to groups, but it is still dumpable
    """
    def __init__(self, name, values):
        super().__init__(name, values, None, False)


class VolatileDomain(Domain):
    """
    a volatile domain is not dumpable, but is subject to groups
    """
    def __init__(self, name, values, group_stack):
        super().__init__(name, values, group_stack, True)


class DumpableDomain(Domain):
    """
    a domain that is both dumpable and subject to groups
    """
    def __init__(self, name, values, group_stack):
        super().__init__(name, values, group_stack, False)


class Array(list):
    SIZE = 65536
    """
    an array of values
    """
    def __init__(self, default=None, size: typing.Optional[int]=None):
        if size is None:
            size = self.SIZE
        if callable(default):
            init = [default() for i in range(size)]
        else:
            init = [default] * size
        super().__init__(init)

    def __getitem__(self, index):
        if index >= self.SIZE:
            index = self.SIZE - 1
        elif index < 0:
            index = 0
        return super().__getitem__(index)
    
    def items(self):
        return enumerate(self)


class State:
    """
    stores the state of the parser, including the local and global parameters and registers.
    """
    def __init__(self):
        self.groups = GroupStack()
        self.domains = {
            # all global variables, not affected by groups
            "globals": GlobalDomain("globals", {}), 
            # all volatile variables, not dumped to a formaat file
            "volatile": VolatileDomain("volatile", {}, self.groups),
            # the equitable saves the definition of all command sequences
            "equitable": DumpableDomain("equitable", {}, self.groups),
            # the set of parameters pertaining to layout
            "layout": DumpableDomain("layout", {}, self.groups),
            # all other parameters
            "parameters": DumpableDomain("parameters", {}, self.groups),
        }
        def setattr(self, index, value):
            self.domains[index] = value
        self.__setattr__ = setattr

    def __getattr__(self, index):
        try:
            return self.domains[index]
        except:
            raise AttributeError(index)

    def __getitem__(self, index):
        return self.domains[index]

    def currentGroup(self):
        return self.groups.top()
    
    def addDomain(self, name: str, values):
        """
        add a dumpable domain to the state
        :param name: the name of the domain
        :param values: the values of the domain
        :param volatile: whether the domain is volatile

        Note that there is exactly one global domain and one volatile domain.
        All other domains are dumpable.
        """
        self.domains[name] = DumpableDomain(name, values, self.groups)
    
    def dump(self):
        """
        dump the state
        @return: a dict that represents the state
        """
        data = {}
        for name, domain in self.domains.items():
            changed = domain.dump()
            if changed:
                for key, value in changed.items():
                    if isinstance(value, serialization.Serializable):
                        value = value.serialize()
                        changed[key] = value
                data[name] = changed
        return data
    
    def load(self, data):
        """
        restore the state from a dump
        @param data: a previously dumped data
        """
        for name, domain in self.domains.items():
            if name in data:
                domain.load(data[name])


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
