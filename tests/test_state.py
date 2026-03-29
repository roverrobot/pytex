import pytest
from pytex import state as st
from pytex import accessor
from pytex import integer
from tests import checkValues
from pytex import macro


class _StateOwner:
    def __init__(self):
        self.groups = []
        self.current_group = None
        self.globals = st.Globals()
        self.volatile = st.Dict("volatile", self)
        self.parameters = st.Dict("parameters", self)
        self.equitable = st.Dict("equitable", self)
        self.layout = st.Dict("layout", self)
        self.arrays = {}

    def remove(self, domain, index):
        if self.current_group:
            self.current_group.remove(domain, index)
            for group in self.groups:
                group.remove(domain, index)

    def beginGroup(self, position, group_type: st.GROUP_TYPE, to_end=None, ended=None):
        if self.current_group:
            self.groups.append(self.current_group)
        self.current_group = st.Group(position, group_type, to_end=to_end, ended=ended)

    def endGroup(self, position, group_type: st.GROUP_TYPE):
        if not self.current_group:
            raise ValueError("no current group")
        group = self.current_group
        aftergroup = group.aftergroup
        to_end = group.to_end
        ended = group.ended
        if not group.match(group_type):
            raise ValueError(f"mismatched group type starting at {group.position} and ending at {position}")
        if to_end:
            to_end(self)
        group.end(position, group_type)
        if self.groups:
            self.current_group = self.groups.pop()
        else:
            self.current_group = None
        if ended:
            ended(self)
        return aftergroup


@pytest.fixture
def state():
    s = _StateOwner()
    d = st.Dict(name="dict", state=s)
    a = st.Array(name="array", state=s, default=0)
    return s, d, a

def test_set_value(state):
    s, d, a = state
    d["key1"] = "value1"
    assert d["key1"] == "value1"
    a[1] = 1
    assert a[1] == 1
    d["key1"] = "value2"
    assert d["key1"] == "value2"
    a[1] = 0
    assert a[1] == 0
 
def test_set_in_group(state):
    s, d, a = state
    d["key1"] = "value1"
    a[1] = 1
    s.beginGroup(group_type=st.GROUP_TYPE.SIMPLE, position=0)
    d["key1"] = "value2"
    assert d["key1"] == "value2"
    a[1] = 0
    assert a[1] == 0
    s.beginGroup(group_type=st.GROUP_TYPE.SEMI_SIMPLE, position=0)
    d["key1"] = "value3"
    assert d["key1"] == "value3"
    a[1] = -1
    assert a[1] == -1
    s.endGroup(group_type=st.GROUP_TYPE.SEMI_SIMPLE, position=0)
    assert d["key1"] == "value2"
    assert a[1] == 0
    s.endGroup(group_type=st.GROUP_TYPE.SIMPLE, position=1)
    assert d["key1"] == "value1"
    assert a[1] == 1


def test_set_global(state):
    s, d, a = state
    d["key1"] = "value1"
    a[1] = 1
    s.beginGroup(group_type=st.GROUP_TYPE.SIMPLE, position=0)
    d["key1"] = "value2"
    assert d["key1"] == "value2"
    a[1] = 0
    assert a[1] == 0
    s.beginGroup(group_type=st.GROUP_TYPE.SEMI_SIMPLE, position=0)
    d.setGlobal("key1", "value3")
    assert d["key1"] == "value3"
    a.setGlobal(1, -1)
    assert a[1] == -1
    s.endGroup(group_type=st.GROUP_TYPE.SEMI_SIMPLE, position=0)
    assert d["key1"] == "value3"
    assert a[1] == -1
    s.endGroup(group_type=st.GROUP_TYPE.SIMPLE, position=1)
    assert d["key1"] == "value3"
    assert a[1] == -1

def test_group_mismatch(state):
    s, d, a = state
    try:
        s.beginGroup(group_type=st.GROUP_TYPE.SIMPLE, position=0)
        s.endGroup(group_type=st.GROUP_TYPE.SEMI_SIMPLE, position=1)
    except ValueError as e:
        pass
    except Exception as e:
        assert False, "unexpected exception: %s" % e


def test_group_to_end_and_ended_order(state):
    s, d, _ = state
    d["key1"] = "outer"
    seen = []
    s.beginGroup(
        group_type=st.GROUP_TYPE.SIMPLE,
        position=0,
        to_end=lambda _: seen.append(("to_end", d["key1"])),
        ended=lambda _: seen.append(("ended", d["key1"])),
    )
    d["key1"] = "inner"
    s.endGroup(group_type=st.GROUP_TYPE.SIMPLE, position=1)
    assert seen == [("to_end", "inner"), ("ended", "outer")]


def test_group_ended_hook_runs_after_restore(state):
    s, d, _ = state
    d["key1"] = "outer"
    seen = []
    s.beginGroup(
        group_type=st.GROUP_TYPE.SIMPLE,
        position=0,
        ended=lambda _: seen.append(d["key1"]),
    )
    d["key1"] = "inner"
    s.endGroup(group_type=st.GROUP_TYPE.SIMPLE, position=1)
    assert seen == ["outer"]


def test_parser_group(parser):
    checkValues(parser, "\\count0=1\\begingroup\\count0=2", [("count", 0, 2)])
    checkValues(parser, "\\endgroup", [("count", 0, 1)])

def test_parser_group_multilevel(parser):
    checkValues(parser, "\\catcode32=9\\begingroup\\begingroup\\catcode32=10", [("catcode", 32, 10)])
    checkValues(parser, "\\endgroup\\endgroup", [("catcode", 32, 9)])

def test_parser_group_mismatch(parser):
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


def test_parser_get_and_set_explicit_value(parser):
    parser.set("count", 0, value=123)
    assert parser.count[0] == 123
    assert parser.current_value == 123
    assert parser.get("count", 0) == 123
    assert parser.current_value == 123


def test_parser_set_uses_current_value(parser):
    parser.current_value = 456
    parser.set("count", 0)
    assert parser.count[0] == 456
    assert parser.current_value == 456


def test_parser_set_global_scope(parser):
    parser.set("count", 0, value=1)
    parser.beginGroup(position=0, group_type=st.GROUP_TYPE.SEMI_SIMPLE)
    parser.set("count", 0, value=2)
    parser.set("count", 0, global_scope=True, value=3)
    parser.endGroup(position=1, group_type=st.GROUP_TYPE.SEMI_SIMPLE)
    assert parser.count[0] == 3


def test_parser_set_globaldefs_positive_forces_global(parser):
    parser.set("count", 0, value=1)
    parser.beginGroup(position=0, group_type=st.GROUP_TYPE.SEMI_SIMPLE)
    parser.parameters["globaldefs"] = 1
    parser.set("count", 0, value=2)
    parser.endGroup(position=1, group_type=st.GROUP_TYPE.SEMI_SIMPLE)
    assert parser.count[0] == 2


def test_parser_set_globaldefs_negative_forces_local(parser):
    parser.set("count", 0, value=1)
    parser.beginGroup(position=0, group_type=st.GROUP_TYPE.SEMI_SIMPLE)
    parser.parameters["globaldefs"] = -1
    parser.set("count", 0, global_scope=True, value=2)
    parser.endGroup(position=1, group_type=st.GROUP_TYPE.SEMI_SIMPLE)
    assert parser.count[0] == 1


def test_parser_get_set_globals(parser):
    parser.set("globals", "demo", value="x")
    assert parser.globals["demo"] == "x"
    assert parser.get("globals", "demo") == "x"
    assert parser.current_value == "x"


def test_parser_set_target_and_use_implicit_get_set(parser):
    parser.count[0] = 12
    parser.setTarget((parser.count, 0), accessor.VALUE_TYPE.INT)
    assert parser.get() == 12
    assert parser.current_value == 12
    parser.current_value = 34
    parser.set()
    assert parser.count[0] == 34


def test_parser_get_and_set_scratch_with_target(parser):
    parser.count[1] = 7
    parser.setTarget((parser.count, 1), accessor.VALUE_TYPE.INT)
    assert parser.get(use_scratch=True) == 7
    assert parser.scratch == 7
    assert parser.scratch_type == accessor.VALUE_TYPE.INT
    parser.scratch = 9
    parser.set(use_scratch=True)
    assert parser.count[1] == 9


def test_parser_read_target_from_accessor(parser):
    acc = integer.IntegerArrayItemAccessor(parser.count, 2, builtin=False)
    assert parser.readTarget(acc) == (parser.count, 2)
    assert parser.target == (parser.count, 2)
    assert parser.target_type == accessor.VALUE_TYPE.INT


def test_insert_runtime_lists(parser):
    inserts = parser.globals["insert"]
    assert len(inserts) == 256
    assert inserts[0] == []
    inserts[0].append("x")
    assert inserts[0] == ["x"]
    assert inserts[1] == []


def test_dump(parser):
    parser.parse("\\count0=1{\\count0=2}\\def\\a{123}")
    data = parser.dumpState()
    assert "globals" not in data
    assert "count" in data
    assert "insert" not in data
    assert data["count"][0] == 1
    assert "equitable" in data
    assert "\\a" in data["equitable"]
    assert isinstance(data["equitable"]["\\a"], macro.Macro)
