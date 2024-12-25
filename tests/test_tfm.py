import unittest
from pytex import tfm
from pytex import texlive

class TestTFM(unittest.TestCase):
    def test_read_tfm(self):
        resolver = texlive.TexliveResolver()
        tfm_file = resolver.openIn("cmr10.tfm")
        try:
            tfm_data = tfm.TFM("cmr10", tfm_file)
            self.assertEqual(tfm_data.header.size, 10.0)
        except FileNotFoundError:
            self.skipTest("cmr10.tfm not found")


if __name__ == '__main__':
    unittest.main()