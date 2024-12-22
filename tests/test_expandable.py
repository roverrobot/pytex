import unittest
from pytex.parser import Parser
from pytex.resolver import InMemoryTextFile


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

    def test_the(self):
        parser = Parser()
        parser.parse("\\count0=0 \\the\\count0")
        self.assertEqual(str(parser.tokens), "0")
        parser.parse("\\dimen0=1pt \\the\\dimen0")
        self.assertEqual(str(parser.tokens), str(parser.state.dimen[0])+"pt")
        parser.parse("\\skip0=1pt plus 1fil minus 1fil \\relax\\the\\skip0")
        self.assertEqual(str(parser.tokens), str(parser.state.skip[0]))
        parser.parse("\\toks0={\\the\\count0}\\the\\toks0")
        self.assertEqual(str(parser.tokens), "0")

    def test_input(self):
        parser = Parser()
        parser.resolver.in_memory_files["test.tex"] = InMemoryTextFile("abc")
        parser.parse("\\input test")
        self.assertEqual(str(parser.tokens), "abc ")


if __name__ == '__main__':
    unittest.main()