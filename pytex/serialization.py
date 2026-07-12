"""
This file implements serialization and desecrialization of objects. These are
used to store an object in json format, thereby enabling dumping parser states,
and reloading them. This is used to implement the format files.
"""

import enum

def serialize(obj):
    """
    serialize the object into a dictionary
    """
    if isinstance(obj, Serializable):
        return obj.serialize()
    if isinstance(obj, list):
        return [serialize(value) for value in obj]
    if isinstance(obj, dict):
        d = {}
        for key, value in obj.items():
            d[key] = serialize(value)
        return d
    if isinstance(obj, enum.Enum):
        return obj.value
    return obj


def getClass(name):
    """
    get the class from the module
    """
    # check if module has the form pytex.module
    names = name.split(".")
    if len(names) == 1:
        return None
    assert names[0] == "pytex", f"invalid class {names[0]}"
    module = __import__(names[0])
    for name in names[1:]:
        module = getattr(module, name)
    return module


def deserialize(parser, data):
    """
    deserialize the object from a dictionary or a list
    """
    if isinstance(data, list):
        return [deserialize(parser, x) for x in data]
    elif not isinstance(data, dict) or not data:
        return data
    class_name = list(data.keys())[0]
    d = {}
    cls = getClass(class_name)
    if cls is None:
        for name, value in data.items():
            d[name] = deserialize(parser, value)
        return d
    init = deserialize(parser, data[class_name])
    obj = cls.new(parser, **init)
    extra = data.get("extra")
    if extra:
        for key, value in extra.items():
            setattr(obj, key, deserialize(parser, value))
    after_deserialize = getattr(obj, "afterDeserialize", None)
    if after_deserialize is not None:
        after_deserialize(parser)
    return obj


class Serializable:
    """
    The base class for all serializable objects. The serialization will be used to dump
    the parser state into a dump file
    """
    __slots__ = ()
    def saveInfo(self):
        """
        return two dictionaries, the first is the arguments to the __init__ method, and the second stores
        the extra instance variables that needs to be saved (or None for no such values)

        One component of the information is argument needed to construct the command, which
        is stored in the "init" element. The other component is the extra attributed,
        which is stored in the "extra" element. If either is empty, the element is not
        included in the dictionary.
        """
        return {}, None
    
    def className(self):
        return f"{self.__module__}.{self.__class__.__name__}"

    def serialize(self):
        init, extra = self.saveInfo()
        info = {}
        info[self.className()] = serialize(init)
        if extra:
            info["extra"] = serialize(extra)
        return info

    init_needs_parser = False
    
    @classmethod
    def new(cls, parser, **kwargs):
        """
        create a new object from the dictionary
        """
        return cls(parser, **kwargs) if cls.init_needs_parser else cls(**kwargs)


class Builtin(Serializable):
    def className(self):
        return "pytex.serialization.Builtin"

    @classmethod
    def new(cls, parser, **kwargs):
        """
        create a new object from the dictionary
        """
        return parser.builtin[kwargs["name"]]

    def saveInfo(self):
        """
        save the command information. This is used to serialize the command.
        @return: a dictionary with the command information
        """
        return {"name": self.name}, None
