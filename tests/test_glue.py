import unittest
from pytex.parser import Parser

class TestReadDimen(unittest.TestCase):
    def test_read_glue(self):
        parser = Parser()
        parser.readFrom("10 pt a")
        result = parser.readGlue()
        self.assertEqual(result.dimen, 10)
        self.assertEqual(result.stretch.factor, 0)
        self.assertEqual(result.stretch.order, 0)
        self.assertEqual(result.shrink.factor, 0)
        self.assertEqual(result.shrink.order, 0)
        t = parser.token_expand()
        self.assertEqual(t.name, 'a')
        parser.readFrom("-10in plus 1pt m")
        result = parser.readGlue()
        self.assertEqual(result.dimen, -10*72.27)
        self.assertEqual(result.stretch.factor, 1)
        self.assertEqual(result.stretch.order, 0)
        self.assertEqual(result.shrink.factor, 0)
        self.assertEqual(result.shrink.order, 0)
        t = parser.token_expand()
        self.assertEqual(t.name, 'm')
        parser.readFrom("-10in minus 1pt")
        result = parser.readGlue()
        self.assertEqual(result.dimen, -10*72.27)
        self.assertEqual(result.stretch.factor, 0)
        self.assertEqual(result.stretch.order, 0)
        self.assertEqual(result.shrink.factor, 1)
        self.assertEqual(result.shrink.order, 0)
        parser.readFrom("-10in plus 1pt minus 2fillll")
        result = parser.readGlue()
        self.assertEqual(result.dimen, -10*72.27)
        self.assertEqual(result.stretch.factor, 1)
        self.assertEqual(result.stretch.order, 0)
        self.assertEqual(result.shrink.factor, 2)
        self.assertEqual(result.shrink.order, 3)
        t = parser.token_expand()
        self.assertIsNone(t)
        
    def test_read_mu(self):
        parser = Parser()
        parser.readFrom("10 mu")
        result = parser.readGlue(mu=True)
        self.assertEqual(result.dimen, 10)
        self.assertEqual(result.stretch.factor, 0)
        self.assertEqual(result.stretch.order, 0)
        self.assertEqual(result.shrink.factor, 0)
        self.assertEqual(result.shrink.order, 0)
        parser.readFrom("-10mu plus 1fil minus 2mu")
        result = parser.readGlue(mu=True)
        self.assertEqual(result.dimen, -10)
        self.assertEqual(result.stretch.factor, 1)
        self.assertEqual(result.stretch.order, 1)
        self.assertEqual(result.shrink.factor, 2)
        self.assertEqual(result.shrink.order, 0)
        parser.readFrom("-10mu plus 1pt")
        try:
            result = parser.readGlue(mu=True)
            self.fail()
        except Exception as e:
            self.assertTrue('mu dimension expected' in str(e))

    def test_glue_array(self):
        parser = Parser()
        parser.parse("\\skip0 = 10 pt plus 1pt minus 2fil")
        skip0 = parser.state.skip[0]
        self.assertEqual(skip0.dimen, 10)
        self.assertEqual(skip0.stretch.factor, 1)
        self.assertEqual(skip0.stretch.order, 0)
        self.assertEqual(skip0.shrink.factor, 2)
        self.assertEqual(skip0.shrink.order, 1)
        parser.parse("{\\skip0 = 1 pt")
        skip0 = parser.state.skip[0]
        self.assertEqual(skip0.dimen, 1)
        self.assertEqual(skip0.stretch.factor, 0)
        self.assertEqual(skip0.stretch.order, 0)
        self.assertEqual(skip0.shrink.factor, 0)
        self.assertEqual(skip0.shrink.order, 0)
        parser.parse("}")
        skip0 = parser.state.skip[0]
        self.assertEqual(skip0.dimen, 10)
        self.assertEqual(skip0.stretch.factor, 1)
        self.assertEqual(skip0.stretch.order, 0)
        self.assertEqual(skip0.shrink.factor, 2)
        self.assertEqual(skip0.shrink.order, 1)


    def test_muglue_array(self):
        parser = Parser()
        parser.parse("\\muskip0 = 1 mu plus 1mu minus 2fil")
        muskip0 = parser.state.muskip[0]
        self.assertEqual(muskip0.dimen, 1)
        self.assertEqual(muskip0.stretch.factor, 1)
        self.assertEqual(muskip0.stretch.order, 0)
        self.assertEqual(muskip0.shrink.factor, 2)
        self.assertEqual(muskip0.shrink.order, 1)
        try:
            parser.parse("\\muskip0 = 1 pt")
            self.fail()
        except Exception as e:
            self.assertTrue('mu dimension expected' in str(e))


if __name__ == '__main__':
    unittest.main()