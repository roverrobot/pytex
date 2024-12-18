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


    def test_ifcase(self):
        parser = Parser()
        parser.parse("\\ifcase0 a\\or b\\fi")
        self.assertEqual(str(parser.tokens), "a")
        parser.parse("\\ifcase1 a\\or b\\fi")
        self.assertEqual(str(parser.tokens), "b")
        parser.parse("\\ifcase2 a\\or b\\fi")
        self.assertEqual(str(parser.tokens), "")
        parser.parse("\\ifcase4 a\\or b\\else c\\fi")
        self.assertEqual(str(parser.tokens), "c")

    def test_ifnum(self):
        parser = Parser()
        parser.parse("\\count0 1\\count 1 2")
        parser.parse("\\ifnum \\count0=\\count1 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "b")
        parser.parse("\\ifnum 1>\\count1 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "b")
        parser.parse("\\ifnum 1=\\count0 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "a")
        parser.parse("\\ifnum 1=2 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "b")
        try:
            parser.parse("\\ifnum 1\\else\\fi")
            self.fail()
        except ValueError as e:
            self.assertIn("else", str(e))
        try:
            parser.parse("\\ifnum 1 2\\else\\fi")
            self.fail()
        except ValueError as e:
            self.assertIn("comparison", str(e))
        try:
            parser.parse("\\ifnum 1=a\\else\\fi")
            self.fail()
        except ValueError as e:
            self.assertIn("integer", str(e))


    def test_ifdim(self):
        parser = Parser()
        parser.parse("\\dimen0 1pt\\dimen1 2pt")
        parser.parse("\\ifdim\\dimen0<\\dimen1 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "a")
        parser.parse("\\ifdim 1pt>\\dimen1 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "b")
        parser.parse("\\ifdim 1pt=\\dimen0 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "a")
        parser.parse("\\ifdim 1pt=\\dimen1 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "b")
        try:
            parser.parse("\\ifdim 1\\else\\fi")
            self.fail()
        except ValueError as e:
            self.assertIn("else", str(e))
        try:
            parser.parse("\\ifdim 1pt\\else\\fi")
            self.fail()
        except ValueError as e:
            self.assertIn("else", str(e))
        try:
            parser.parse("\\ifdim 1pt 2pt\\else\\fi")
            self.fail()
        except ValueError as e:
            self.assertIn("comparison", str(e))
        try:
            parser.parse("\\ifdim 1pt=a\\else\\fi")
            self.fail()
        except ValueError as e:
            self.assertIn("number", str(e))

    def test_ifodd(self):
        parser = Parser()
        parser.parse("\\ifodd1 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "a")
        parser.parse("\\ifodd2 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "b")
        parser.parse("\\count0 3 \\ifodd\\count0 a\\else b\\fi")
        self.assertEqual(str(parser.tokens), "a")


if __name__ == '__main__':
    unittest.main()
