"""Search engine shared by the editor, the Find dialog and Find in Files (no Qt in here, so it is easy to test)."""
import fnmatch
import os
import re
from dataclasses import dataclass, field

from . import util

NORMAL, EXTENDED, REGEX = "normal", "extended", "regex"
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".idea", ".vs"}
MAX_FILE_BYTES = 40 * 1024 * 1024
MAX_HITS = 20000


@dataclass
class Options:
    text: str = ""
    mode: str = NORMAL
    match_case: bool = False
    whole_word: bool = False
    wrap: bool = True
    backward: bool = False
    dotall: bool = False
    replacement: str = ""
    filters: str = "*.*"
    directory: str = ""
    subfolders: bool = True
    skip_hidden: bool = True


class SearchError(ValueError):
    pass


_ESC = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "\\": "\\"}


def unescape_extended(s):
    """\\n \\r \\t \\0 \\\\ and \\xHH / \\uHHHH in a search or replace string."""
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt in _ESC:
                out.append(_ESC[nxt])
                i += 2
                continue
            if nxt == "x" and re.fullmatch(r"[0-9a-fA-F]{2}", s[i + 2:i + 4] or ""):
                out.append(chr(int(s[i + 2:i + 4], 16)))
                i += 4
                continue
            if nxt == "u" and re.fullmatch(r"[0-9a-fA-F]{4}", s[i + 2:i + 6] or ""):
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def compile_pattern(o):
    if not o.text:
        raise SearchError("Nothing to search for.")
    if o.mode == REGEX:
        pat = o.text
    else:
        pat = re.escape(unescape_extended(o.text) if o.mode == EXTENDED else o.text)
    if o.whole_word:
        pat = rf"(?<!\w)(?:{pat})(?!\w)"
    flags = re.M | (0 if o.match_case else re.I) | (re.S if o.dotall and o.mode == REGEX else 0)
    try:
        return re.compile(pat, flags)
    except re.error as e:
        raise SearchError(f"Invalid regular expression: {e}") from None


def expand_replacement(o, m):
    """The replacement text for one match."""
    if o.mode == REGEX:
        try:
            return m.expand(o.replacement)
        except (re.error, IndexError) as e:
            raise SearchError(f"Invalid replacement: {e}") from None
    return unescape_extended(o.replacement) if o.mode == EXTENDED else o.replacement


def replace_all(o, text):
    """-> (new text, number of replacements)."""
    rx = compile_pattern(o)
    if o.mode == REGEX:
        return rx.subn(lambda m: expand_replacement(o, m), text)
    repl = unescape_extended(o.replacement) if o.mode == EXTENDED else o.replacement
    return rx.subn(lambda m: repl, text)


def find_next(rx, text, start, backward=False, wrap=True):
    """-> match object or None. `start` is where the search begins (selection end when searching forward,
    selection start when backward)."""
    if not backward:
        m = rx.search(text, start)
        if m is None and wrap and start > 0:
            m = rx.search(text, 0)
        return m
    last = None
    for m in rx.finditer(text, 0, start):
        last = m
    if last is None and wrap:
        for m in rx.finditer(text, start):
            last = m
    return last


@dataclass
class Hit:
    line: int           # 1-based
    col: int            # 0-based column of the match inside the line
    length: int
    text: str           # the line's text (trimmed of leading whitespace for display)
    shift: int = 0      # characters trimmed from the front of `text`
    pos: int = 0        # absolute character offset in the file


@dataclass
class FileResult:
    path: str
    hits: list = field(default_factory=list)


def hits_in_text(rx, text, limit=MAX_HITS):
    hits = []
    if not text:
        return hits
    line_starts = [0]
    for m in re.finditer("\n", text):
        line_starts.append(m.end())
    import bisect
    for m in rx.finditer(text):
        if len(hits) >= limit:
            break
        ln = bisect.bisect_right(line_starts, m.start()) - 1
        start = line_starts[ln]
        end = text.find("\n", start)
        line = text[start:end if end >= 0 else len(text)]
        stripped = line.lstrip()
        shift = len(line) - len(stripped)
        length = max(0, min(m.end(), start + len(line)) - m.start())
        shown = stripped[:400]
        hits.append(Hit(ln + 1, m.start() - start, length, shown, shift, m.start()))
    return hits


def split_filters(filters):
    parts = [p for p in re.split(r"[;,\s]+", filters or "") if p]
    include = [p for p in parts if not p.startswith("!")] or ["*"]
    exclude = [p[1:] for p in parts if p.startswith("!")]
    return include, exclude


def iter_files(directory, filters="*.*", subfolders=True, skip_hidden=True):
    include, exclude = split_filters(filters)
    include = ["*" if p == "*.*" else p for p in include]
    for root, dirs, files in os.walk(directory):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (skip_hidden and d.startswith(".")))
        if not subfolders:
            dirs[:] = []
        for name in sorted(files):
            if skip_hidden and name.startswith("."):
                continue
            if any(fnmatch.fnmatch(name.lower(), p.lower()) for p in include) and \
                    not any(fnmatch.fnmatch(name.lower(), p.lower()) for p in exclude):
                yield os.path.join(root, name)


def read_for_search(path):
    """-> (text, encoding, eol) or None for files that are binary, too large or unreadable."""
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, "rb") as f:
            head = f.read(4096)
        if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
            return None
        text, enc, eol, _ = util.read_text_file(path)
        return text, enc, eol
    except OSError:
        return None


def search_files(o, cancelled=lambda: False, progress=lambda n: None):
    """Yields FileResult for every file with hits. Reads files from disk."""
    rx = compile_pattern(o)
    count = 0
    for path in iter_files(o.directory, o.filters, o.subfolders, o.skip_hidden):
        if cancelled():
            return
        count += 1
        if count % 20 == 0:
            progress(count)
        data = read_for_search(path)
        if data is None:
            continue
        hits = hits_in_text(rx, data[0])
        if hits:
            yield FileResult(path, hits)
    progress(count)


def replace_in_files(o, paths, skip=lambda p: False):
    """Replaces in the given files on disk. -> (files changed, replacements, [paths skipped])."""
    rx = compile_pattern(o)
    changed = total = 0
    skipped = []
    for path in paths:
        if skip(path):
            skipped.append(path)
            continue
        data = read_for_search(path)
        if data is None:
            skipped.append(path)
            continue
        text, enc, eol = data
        new, n = (rx.subn(lambda m: expand_replacement(o, m), text))
        if n:
            util.write_text_file(path, new, enc, eol)
            changed += 1
            total += n
    return changed, total, skipped
