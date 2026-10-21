"""The comparison engine behind the Compare window (no Qt in here): comparison options, line / word / character differences,
unimportant differences, alignment overrides, three-way merge, reports and patches, comparison sessions, and a streaming
comparison for very large files."""
import difflib
import html
import json
import re
from dataclasses import asdict, dataclass, field

WS_MODES = {
    "none": "Compare whitespace",
    "leading": "Ignore leading whitespace",
    "trailing": "Ignore trailing whitespace",
    "leading_trailing": "Ignore leading and trailing",
    "amount": "Ignore differences in amount",
    "all": "Ignore all whitespace",
}
GRANULARITY = {"words": "Words", "chars": "Characters", "lines": "Whole lines"}
MAX_EXACT_LINES = 60000          # beyond this the exact (quadratic worst case) matcher is too slow: see diff_stream
MAX_INTRA_CHARS = 3000           # lines longer than this get no word / character detail


@dataclass
class Options:
    ws: str = "none"
    ignore_case: bool = False
    ignore_eol: bool = True
    ignore_blank_lines: bool = False
    ignore_rules: list = field(default_factory=list)        # regexes: text matching them is "unimportant"
    replace_rules: list = field(default_factory=list)       # [(regex, replacement)] applied before comparing
    granularity: str = "words"
    syntax_aware: bool = False
    comment_prefix: str = ""                                 # set from the language when syntax_aware is on

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        o = cls()
        for k, v in (d or {}).items():
            if hasattr(o, k):
                setattr(o, k, v)
        o.replace_rules = [tuple(r) for r in o.replace_rules]
        return o


def check_regex(rx):
    """None when `rx` is a valid regular expression, else the error text."""
    try:
        re.compile(rx)
        return None
    except re.error as e:
        return str(e)


def _compiled(rules):
    out = []
    for r in rules:
        try:
            out.append(re.compile(r))
        except re.error:
            pass
    return out


def _compiled_replace(rules):
    out = []
    for pat, rep in rules:
        try:
            out.append((re.compile(pat), rep))
        except re.error:
            pass
    return out


def _strip_trailing_comment(line, prefix):
    """The line without a trailing comment (a comment marker inside quotes does not count)."""
    if not prefix:
        return line
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif line.startswith(prefix, i):
            return line[:i]
        i += 1
    return line


class Normalizer:
    """Turns lines into comparison keys following the options. `strict` applies the whitespace / case / replace rules; `lenient`
    also removes the 'unimportant' text, so a line pair that is equal only leniently is an unimportant difference."""

    def __init__(self, o):
        self.o = o
        self.ign = _compiled(o.ignore_rules)
        self.rep = _compiled_replace(o.replace_rules)

    def _ws(self, s):
        m = self.o.ws
        if m == "leading":
            return s.lstrip()
        if m == "trailing":
            return s.rstrip()
        if m == "leading_trailing":
            return s.strip()
        if m == "all":
            return re.sub(r"\s+", "", s)
        if m == "amount":
            return re.sub(r"\s+", " ", s)
        return s

    def strict(self, line):
        s = line
        if self.o.syntax_aware:
            s = _strip_trailing_comment(s, self.o.comment_prefix)
        for rx, rep in self.rep:
            s = rx.sub(rep, s)
        s = self._ws(s)
        if self.o.syntax_aware and self.o.ws == "none":
            s = s.rstrip()
        return s.lower() if self.o.ignore_case else s

    def lenient(self, line):
        s = self.strict(line)
        for rx in self.ign:
            s = rx.sub("", s)
        return re.sub(r"\s+", " ", s).strip() if self.ign else s

    def ignorable(self, line):
        """A line that takes no part in the comparison (blank lines on request, blank and comment-only lines in syntax mode)."""
        st = line.strip()
        if self.o.ignore_blank_lines and not st:
            return True
        if self.o.syntax_aware:
            return not st or bool(self.o.comment_prefix and st.startswith(self.o.comment_prefix))
        return False


@dataclass
class Result:
    blocks: list                    # [(tag, i1, i2, j1, j2)] tag: 'add' (only right), 'del' (only left), 'chg'
    unimportant_left: set
    unimportant_right: set
    intra_left: dict                # {line: [(start, end)]}
    intra_right: dict
    pairs: dict                     # {left line: right line} for the lines paired inside changed blocks
    n_left: int
    n_right: int

    @property
    def identical(self):
        return not self.blocks

    def stats(self):
        added = sum(j2 - j1 for t, i1, i2, j1, j2 in self.blocks if t == "add")
        removed = sum(i2 - i1 for t, i1, i2, j1, j2 in self.blocks if t == "del")
        changed = sum(max(i2 - i1, j2 - j1) for t, i1, i2, j1, j2 in self.blocks if t == "chg")
        return added, removed, changed


def _diff_keys(ka, kb, keep_a, keep_b, a_len, b_len):
    """Opcodes over the lines that take part (keep_*), mapped back to full line numbers."""
    sa, sb = [ka[i] for i in keep_a], [kb[j] for j in keep_b]
    out = []

    def pos(keep, x, n):
        return keep[x - 1] + 1 if x > 0 else 0

    for tag, x1, x2, y1, y2 in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        i1, i2 = (keep_a[x1], keep_a[x2 - 1] + 1) if x1 < x2 else (pos(keep_a, x1, a_len),) * 2
        j1, j2 = (keep_b[y1], keep_b[y2 - 1] + 1) if y1 < y2 else (pos(keep_b, y1, b_len),) * 2
        out.append(({"insert": "add", "delete": "del", "replace": "chg"}[tag], i1, i2, j1, j2))
    return out


def tokens(line, granularity):
    if granularity == "chars":
        return list(line)
    return re.findall(r"\s+|\w+|[^\w\s]", line)


def intra_spans(a, b, o):
    """([(s, e)] differing parts of a, [(s, e)] differing parts of b)."""
    if o.granularity == "lines" or len(a) > MAX_INTRA_CHARS or len(b) > MAX_INTRA_CHARS:
        return ([(0, len(a))] if a else []), ([(0, len(b))] if b else [])
    ta, tb = tokens(a, o.granularity), tokens(b, o.granularity)

    def key(t):
        if t.isspace() and o.ws != "none":
            return " "
        return t.lower() if o.ignore_case else t
    ka, kb = [key(t) for t in ta], [key(t) for t in tb]
    pa, pb = [0], [0]
    for t in ta:
        pa.append(pa[-1] + len(t))
    for t in tb:
        pb.append(pb[-1] + len(t))
    sa, sb = [], []
    for tag, x1, x2, y1, y2 in difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if x2 > x1:
            sa.append((pa[x1], pa[x2]))
        if y2 > y1:
            sb.append((pb[y1], pb[y2]))
    return sa, sb


def _pair_lines(a_lines, b_lines, i1, i2, j1, j2):
    """Which left line of a changed block goes with which right line: by position when the block is square, else by similarity."""
    if i2 - i1 == j2 - j1:
        return [(i1 + k, j1 + k) for k in range(i2 - i1)]
    pairs, p = [], j1
    for i in range(i1, i2):
        best, best_r = None, 0.55
        for j in range(p, min(j2, p + 25)):
            r = difflib.SequenceMatcher(None, a_lines[i], b_lines[j]).quick_ratio()
            if r > best_r:
                best, best_r = j, r
        if best is not None:
            pairs.append((i, best))
            p = best + 1
    return pairs


def compare(a_lines, b_lines, o=None, anchors=()):
    """Compares two lists of lines. `anchors` = [(left line, right line)] pairs the user forced to line up."""
    o = o or Options()
    if len(a_lines) > MAX_EXACT_LINES or len(b_lines) > MAX_EXACT_LINES:
        raise ValueError(f"Too many lines for the exact comparison (limit {MAX_EXACT_LINES:,}); use the large file mode.")
    nz = Normalizer(o)
    len_a, len_b = len(a_lines), len(b_lines)
    ka, kb = [nz.lenient(l) for l in a_lines], [nz.lenient(l) for l in b_lines]
    ig_a, ig_b = [nz.ignorable(l) for l in a_lines], [nz.ignorable(l) for l in b_lines]
    blocks = []
    cut = [(0, 0)] + sorted((i, j) for i, j in anchors if 0 <= i < len_a and 0 <= j < len_b) + [(len_a, len_b)]
    prev_i = prev_j = 0
    for k, (ai, aj) in enumerate(cut[1:], 1):
        is_anchor = k < len(cut) - 1
        seg_a, seg_b = range(prev_i, ai), range(prev_j, aj)
        keep_a = [i for i in seg_a if not ig_a[i]]
        keep_b = [j for j in seg_b if not ig_b[j]]
        for tag, i1, i2, j1, j2 in _diff_keys(ka, kb, keep_a, keep_b, ai, aj):
            blocks.append((tag, max(i1, prev_i), min(max(i2, i1), ai), max(j1, prev_j), min(max(j2, j1), aj)))
        if is_anchor:
            if ka[ai] != kb[aj]:
                blocks.append(("chg", ai, ai + 1, aj, aj + 1))
            prev_i, prev_j = ai + 1, aj + 1
    # an 'add' / 'del' pair of neighbouring blocks that touch (separated only by ignorable lines) reads better as one change
    merged = []
    for blk in blocks:
        if merged:
            t0, a1, a2, b1, b2 = merged[-1]
            if blk[0] != t0 and blk[1] <= a2 and blk[3] <= b2 and {t0, blk[0]} == {"add", "del"}:
                merged[-1] = ("chg", min(a1, blk[1]), max(a2, blk[2]), min(b1, blk[3]), max(b2, blk[4]))
                continue
        merged.append(blk)
    blocks = merged
    # unimportant differences: lines that are equal leniently but differ strictly, inside the matching stretches
    in_block_a = set()
    in_block_b = set()
    for t, i1, i2, j1, j2 in blocks:
        in_block_a.update(range(i1, i2))
        in_block_b.update(range(j1, j2))
    ua, ub = set(), set()
    if o.ignore_rules:
        eq_a = [i for i in range(len_a) if i not in in_block_a and not ig_a[i]]
        eq_b = [j for j in range(len_b) if j not in in_block_b and not ig_b[j]]
        for i, j in zip(eq_a, eq_b):
            if nz.strict(a_lines[i]) != nz.strict(b_lines[j]):
                ua.add(i)
                ub.add(j)
    intra_a, intra_b, pairs = {}, {}, {}
    for t, i1, i2, j1, j2 in blocks:
        if t != "chg":
            continue
        for i, j in _pair_lines(a_lines, b_lines, i1, i2, j1, j2):
            sa, sb = intra_spans(a_lines[i], b_lines[j], o)
            pairs[i] = j
            if sa:
                intra_a[i] = sa
            if sb:
                intra_b[j] = sb
    return Result(blocks, ua, ub, intra_a, intra_b, pairs, len_a, len_b)


def map_line(result, side, line):
    """The line on the other side that matches `line` (0-based) of `side` (0 = left): exact inside matching stretches."""
    shift = 0
    for t, i1, i2, j1, j2 in result.blocks:
        s1, s2, o1, o2 = (i1, i2, j1, j2) if side == 0 else (j1, j2, i1, i2)
        if line < s1:
            break
        if line < s2:
            return o1
        shift = o2 - s2
    return max(0, line + shift)


def hidden_ranges(result, context=3):
    """Matching stretches to hide when only differences should show: [(first left, last left, first right, last right)] with
    `context` lines kept around every difference (equal stretches have the same length on both sides)."""
    out = []
    pi = pj = 0
    marks = list(result.blocks) + [("end", result.n_left, result.n_left, result.n_right, result.n_right)]
    for k, (t, i1, i2, j1, j2) in enumerate(marks):
        n = i1 - pi
        if n > 0:
            top = context if k > 0 else 0
            bottom = context if t != "end" else 0
            if n - top - bottom >= 2:
                out.append((pi + top, i1 - bottom - 1, pj + top, j1 - bottom - 1))
        pi, pj = i2, j2
    return out


# ---- three-way merge ---------------------------------------------------------------------------------------------------------------
def merge3(base, left, right):
    """Merges two edited versions of `base`. -> list of chunks: ('same', lines) | ('left', lines) | ('right', lines) |
    ('both', lines) (the same change on both sides) | ('conflict', base lines, left lines, right lines)."""
    changes = []
    for side, other in (("L", left), ("R", right)):
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, other, autojunk=False).get_opcodes():
            if tag != "equal":
                changes.append((i1, i2, side, other[j1:j2]))
    changes.sort(key=lambda c: (c[0], c[1]))
    groups = []
    for ch in changes:
        g0 = groups[-1] if groups else None
        # changes that overlap belong together; changes that merely touch do not (they merge on their own), except two
        # insertions at the very same spot, which are a real conflict
        if g0 and (ch[0] < g0["end"] or (ch[0] == g0["end"] and ch[0] == ch[1] and any(c[0] == c[1] == ch[0] for c in g0["items"]))):
            g = groups[-1]
            g["end"] = max(g["end"], ch[1])
            g["items"].append(ch)
        else:
            groups.append({"start": ch[0], "end": ch[1], "items": [ch]})
    chunks, pos = [], 0
    for g in groups:
        if g["start"] > pos:
            chunks.append(("same", base[pos:g["start"]]))

        def version(side):
            out, p = [], g["start"]
            for c1, c2, s, new in g["items"]:
                if s != side:
                    continue
                out += base[p:c1] + new
                p = c2
            return out + base[p:g["end"]]
        lv, rv, bv = version("L"), version("R"), base[g["start"]:g["end"]]
        if lv == bv:
            chunks.append(("right", rv))
        elif rv == bv:
            chunks.append(("left", lv))
        elif lv == rv:
            chunks.append(("both", lv))
        else:
            chunks.append(("conflict", bv, lv, rv))
        pos = g["end"]
    if pos < len(base):
        chunks.append(("same", base[pos:]))
    return chunks


MARK_L, MARK_B, MARK_M, MARK_R = "<<<<<<< LEFT", "||||||| BASE", "=======", ">>>>>>> RIGHT"


def render_merge(chunks, with_base=True):
    """The merged text, with git-style markers around every conflict. -> (text, number of conflicts)."""
    lines, conflicts = [], 0
    for ch in chunks:
        if ch[0] == "conflict":
            conflicts += 1
            lines.append(MARK_L)
            lines += ch[2]
            if with_base:
                lines.append(MARK_B)
                lines += ch[1]
            lines.append(MARK_M)
            lines += ch[3]
            lines.append(MARK_R)
        else:
            lines += ch[1]
    return "\n".join(lines), conflicts


def two_way_conflicts(a_lines, b_lines, o=None):
    """For a plain two-way merge: every difference is a conflict between the left and the right version."""
    res = compare(a_lines, b_lines, o)
    chunks, pi = [], 0
    for t, i1, i2, j1, j2 in res.blocks:
        if i1 > pi:
            chunks.append(("same", a_lines[pi:i1]))
        chunks.append(("conflict", [], a_lines[i1:i2], b_lines[j1:j2]))
        pi = i2
    if pi < len(a_lines):
        chunks.append(("same", a_lines[pi:]))
    return chunks


def find_conflicts(lines):
    """[(first line, last line, left lines, base lines or None, right lines)] for the marker groups in `lines` (0-based, inclusive)."""
    out, i, n = [], 0, len(lines)
    while i < n:
        if lines[i].startswith(MARK_L):
            start, left, base, right, state = i, [], None, [], "L"
            i += 1
            while i < n:
                ln = lines[i]
                if ln.startswith(MARK_B) and state == "L":
                    state, base = "B", []
                elif ln == MARK_M and state in ("L", "B"):
                    state = "R"
                elif ln.startswith(MARK_R) and state == "R":
                    out.append((start, i, left, base, right))
                    break
                elif state == "L":
                    left.append(ln)
                elif state == "B":
                    base.append(ln)
                else:
                    right.append(ln)
                i += 1
        i += 1
    return out


def resolve_conflict(lines, index, choice):
    """Replaces conflict number `index` by 'left', 'right', 'both' (left then right), 'both_rev', 'base' or 'none'."""
    cs = find_conflicts(lines)
    if not 0 <= index < len(cs):
        return lines
    first, last, left, base, right = cs[index]
    pick = {"left": left, "right": right, "both": left + right, "both_rev": right + left, "base": base or [], "none": []}[choice]
    return lines[:first] + pick + lines[last + 1:]


# ---- patches and reports ---------------------------------------------------------------------------------------------------------------
def unified(a, b, an="left", bn="right", n=3):
    return "".join(l if l.endswith("\n") else l + "\n" for l in difflib.unified_diff(a, b, an, bn, lineterm="", n=n))


def context(a, b, an="left", bn="right", n=3):
    return "".join(l if l.endswith("\n") else l + "\n" for l in difflib.context_diff(a, b, an, bn, lineterm="", n=n))


def normal(a, b):
    """The classic 'normal' diff format (3c3, 5a6,7, 9d8)."""
    out = []

    def rng(x1, x2):
        return str(x1 + 1) if x2 - x1 == 1 else f"{x1 + 1},{x2}"
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "insert":
            out.append(f"{i1}a{rng(j1, j2)}")
        elif tag == "delete":
            out.append(f"{rng(i1, i2)}d{j1}")
        else:
            out.append(f"{rng(i1, i2)}c{rng(j1, j2)}")
        out += [f"< {l}" for l in a[i1:i2]]
        if tag == "replace":
            out.append("---")
        out += [f"> {l}" for l in b[j1:j2]]
    return "\n".join(out) + ("\n" if out else "")


def _mark_spans(line, spans, cls):
    out, pos = [], 0
    for s, e in sorted(spans):
        if s < pos:
            continue
        out.append(html.escape(line[pos:s]))
        out.append(f'<span class="{cls}">{html.escape(line[s:e])}</span>')
        pos = e
    out.append(html.escape(line[pos:]))
    return "".join(out)


def report_html(res, a_lines, b_lines, left_title="Left", right_title="Right", context_lines=3, fragment=False):
    """A side-by-side HTML report with the differing lines (and the changed words inside them) coloured."""
    rows = []
    hidden = {(r[0], r[1]): r for r in hidden_ranges(res, context_lines)}
    skip_a = set()
    for r in hidden.values():
        skip_a.update(range(r[0], r[1] + 1))
    block_of = {}
    for t, i1, i2, j1, j2 in res.blocks:
        for k in range(max(i2 - i1, j2 - j1)):
            block_of[(i1 + k, j1 + k)] = t
    i = j = 0
    for t, i1, i2, j1, j2 in res.blocks + [("end", len(a_lines), len(a_lines), len(b_lines), len(b_lines))]:
        while i < i1 and j < j1:                                  # matching lines before this block
            if i in skip_a:
                r = next(rr for rr in hidden.values() if rr[0] <= i <= rr[1])
                rows.append(f'<tr class="skip"><td colspan="4">... {r[1] - r[0] + 1} matching lines hidden ...</td></tr>')
                i, j = r[1] + 1, r[3] + 1
                continue
            cls = "unimp" if i in res.unimportant_left else ""
            rows.append(f'<tr class="{cls}"><td class="n">{i + 1}</td><td>{html.escape(a_lines[i])}</td>'
                        f'<td class="n">{j + 1}</td><td>{html.escape(b_lines[j])}</td></tr>')
            i += 1
            j += 1
        if t == "end":
            break
        for k in range(max(i2 - i1, j2 - j1)):
            li, rj = i1 + k, j1 + k
            ltxt = rtxt = ""
            if li < i2:
                ltxt = _mark_spans(a_lines[li], res.intra_left.get(li, []), "w") if res.pairs.get(li) is not None else html.escape(a_lines[li])
            if rj < j2:
                rtxt = _mark_spans(b_lines[rj], res.intra_right.get(rj, []), "w")
            rows.append(f'<tr class="{t}"><td class="n">{li + 1 if li < i2 else ""}</td><td>{ltxt}</td>'
                        f'<td class="n">{rj + 1 if rj < j2 else ""}</td><td>{rtxt}</td></tr>')
        i, j = i2, j2
    added, removed, changed = res.stats()
    style = ("body{font-family:Segoe UI,Arial,sans-serif;font-size:13px} table{border-collapse:collapse;width:100%;font-family:Consolas,monospace;font-size:12px}"
             "td{padding:1px 6px;vertical-align:top;white-space:pre-wrap;border:1px solid #e3e6eb} td.n{color:#8a93a3;width:40px;text-align:right}"
             "tr.add td{background:#e3f6dd} tr.del td{background:#fde2e0} tr.chg td{background:#fdf0d6} tr.unimp td{background:#eef0f3;color:#6b7482}"
             "tr.skip td{background:#f6f7f9;color:#8a93a3;text-align:center} .w{background:#f5b042;color:#000} th{text-align:left;padding:4px 6px}")
    summary = (f"{len(res.blocks)} difference block{'s' if len(res.blocks) != 1 else ''}: {added} added, {removed} removed, {changed} changed lines"
               if res.blocks else "The two sides are identical.")
    table = (f"<table><tr><th colspan='2'>{html.escape(left_title)}</th><th colspan='2'>{html.escape(right_title)}</th></tr>" + "".join(rows) + "</table>")
    if fragment:
        return f"<style>{style}</style><p>{html.escape(summary)}</p>{table}"
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Compare report</title><style>{style}</style></head><body>"
            f"<h2>Text compare report</h2><p>{html.escape(summary)}</p>{table}</body></html>")


def report_text(res, a_lines, b_lines, left_title="Left", right_title="Right"):
    added, removed, changed = res.stats()
    out = [f"Text compare report", f"  left : {left_title}", f"  right: {right_title}",
           "  " + ("identical" if res.identical else f"{len(res.blocks)} difference blocks: {added} added, {removed} removed, {changed} changed lines"), ""]
    for k, (t, i1, i2, j1, j2) in enumerate(res.blocks, 1):
        label = {"add": "only in right", "del": "only in left", "chg": "changed"}[t]
        out.append(f"#{k} {label}: left lines {i1 + 1}-{i2}  right lines {j1 + 1}-{j2}" if i2 > i1 and j2 > j1 else
                   f"#{k} {label}: " + (f"left lines {i1 + 1}-{i2}" if i2 > i1 else f"right lines {j1 + 1}-{j2}"))
        out += [f"  - {l}" for l in a_lines[i1:i2]]
        out += [f"  + {l}" for l in b_lines[j1:j2]]
    return "\n".join(out) + "\n"


# ---- comparison sessions ----------------------------------------------------------------------------------------------------------------
def session_to_json(data):
    return json.dumps(data, indent=1, ensure_ascii=False)


def session_from_json(text):
    d = json.loads(text)
    if not isinstance(d, dict) or "left" not in d or "right" not in d:
        raise ValueError("This is not a comparison session file.")
    return d


# ---- very large files: stream both files, show only the differences ---------------------------------------------------------------------
def diff_stream(path_a, path_b, o=None, context_lines=3, max_blocks=3000, window=4000, cancelled=lambda: False, progress=lambda f: None):
    """Compares two files too big to load, line by line, without holding them in memory. When the files go out of step it looks
    ahead (`window` lines) for the nearest place where they match again. -> (excerpts, total differing blocks, truncated).
    An excerpt is {'left_start', 'right_start', 'left', 'right', 'tag'} (line numbers are 0-based; lines include context)."""
    import collections
    import os
    o = o or Options()
    nz = Normalizer(o)
    size = max(1, os.path.getsize(path_a))
    excerpts, total = [], 0
    with open(path_a, "r", encoding="utf-8", errors="replace", newline=None) as fa, open(path_b, "r", encoding="utf-8", errors="replace", newline=None) as fb:
        ita = (l.rstrip("\n") for l in fa)
        itb = (l.rstrip("\n") for l in fb)
        buf_a, buf_b = collections.deque(), collections.deque()
        base_a = base_b = 0                       # line numbers of buf_*[0]
        done_a = done_b = False
        recent_a, recent_b = collections.deque(maxlen=context_lines), collections.deque(maxlen=context_lines)
        count = 0

        def fill():
            nonlocal done_a, done_b
            while not done_a and len(buf_a) < window:
                try:
                    buf_a.append(next(ita))
                except StopIteration:
                    done_a = True
            while not done_b and len(buf_b) < window:
                try:
                    buf_b.append(next(itb))
                except StopIteration:
                    done_b = True
        pending = None                            # an excerpt still collecting trailing context
        while True:
            if cancelled():
                break
            fill()
            if not buf_a and not buf_b:
                break
            if buf_a and buf_b and nz.lenient(buf_a[0]) == nz.lenient(buf_b[0]):
                line_a, line_b = buf_a.popleft(), buf_b.popleft()
                if pending is not None:
                    if pending["trail"] < context_lines:
                        pending["left"].append(line_a)
                        pending["right"].append(line_b)
                        pending["trail"] += 1
                    else:
                        excerpts.append(pending)
                        pending = None
                recent_a.append(line_a)
                recent_b.append(line_b)
                base_a += 1
                base_b += 1
                count += 1
                if count % 200000 == 0:
                    progress(min(1.0, base_a / max(1, size / 60)))
                continue
            # the files differ here: find the nearest place where they match again
            ka = [nz.lenient(l) for l in list(buf_a)[:window]]
            kb = [nz.lenient(l) for l in list(buf_b)[:window]]
            pos_b = {}
            for y, k in enumerate(kb):
                pos_b.setdefault(k, []).append(y)
            best = None
            for x, k in enumerate(ka):
                for y in pos_b.get(k, ()):
                    if best is not None and x + y >= best[0] + best[1]:
                        break
                    if all(x + d < len(ka) and y + d < len(kb) and ka[x + d] == kb[y + d] for d in range(1, 3)) or (x + 3 >= len(ka) and y + 3 >= len(kb)):
                        best = (x, y)
                        break
                if best is not None and x >= best[0] + best[1]:
                    break
            if best is None:
                x, y = len(buf_a), len(buf_b)           # nothing matches inside the window: everything left in it differs
            else:
                x, y = best
            total += 1
            if total > max_blocks:
                return excerpts, total, True
            removed = [buf_a.popleft() for _ in range(x)]
            added = [buf_b.popleft() for _ in range(y)]
            tag = "chg" if removed and added else "del" if removed else "add"
            if pending is not None and pending["trail"] < context_lines:       # two differences close together share one excerpt
                pending["left"] += removed
                pending["right"] += added
                pending["trail"] = 0
                pending["tag"] = "chg"
            else:
                if pending is not None:
                    excerpts.append(pending)
                pending = {"left_start": base_a - len(recent_a), "right_start": base_b - len(recent_b), "tag": tag, "trail": 0,
                           "left": list(recent_a) + removed, "right": list(recent_b) + added}
            base_a += len(removed)
            base_b += len(added)
            recent_a.clear()
            recent_b.clear()
            if not buf_a and not buf_b and done_a and done_b:
                break
    if pending is not None:
        excerpts.append(pending)
    return excerpts, total, False
