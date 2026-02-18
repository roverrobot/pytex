"""
This module implements hyphenation

We keep the adhoc hyphenation command \\hyphenation, but the general algorithm uses
the pyphen library. The \\patterns command thus does nothing.
"""

from pytex import token
from pytex.module import Module
import pyphen


class Hyphenation(token.Command):
    """
    The \\hyphenation command
    """
    def execute(self, parser):
        words = {}
        content = parser.readGeneralText()
        word = ""
        positions = []
        hyphenchar = chr(parser.hyphenChar())
        for t in content:
            if t.isSpace(True) and word:
                words[word] = positions
                word = ""
                positions = []
            elif t.catcode == token.CATCODE.LETTER:
                c = parser.state.lccode[ord(t.name)]
                if c != 0:
                    word += chr(c)
            elif t.name == hyphenchar:
                positions.append(len(word))
        if word:
            words[word] = positions
        parser.hyphenator.addWords(words)


class Hyphenator:
    """
    The hyphenator class
    """
    LANGUAGES = 256
    def __init__(self):
        # the words are organized into dictionaries that are indexed by the language
        self.dicts = [{} for i in range(self.LANGUAGES)]
        self.language = 0
        self.words = self.dicts[self.language]
        self.patterns = {}

    def setLanguage(self, language):
        """
        Set the language
        """
        if self.language != language:
            self.language = language
            self.words = self.dicts[self.language]

    def addWords(self, words):
        """
        Add words to the hyphenator
        """
        for word, positions in words.items():
            if word in self.words:
                self.words[word] += positions
            else:
                self.words[word] = positions

    def hyphenate(self, word):
        """
        Hyphenate a word
        """
        if word in self.words:
            return self.words[word]
        pattern = self.patterns.get(self.language, None)
        if pattern is None:
            # TODO: map integer language ids to specific pattern names.
            pattern = pyphen.Pyphen(lang="en_US")
            self.patterns[self.language] = pattern
        return pattern.positions(word)


class Patterns(token.Command):
    """
    The \\patterns command

    THe hyphanator will use external libraries. So patterns are not implemented
    """
    def execute(self, parser):
        parser.readGeneralText()


mod = Module("hyphen",
    attributes={
        "hyphenator": Hyphenator()
    },
    commands={
        "hyphenation": Hyphenation(),
        "patterns": Patterns(),
    },
)
