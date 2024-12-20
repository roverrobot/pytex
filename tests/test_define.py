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
        self.assertEqual(str(parser.tokens), "01")

    def test_chardef(self):
        parser = Parser()
        parser.parse("\\chardef\\a=`a \\a")
        self.assertEqual(str(parser.tokens), "a")
        parser.parse("\\count0=\\a")
        self.assertEqual(parser.state.count[0], ord("a"))

    def test_countdef(self):
        parser = Parser()
        parser.parse("\\countdef\\a=0\\a=1\\count1=-\\a")
        self.assertEqual(parser.state.count[0], 1)
        self.assertEqual(parser.state.count[1], -1)

    def test_afterassignment(self):
        parser = Parser()
        parser.parse("\\afterassignment a{\\count0=1}")
        self.assertEqual(str(parser.tokens), "a ")


class TestDefine(unittest.TestCase):
    def test_macro_definition(self):
        parser = Parser()
        parser.parse("\\def\\a{1}")
        a = parser.lookup("\\a")
        self.assertIsNotNone(a)
        self.assertEqual(len(a.parameters), 0)
        self.assertEqual(len(a.replacement), 1)
        self.assertEqual(a.replacement[0].name, "1")
        parser.parse("\\def\\a#1{#1}")
        a = parser.lookup("\\a")
        self.assertIsNotNone(a)
        self.assertEqual(len(a.parameters), 2)
        self.assertEqual(a.parameters[0].catcode, CATCODE.PARAMETER)
        self.assertEqual(a.parameters[1].name, "1")
        self.assertEqual(len(a.replacement), 2)
        self.assertEqual(a.replacement[0].catcode, CATCODE.PARAMETER)
        self.assertEqual(a.replacement[1].name, "1")
        parser.parse("\\def\\a#1#2{#1#2}")
        a = parser.lookup("\\a")
        self.assertIsNotNone(a)
        self.assertEqual(len(a.parameters), 4)
        self.assertEqual(a.parameters[0].catcode, CATCODE.PARAMETER)
        self.assertEqual(a.parameters[1].name, "1")
        self.assertEqual(a.parameters[2].catcode, CATCODE.PARAMETER)
        self.assertEqual(a.parameters[3].name, "2")
        self.assertEqual(len(a.replacement), 4)
        self.assertEqual(a.replacement[0].catcode, CATCODE.PARAMETER)
        self.assertEqual(a.replacement[1].name, "1")
        self.assertEqual(a.replacement[2].catcode, CATCODE.PARAMETER)
        self.assertEqual(a.replacement[3].name, "2")
        parser.parse("\\def\\a12 {1}")
        a = parser.lookup("\\a")
        self.assertIsNotNone(a)
        self.assertEqual(len(a.parameters), 3)
        self.assertEqual(a.parameters[0].name, "1")
        self.assertEqual(a.parameters[1].name, "2")
        self.assertEqual(a.parameters[2].name, " ")
        self.assertEqual(len(a.replacement), 1)
        self.assertEqual(a.replacement[0].name, "1")
        parser.parse("\\def\\a1#12{}")
        a = parser.lookup("\\a")
        self.assertIsNotNone(a)
        self.assertEqual(len(a.parameters), 4)
        self.assertEqual(a.parameters[0].name, "1")
        self.assertEqual(a.parameters[1].catcode, CATCODE.PARAMETER)
        self.assertEqual(a.parameters[2].name, "1")
        self.assertEqual(a.parameters[3].name, "2")
        self.assertEqual(len(a.replacement), 0)
        parser.parse("\\def\\a1#12#2{}")
        a = parser.lookup("\\a")
        self.assertEqual(len(a.parameters), 6)
        self.assertEqual(a.parameters[0].name, "1")
        self.assertEqual(a.parameters[1].catcode, CATCODE.PARAMETER)
        self.assertEqual(a.parameters[2].name, "1")
        self.assertEqual(a.parameters[3].name, "2")
        self.assertEqual(a.parameters[4].catcode, CATCODE.PARAMETER)
        self.assertEqual(a.parameters[5].name, "2")
        self.assertEqual(len(a.replacement), 0)
        try:
            parser.parse("\\def\\a1#12#2")
            self.fail("Expected ValueError")
        except ValueError as e:
            self.assertIn("{", str(e))
        try:
            parser.parse("\\def\\a1#12#2{")
            self.fail("Expected ValueError")
        except ValueError as e:
            self.assertIn("unbalanced", str(e))
        try:
            parser.parse("\\def\\a1#2{}")
            self.fail("Expected ValueError")
        except ValueError as e:
            self.assertIn("from 1", str(e))

    def test_macro_expansion(self):
        parser = Parser()
        parser.parse("\\def\\a{1}\\a")
        self.assertEqual(str(parser.tokens), "1")
        parser.parse("\\def\\a#1{#1}\\a{2}")
        self.assertEqual(str(parser.tokens), "2 ")
        parser.parse("\\def\\a#1#2{#1#2}\\a{1} 2")
        self.assertEqual(str(parser.tokens), "12 ")
        parser.parse("\\def\\a12 {1}\\a12")
        self.assertEqual(str(parser.tokens), "1")
        parser.parse("\\def\\a1#12{#1}\\a1{2}2")
        self.assertEqual(str(parser.tokens), "2 ")
        parser.parse("\\def\\a1#12#2{#1#2}\\a1{2}23")
        self.assertEqual(str(parser.tokens), "23 ")
        try:
            parser.parse("\\def\\a1#12#2{#1#2}\\a1{2}")
            self.fail("Expected ValueError")
        except ValueError as e:
            self.assertIn("macro does not match", str(e))
        try:
            parser.parse("\\def\\a1#12#2b{#1#2}\\a1{2}2{3}a")
            self.fail("Expected ValueError")
        except ValueError as e:
            self.assertIn("match", str(e))


    def test_prefixes(self):
        parser = Parser()
        parser.parse("\\def\\a{1}\\long\\def\\b{2}{\\global\\def\\c{3}}\\outer\\def\\d{4}")
        a = parser.lookup("\\a")
        self.assertFalse(a.long)
        self.assertFalse(a.outer)
        b = parser.lookup("\\b")
        self.assertTrue(b.long)
        self.assertFalse(b.outer)
        c = parser.lookup("\\c")
        self.assertIsNotNone(c)
        self.assertFalse(c.long)
        self.assertFalse(c.outer)
        d = parser.lookup("\\d")
        self.assertTrue(d.outer)
        self.assertFalse(d.long)
        parser.parse("{\\global\\outer\\def\\e{5}}")
        e = parser.lookup("\\e")
        self.assertIsNotNone(e)
        self.assertTrue(e.outer)
        self.assertFalse(e.long)
        try:
            parser.parse("\\outer\\let\\f6")
            self.fail("Expected ValueError")
        except ValueError as e:
            self.assertIn("macro", str(e))
    
    def test_edef_gdef(self):
        parser = Parser()
        parser.parse("\\def\\a{1}\\edef\\b{\\a}\\b")
        self.assertEqual(str(parser.tokens), "1")
        b = parser.lookup("\\b")
        self.assertEqual(b.replacement[0].name, "1")
        parser.parse("{\\gdef\\a{2}}\\a")
        self.assertEqual(str(parser.tokens), "2")
        try:
            parser.parse("{\\xdef\\c{\\a}")
            c = parser.lookup("\\c")
            self.assertEqual(c.replacement[0].name, "2")
        except ValueError as e:
            self.assertIn("defined", str(e))
            self.fail()


if __name__ == '__main__':
    unittest.main()