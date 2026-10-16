"""Spell checking and auto-correct (English, via pyspellchecker's bundled dictionary; loaded on first use)."""
import os
import re

from . import util

# a plain, lower-case or Capitalised word that is not part of camelCase / snake_case / an identifier with digits
WORD = re.compile(r"(?<![\w'])[A-Za-z][a-z']{2,}(?![\w'])")


class Speller:
    def __init__(self):
        self._sc = None
        self._failed = False
        self.ignored = set()
        self.custom = set()
        self.path = os.path.join(util.data_dir(), "dictionary.txt")
        try:
            with open(self.path, encoding="utf-8") as f:
                self.custom = {w.strip().lower() for w in f if w.strip()}
        except OSError:
            pass

    def _checker(self):
        if self._sc is None and not self._failed:
            try:
                from spellchecker import SpellChecker
                self._sc = SpellChecker()
            except Exception:  # noqa: BLE001 - a missing dictionary only turns spell check off
                self._failed = True
        return self._sc

    @property
    def available(self):
        return self._checker() is not None

    def is_wrong(self, word):
        sc = self._checker()
        w = word.lower().strip("'")
        if sc is None or len(w) < 3 or w in self.ignored or w in self.custom:
            return False
        return w not in sc

    def suggestions(self, word, limit=6):
        sc = self._checker()
        if sc is None:
            return []
        cands = sc.candidates(word.lower()) or set()
        best = sc.correction(word.lower())
        ordered = sorted(cands, key=lambda c: (c != best, -sc.word_usage_frequency(c) if hasattr(sc, "word_usage_frequency") else 0, c))
        return [self._match_case(word, c) for c in ordered[:limit]]

    def correction(self, word):
        """A confident automatic fix for a mistyped word, or None (unknown names and far-off guesses are left alone)."""
        if not self.is_wrong(word) or word.isupper() or len(word) < 3:
            return None
        sc = self._checker()
        best = sc.correction(word.lower())
        if not best or best == word.lower() or " " in best:
            return None
        if len(sc.edit_distance_1(word.lower()) & {best}) == 0:     # only single-edit typos: teh, recieve, wrold ...
            return None
        return self._match_case(word, best)

    @staticmethod
    def _match_case(word, fixed):
        return fixed.capitalize() if word[:1].isupper() else fixed

    def words_with_prefix(self, prefix, limit=8):
        """Common English words that start with `prefix`, most frequent first."""
        sc = self._checker()
        if sc is None:
            return []
        if not hasattr(self, "_by_freq"):
            self._by_freq = sorted(sc.word_frequency.dictionary.items(), key=lambda kv: -kv[1])[:30000]
        out = []
        for w, _n in self._by_freq:
            if w.startswith(prefix) and w != prefix and len(w) > len(prefix) + 1 and w.isalpha():
                out.append(w)
                if len(out) >= limit:
                    break
        return out

    def add_word(self, word):
        w = word.lower()
        self.custom.add(w)
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(w + "\n")
        except OSError:
            pass

    def ignore(self, word):
        self.ignored.add(word.lower())


speller = Speller()
