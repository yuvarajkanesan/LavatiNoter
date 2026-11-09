"""Text tables without a window: TableModel -> render(style) -> text, and parse(text) -> TableModel.

Columns are as wide as the widest cell measured in display columns (CJK and emoji take two, combining marks none), never narrower
than MIN_WIDTH, so empty cells keep their size and the borders always line up. Styles: markdown, ascii, unicode, plain."""
import re
import unicodedata

MIN_WIDTH = 3
STYLES = ("markdown", "ascii", "unicode", "plain")
ALIGNS = ("left", "center", "right")

_UNI = {"tl": "┌", "tm": "┬", "tr": "┐", "ml": "├", "mm": "┼", "mr": "┤",
        "bl": "└", "bm": "┴", "br": "┘", "h": "─", "v": "│"}
_ASC = {"tl": "+", "tm": "+", "tr": "+", "ml": "+", "mm": "+", "mr": "+", "bl": "+", "bm": "+", "br": "+", "h": "-", "v": "|"}
_BORDER_CHARS = set("+-=|┌┬┐├┼┤└┴┘─│═ :")


def char_width(ch):
    """Display columns of one character: 0 for combining / zero-width, 2 for wide (CJK, emoji), else 1."""
    o = ord(ch)
    if o < 32 or o == 127:
        return 0
    if o == 0x200B or o == 0x200D or 0xFE00 <= o <= 0xFE0F or 0x1F3FB <= o <= 0x1F3FF:
        return 0
    cat = unicodedata.category(ch)
    if cat in ("Mn", "Me", "Cf"):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    if 0x1F300 <= o <= 0x1FAFF or 0x2600 <= o <= 0x27BF and ch in "✅❌✨⭐⚡☔⚽":
        return 2
    return 1


def display_width(text):
    return sum(char_width(c) for c in text)


def clean_cell(text):
    """What may live in one cell of a one-line-per-row table: no line breaks, tabs as four spaces."""
    return " ".join(str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ").split("\n")).strip()


def pad(text, width, align="left"):
    gap = max(width - display_width(text), 0)
    if align == "right":
        return " " * gap + text
    if align == "center":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


class TableModel:
    def __init__(self, rows=None, aligns=None, header=True, style="markdown"):
        self.rows = [[clean_cell(c) for c in r] for r in (rows or [[""]])]
        n = max(len(r) for r in self.rows)
        for r in self.rows:
            r.extend([""] * (n - len(r)))
        self.aligns = list(aligns or [])[:n] + ["left"] * max(n - len(aligns or []), 0)
        self.header, self.style = bool(header), style

    @classmethod
    def blank(cls, rows, cols, header=True, aligns=None, style="markdown"):
        """A new table: a header named Column N (when asked) and empty body cells. `rows` counts every row, header included."""
        body = [[""] * cols for _ in range(max(rows, 1))]
        if header:
            body[0] = [f"Column {i + 1}" for i in range(cols)]
        return cls(body, aligns, header, style)

    @property
    def ncols(self):
        return len(self.rows[0])

    def shown(self, text, style=None):
        """A cell as it is written in the table: a | inside it is escaped (markdown) or swapped for a broken bar, so it can not split the row."""
        style = style or self.style
        if style == "markdown":
            return text.replace("\\|", "|").replace("|", "\\|")
        if style == "unicode":
            return text.replace("\u2502", "\u00a6")
        if style == "ascii":
            return text.replace("|", "\u00a6")
        return text

    def widths(self, style=None):
        w = [MIN_WIDTH] * self.ncols
        for r in self.rows:
            for i, c in enumerate(r):
                w[i] = max(w[i], display_width(self.shown(c, style)))
        return w

    # ---- editing ----------------------------------------------------------------------------------------------------------
    def add_row(self, at=None):
        at = len(self.rows) if at is None else at
        self.rows.insert(at, [""] * self.ncols)

    def delete_row(self, at):
        if len(self.rows) > 1:
            del self.rows[at]

    def add_column(self, at=None):
        at = self.ncols if at is None else at
        for r in self.rows:
            r.insert(at, "")
        self.aligns.insert(at, "left")
        if self.header:
            self.rows[0][at] = f"Column {self.ncols}"

    def delete_column(self, at):
        if self.ncols > 1:
            for r in self.rows:
                del r[at]
            del self.aligns[at]

    # ---- rendering --------------------------------------------------------------------------------------------------------
    def render(self, style=None, eol="\n"):
        return eol.join(self.render_lines(style)[0]) + eol

    def render_lines(self, style=None):
        """([text lines], [index of the line holding each row]). Cells are padded to the column width."""
        style = style or self.style
        w = self.widths(style)
        out, at = [], []

        def row_line(r, v):
            return v + v.join(" " + pad(self.shown(c, style), w[i], self.aligns[i]) + " " for i, c in enumerate(r)) + v

        if style == "markdown":
            sep = []
            for i, a in enumerate(self.aligns):
                n = w[i]
                sep.append(":" + "-" * (n - 2) + ":" if a == "center" else "-" * (n - 1) + ":" if a == "right" else "-" * n)
            for k, r in enumerate(self.rows):
                at.append(len(out))
                out.append(row_line(r, "|"))
                if k == 0:
                    out.append("| " + " | ".join(sep) + " |")
            return out, at
        if style == "plain":
            for r in self.rows:
                at.append(len(out))
                out.append("  ".join(pad(c, w[i], self.aligns[i]) for i, c in enumerate(r)).rstrip())
            return out, at
        g = _UNI if style == "unicode" else _ASC

        def border(l, m, r):
            return l + m.join(g["h"] * (n + 2) for n in w) + r

        out.append(border(g["tl"], g["tm"], g["tr"]))
        for k, r in enumerate(self.rows):
            at.append(len(out))
            out.append(row_line(r, g["v"]))
            if k == 0 and self.header and len(self.rows) > 1:
                out.append(border(g["ml"], g["mm"], g["mr"]))
        out.append(border(g["bl"], g["bm"], g["br"]))
        return out, at

    # ---- text helpers -----------------------------------------------------------------------------------------------------
    def to_plain(self):
        return TableModel(self.rows, self.aligns, self.header, "plain").render()

    def to_csv(self):
        out = []
        for r in self.rows:
            out.append(",".join('"' + c.replace('"', '""') + '"' if any(ch in c for ch in ',"') else c for c in r))
        return "\n".join(out) + "\n"


# ---- parsing --------------------------------------------------------------------------------------------------------------------
def _is_border(line):
    s = line.strip()
    return (len(s) >= 3 and s[0] in "+┌├└" and any(ch in s for ch in "-─=═")
            and all(ch in _BORDER_CHARS or ch in "┬┼┴┐┤┘" for ch in s))


_MD_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")


def is_table_line(line):
    s = line.strip()
    return bool(s) and (s[0] in "|│" or _is_border(line))


def split_cells(line, delim):
    """[(start, end)] of the raw text between delimiters of one row line (an escaped \\| does not split)."""
    s = line
    first = s.find(delim)
    if first < 0:
        return []
    spans, start, i = [], first + 1, first + 1
    while i < len(s):
        ch = s[i]
        if ch == "\\" and delim == "|" and i + 1 < len(s) and s[i + 1] == "|":
            i += 2
            continue
        if ch == delim:
            spans.append((start, i))
            start = i + 1
        i += 1
    if start < len(s) and s[start:].strip():
        spans.append((start, len(s)))                         # a last cell without a closing delimiter
    return spans


def _row_cells(line, delim):
    out = []
    for a, b in split_cells(line, delim):
        text = line[a:b].strip()
        out.append(text.replace("\\|", "|") if delim == "|" else text)
    return out


def detect_style(lines):
    first = next((l.strip() for l in lines if l.strip()), "")
    if first[:1] in "┌│├└":
        return "unicode"
    if first[:1] == "+":
        return "ascii"
    if first[:1] == "|":
        return "markdown" if len(lines) > 1 and _MD_SEP.match(lines[1]) else ("ascii" if any(_is_border(l) for l in lines) else "markdown")
    return "plain"


def _guess_align(cells):
    votes = {"left": 0, "center": 0, "right": 0}
    for raw in cells:
        if not raw.strip():
            continue
        lead, trail = len(raw) - len(raw.lstrip(" ")), len(raw) - len(raw.rstrip(" "))
        lead, trail = max(lead - 1, 0), max(trail - 1, 0)
        votes["right" if lead > trail + 1 else "center" if abs(lead - trail) <= 1 and lead > 0 else "left"] += 1
    return max(votes, key=lambda k: (votes[k], k == "left"))


def _plain_rows(lines):
    """Rows of an aligned plain table: tab separated, or split at the columns that are blank in every line (so empty cells survive)."""
    if all("\t" in l for l in lines):
        return [l.split("\t") for l in lines]
    width = max(len(l) for l in lines)
    blank = [all(i >= len(l) or l[i] == " " for l in lines) for i in range(width)]
    cuts, i = [], 0
    while i < width:
        if blank[i]:
            j = i
            while j < width and blank[j]:
                j += 1
            if j - i >= 2 and i > 0 and j < width:
                cuts.append((i, j))
            i = j
        else:
            i += 1
    bounds, start = [], 0
    for a, b in cuts:
        bounds.append((start, a))
        start = b
    bounds.append((start, width))
    return [[l[a:b].strip() for a, b in bounds] for l in lines]




def parse(text):
    """The table in `text` (any of the four styles) as a TableModel, or None."""
    lines = [l for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if l.strip()]
    if not lines:
        return None
    style = detect_style(lines)
    rows, aligns, header = [], None, True
    if style == "plain":
        rows = _plain_rows(lines)
        return TableModel(rows, None, True, "plain") if rows and max(len(r) for r in rows) > 1 else None
    delim = "│" if style == "unicode" else "|"
    raw_rows = []
    mid_after = None
    for l in lines:
        if style == "markdown" and _MD_SEP.match(l) and rows and aligns is None:
            aligns = []
            for c in _row_cells(l, "|"):
                aligns.append("center" if c.startswith(":") and c.endswith(":") and len(c) > 1 else "right" if c.endswith(":") else "left")
            continue
        if _is_border(l):
            if rows and mid_after is None:
                mid_after = len(rows)
            continue
        if delim in l:
            rows.append(_row_cells(l, delim))
            raw_rows.append([l[a:b] for a, b in split_cells(l, delim)])
    if not rows:
        return None
    if style != "markdown":
        header = mid_after == 1 and len(rows) > 1
    n = max(len(r) for r in rows)
    if aligns is None:
        aligns = [_guess_align([r[i] for r in raw_rows if i < len(r)]) for i in range(n)] if style != "markdown" else ["left"] * n
    return TableModel(rows, aligns, header, style)


def locate(line, pos, style):
    """(cell index, offset inside the cell text) for a caret at `pos` of a row line, or None for borders / non-rows."""
    delim = "│" if style == "unicode" else "|"
    if _is_border(line):
        return None
    spans = split_cells(line, delim)
    if not spans:
        return None
    for i, (a, b) in enumerate(spans):
        if pos <= b or i == len(spans) - 1:
            raw = line[a:b]
            lead = len(raw) - len(raw.lstrip(" "))
            return i, max(0, min(pos - a - lead, len(raw.strip())))
    return None


def to_index(line, pos16):
    """Qt counts UTF-16 units (an emoji is two); Python counts code points. Converts a Qt position in `line` to a string index."""
    n = 0
    for i, ch in enumerate(line):
        if n >= pos16:
            return i
        n += 2 if ord(ch) > 0xFFFF else 1
    return len(line)


def to_u16(line, index):
    """The Qt position of string index `index` in `line`."""
    return sum(2 if ord(ch) > 0xFFFF else 1 for ch in line[:index])


def caret_column(model, row, cell, offset):
    """String index in the rendered row line of the caret inside `cell`, `offset` characters into the cell text."""
    lines, at = model.render_lines()
    line = lines[at[row]]
    text = model.shown(model.rows[row][cell])
    w = model.widths()[cell]
    gap = max(w - display_width(text), 0)
    a = model.aligns[cell]
    lead = gap if a == "right" else gap // 2 if a == "center" else 0
    if model.style == "plain":
        start = 0
        for i in range(cell):
            start += len(pad(model.shown(model.rows[row][i]), model.widths()[i], model.aligns[i])) + 2
        return start + lead + min(offset, len(text))
    delim = "\u2502" if model.style == "unicode" else "|"
    spans = split_cells(line, delim)
    begin = spans[min(cell, len(spans) - 1)][0]
    return begin + 1 + lead + min(offset, len(text))
