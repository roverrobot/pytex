import unittest
from pytex.parser import Parser

class TestReadDimen(unittest.TestCase):
    def test_advance(self):
        parser = Parser()
        parser.parse("\\dimen0 = 10 pt\\advance \\dimen0 by 10 pt")
        self.assertEqual(parser.state.dimen[0], 20)
        parser.parse("{\\advance \\dimen0 by 10 pt")
        self.assertEqual(parser.state.dimen[0], 30)
        parser.parse("}")
        self.assertEqual(parser.state.dimen[0], 20)
        parser.parse("{\\global \\advance \\dimen0 by 10 pt}")
        self.assertEqual(parser.state.dimen[0], 30)
        try:
            parser.parse("\\advance \\dimen0 by 10")
            self.fail()
        except Exception as e:
            self.assertTrue('dimension unit expected' in str(e))
        
    def test_read_multiply(self):
        parser = Parser()
        parser.parse("\\dimen0 = 10 pt\\multiply \\dimen0 by 2 pt")
        self.assertEqual(parser.state.dimen[0], 20)
        self.assertEqual(parser.tokens, "pt ")

    
    def test_read_divide(self):
        parser = Parser()
        parser.parse("\\dimen0 = 10 pt\\divide \\dimen0 by 2")
        self.assertEqual(parser.state.dimen[0], 5)


if __name__ == '__main__':
    unittest.main()