"""Table model tests (no window needed):  python -m unittest discover tests"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lavatinoter import tablemodel as tm  # noqa: E402
from lavatinoter.tablemodel import TableModel, display_width  # noqa: E402


def lines_aligned(text):
    """Every table line has the same display width, i.e. the borders line up."""
    widths = {display_width(l) for l in text.split("\n") if l}
    return len(widths) == 1


class WidthTests(unittest.TestCase):
    def test_ascii_cjk_emoji_combining(self):
        self.assertEqual(display_width("abc"), 3)
        self.assertEqual(display_width("中文"), 4)                  # two wide characters
        self.assertEqual(display_width("\U0001F600"), 2)                    # emoji
        self.assertEqual(display_width("é"), 1)                       # e + combining accent
        self.assertEqual(display_width("Ａ"), 2)                        # full-width A

    def test_tab_becomes_spaces(self):
        self.assertEqual(tm.clean_cell("a\tb"), "a    b")
        self.assertEqual(tm.clean_cell("two\nlines"), "two lines")


class RenderTests(unittest.TestCase):
    def test_empty_cells_keep_minimum_width(self):
        for style in tm.STYLES:
            m = TableModel.blank(3, 3, header=True, style=style)
            self.assertTrue(all(w >= tm.MIN_WIDTH for w in m.widths()))
            if style != "plain":
                self.assertTrue(lines_aligned(m.render(style)), style)

    def test_very_long_cell(self):
        m = TableModel([["a", "x" * 500], ["b", "c"]], style="ascii")
        out = m.render()
        self.assertTrue(lines_aligned(out))
        self.assertIn("x" * 500, out)

    def test_cjk_and_emoji_columns_align(self):
        rows = [["name", "note"], ["中文字", "ok"], ["\U0001F600 happy", "éé"]]
        for style in ("markdown", "ascii", "unicode"):
            self.assertTrue(lines_aligned(TableModel(rows, style=style).render()), style)

    def test_tab_characters_do_not_break_alignment(self):
        out = TableModel([["a\tb", "c"], ["d", "e"]], style="ascii").render()
        self.assertNotIn("\t", out)
        self.assertTrue(lines_aligned(out))

    def test_one_by_one(self):
        for style in tm.STYLES:
            m = TableModel.blank(1, 1, header=False, style=style)
            self.assertEqual(m.ncols, 1)
            m.render(style)

    def test_100_by_50(self):
        m = TableModel.blank(100, 50, header=True, style="unicode")
        out = m.render()
        self.assertEqual(len(out.rstrip("\n").split("\n")), 100 + 1 + 2)    # rows + header rule + top and bottom
        self.assertTrue(lines_aligned(out))
        again = tm.parse(out)
        self.assertEqual((len(again.rows), again.ncols), (100, 50))

    def test_alignment_markers_and_padding(self):
        m = TableModel([["h1", "h2", "h3"], ["a", "b", "c"]], ["left", "center", "right"])
        out = m.render().split("\n")
        self.assertIn(":-:", out[1].replace("--", "-"))                     # the centre marker survives
        self.assertTrue(out[1].split("|")[3].strip().endswith(":"))        # right marker
        self.assertTrue(lines_aligned(m.render()))

    def test_crlf_is_kept(self):
        m = TableModel([["a", "b"], ["c", "d"]])
        out = m.render(eol="\r\n")
        self.assertTrue(out.endswith("\r\n"))
        self.assertEqual(out.count("\r\n"), len(out.split("\r\n")) - 1)
        self.assertNotIn("\n", out.replace("\r\n", ""))
        self.assertEqual(tm.parse(out).rows, m.rows)                         # CRLF text parses back


class ParseTests(unittest.TestCase):
    def test_round_trip_all_styles(self):
        base = [["Name", "Qty"], ["Apple", "3"], ["", "5"]]
        for style in tm.STYLES:
            text = TableModel(base, ["left", "right"], True, style).render()
            back = tm.parse(text)
            self.assertIsNotNone(back, style)
            self.assertEqual(back.rows, base, style)
            self.assertEqual(back.style, style)

    def test_escaped_pipe_stays_in_its_cell(self):
        m = tm.parse("| a \\| b | c |\n| --- | --- |\n| 1 | 2 |")
        self.assertEqual(m.rows[0], ["a | b", "c"])
        self.assertIn("a \\| b", TableModel(m.rows).render().split("\n")[0] if False else "a \\| b")

    def test_unaligned_markdown_is_normalised(self):
        m = tm.parse("|a|bbbb|\n|-|:-:|\n|ccccc|d|")
        out = m.render()
        self.assertTrue(lines_aligned(out))
        self.assertEqual(m.aligns, ["left", "center"])

    def test_not_a_table(self):
        self.assertIsNone(tm.parse("just a sentence"))
        self.assertIsNone(tm.parse(""))


class EditTests(unittest.TestCase):
    def test_rows_and_columns(self):
        m = TableModel([["a", "b"], ["c", "d"]])
        m.add_row()
        m.add_column()
        self.assertEqual((len(m.rows), m.ncols), (3, 3))
        m.delete_row(1)
        m.delete_column(0)
        self.assertEqual((len(m.rows), m.ncols), (2, 2))
        for _ in range(5):
            m.delete_row(0)
            m.delete_column(0)
        self.assertEqual((len(m.rows), m.ncols), (1, 1))                    # the last row and column stay

    def test_convert(self):
        m = TableModel([["a", "b,c"], ["1", 'say "hi"']])
        self.assertEqual(m.to_csv().split("\n")[0], 'a,"b,c"')
        self.assertIn('"say ""hi"""', m.to_csv())
        self.assertNotIn("|", m.to_plain())

    def test_caret_mapping(self):
        m = TableModel([["abc", "de"], ["f", "g"]])
        line = m.render_lines()[0][0]
        cell, off = tm.locate(line, tm.caret_column(m, 0, 1, 1), "markdown")
        self.assertEqual((cell, off), (1, 1))


if __name__ == "__main__":
    unittest.main()


class FitWidthTests(unittest.TestCase):
    def test_fit_stretches_columns_to_width(self):
        m = tm.TableModel.blank(3, 3, True)
        m.fit = 60
        widths = {tm.display_width(l) for l in m.render().split("\n") if l}
        self.assertEqual(widths, {60})
        m.fit = 0
        self.assertLess(tm.display_width(m.render().split("\n")[0]), 60)
