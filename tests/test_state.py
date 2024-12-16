import unittest
from pytex import state
from pytex.parser import Parser


class TestGroupStack(unittest.TestCase):
    def setUp(self):
        self.group_stack = state.GroupStack()
        self.dict = state.Domain(name="dict", values={}, group_stack=self.group_stack)
        self.array = state.Domain(name="array", values=[0], group_stack=self.group_stack)

    def test_set_value(self):
        self.dict["key1"] = "value1"
        self.assertEqual(self.dict["key1"], "value1")
        self.array[0] = 0
        self.assertEqual(self.array[0], 0)
        self.dict["key1"] = "value2"
        self.assertEqual(self.dict["key1"], "value2")
        self.array[0] = 1
        self.assertEqual(self.array[0], 1)

    def test_set_in_group(self):
        self.dict["key1"] = "value1"
        self.array[0] = 0
        self.group_stack.begin(group_type=state.GROUP_TYPE.SIMPLE, position=0)
        self.dict["key1"] = "value2"
        self.assertEqual(self.dict["key1"], "value2")
        self.array[0] = 1
        self.assertEqual(self.array[0], 1)
        self.group_stack.begin(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=0)
        self.dict["key1"] = "value3"
        self.assertEqual(self.dict["key1"], "value3")
        self.array[0] = 2
        self.assertEqual(self.array[0], 2)
        self.group_stack.end(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=0)
        self.assertEqual(self.dict["key1"], "value2")
        self.assertEqual(self.array[0], 1)
        self.group_stack.end(group_type=state.GROUP_TYPE.SIMPLE, position=1)
        self.assertEqual(self.dict["key1"], "value1")
        self.assertEqual(self.array[0], 0)

    def test_set_global(self):
        self.dict["key1"] = "value1"
        self.array[0] = 0
        self.group_stack.begin(group_type=state.GROUP_TYPE.SIMPLE, position=0)
        self.dict["key1"] = "value2"
        self.assertEqual(self.dict["key1"], "value2")
        self.array[0] = 1
        self.assertEqual(self.array[0], 1)
        self.group_stack.begin(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=0)
        self.dict.setGlobal("key1", "value3")
        self.assertEqual(self.dict["key1"], "value3")
        self.array.setGlobal(0, 2)
        self.assertEqual(self.array[0], 2)
        self.group_stack.end(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=0)
        self.assertEqual(self.dict["key1"], "value3")
        self.assertEqual(self.array[0], 2)
        self.group_stack.end(group_type=state.GROUP_TYPE.SIMPLE, position=1)
        self.assertEqual(self.dict["key1"], "value3")
        self.assertEqual(self.array[0], 2)

    def test_group_mismatch(self):
        try:
            self.group_stack.begin(group_type=state.GROUP_TYPE.SIMPLE, position=0)
            self.group_stack.end(group_type=state.GROUP_TYPE.SEMI_SIMPLE, position=1)
        except ValueError as e:
            pass
        except Exception as e:
            self.fail("unexpected exception: %s" % e)
    
    def test_parser(self):
        parser = Parser()
        parser.parse("\\count0=1\\begingroup\\count0=2")
        self.assertEqual(parser.state.count[0], 2)
        parser.parse("\\endgroup")
        self.assertEqual(parser.state.count[0], 1)
        try:
            parser.parse("{\\endgroup")
            self.fail("group matching failed")
        except ValueError as e:
            self.assertTrue("mismatch" in str(e))
        try:
            parser.parse("\\begingroup}")
            self.fail("group matching failed")
        except ValueError as e:
            self.assertTrue("mismatch" in str(e))
        

if __name__ == '__main__':
    unittest.main()