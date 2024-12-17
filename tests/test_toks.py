import unittest
from pytex.parser import Parser


class TestToks(unittest.TestCase):
    def test_read_toks(self):
        parser = Parser()
        parser.readFrom("{abcd}")
        k = parser.readBalanced(expand=False)
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
        self.assertEqual(parser.tokens, "ab ")
        
if __name__ == '__main__':
    unittest.main()