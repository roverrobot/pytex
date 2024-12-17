import unittest
from pytex.parser import Parser


class TestToks(unittest.TestCase):
    def test_read_toks(self):
        parser = Parser()
        parser.readFrom("{abcd}")
        k = parser.readBalancedText(expand=False)
        self.assertEqual(len(k), 4)
        self.assertEqual(k[3].name, "d")
    
    def test_read_general_text(self):
        parser = Parser()
        parser.readFrom(" \\relax  {abcd}")
        k = parser.readGeneralText(expand=False)
        self.assertEqual(len(k), 4)
        self.assertEqual(k[3].name, "d")


    def test_toks_register(self):
        parser = Parser()
        parser.parse("\\toks0={abcd}")
        k = parser.state.toks[0]
        self.assertEqual(len(k), 4)
        self.assertEqual(k[3].name, "d")

    def test_aftergroup(self):
        parser = Parser()
        parser.parse("\\aftergroup a\\aftergroup b{\\count0=1}")
        self.assertEqual(str(parser.tokens), "ab ")
        
    def test_case(self):
        parser = Parser()
        parser.parse("\\uppercase{a!}")
        self.assertEqual(str(parser.tokens), "A! ")
        parser.parse("\\lowercase{!A}")
        self.assertEqual(str(parser.tokens), "!a ")
        try:
            parser.parse("\\catcode`z=13\\let z=a\\uppercase{azb}")
            self.fail()
        except ValueError as e:
            self.assertIn("Z", str(e))


if __name__ == '__main__':
    unittest.main()