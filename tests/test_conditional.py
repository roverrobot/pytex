import unittest
from pytex.parser import Parser


class TestConditional(unittest.TestCase):
    def test_if(self):
        parser = Parser()
        parser.parse("\\if00a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "a")
        parser.parse("\\if00\\else b\\fi")
        self.assertEqual(str(parser.tokens), "")
        t = parser.token_expand()
        self.assertIsNone(t)
        parser.parse("\\if01a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "b")
        t = parser.token_expand()
        self.assertIsNone(t)
        parser.parse("\\if01a\\fi")
        self.assertEqual(str(parser.tokens), "")
        try:
            parser.parse("\\if00a\\else b")
            self.fail()
        except ValueError as e:
            self.assertIn("\\fi", str(e))
            parser.ifstack.clear()
        try:
            parser.parse("\\fi")
            self.fail()
        except ValueError as e:
            self.assertIn("\\fi", str(e))
        try:
            parser.parse("\\else")
            self.fail()
        except ValueError as e:
            self.assertIn("\\else", str(e))
        try:
            parser.parse("\\if00a\\or b\\fi")
            self.fail()
        except ValueError as e:
            self.assertIn("\\or", str(e))
            parser.ifstack.clear()
    
    def test_ifx(self):
        parser = Parser()
        parser.parse("\\def\\a{a}\\def\\b{a}\\ifx\\a\\b a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "a")
        parser.parse("\\def\\a{0}\\ifx\\a 0 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "b")


if __name__ == '__main__':
    unittest.main()
