import unittest
from pytex.parser import Parser


class TestExpandable(unittest.TestCase):
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

    def test_csname(self):
        parser = Parser()
        parser.readFrom("\\csname test\\endcsname")
        t = parser.token_expand()
        self.assertTrue(t.is_command)
        t = parser.token_expand()
        self.assertIsNone(t)
        parser.parse("\\test")
        self.assertEqual(str(parser.tokens), "")
        parser.parse("\\def\\test{a}\\csname test\\endcsname")
        self.assertEqual(str(parser.tokens), "a")
        try:
            parser.parse("\\csname test")
            self.fail()
        except ValueError as e:
            self.assertEqual(str(e), "expecting \\endcsname")
        try:
            parser.parse("\\csname \\count\\endcsname")
            self.fail()
        except ValueError as e:
            self.assertEqual(str(e), "expecting \\endcsname")
        try:
            parser.parse("\\endcsname")
            self.fail()
        except ValueError as e:
            self.assertEqual(str(e), "unexpected \\endcsname")

    def test_number_romannumeral(self):
        parser = Parser()
        parser.parse("\\count0=123 \\number\\count0")
        self.assertEqual(str(parser.tokens), "123")
        parser.parse("\\romannumeral\\count0")
        self.assertEqual(str(parser.tokens), "cxxiii")

    def test_string(self):
        parser = Parser()
        parser.parse("\\escapechar=`! \\string\\test")
        self.assertEqual(str(parser.tokens), "!test")

if __name__ == '__main__':
    unittest.main()