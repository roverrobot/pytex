"""
This file implements serialization and desecrialization of objects. These are
used to store an object in json format, thereby enabling dumping parser states,
and reloading them. This is used to implement the format files.
"""

import enum

import json

def serialize(obj):
    """
    serialize the object into a dictionary
    """
    if isinstance(obj, Serializable):
        return obj.serialize()
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            obj[i] = serialize(value)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            obj[key] = serialize(value)
    elif isinstance(obj, enum.Enum):
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
        items = enumerate(data)
    elif isinstance(data, dict):
        items = data.items()
    else:
        items = None
    if items is not None:
        for key, value in items:
            data[key] = deserialize(parser, value)
    if isinstance(data, dict) and "__classname__" in data:
        cls = getClass(data["__classname__"])
        data = cls.deserialize(parser, data)
    return data


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

    @classmethod
    def new(cls, parser, **kwargs):
        """
        create a new object from the dictionary
        """
        return cls(**kwargs)

    @classmethod
    def deserialize(cls, parser, data):
        """
        deserialize the object from a string
        """
        init = deserialize(parser, data["init"]) if "init" in data else {}
        cls = getClass(data["__classname__"])
        obj = cls.new(parser, **init)
        if "extra" in data:
            for key, value in data["extra"].items():
                if isinstance(value, dict) and "__classname__" in value:
                    cls = getClass(value["classname"])
                    value = cls.deserialize(parser, value)
                setattr(obj, key, value)
        return obj
