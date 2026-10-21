"""Turns the formatting marks (**bold**, _italic_, <u>underline</u>, <span style="font-size:..px">size</span>) into clean text or
real HTML, so a copy pastes properly into Word, mail and web pages instead of showing the raw ** and _ characters."""
import html

from .highlighter import mark_spans, rich_matches


def strip_marks(text):
    """The visible text only: the marks removed."""
    out = []
    for line in text.split("\n"):
        spans = mark_spans(line)
        if not spans:
            out.append(line)
            continue
        hidden = set()
        for a, b in spans:
            hidden.update(range(a, b))
        out.append("".join(ch for i, ch in enumerate(line) if i not in hidden))
    return "\n".join(out)


def has_marks(text):
    return any(mark_spans(line) for line in text.split("\n"))


def _line_runs(line):
    """[(text, bold, italic, underline, px)] for one line, with the marks left out."""
    n = len(line)
    bold, ital, under, size = [False] * n, [False] * n, [False] * n, [0] * n
    for kind, m, a, b in rich_matches(line):
        px = int(m.group(2)) if kind == "size" else 0
        for i in range(a, b):
            if kind == "bold":
                bold[i] = True
            elif kind == "italic":
                ital[i] = True
            elif kind == "underline":
                under[i] = True
            else:
                size[i] = px
    hidden = set()
    for a, b in mark_spans(line):
        hidden.update(range(a, b))
    runs = []
    for i, ch in enumerate(line):
        if i in hidden:
            continue
        key = (bold[i], ital[i], under[i], size[i])
        if runs and tuple(runs[-1][1:]) == key:
            runs[-1][0] += ch
        else:
            runs.append([ch, *key])
    return [tuple(r) for r in runs]


_BOLD, _ITALIC, _BOLD_ITALIC = (0x1D400, 0x1D41A, 0x1D7CE), (0x1D434, 0x1D44E, None), (0x1D468, 0x1D482, None)


def _styled_char(ch, bold, italic):
    """The 'Mathematical Alphanumeric' look-alike of a letter or digit (bold, italic or both), else the character itself."""
    table = _BOLD_ITALIC if bold and italic else _BOLD if bold else _ITALIC if italic else None
    if table is None:
        return ch
    if "A" <= ch <= "Z":
        return chr(table[0] + ord(ch) - 65)
    if "a" <= ch <= "z":
        if ch == "h" and table is _ITALIC:
            return "\u210e"                                 # the one hole in the italic alphabet
        return chr(table[1] + ord(ch) - 97)
    if "0" <= ch <= "9" and table[2] is not None:
        return chr(table[2] + ord(ch) - 48)
    return ch


def to_unicode(text):
    """The formatting carried by characters that look bold / italic / underlined, so it survives a paste into programs that
    only take plain text (chat boxes, form fields). Sizes cannot be expressed this way and are dropped."""
    out = []
    for line in text.split("\n"):
        parts = []
        for chunk, b, i, u, _px in _line_runs(line):
            for ch in chunk:
                s = _styled_char(ch, b, i)
                parts.append(s + "\u0332" if u and not ch.isspace() else s)
        out.append("".join(parts))
    return "\n".join(out)


def marks_to_html(text, fragment=False):
    """HTML with real <b>, <i>, <u> and font sizes. `fragment=True` gives just the body content."""
    lines = []
    for line in text.split("\n"):
        parts = []
        for chunk, b, i, u, px in _line_runs(line):
            s = html.escape(chunk).replace("  ", "&nbsp; ")
            style = []
            if px:
                style.append(f"font-size:{px}px")
            if style:
                s = f'<span style="{";".join(style)}">{s}</span>'
            if u:
                s = f"<u>{s}</u>"
            if i:
                s = f"<i>{s}</i>"
            if b:
                s = f"<b>{s}</b>"
            parts.append(s)
        lines.append("".join(parts))
    body = "<br>\n".join(lines)
    return body if fragment else f"<html><body>\n<!--StartFragment-->{body}<!--EndFragment-->\n</body></html>"
