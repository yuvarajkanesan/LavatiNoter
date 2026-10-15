"""Pure-Python tests (no window needed):  python -m unittest discover tests"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lavatinoter import search, util  # noqa: E402


class SearchTests(unittest.TestCase):
    def test_whole_word_and_case(self):
        o = search.Options(text="log_dir", whole_word=True, match_case=True)
        rx = search.compile_pattern(o)
        self.assertEqual(len(search.hits_in_text(rx, "log_dir LOG_DIR log_dir2 log_dir")), 2)

    def test_regex_replace_groups(self):
        o = search.Options(text=r"(\w+)=(\w+)", mode=search.REGEX, replacement=r"\2=\1")
        self.assertEqual(search.replace_all(o, "a=b c=d"), ("b=a d=c", 2))

    def test_bad_regex(self):
        with self.assertRaises(search.SearchError):
            search.compile_pattern(search.Options(text="(", mode=search.REGEX))

    def test_find_backward_wraps(self):
        rx = search.compile_pattern(search.Options(text="x"))
        self.assertEqual(search.find_next(rx, "x..x", 0, backward=True, wrap=True).start(), 3)


class FileTests(unittest.TestCase):
    def test_roundtrip_encodings_and_eol(self):
        d = tempfile.mkdtemp()
        for enc in ("UTF-8", "UTF-8 with BOM", "UTF-16 LE BOM", "UTF-16 BE BOM", "ANSI (Windows-1252)"):
            for eol in ("\r\n", "\n"):
                p = os.path.join(d, "t.txt")
                util.write_text_file(p, "café\nline2\n", enc, eol)
                text, got_enc, got_eol, _ = util.read_text_file(p)
                self.assertEqual((text, got_enc, got_eol), ("café\nline2\n", enc, eol))

    def test_strict_write_refuses_unencodable(self):
        p = os.path.join(tempfile.mkdtemp(), "t.txt")
        with self.assertRaises(UnicodeEncodeError):
            util.write_text_file(p, "中", "ANSI (Windows-1252)", "\n", "strict")
        self.assertFalse(os.path.exists(p))

    def test_image_refs(self):
        refs = util.find_image_refs("see ![a](images/x%20y.png) and <img src='b.jpg'>")
        self.assertEqual([r[2] for r in refs], ["images/x%20y.png", "b.jpg"])


if __name__ == "__main__":
    unittest.main()
