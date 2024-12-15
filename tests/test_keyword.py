import unittest
from pytex.parser import Parser


class TestReadKeyword(unittest.TestCase):
    def test_read_keyword(self):
        parser = Parser()
        parser.readFrom(" test  ")
        k = parser.readKeyword({"tes"})
        self.assertEqual(k, "tes")
        t = parser.token_expand()
        self.assertEqual(t.name, "t")
        parser.readFrom(" test  ")
        k = parser.readKeyword({"test", "false"})
        self.assertEqual(k, "test") 
        t = parser.token_expand()
        self.assertIsNone(t)
        parser.readFrom(" tes  ")
        k = parser.readKeyword({"test", "false"})
        self.assertIsNone(k)
        t = parser.token_expand()
        self.assertEqual(t.name, "t")


if __name__ == '__main__':
    unittest.main()