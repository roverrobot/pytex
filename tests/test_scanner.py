import unittest
from pytex.token import CATCODE
from pytex import lexer


class TestScanner(unittest.TestCase):
    def catcode(self):
        catcode = []
        for c in range(256):
            catcode.append(CATCODE.OTHER)
        for c in range(ord("A"), ord("Z") + 1):
            catcode[c] = CATCODE.LETTER
            catcode[c + 32] = CATCODE.LETTER
        catcode[ord("\\")] = CATCODE.ESCAPE
        catcode[ord("{")] = CATCODE.BEGIN_GROUP
        catcode[ord("}")] = CATCODE.END_GROUP
        catcode[ord("\r")] = CATCODE.END_OF_LINE
        catcode[ord(" ")] = CATCODE.SPACE
        catcode[ord("\t")] = CATCODE.SPACE
        catcode[ord("^")] = CATCODE.SUPERSCRIPT
        catcode[ord("_")] = CATCODE.SUBSCRIPT
        catcode[ord("$")] = CATCODE.MATH_SHIFT
        catcode[ord("#")] = CATCODE.PARAMETER
        catcode[ord("&")] = CATCODE.ALIGNMENT_TAB
        catcode[ord("%")] = CATCODE.COMMENT
        catcode[ord("@")] = CATCODE.ACTIVE
        catcode[8] = CATCODE.INVALID
        return catcode

    def test_token(self):
        catcode = self.catcode()
        scanner = lexer.Scanner(catcode, "A1{}^_$#&@")
        token = scanner.read()
        self.assertEqual(token.name, "A")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        token = scanner.read()
        self.assertEqual(token.name, "1")
        self.assertEqual(token.catcode, CATCODE.OTHER)
        token = scanner.read()
        self.assertEqual(token.name, "{")
        self.assertEqual(token.catcode, CATCODE.BEGIN_GROUP)
        token = scanner.read()
        self.assertEqual(token.name, "}")
        self.assertEqual(token.catcode, CATCODE.END_GROUP)
        token = scanner.read()
        self.assertEqual(token.name, "^")
        self.assertEqual(token.catcode, CATCODE.SUPERSCRIPT)
        token = scanner.read()
        self.assertEqual(token.name, "_")
        self.assertEqual(token.catcode, CATCODE.SUBSCRIPT)
        token = scanner.read()
        self.assertEqual(token.name, "$")
        self.assertEqual(token.catcode, CATCODE.MATH_SHIFT)
        token = scanner.read()
        self.assertEqual(token.name, "#")
        self.assertEqual(token.catcode, CATCODE.PARAMETER)
        token = scanner.read()
        self.assertEqual(token.name, "&")
        self.assertEqual(token.catcode, CATCODE.ALIGNMENT_TAB)
        token = scanner.read()
        self.assertEqual(token.name, "@")
        self.assertIsNone(token.catcode)
        token = scanner.read()
        self.assertEqual(token.catcode, CATCODE.SPACE)
        token = scanner.read()
        self.assertIsNone(token)

    def test_command(self):
        catcode = self.catcode()
        scanner = lexer.Scanner(catcode, "\\alpha 1\\beta\n")
        token = scanner.read()
        self.assertEqual(token.name, "\\alpha")
        self.assertIsNone(token.catcode)
        token = scanner.read()
        self.assertEqual(token.name, "1")
        self.assertEqual(token.catcode, CATCODE.OTHER)
        token = scanner.read()
        self.assertEqual(token.name, "\\beta")
        self.assertIsNone(token.catcode)
        token = scanner.read()
        self.assertIsNone(token)

    def test_comment(self):
        catcode = self.catcode()
        scanner = lexer.Scanner(catcode, "A%comment")
        token = scanner.read()
        self.assertEqual(token.name, "A")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        token = scanner.read()
        self.assertIsNone(token)

    def test_space(self):
        catcode = self.catcode()
        scanner = lexer.Scanner(catcode, "A  \tB")
        token = scanner.read()
        self.assertEqual(token.name, "A")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        token = scanner.read()
        self.assertEqual(token.name, " ")
        self.assertEqual(token.catcode, CATCODE.SPACE)
        token = scanner.read()
        self.assertEqual(token.name, "B")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        token = scanner.read()
        self.assertEqual(token.catcode, CATCODE.SPACE)
        token = scanner.read()
        self.assertIsNone(token)

    def test_eol(self):
        catcode = self.catcode()
        scanner = lexer.Scanner(catcode, "A \n \n B")
        token = scanner.read()
        self.assertEqual(token.name, "A")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        token = scanner.read()
        self.assertEqual(token.name, " ")
        self.assertEqual(token.catcode, CATCODE.SPACE)
        token = scanner.read()
        self.assertEqual(token.name, "\\par")
        self.assertIsNone(token.catcode)
        token = scanner.read()
        self.assertEqual(token.name, "B")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        p = scanner.position()
        self.assertEqual(p.line, 3)
        self.assertEqual(p.column, 2)
        token = scanner.read()
        self.assertEqual(token.catcode, CATCODE.SPACE)
        token = scanner.read()
        self.assertIsNone(token)

    def test_expand(self):
        catcode = self.catcode()
        scanner = lexer.Scanner(catcode, "^^61^^a")
        token = scanner.read()
        self.assertEqual(token.name, "a")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        token = scanner.read()
        self.assertEqual(token.name, "!")
        self.assertEqual(token.catcode, CATCODE.OTHER)
        token = scanner.read()
        self.assertEqual(token.catcode, CATCODE.SPACE)
        token = scanner.read()
        self.assertIsNone(token)

    def test_input_stack(self):
        catcode = self.catcode()
        stack = lexer.InputStack()
        scanner = lexer.Scanner(catcode, "ABC")
        stack.push(scanner)
        token = stack.read()
        self.assertEqual(token.name, "A")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        B = stack.read()
        C = stack.read()
        stack.unread(C)
        stack.unread(B)
        scanner = lexer.Scanner(catcode, "1")
        stack.push(scanner)
        token = stack.read()
        self.assertEqual(token.name, "1")
        self.assertEqual(token.catcode, CATCODE.OTHER)
        token = scanner.read()
        self.assertEqual(token.catcode, CATCODE.SPACE)
        token = stack.read()
        self.assertEqual(token.name, "C")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        token = stack.read()
        self.assertEqual(token.name, "B")
        self.assertEqual(token.catcode, CATCODE.LETTER)
        token = scanner.read()
        self.assertIsNone(token)


if __name__ == '__main__':
    unittest.main()