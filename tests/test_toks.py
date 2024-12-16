import unittest
from pytex.parser import Parser


class TestToks(unittest.TestCase):
    def test_read_toks(self):
        parser = Parser()
        parser.readFrom("{abcd}")
        k = parser.readBalanced(expand=False)
        self.assertEqual(len(k), 4)
        self.assertEqual(k[3].name, "d")


    def test_toks_register(self):
        parser = Parser()
        parser.parse("\\toks0={abcd}")
        k = parser.state.toks[0]
        self.assertEqual(len(k), 4)
        self.assertEqual(k[3].name, "d")

if __name__ == '__main__':
    unittest.main()