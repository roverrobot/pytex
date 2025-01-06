import pytest
from pytex import state
from pytex.parser import Parser


@pytest.fixture
def groupstack():
    stack = state.GroupStack()
    d = state.Domain(name="dict", values={}, group_stack=stack)
    a = state.Domain(name="array", values=[0,0,0], group_stack=stack)
    return stack, d, a

def test_set_value(groupstack):
    stack, d, a = groupstack
    d["key1"] = "value1"
    assert d["key1"] == "value1"
    a[1] = 1
    assert a[1] == 1
    d["key1"] = "value2"
    assert d["key1"] == "value2"
    a[1] = 0
    assert a[1] == 0
 
def test_set_in_group(groupstack):
    stack, d, a = groupstack
    d["key1"] = "value1"
    a[1] = 1
    stack.begin(group_type=state.GROUP_TYPE.SIMPLE, position=0)
    d["key1"] = "value2"
    assert d["key1"] == "value2"
    a[1] = 0
    assert a[1] == 0
    stack.begin(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=0)
    d["key1"] = "value3"
    assert d["key1"] == "value3"
    a[1] = -1
    assert a[1] == -1
    stack.end(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=0)
    assert d["key1"] == "value2"
    assert a[1] == 0
    stack.end(group_type=state.GROUP_TYPE.SIMPLE, position=1)
    assert d["key1"] == "value1"
    assert a[1] == 1


def test_set_global(groupstack):
    stack, d, a = groupstack
    d["key1"] = "value1"
    a[1] = 1
    stack.begin(group_type=state.GROUP_TYPE.SIMPLE, position=0)
    d["key1"] = "value2"
    assert d["key1"] == "value2"
    a[1] = 0
    assert a[1] == 0
    stack.begin(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=0)
    d.setGlobal("key1", "value3")
    assert d["key1"] == "value3"
    a.setGlobal(1, -1)
    assert a[1] == -1
    stack.end(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=0)
    assert d["key1"] == "value3"
    assert a[1] == -1
    stack.end(group_type=state.GROUP_TYPE.SIMPLE, position=1)
    assert d["key1"] == "value3"
    assert a[1] == -1

def test_group_mismatch(groupstack):
    stack, d, a = groupstack
    try:
        stack.begin(group_type=state.GROUP_TYPE.SIMPLE, position=0)
        stack.end(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=1)
    except ValueError as e:
        pass
    except Exception as e:
        assert False, "unexpected exception: %s" % e

def test_parser_group():
    parser = Parser()
    parser.parse("\\count0=1\\begingroup\\count0=2")
    assert parser.state.count[0] == 2
    parser.parse("\\endgroup")
    assert parser.state.count[0] == 1

def test_parser_group_mismatch():
    parser = Parser()
    try:
        parser.parse("{\\endgroup")
        assert False, "group matching failed"
    except ValueError as e:
        assert "mismatch" in str(e)
    try:
        parser.parse("\\begingroup}")
        assert False, "group matching failed"
    except ValueError as e:
        assert "mismatch" in str(e)
