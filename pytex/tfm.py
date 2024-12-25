"""
TeX Font Metrics (TFM) file format
"""

from pytex import node
from struct import unpack
import typing


class BinaryStream:
    """
    A binary stream.
    """
    def __init__(self, data):
        self.data = data

    DIVISOR = 1024.0 * 1024.0
    
    def read(self, n):
        """
        Check if the end of the stream is reached.
        """
        value = self.data.read(n)
        k = len(value)
        if k < n:
            pos = data.tell()
            data.close()
            raise EOFError(pos)
        return value

    def readByte(self):
        """
        Read a byte.
        """
        return self.read(1)[0]

    def readWord(self):
        """
        Read a word.
        """
        x = self.read(4)
        return unpack(">I", x)[0]
    
    def readHalfWord(self):
        """
        Read a half word.
        """
        x = self.read(2)
        return unpack(">H", x)[0]
    
    def readShort(self):
        """
        Read a half integer.
        """
        x = self.read(2)
        return unpack(">h", x)[0]

    def readInt(self):
        """
        Read an integer.
        """
        x = self.read(4)
        return unpack(">i", x)[0]

    def readFixed(self, n=None):
        """
        Read n fixed-point numbers.
        @param n: the number of fixed-point numbers to read, or None to read one
        @return: the fixed-point number if n= is None or a list of fixed-point numbers
        """
        if n is None:
            return self.readInt() / self.DIVISOR
        x = self.read(4 * n)
        ints = unpack(f">{n}i", x)
        return [x / self.DIVISOR for x in ints]


    def close(self):
        """
        Close the stream.
        """
        self.data.close()


class Header:
    """
    The header of a TFM file.
    """
    def __init__(self, size: int, data: BinaryStream):
        self.checksum = data.readWord()
        self.size = data.readFixed() # design size
        self.data = data.read(size - 8)


class Op:
    """
    A ligature or kerning operation.
    @param next_char: the next character to match the operation
    """
    def __init__(self, next_char: int):
        self.next_char = next_char
        self.next_step = None

    def op(self, ligature: node.Ligature, next: int):
        """
        Perform the operation.
        @param current: the position of the current character in hlist
        @param next: the next character
        """

    def kernBetween(self, char: int):
        """
        return the kerning between the current character and char.
        @param char: the next character
        """
        return 0 if self.next_step is None else self.next_step.kernBetween(char)


class LigOp(Op):
    """
    A ligature operation.
    @param next_char: the next character to match the operation
    @param insert: the character to insert
    @param op: the operation code

    if the next character is equal to next_char, the insert character is always inserted 
    between the current char and the next_char. What happen next depends on the operation code.
    The operation code is a 4-bit integer 4a+2b+c where b and c are bits and a is a 2-bit integer,
    and a<=b+c.
    c: keep the next character if 1, remove it if 0
    b: keep the current character if 1, remove it if 0
    a: move the current character forward a positions. 
    """
    def __init__(self, next_char: str, insert: int, op: int):
        super().__init__(next_char)
        self.insert = insert
        self.delete_current = op & 2 == 0
        self.keep_next = op & 1 == 1
        self.move = op >> 2

    def op(self, ligature: node.Ligature, next: node.CharNode):
        pass



class KernOp(Op):
    """
    A kerning operation.
    @param next_char: the next character to match the operation
    @param kern: the kerning

    if the next character is equal to next_char, the additional kerning is added between the 
    current char and the next_char.
    """
    def __init__(self, next_char: str, kern: float):
        super().__init__(next_char)
        self.kern = kern

    def op(self, ligature: node.Ligature, next: node.CharNode):
        pass

    def kernBetween(self, char):
        return self.kern if self.next_char == char else super().kernBetween(char)


class LigKern:
    def __init__(self, data: BinaryStream):
        self.skip, self.next, self.opcode, self.remainder = data.read(4)

    def op(self, kern):
        if self.opcode >= 128:
            return KernOp(self.next, kern[256 * (self.opcode - 128) + self.remainder])
        return LigOp(self.next, insert=self.remainder, op=self.opcode)


class Program:
    def __init__(self, ligkern, kern):
        n = len(ligkern)
        self.instructions = [None]*n
        self.left_boundary = None
        self.right_boundary = None
        for i in range(n):
            self.instructions[i] = ligkern[i].op(kern)
        for i in range(n):
            step = ligkern[i]
            if step.skip < 128:
                self.instructions[i].next_step = self.instructions[i + step.skip + 1]
        if n > 0:
            if ligkern[0].skip == 255:
                self.right_boundary = self.instructions[0]
            if ligkern[-1].skip == 255:
                self.left_boundary = self.instructions[ligkern[-1].opcode * 256 + ligkern[-1].remainder]


class CharInfoData:
    NO_TAG = 0
    LIG_TAG = 1
    LIST_TAG = 2
    EXT_TAG = 3

    def __init__(self, char, data: BinaryStream):
        self.char = char
        self.width_index, b, c, self.remainder = data.read(4)
        self.height_index = b // 16
        self.depth_index = b % 16
        self.italic_index = c // 4
        self.tag = c % 4


class CharInfo:
    def __init__(self, char, data: CharInfoData, tfm):
        self.char = char
        self.program = None
        self.chain = None
        self.extend = None
        if tfm is None:
            self.width = 0
            self.height = 0
            self.depth = 0
            self.italic = 0
        else:
            self.width = tfm.width[data.width_index]
            self.height = tfm.height[data.height_index]
            self.depth = tfm.depth[data.depth_index]
            self.italic = tfm.italic[data.italic_index]
            if data.tag == data.LIG_TAG:
                self.program = {}
                step = tfm.program.instructions[data.remainder]
                while step is not None:
                    self.program[step.next_char] = step
                    step = step.next_step
            elif data.tag == data.LIST_TAG:
                self.chain = chr(data.remainder)
            elif data.tag == data.EXT_TAG:
                self.extend = tfm.extend[data.remainder]


class Extend:
    def __init__(self, data: BinaryStream):
        x = data.read(4)
        self.top, self.mod, self.bot, self.rep = unpack(">4B", x)


class TFM:
    def __init__(self, name: str, stream):
        data = BinaryStream(stream)
        self.name = name
        x = data.read(24)
        lf, lh, bc, ec, nw, nh, nd, ni, nl, nk, ne, np = unpack(">12H", x)
        self.bc = bc
        self.ec = ec
        chars = ec - bc + 1
        total = 6 + lh + chars + nw + nh + nd + ni + nl + nk + ne + np
        if lf != total:
            raise ValueError("invalid header")
        self.header = Header(lh * 4, data)
        char_data = [None] * chars
        for i in range(chars):
            char_data[i] = CharInfoData(chr(i+bc), data)
        self.width = data.readFixed(nw)
        self.height = data.readFixed(nh)
        self.depth = data.readFixed(nd)
        self.italic = data.readFixed(ni)
        ligkern = [None]*nl
        for i in range(nl):
            ligkern[i] = LigKern(data)
        self.kern = data.readFixed(nk)
        self.program = Program(ligkern, self.kern)
        self.extend = [None]*ne
        for i in range(ne):
            self.extend[i] = Extend(data)
        self.param = data.readFixed(np)
        for i in range(len(char_data)):
            c = char_data[i]
            if c.tag == c.LIG_TAG:
                step = ligkern[c.remainder]
                if step.skip > 128:
                    c.remainder = step.opcode * 256 + step.remainder
        self.char_info = [None]*chars
        for i in range(chars):
            self.char_info[i] = CharInfo(chr(i+bc), char_data[i], self)
        data.close()


