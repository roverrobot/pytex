import unittest
from pytex.parser import Parser


class TestReadKeyword(unittest.TestCase):
    def test_noexpand(self):
        parser = Parser()
        parser.readFrom("\\noexpand\\test")
        t = parser.token_expand()
        self.assertEqual(t.name, "\\test")
        t = parser.token_expand()
        self.assertIsNone(t)
        parser.readFrom("\\noexpand a")
        t = parser.token_expand()
        self.assertEqual(t.name, "a")

    def test_expandafter(self):
        parser = Parser()
        parser.parse("\\def\\a{a}")
        parser.readFrom("\\expandafter a\\a")
        t = parser.token_expand()
        self.assertEqual(t.name, "a")
        t = parser.token_expand()
        self.assertEqual(t.name, "a")
        t = parser.token_expand()
        self.assertIsNone(t)


if __name__ == '__main__':
    unittest.main()