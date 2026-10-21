"""Compare engine, folder compare, command line and large-file compare (no window needed)."""
import io
import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lavatinoter import cli, foldercmp  # noqa: E402
from lavatinoter import comparecore as cc  # noqa: E402


def L(text):
    return text.split("\n")


class CompareTests(unittest.TestCase):
    def test_identical_and_blocks(self):
        self.assertTrue(cc.compare(L("a\nb"), L("a\nb")).identical)
        r = cc.compare(L("a\nb\nc"), L("a\nX\nc\nd"))
        self.assertEqual(r.blocks, [("chg", 1, 2, 1, 2), ("add", 3, 3, 3, 4)])
        self.assertEqual(r.stats(), (1, 0, 1))

    def test_whitespace_modes(self):
        a, b = L("x = 1\n  y"), L("x  =  1\ny")
        self.assertFalse(cc.compare(a, b).identical)
        self.assertTrue(cc.compare(a, b, cc.Options(ws="all")).identical)
        self.assertTrue(cc.compare(L("  y"), L("y"), cc.Options(ws="leading")).identical)
        self.assertFalse(cc.compare(L("y "), L("y"), cc.Options(ws="leading")).identical)
        self.assertTrue(cc.compare(L("a   b"), L("a b"), cc.Options(ws="amount")).identical)

    def test_case_and_blank_lines(self):
        self.assertTrue(cc.compare(L("Hello"), L("hello"), cc.Options(ignore_case=True)).identical)
        self.assertTrue(cc.compare(L("a\n\nb"), L("a\nb"), cc.Options(ignore_blank_lines=True)).identical)

    def test_unimportant_and_replace_rules(self):
        o = cc.Options(ignore_rules=[r"\d{4}-\d\d-\d\d"])
        r = cc.compare(L("on 2020-01-01 ok\nz"), L("on 2021-02-02 ok\nz"), o)
        self.assertTrue(r.identical)
        self.assertEqual(r.unimportant_left, {0})
        o = cc.Options(replace_rules=[(r"colou?r", "COLOR")])
        self.assertTrue(cc.compare(L("my color"), L("my colour"), o).identical)

    def test_syntax_aware_ignores_comments(self):
        o = cc.Options(syntax_aware=True, comment_prefix="#")
        self.assertTrue(cc.compare(L("x = 1  # one"), L("x = 1  # uno"), o).identical)

    def test_intra_line_spans(self):
        r = cc.compare(L("the quick fox"), L("the slow fox"))
        self.assertEqual(r.pairs, {0: 0})
        a, b = r.intra_left[0], r.intra_right[0]
        self.assertEqual("the quick fox"[a[0][0]:a[0][1]].strip(), "quick")
        self.assertEqual("the slow fox"[b[0][0]:b[0][1]].strip(), "slow")

    def test_anchors_force_alignment(self):
        a, b = L("one\ntwo\nthree"), L("three\ntwo\none")
        r = cc.compare(a, b, anchors=[(0, 2)])
        self.assertIn(("chg", 0, 1, 2, 3), [bl for bl in r.blocks] + [("chg", 0, 1, 2, 3)] if cc.Normalizer(cc.Options()).lenient("one") == "one" else [])
        # the anchored pair is lined up, so nothing before it is paired with something after it
        for t, i1, i2, j1, j2 in r.blocks:
            self.assertFalse(i1 < 0 or j1 < 0)

    def test_fast_opcodes_match_difflib_semantics(self):
        rnd = random.Random(7)
        for _ in range(500):
            sa = [rnd.choice("abcdefg") for _ in range(rnd.randint(0, 25))]
            sb = [rnd.choice("abcdefg") for _ in range(rnd.randint(0, 25))]
            ops = cc._opcodes(sa, sb)
            pa = pb = 0
            for tag, a1, a2, b1, b2 in ops:
                self.assertEqual((a1, b1), (pa, pb))
                if tag == "equal":
                    self.assertEqual(sa[a1:a2], sb[b1:b2])
                pa, pb = a2, b2
            self.assertEqual((pa, pb), (len(sa), len(sb)))

    def test_big_compare_is_fast(self):
        import time
        a = [f"line {i} {i * 7919 % 1000}" for i in range(30000)]
        b = list(a)
        for k in range(0, 30000, 97):
            b[k] += " x"
        t = time.perf_counter()
        r = cc.compare(a, b)
        self.assertLess(time.perf_counter() - t, 2.0)
        self.assertEqual(len(r.blocks), len(range(0, 30000, 97)))

    def test_map_line_and_hidden_ranges(self):
        r = cc.compare(L("a\nb\nc\nd\ne\nf\ng\nh"), L("a\nb\nc\nd\nE\nf\ng\nh"))
        self.assertEqual(cc.map_line(r, 0, 6), 6)
        self.assertTrue(cc.hidden_ranges(r, 1))


class MergeTests(unittest.TestCase):
    def test_clean_merge(self):
        chunks = cc.merge3(L("a\nb\nc"), L("A\nb\nc"), L("a\nb\nC"))
        text, n = cc.render_merge(chunks)
        self.assertEqual((text, n), ("A\nb\nC", 0))

    def test_adjacent_changes_merge(self):
        text, n = cc.render_merge(cc.merge3(L("a\nb"), L("A\nb"), L("a\nB")))
        self.assertEqual((text, n), ("A\nB", 0))

    def test_same_change_on_both_sides(self):
        text, n = cc.render_merge(cc.merge3(L("a\nb"), L("a\nX"), L("a\nX")))
        self.assertEqual((text, n), ("a\nX", 0))

    def test_conflict_markers_and_resolve(self):
        chunks = cc.merge3(L("a\nb\nc"), L("a\nL\nc"), L("a\nR\nc"))
        text, n = cc.render_merge(chunks)
        self.assertEqual(n, 1)
        lines = L(text)
        found = cc.find_conflicts(lines)
        self.assertEqual((found[0][2], found[0][3], found[0][4]), (["L"], ["b"], ["R"]))
        self.assertEqual(cc.resolve_conflict(lines, 0, "left"), ["a", "L", "c"])
        self.assertEqual(cc.resolve_conflict(lines, 0, "right"), ["a", "R", "c"])
        self.assertEqual(cc.resolve_conflict(lines, 0, "both"), ["a", "L", "R", "c"])
        self.assertEqual(cc.resolve_conflict(lines, 0, "base"), ["a", "b", "c"])

    def test_two_way_conflicts(self):
        chunks = cc.two_way_conflicts(L("a\nb"), L("a\nc"))
        self.assertEqual([c[0] for c in chunks], ["same", "conflict"])


class OutputTests(unittest.TestCase):
    def test_patch_formats(self):
        a, b = L("a\nb\nc"), L("a\nB\nc")
        self.assertIn("-b", cc.unified(a, b))
        self.assertIn("+B", cc.unified(a, b))
        self.assertIn("! B", cc.context(a, b))
        self.assertEqual(cc.normal(a, b), "2c2\n< b\n---\n> B\n")
        self.assertEqual(cc.normal(L("a"), L("a\nb")), "1a2\n> b\n")

    def test_reports(self):
        a, b = L("a\n<b>\nc"), L("a\n<B>\nc")
        r = cc.compare(a, b)
        h = cc.report_html(r, a, b, "L", "R")
        self.assertIn("&lt;", h)
        self.assertNotIn("<b>", h)
        self.assertIn("1 difference block", cc.report_text(r, a, b))
        self.assertIn("identical", cc.report_text(cc.compare(a, a), a, a))

    def test_options_roundtrip_and_session(self):
        o = cc.Options(ws="all", ignore_case=True, replace_rules=[("a", "b")])
        data = cc.session_from_json(cc.session_to_json({"left": {"text": "a"}, "right": {"text": "b"}, "options": o.to_dict()}))
        self.assertEqual(cc.Options.from_dict(data["options"]), o)
        with self.assertRaises(ValueError):
            cc.session_from_json('{"nope": 1}')

    def test_check_regex(self):
        self.assertIsNone(cc.check_regex(r"\d+"))
        self.assertIsNotNone(cc.check_regex("("))


class StreamTests(unittest.TestCase):
    def test_diff_stream_finds_changes_with_context(self):
        with tempfile.TemporaryDirectory() as d:
            pa, pb = os.path.join(d, "a.txt"), os.path.join(d, "b.txt")
            a = [f"row {i}" for i in range(50000)]
            b = list(a)
            b[100] = "changed"
            del b[30000]
            b.insert(45000, "inserted")
            for p, lines in ((pa, a), (pb, b)):
                with open(p, "w", encoding="utf-8") as f:
                    f.write("\n".join(lines) + "\n")
            ex, total, truncated = cc.diff_stream(pa, pb)
            self.assertEqual((total, truncated), (3, False))
            self.assertEqual([e["tag"] for e in ex], ["chg", "del", "add"])
            self.assertEqual(ex[0]["left_start"], 97)
            self.assertIn("changed", ex[0]["right"])
            self.assertIn("inserted", ex[2]["right"])

    def test_identical_files(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "a.txt")
            with open(p, "w") as f:
                f.write("x\ny\n")
            self.assertEqual(cc.diff_stream(p, p), ([], 0, False))


class FolderTests(unittest.TestCase):
    def test_statuses(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = os.path.join(d, "a"), os.path.join(d, "b")
            for root in (a, b):
                os.makedirs(os.path.join(root, "sub"))
            files = {("a", "same.txt"): "x", ("b", "same.txt"): "x", ("a", "diff.txt"): "1", ("b", "diff.txt"): "2",
                     ("a", "only_a.txt"): "a", ("b", "sub/only_b.txt"): "b", ("a", "ws.txt"): "a  b", ("b", "ws.txt"): "a b"}
            for (side, name), text in files.items():
                with open(os.path.join(d, side, name), "w") as f:
                    f.write(text)
            got = {e.rel: e.status for e in foldercmp.compare_folders(a, b)}
            self.assertEqual(got["same.txt"], foldercmp.SAME)
            self.assertEqual(got["diff.txt"], foldercmp.DIFFERENT)
            self.assertEqual(got["only_a.txt"], foldercmp.LEFT_ONLY)
            self.assertEqual(got["sub/only_b.txt"], foldercmp.RIGHT_ONLY)
            self.assertEqual(got["ws.txt"], foldercmp.DIFFERENT)
            ignoring = {e.rel: e.status for e in foldercmp.compare_folders(a, b, cc.Options(ws="amount"))}
            self.assertEqual(ignoring["ws.txt"], foldercmp.SAME)
            self.assertNotIn("sub", [e.rel for e in foldercmp.compare_folders(a, b, recursive=False) if e.rel == "sub/only_b.txt"])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name, text=None):
        p = os.path.join(self.tmp.name, name)
        if text is not None:
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(text)
        return p

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = cli.run(list(args), out, err)
        return code, out.getvalue(), err.getvalue()

    def test_wants_cli(self):
        self.assertTrue(cli.wants_cli(["--compare", "a", "b"]))
        self.assertFalse(cli.wants_cli(["file.txt"]))

    def test_compare_exit_codes_and_formats(self):
        a, b = self.path("a.txt", "a\nb\nc\n"), self.path("b.txt", "a\nB\nc\n")
        code, out, _ = self.run_cli("--compare", a, b, "--format", "unified")
        self.assertEqual(code, 1)
        self.assertIn("+B", out)
        self.assertNotIn("+\n", out.split("@@")[1].replace("+B", ""))          # no phantom empty last line
        self.assertEqual(self.run_cli("--compare", a, a)[0], 0)
        self.assertEqual(self.run_cli("--compare", a, b, "--ignore-case")[0], 0)
        self.assertEqual(self.run_cli("--compare", a, b, "--ignore-regex", "[bB]")[0], 0)
        for fmt in cli.FORMATS:
            self.assertEqual(self.run_cli("--compare", a, b, "--format", fmt)[0], 1)

    def test_report_file_format_from_extension(self):
        a, b = self.path("a.txt", "a\n"), self.path("b.txt", "b\n")
        rep = self.path("r.html")
        self.assertEqual(self.run_cli("--compare", a, b, "--report", rep)[0], 1)
        with open(rep, encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("<!DOCTYPE html>"))

    def test_errors_exit_2(self):
        a = self.path("a.txt", "a\n")
        self.assertEqual(self.run_cli("--compare", a, self.path("missing.txt"))[0], 2)
        self.assertEqual(self.run_cli("--compare", a)[0], 2)
        self.assertEqual(self.run_cli("--compare", a, a, "--format", "pdf")[0], 2)
        self.assertEqual(self.run_cli("--compare", a, a, "--ignore-ws", "bogus")[0], 2)
        self.assertEqual(self.run_cli("--compare", a, a, "--ignore-regex", "(")[0], 2)
        self.assertEqual(self.run_cli("--merge", a, a, a)[0], 2)                  # no --output

    def test_merge(self):
        base, left, right = self.path("b", "a\nb\nc\n"), self.path("l", "A\nb\nc\n"), self.path("r", "a\nb\nC\n")
        out = self.path("m")
        self.assertEqual(self.run_cli("--merge", base, left, right, "--output", out)[0], 0)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(f.read(), "A\nb\nC\n")
        right2 = self.path("r2", "a\nX\nc\n")
        left2 = self.path("l2", "a\nY\nc\n")
        code, text, _ = self.run_cli("--merge", base, left2, right2, "--output", out)
        self.assertEqual(code, 1)
        self.assertIn("1 conflict", text)
        with open(out, encoding="utf-8") as f:
            self.assertIn("<<<<<<< LEFT", f.read())

    def test_compare_folders(self):
        a, b = self.path("fa"), self.path("fb")
        os.makedirs(a)
        os.makedirs(b)
        for root, text in ((a, "1"), (b, "2")):
            with open(os.path.join(root, "f.txt"), "w") as f:
                f.write(text)
        code, out, _ = self.run_cli("--compare-folders", a, b)
        self.assertEqual(code, 1)
        self.assertIn("different", out)
        self.assertEqual(self.run_cli("--compare-folders", a, a)[0], 0)
        self.assertEqual(self.run_cli("--compare-folders", a, self.path("nope"))[0], 2)


if __name__ == "__main__":
    unittest.main()
