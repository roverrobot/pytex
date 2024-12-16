import unittest
from pytex.parser import Parser
from pytex.token import CATCODE

class TestDefine(unittest.TestCase):
    def test_let(self):
        parser = Parser()
        parser.parse("\\let\\a=0\\count\\a=1")
        self.assertEqual(parser.state.equitable["\\a"].name, "0")
        self.assertEqual(parser.state.equitable["\\a"].catcode, CATCODE.OTHER)
        self.assertEqual(parser.state.count[0], 1)
        parser.parse("{\\let\\a=1\\count\\a=1")
        self.assertEqual(parser.state.count[1], 1)
        parser.parse("}")
        self.assertEqual(parser.state.equitable["\\a"].name, "0")
        self.assertEqual(parser.state.equitable["\\a"].catcode, CATCODE.OTHER)

    def test_futurelet(self):
        parser = Parser()
        parser.parse("\\futurelet\\a=01\\a")
        self.assertEqual(parser.tokens, "01")

    def test_chardef(self):
        parser = Parser()
        parser.parse("\\chardef\\a=`a \\a")
        self.assertEqual(parser.tokens, "a")
        parser.parse("\\count0=\\a")
        self.assertEqual(parser.state.count[0], ord("a"))

    def test_countdef(self):
        parser = Parser()
        parser.parse("\\countdef\\a=0\\a=1\\count1=-\\a")
        self.assertEqual(parser.state.count[0], 1)
        self.assertEqual(parser.state.count[1], -1)

if __name__ == '__main__':
    unittest.main()