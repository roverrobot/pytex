import unittest
from pytex import tfm
from pytex.parser import Parser
from pytex import texlive

class TestTFM(unittest.TestCase):
    def test_read_tfm(self):
        resolver = texlive.TexliveResolver()
        tfm_file = resolver.openIn("cmr10.tfm")
        try:
            tfm_data = tfm.TFM(tfm_file)
            self.assertEqual(tfm_data.header.size, 10.0)
        except FileNotFoundError:
            self.skipTest("cmr10.tfm not found")
    
    def test_nullfont(self):
        parser = Parser()
        nullfont = parser.state.globals["tfm"]["nullfont"]
        self.assertEqual(nullfont.header.size, 0.0)
        self.assertEqual(nullfont.ec, 0)
        self.assertEqual(nullfont.bc, 0)
        c = nullfont.char_info[0]
        self.assertEqual(c.width, 0)
        self.assertEqual(c.height, 0)
        self.assertEqual(c.depth, 0)
        self.assertEqual(c.italic, 0)
        self.assertEqual(c.program, None)
        self.assertEqual(c.chain, None)
        self.assertEqual(c.extend, None)
        self.assertEqual(nullfont.param, [0] * 7)



if __name__ == '__main__':
    unittest.main()