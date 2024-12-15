import unittest
from pytex.parser import Parser
from pytex.token import Token, CATCODE

class TestInteger(unittest.TestCase):
    def test_read_integer(self):
        parser = Parser()
        parser.readFrom("123 a")
        result = parser.readInteger()
        self.assertEqual(result, 123)
        t = parser.token_expand()
        self.assertIsNotNone(t)
        self.assertEqual(t.catcode, CATCODE.LETTER)
        self.assertEqual(t.name, "a")
        parser.readFrom("'10")
        result = parser.readInteger()
        self.assertEqual(result, 8)
        parser.readFrom('"10')
        result = parser.readInteger()
        self.assertEqual(result, 16)
        parser.readFrom("`a")
        result = parser.readInteger()
        self.assertEqual(result, 97)
        parser.readFrom("`\\a")
        result = parser.readInteger()
        self.assertEqual(result, 97)

    
    def test_read_signed_integer(self):
        parser = Parser()
        parser.readFrom("-123")
        result = parser.readInteger()
        self.assertEqual(result, -123)
        parser.readFrom("+123")
        result = parser.readInteger()
        self.assertEqual(result, 123)
        parser.readFrom("--123")
        result = parser.readInteger()
        self.assertEqual(result, 123)
        parser.readFrom("-+123")
        result = parser.readInteger()
        self.assertEqual(result, -123)
        parser.readFrom("++123")
        result = parser.readInteger()
        self.assertEqual(result, 123)
        try:
            parser.readFrom("abc")
            result = parser.readInteger()
        except ValueError as e:
            pass

    def test_integer_array(self):
        parser = Parser()
        parser.parse("\\count0=1")
        self.assertEqual(parser.state.count[0], 1)
        parser.parse("\\count0 2")
        self.assertEqual(parser.state.count[0], 2)
        parser.parse("\\count1=-\\count0")
        self.assertEqual(parser.state.count[1], -2)
        parser.parse("{\\count1=1")
        self.assertEqual(parser.state.count[1], 1)
        parser.parse("}")
        self.assertEqual(parser.state.count[1], -2)
        parser.parse("{\\global\\count1=1}")
        self.assertEqual(parser.state.count[1], 1)

if __name__ == '__main__':
    unittest.main()