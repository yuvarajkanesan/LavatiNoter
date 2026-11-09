"""Tables on the clipboard: HTML tables (web pages, Word, Excel) and tab-separated cells become Markdown tables when pasted,
and a copied Markdown table also carries a real HTML table so it pastes as a table into Word, Excel and mail."""
import html
import re
from html.parser import HTMLParser


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._stack = [], []
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._stack[-1].append([])
        elif tag in ("td", "th") and self._stack:
            if not self._stack[-1]:
                self._stack[-1].append([])
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._stack:
            self._stack[-1][-1].append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "table" and self._stack:
            rows = [r for r in self._stack.pop() if r]
            if not self._stack:
                self.tables.append(rows)

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _cell(text):
    return text.replace("|", "\\|").replace("\n", " ").strip()


def rows_to_markdown(rows):
    """Header row, separator, body: every row padded to the widest one."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [[_cell(c) for c in r] + [""] * (width - len(r)) for r in rows]
    cols = [max(3, max(len(r[i]) for r in rows)) for i in range(width)]

    def line(r):
        return "| " + " | ".join(c.ljust(cols[i]) for i, c in enumerate(r)) + " |"
    out = [line(rows[0]), "| " + " | ".join("-" * w for w in cols) + " |"]
    out += [line(r) for r in rows[1:]]
    return "\n".join(out) + "\n"


def from_html(markup):
    """The first table of an HTML fragment as Markdown, or None."""
    if "<table" not in markup.lower():
        return None
    p = _TableParser()
    try:
        p.feed(markup)
    except Exception:  # noqa: BLE001
        return None
    for rows in p.tables:
        if rows and any(any(c for c in r) for r in rows):
            return rows_to_markdown(rows)
    return None


def from_tsv(text):
    """Cells copied from a spreadsheet (tab separated, at least two rows and two columns) as Markdown, or None."""
    lines = [l for l in text.replace("\r\n", "\n").split("\n") if l.strip()]
    if len(lines) < 2 or not all("\t" in l for l in lines):
        return None
    rows = [l.split("\t") for l in lines]
    if min(len(r) for r in rows) < 2:
        return None
    return rows_to_markdown(rows)


def from_mime(src, tsv=False):
    """A Markdown table for what is on the clipboard (HTML table first), or None when it holds no table."""
    if src.hasHtml():
        t = from_html(src.html())
        if t:
            return t
    if tsv and src.hasText():
        return from_tsv(src.text())
    return None


_ROW = re.compile(r"^\s*\|.*\|\s*$")
_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def _split(line):
    s = line.strip().strip("|")
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def markdown_to_html(text):
    """An HTML table for selected Markdown table lines, or None when the selection is not a table."""
    lines = [l for l in text.replace("\r", "").split("\n") if l.strip()]
    if len(lines) < 2 or not all(_ROW.match(l) for l in lines) or not _SEP.match(lines[1]):
        return None
    head = _split(lines[0])
    aligns = []
    for c in _split(lines[1]):
        aligns.append("center" if c.startswith(":") and c.endswith(":") else "right" if c.endswith(":") else "left")
    out = ['<table border="1" cellspacing="0" cellpadding="4">', "<tr>"]
    out += [f'<th align="{aligns[i] if i < len(aligns) else "left"}">{html.escape(c)}</th>' for i, c in enumerate(head)]
    out.append("</tr>")
    for l in lines[2:]:
        out.append("<tr>" + "".join(f'<td align="{aligns[i] if i < len(aligns) else "left"}">{html.escape(c)}</td>'
                                    for i, c in enumerate(_split(l))) + "</tr>")
    out.append("</table>")
    return "".join(out)


def is_row(line):
    return bool(_ROW.match(line))


def align(lines):
    """Re-pads the lines of a Markdown table so every column is as wide as its widest cell and the pipes line up.
    Keeps the :---: markers of the separator row. Returns (new_lines, column_widths)."""
    rows = [_split(l) for l in lines]
    sep_at = 1 if len(lines) > 1 and _SEP.match(lines[1]) else None
    width = max(len(r) for r in rows)
    kinds = []
    if sep_at is not None:
        for i in range(width):
            c = rows[1][i] if i < len(rows[1]) else "---"
            kinds.append("center" if c.startswith(":") and c.endswith(":") and len(c) > 1 else "right" if c.endswith(":") else "left")
    cols = [3] * width
    for n, r in enumerate(rows):
        if n == sep_at:
            continue
        for i, c in enumerate(r):
            cols[i] = max(cols[i], len(_cell(c)))
    out = []
    for n, r in enumerate(rows):
        if n == sep_at:
            cells = []
            for i in range(width):
                w = cols[i]
                k = kinds[i]
                cells.append(":" + "-" * (w - 2) + ":" if k == "center" else "-" * (w - 1) + ":" if k == "right" else "-" * w)
        else:
            r = r + [""] * (width - len(r))
            cells = [_cell(c).ljust(cols[i]) for i, c in enumerate(r)]
        out.append("| " + " | ".join(cells) + " |")
    return out, cols


def cell_start(cols, c):
    """Offset of the text of cell `c` inside an aligned row."""
    return 2 + sum(w + 3 for w in cols[:c])
