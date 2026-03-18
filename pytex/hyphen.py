"""
This module implements hyphenation

Explicit \\hyphenation exceptions are supported.
\\patterns is parsed, stored in a trie, and used for pattern hyphenation.

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
    def __init__(self, parser=None):
        self.parser = parser
        self._reset()

    def _reset(self):
        # the words are organized into dictionaries that are indexed by the language
        self.dicts = [{} for i in range(self.LANGUAGES)]
        # one pattern trie per language id (filled by \\patterns in a later step)
        self.pattern_tries = [_PatternTrieNode() for i in range(self.LANGUAGES)]
        # per-language cache of computed hyphenation points
        self.caches = [{} for i in range(self.LANGUAGES)]
        self._lazy_entries = {}
        self.language = 0
        self.words = self.dicts[self.language]
        self.pattern_trie = self.pattern_tries[self.language]
        self.cache = self.caches[self.language]

    @staticmethod
    def _insertPattern(root, letters, weights):
        """
        Insert one normalized TeX pattern into a trie root.

        If the same letter pattern is declared multiple times, keep the
        element-wise maximum weights. That matches TeX's effective behavior,
        since all matching patterns contribute maxima during hyphenation.
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
        if node.weights is None:
            node.weights = list(weights)
            return False
        existing = node.weights
        if len(existing) < len(weights):
            existing.extend([0] * (len(weights) - len(existing)))
        for i, weight in enumerate(weights):
            if weight > existing[i]:
                existing[i] = weight
        return True

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
        """
        self._ensureLanguageLoaded(self.language)
        root = self.pattern_trie
        for pattern in patterns:
            letters, weights = self._parsePattern(pattern)
            self._insertPattern(root, letters, weights)
        self.cache.clear()

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

    def dumpLanguage(self, language):
        """
        Dump one language's hyphenation data, or None if it is empty.
        """
        self._ensureLanguageLoaded(language)
        words = self.dicts[language]
        patterns = self._dumpPatternTrie(self.pattern_tries[language])
        if not words and not patterns:
            return None
        return {
            "words": {word: list(pos) for word, pos in words.items()},
            "patterns": patterns,
        }

    def dumpLanguages(self):
        """
        Iterate over non-empty language payloads for container dumps.
        """
        for language in range(self.LANGUAGES):
            data = self.dumpLanguage(language)
            if data is not None:
                yield language, data

    def _loadLanguageData(self, language, data):
        """
        Load one language payload into in-memory dictionaries and tries.
        """
        words = data.get("words", {})
        self.dicts[language] = {word: list(pos) for word, pos in words.items()}
        root = _PatternTrieNode()
        for letters, weights in data.get("patterns", ()):
            self._insertPattern(root, letters, weights)
        self.pattern_tries[language] = root
        self.caches[language] = {}
        if self.language == language:
            self.words = self.dicts[language]
            self.pattern_trie = root
            self.cache = self.caches[language]

    def _ensureLanguageLoaded(self, language):
        """
        Load a lazy language payload on first use.
        """
        entry = self._lazy_entries.get(language, None)
        if entry is None:
            return
        container = getattr(self.parser, "formatfile", None)
        if container is None:
            raise ValueError("lazy hyphen data requires parser.formatfile")
        data = container.readJSON(entry)
        del self._lazy_entries[language]
        self._loadLanguageData(language, data)

    def load(self, data):
        """
        Load container metadata and defer per-language payloads until used.
        """
        self._reset()
        for key, value in data.get("entries", {}).items():
            language = int(key)
            if 0 <= language < self.LANGUAGES:
                self._lazy_entries[language] = value
        language = data.get("language", 0)
        if not isinstance(language, int) or language < 0 or language >= self.LANGUAGES:
            language = 0
        self.language = language
        self.words = self.dicts[language]
        self.pattern_trie = self.pattern_tries[language]
        self.cache = self.caches[language]

    def setLanguage(self, language):
        """
        Set the language
        """
        if self.language != language:
            self.language = language
            self.words = self.dicts[self.language]
            self.pattern_trie = self.pattern_tries[self.language]
            self.cache = self.caches[self.language]
        self._ensureLanguageLoaded(language)

    def addWords(self, words):
        """
        Add words to the hyphenator
        """
        self._ensureLanguageLoaded(self.language)
        for word, positions in words.items():
            if word in self.words:
                self.words[word] += positions
            else:
                self.words[word] = positions
        self.cache.clear()

    def hyphenate(self, word):
        """
        Hyphenate a word
        """
        self._ensureLanguageLoaded(self.language)
        # Explicit exceptions take precedence and are looked up directly.
        # We cache only pattern-derived results.
        exceptions = self.words.get(word, None)
        if exceptions is not None:
            return exceptions

        cached = self.cache.get(word, None)
        if cached is not None:
            return cached
        # TeX pattern matching is done against ".word.".
        text = "." + word + "."
        boundaries = [0] * (len(text) + 1)
        root = self.pattern_trie

        for start in range(len(text)):
            node = root
            pos = start
            while pos < len(text):
                node = node.children.get(text[pos], None)
                if node is None:
                    break
                if node.weights is not None:
                    for i, w in enumerate(node.weights):
                        b = start + i
                        if w > boundaries[b]:
                            boundaries[b] = w
                pos += 1

        points = []
        # In ".word.", word boundary k corresponds to boundary index k+1.
        for k in range(1, len(word)):
            if boundaries[k + 1] % 2 == 1:
                points.append(k)
        self.cache[word] = points
        return points


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

        parser.hyphenator.addPatterns(patterns)


def init(parser):
    parser.hyphenator = Hyphenator(parser)


mod = Module("hyphen",
    init=init,
    commands={
        "hyphenation": Hyphenation(),
        "patterns": Patterns(),
    },
)
