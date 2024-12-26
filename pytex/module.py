"""
We divide the functionality into modules. For example, we implement branching commands,
integer arrays, and so on as modules. Each module tells a parser what commands, 
registers, parameters it defines. It registers itself with a module manager, and
when a parser is created, it will consult the module manager to get the modules that it
should use. The the parser calls each module to populate the funcionalities.
Here we define the class that represent a module and the manager class.
a module.
"""


import types
import typing


ModuleManager = {}    


class Module:
    """
    A module defines a set of commands, registers, parameters, etc. that can be used by a parser.
    @param name: the name of the module
    @param commands: the commands defined by the module, a dict of name -> command
    @param registers: the registers defined by the module, a dict of name -> register
    @param parameters: the parameters defined by the module, a dict of name -> parameter
    @param globals: the globals defined by the module, a dict of name -> global
    """
    def __init__(self, name: str, commands=None, domains=None, parameters=None, 
                attributes=None):
        self.name = name
        self.commands = commands
        self.domains = domains
        self.parameters = parameters
        self.attributes = attributes
        ModuleManager[name] = self

    def populateCommands(self, parser):
        """
        populate the parser with the commands defined by the module
        @param parser: the parser
        """
        if self.commands is not None:
            for name, command in self.commands.items():
                parser.state.equitable.setGlobal("\\"+name, command)

    def populateDomains(self, parser):
        """
        populate the parser with the domains defined by the module
        @param parser: the parser
        """
        if self.domains is not None:
            for name, domain in self.domains.items():
                parser.state.addDomain(name, domain["generator"]())
                pointer_generator = domain["type"]
                accessor = domain["accessor"]
                parser.state.equitable.setGlobal("\\"+name, accessor(name, pointer_generator))

    def populateAttributes(self, parser):
        """
        populate the parser with the attributes defined by the module
        @param parser: the parser
        """
        if self.attributes is not None:
            for name, value in self.attributes.items():
                if callable(value):
                    setattr(parser, name, types.MethodType(value, parser))
                else:
                    setattr(parser, name, value)

    def populateParameters(self, parser):
        """
        populate the parser with the parameters defined by the module
        @param parser: the parser
        """
        if self.parameters is not None:
            for name, item in self.parameters.items():
                domain = item["domain"]
                value = item["value"]
                if callable(value):
                    value = value()
                accessor = item["accessor"]
                parser.state[domain][name] = value
                if accessor is not None:
                    pointer_generator = item["type"]
                    parser.state.equitable.setGlobal("\\"+name, accessor(domain, name, pointer_generator))


    def populate(self, parser):
        """
        populate the parser with the commands, registers, parameters, etc. defined by the module
        @param parser: the parser
        """
        self.populateCommands(parser)
        self.populateDomains(parser)
        self.populateAttributes(parser)
        self.populateParameters(parser)
