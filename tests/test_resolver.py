import unittest
from pytex.parser import Parser
from pytex import texlive
from pytex.resolver import InMemoryTextFile

import os
class TestTeXLive(unittest.TestCase):
    def test_resolve_read(self):
        parser = Parser()
        f = parser.resolver.openIn("tests/test_resolver.py")
        self.assertIsNotNone(f)
        f.close()
        f = parser.resolver.openIn("plain", "source")
        self.assertIsNotNone(f)

    def test_read_file_name(self):
        parser = Parser()
        parser.readFrom("abc.def g")
        name = parser.readFileName()
        self.assertEqual(name, "abc.def")
        t = parser.token()
        self.assertEqual(t.name, "g")
        parser.readFrom("abc.def{")
        name = parser.readFileName()
        self.assertEqual(name, "abc.def")
        parser.readFrom("abc.def}")
        name = parser.readFileName()
        self.assertEqual(name, "abc.def")
        
    def test_in_memory_file(self):
        parser = Parser()
        parser.resolver.in_memory_files["test.tex"] = InMemoryTextFile("abc")
        f = parser.resolver.openIn("test.tex", "source")
        self.assertIsNotNone(f)
        f = parser.resolver.openIn("test", "source")
        self.assertIsNotNone(f)


if __name__ == '__main__':
    unittest.main()