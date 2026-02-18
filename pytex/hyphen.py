"""
This module implements hyphenation

Only explicit \\hyphenation exceptions are implemented for now.
\\patterns is parsed and stored, but pattern matching is not implemented yet.

Planned \\patterns representation:
- one trie per integer \\language id.
- each pattern is split into:
  - letters (trie path), and
  - inter-letter weights stored at the terminal node.
- during matching, we will walk the trie from each start position in ".word."
  and merge terminal weights with element-wise max, then keep odd positions.
"""

from pytex import token
from pytex.module import Module


class _PatternTrieNode:
    """
    Trie node for TeX hyphenation patterns.

    - `children`: next letter -> child node.
    - `weights`: terminal pattern weights at this node, or None if this node
      does not terminate a pattern.
    """
    __slots__ = ("children", "weights")

    def __init__(self):
        self.children = {}
        self.weights = None


class Hyphenation(token.Command):
    """
    The \\hyphenation command
    """
    def execute(self, parser):
        parser.hyphenator.setLanguage(parser.state.parameters["language"])
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
    Hyphenator state for all TeX language ids.

    Data model:
    - `dicts[lang]`: explicit \\hyphenation exception map for that language.
    - `pattern_tries[lang]`: root trie node for \\patterns of that language.
    - `words` / `pattern_trie`: active views for current `language`.
    """
    LANGUAGES = 256
    def __init__(self):
        # the words are organized into dictionaries that are indexed by the language
        self.dicts = [{} for i in range(self.LANGUAGES)]
        # one pattern trie per language id (filled by \\patterns in a later step)
        self.pattern_tries = [_PatternTrieNode() for i in range(self.LANGUAGES)]
        self.language = 0
        self.words = self.dicts[self.language]
        self.pattern_trie = self.pattern_tries[self.language]

    @staticmethod
    def _insertPattern(root, letters, weights):
        """
        Insert one normalized TeX pattern into a trie root.

        @return True if this pattern key already existed.
        """
        if not letters:
            return False
        node = root
        for c in letters:
            child = node.children.get(c)
            if child is None:
                child = _PatternTrieNode()
                node.children[c] = child
            node = child
        duplicate = node.weights is not None
        # For now we keep the latter declaration when duplicates occur.
        node.weights = list(weights)
        return duplicate

    @staticmethod
    def _parsePattern(pattern):
        """
        Parse one normalized pattern token into letters and inter-letter weights.
        """
        letters = []
        weights = [0]
        for c in pattern:
            if "0" <= c <= "9":
                value = ord(c) - ord("0")
                if value > weights[-1]:
                    weights[-1] = value
                continue
            letters.append(c)
            weights.append(0)
        return "".join(letters), weights

    def addPatterns(self, patterns):
        """
        Add normalized pattern tokens to the trie of the current language.

        @return list of duplicate pattern letter-keys.
        """
        root = self.pattern_trie
        duplicates = []
        for pattern in patterns:
            letters, weights = self._parsePattern(pattern)
            if self._insertPattern(root, letters, weights):
                duplicates.append(letters)
        return duplicates

    @staticmethod
    def _dumpPatternTrie(root):
        """
        Flatten one trie into serializable [letters, weights] pairs.
        """
        out = []
        stack = [("", root)]
        while stack:
            letters, node = stack.pop()
            if node.weights is not None:
                out.append([letters, list(node.weights)])
            # Keep deterministic dump order.
            keys = sorted(node.children.keys(), reverse=True)
            for c in keys:
                stack.append((letters + c, node.children[c]))
        return out

    def dump(self):
        """
        Dump hyphenator data for parser format files.
        """
        words = {}
        for i, d in enumerate(self.dicts):
            if d:
                words[str(i)] = {word: list(pos) for word, pos in d.items()}
        patterns = {}
        for i, root in enumerate(self.pattern_tries):
            flattened = self._dumpPatternTrie(root)
            if flattened:
                patterns[str(i)] = flattened
        return {
            "language": self.language,
            "words": words,
            "patterns": patterns,
        }

    def load(self, data):
        """
        Load hyphenator data previously produced by dump().
        """
        self.dicts = [{} for i in range(self.LANGUAGES)]
        self.pattern_tries = [_PatternTrieNode() for i in range(self.LANGUAGES)]
        words = data.get("words", {})
        for key, d in words.items():
            i = int(key)
            if i < 0 or i >= self.LANGUAGES:
                continue
            self.dicts[i] = {word: list(pos) for word, pos in d.items()}
        patterns = data.get("patterns", {})
        for key, flattened in patterns.items():
            i = int(key)
            if i < 0 or i >= self.LANGUAGES:
                continue
            root = self.pattern_tries[i]
            for item in flattened:
                letters, weights = item
                self._insertPattern(root, letters, weights)
        language = data.get("language", 0)
        if not isinstance(language, int) or language < 0 or language >= self.LANGUAGES:
            language = 0
        self.language = 0
        self.words = self.dicts[0]
        self.pattern_trie = self.pattern_tries[0]
        self.setLanguage(language)

    def setLanguage(self, language):
        """
        Set the language
        """
        if self.language != language:
            self.language = language
            self.words = self.dicts[self.language]
            self.pattern_trie = self.pattern_tries[self.language]

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
        return self.words.get(word, [])


class Patterns(token.Command):
    """
    The \\patterns command

    Parse and store TeX hyphenation patterns for the current language.
    """
    def execute(self, parser):
        parser.hyphenator.setLanguage(parser.state.parameters["language"])
        content = parser.readGeneralText()
        lccode = parser.state.lccode
        patterns = []
        current = []

        for t in content:
            if t.isSpace(True):
                if current:
                    patterns.append(current)
                    current = []
                continue

            c = None
            if t.catcode == token.CATCODE.LETTER:
                code = lccode[ord(t.name)]
                if code != 0:
                    c = chr(code)
            elif t.catcode == token.CATCODE.OTHER and (
                ("0" <= t.name <= "9") or t.name == "."
            ):
                c = t.name

            if c is not None:
                current.append(c)

        if current:
            patterns.append(current)

        duplicates = parser.hyphenator.addPatterns(patterns)
        for letters in duplicates:
            parser.message(
                f"warning: duplicate hyphenation pattern '{letters}', using latter weights",
                console=False,
            )


def init(parser):
    parser.hyphenator = Hyphenator()


mod = Module("hyphen",
    init=init,
    commands={
        "hyphenation": Hyphenation(),
        "patterns": Patterns(),
    },
)
