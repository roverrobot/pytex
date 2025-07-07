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
        if isinstance(domain, Dict) and index not in domain:
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


class Domain:
    """
    a Domamin is a dict or list that respect groups.
    @param name: the name of the domain
    @param values: the values in the domain
    @param state: the a State object for parser state
    """
    def __init__(self, name: str, state=None):
        self.name = name
        self.state = state

    def save(self, index):
        if self.state:
            top = self.state.current_group
            if top:
                top.store(self, index)

    def setGlobal(self, index, value):
        """
        set the value of the domain at the index globally
        @param index: the index of the value
        @param: the value

        This is like __setitem__, but also should clear the saved values in group_stack.
        """
        self[index] = value
        if self.state:
            self.state.remove(self, index)
        

class Dict(Domain, dict):
    """
    a domain that is a dict, and respects groups.
    @param name: the name of the domain
    @param values: the values in the domain
    @param state: the a State object for parser state
    """
    def __init__(self, name, state=None):
        Domain.__init__(self, name, state)
        dict.__init__(self)

    def __setitem__(self, index, value):
        """
        set the value of the domain at the index
        @param index: the index of the value
        @param: the value
        """
        self.save(index)
        dict.__setitem__(self, index, value)

    def __delitem__(self, index):
        self.save(index)
        return dict.__delitem__(self, index)

    def restore(self, index, value):
        """
        restore the value at the index in the domain
        @param index: the index of the value
        @param: the value
        """
        if value is None:
            dict.__delitem__(self, index)
        else:
            dict.__setitem__(self, index, value)

    def load(self, data):
        """
        restore the domain from a dump
        @param data: the data to restore the domain
        """
        for i, v in data.items():
            self[i] = v
            

class Layout(Dict):
    """
    a domain that store layout related parameters.
    @param state: the a State object for parser state

    This domain maintains the values that are chenged.
    """
    def __init__(self, state=None):
        super().__init__("layout", state)
        self._changed = {}

    def __setitem__(self, index, value):
        super().__setitem__(index, value)
        self._changed[index] = value

    def changed(self):
        """
        dump the changed values of the domain and clear the changed dict.
        @return: a dict that contains the changed values
        """
        _changed = self._changed
        self._changed = {}
        return _changed


class Array(Domain, list):
    SIZE = 65536
    """
    an array of values
    """
    def __init__(self, name: str, state=None, default=None, size: typing.Optional[int]=None):
        Domain.__init__(self, name, state)
        if size is None:
            size = self.SIZE
        if callable(default):
            init = [default() for i in range(size)]
        else:
            init = [default] * size
        list.__init__(self, init)
        self.size = size

    def __getitem__(self, index):
        if index >= self.size:
            index = self.size - 1
        elif index < 0:
            index = 0
        return list.__getitem__(self, index)
    
    def __setitem__(self, index, value):
        if index >= self.size:
            index = self.size - 1
        elif index < 0:
            index = 0
        self.save(index)
        list.__setitem__(self, index, value)

    restore = list.__setitem__

    def load(self, data):
        """
        restore the array from a dump
        @param data: the data to restore the array
        """
        for i, v in enumerate(data):
            self[i] = v
    

class State:
    """
    stores the state of the parser, including the local and global parameters and registers.
    """
    def __init__(self):
        self.groups = [] # group stack
        self.current_group = None
        self.globals = {}
        self.domains = {}
        # the loaded TFM files. These files are not dumped, as they are loaded onthe fly by the 
        # font loader
        self.tfm = {} 
        self.volatile = Dict("volatile", self)  # the volatile domain do not need to be dumped
        self.setDomain("equitable", Dict("equitable", self))  # the equitable domain
        self.setDomain("layout", Layout(self))  # the layout domain
        self.setDomain("parameters", Dict("parameters", self))  # the parameters domain

    def setDomain(self, name, domain):
        """
        set a domain with the given name and values.
        @param name: the name of the domain
        @param values: the values of the domain
        """
        setattr(self, name, domain)
        self.domains[name] = domain

    def dump(self):
        """
        dump the state
        @return: a dict that represents the state
        """
        data = {"globals": self.globals}
        for name, domain in self.domains.items():
            data[name] = domain
        return data
    
    def load(self, data):
        """
        restore the state from a dump
        @param data: a previously dumped data
        """
        if "globals" in data:
            self.globals = data["globals"]
        for name, domain in self.domains.items():
            if name in data:
                domain.load(data[name])

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

    def beginGroup(self, position, group_type: GROUP_TYPE, callback=None):
        """
        begin a group, and push it to the group stack.
        @param position: the position of the token starting the group
        @param group_type: the type of the group
        @param callback: a callback to be called when the group is closed
        """
        if self.current_group:
            self.groups.append(self.current_group)
        self.current_group = Group(position, group_type, callback)

    def endGroup(self, position, group_type: GROUP_TYPE):
        """
        end the group, and pop it from the group stack.
        @param position: the position of the token ending the group
        @param group_type: the type of the group
        @return the aftergroup tokens
        """
        if not self.current_group:
            raise ValueError("no current group")
        aftergroup = self.current_group.aftergroup
        self.current_group.end(position, group_type)
        if self.groups:
            self.current_group = self.groups.pop()
        else:
            self.current_group = None
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
