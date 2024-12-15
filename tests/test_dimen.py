import unittest
from pytex.parser import Parser

class TestReadDimen(unittest.TestCase):
    def test_read_dimen(self):
        parser = Parser()
        parser.readFrom("10 pt")
        result = parser.readDimen()
        self.assertEqual(result, 10)
        parser.readFrom("-10in")
        result = parser.readDimen()
        self.assertEqual(result, -10*72.27)
        parser.readFrom("-1truept")
        result = parser.readDimen()
        self.assertEqual(result, -1)
        parser.readFrom("-1 true pt")
        result = parser.readDimen()
        self.assertEqual(result, -1)      
        
    def test_read_mu(self):
        parser = Parser()
        parser.readFrom("10 mu")
        result = parser.readDimen(mu=True)
        self.assertEqual(result, 10)
        try:
            parser.readFrom("10 pt")
            result = parser.readDimen(mu=True)
            self.fail()
        except Exception as e:
            self.assertTrue('mu dimension expected' in str(e))
    
    def test_read_dimen_with_invalid_token(self):
        parser = Parser()
        parser.readFrom("10 p")
        try:
            result = parser.readDimen()
            self.fail()
        except Exception as e:
            print(e)
            self.assertTrue('dimension unit expected' in str(e))

    def test_dimen_array(self):
        parser = Parser()
        parser.parse("\\dimen0 = 10 pt")
        self.assertEqual(parser.state.dimen[0], 10)
        parser.parse("{\\dimen0 = 1 pt")
        self.assertEqual(parser.state.dimen[0], 1)
        parser.parse("}")
        self.assertEqual(parser.state.dimen[0], 10)


if __name__ == '__main__':
    unittest.main()