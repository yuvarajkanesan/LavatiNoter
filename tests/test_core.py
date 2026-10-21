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


class FormatterTests(unittest.TestCase):
    def test_json_roundtrip_and_error_position(self):
        from lavatinoter import formatter as f
        self.assertEqual(f.format_json('{"a":[1,2]}', 2), '{\n  "a": [\n    1,\n    2\n  ]\n}\n')
        self.assertEqual(f.minify_json('{\n "a": 1\n}'), '{"a":1}\n')
        with self.assertRaises(f.FormatError) as cm:
            f.format_json('{"a": 1,}')
        self.assertEqual(cm.exception.line, 1)

    def test_brace_reindent_keeps_tokens(self):
        from lavatinoter import formatter as f
        src = "if (a) {\nb();\n}\n"
        out = f.reindent_braces(src)
        self.assertEqual(out.split(), src.split())
        self.assertEqual(out, "if (a) {\n    b();\n}\n")

    def test_bracket_check_ignores_strings_and_comments(self):
        from lavatinoter import formatter as f
        self.assertIsNone(f.check_brackets('x = "(" // )\n{ [ ] }'))
        self.assertEqual(f.check_brackets("a(b]")[0], "Unmatched ']'")

    def test_css_and_sql(self):
        from lavatinoter import formatter as f
        self.assertEqual(f.format_css("a{color:red}"), "a {\n    color: red;\n}\n")
        self.assertIn("\nFROM t", f.format_sql("select a from t"))


class FileTypeTests(unittest.TestCase):
    def test_extension_rules(self):
        from lavatinoter import filetypes as ft
        self.assertEqual(ft.with_extension("notes", "Text files (*.txt)"), "notes.txt")
        self.assertEqual(ft.with_extension("app", "Python (*.py *.pyw)"), "app.py")
        self.assertEqual(ft.with_extension("app.js", "Text files (*.txt)"), "app.js")
        self.assertEqual(ft.filter_list()[0], "Text files (*.txt)")


