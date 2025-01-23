"""
This file defines facilities to implement versioned values and groups.
"""


import typing
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
            store = (domain, {})
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
        if self.group_type == GROUP_TYPE.SEMI_SIMPLE or self.group_type == GROUP_TYPE.MATH:
            return group_type == self.group_type
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


class GroupStack(list):
    """
    a stack of groups.
    """

    def begin(self, position, group_type: GROUP_TYPE, callback=None):
        """
        begin a new group
        @param position: the position of the token starting the group
        @param group_type: the type of the group
        @param callback: a callback to be called when the group is closed
        """
        group = Group(position, group_type, callback)
        self.append(group)

    def end(self, position, group_type: GROUP_TYPE):
        """
        end the current group
        @param group_type: the type of the group
        @param position: the position of the token ending the group
        """
        if len(self) == 0:
            raise ValueError("no group to end")
        group = self.pop(-1)
        group.end(position, group_type)

    def top(self):
        """
        get the top group
        @return: the top group or None if there is no group
        """
        if len(self) == 0:
            return None
        return self[-1]
    
    def remove(self, domain, index):
        """
        remove a value from all groups. This is to implement \\global
        @param domain: the domain of the value
        @param index: the index of the value
        """
        for group in self:
            group.remove(domain, index)


class Domain:
    """
    a Domamin is a dict or list to store values that can be changed and restored. 
    It is used to implement groups.
    @param name: the name of the domain
    @param values: the values in the domain
    @param group_stack: the group stack to store the values
    """
    def __init__(self, name: str, values, group_stack: GroupStack):
        self.name = name
        self.values = values
        self.group_stack = group_stack

    def __setitem__(self, index, value):
        """
        set the value of the domain at the index
        @param index: the index of the value
        @param: the value
        """
        group = self.group_stack.top()
        if group is not None:
            group.store(self, index)
        self.values[index] = value
    
    def __getitem__(self, index):
        """
        get the value of the domain at the index
        @param index: the index of the value
        @return: the value
        """
        return self.values[index]
    
    def setGlobal(self, index, value):
        """
        set the value of the domain at the index globally
        @param index: the index of the value
        @param: the value
        """
        self.group_stack.remove(self, index)
        self.values[index] = value

    def restore(self, index, value):
        """
        restore the value of the domain at the index
        @param index: the index of the value
        @param: the value
        """
        if value is None:
            del self.values[index]
        else:
            self.values[index] = value

    def __repr__(self):
        return self.values.__repr__()


class LayoutParameters(dict):
    """
    a class to store the parameters of a parser
    """
    def __init__(self):
        self.changed = {}

    def __setitem__(self, index, value):
        super().__setitem__(index, value)
        self.changed[index] = value

    def getChanged(self):
        """
        get the changed parameters, and clear the changed dict
        """
        changed = self.changed
        self.changed = {}
        return changed


class Array(list):
    SIZE = 65536
    """
    a character code
    """
    def __init__(self, default=None, size: typing.Optional[int]=None):
        if size is None:
            size = self.SIZE
        if callable(default):
            init = [default() for i in range(size)]
        else:
            init = [default] * size
        super().__init__(init)


class State:
    """
    stores the state of the parser, including the local and global parameters and registers.
    """
    def __init__(self):
        self.groups = GroupStack()
        self.domains = {"globals": {}}
        self.addDomain("equitable", {})
        self.addDomain("layout", LayoutParameters())
        self.addDomain("parameters", {})
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

    def beginGroup(self, position, group_type: GROUP_TYPE=GROUP_TYPE.SIMPLE, callback=None):
        """
        starts a new group
        @param position: the position of the group
        @param group_type: the type of the group
        @param callback: a callback to be called when the group is closed
        """
        self.groups.begin(position, group_type, callback)

    def endGroup(self, position, group_type: GROUP_TYPE=GROUP_TYPE.SIMPLE):
        """
        ends the current group
        :param context: the context of the group
        """
        self.groups.end(position, group_type)
            
    
    def addDomain(self, name: str, values):
        """
        add a domain to the state
        :param name: the name of the domain
        :param values: the values of the domain
        """
        self.domains[name] = Domain(name, values, self.groups)


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
