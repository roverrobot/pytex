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
        return __import__(name)
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
    elif not isinstance(data, dict):
        return data
    d = {}
    cls = None
    for key, value in data.items():
        if key == "__classname__":
            cls = getClass(value)
        else:
            d[key] = deserialize(parser, value)
    if cls is None:
        return d
    init = d.get("init", {})
    obj = cls.new(parser, **init)
    for key, value in d.get("extra", {}).items():
        setattr(obj, key, value)
    return obj


class Serializable:
    """
    The base class for all serializable objects. The serialization will be used to dump
    the parser state into a dump file
    """
    def saveInfo(self):
        """
        save the information of the command into a dictionary

        One component of the information is argument needed to construct the command, which
        is stored in the "init" element. The other component is the extra attributed,
        which is stored in the "extra" element. If either is empty, the element is not
        included in the dictionary.
        """
        return {}

    def serialize(self):
        info = serialize(self.saveInfo())
        info["__classname__"] = f"{self.__module__}.{self.__class__.__name__}"
        return info

    init_needs_parser = False
    
    @classmethod
    def new(cls, parser, **kwargs):
        """
        create a new object from the dictionary
        """
        return cls(parser, **kwargs) if cls.init_needs_parser else cls(**kwargs)
