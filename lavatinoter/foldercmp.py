"""Folder comparison without any window: which files are only on one side, which differ, which match."""
import fnmatch
import os
from dataclasses import dataclass

from . import comparecore as cc
from . import util

SAME, DIFFERENT, LEFT_ONLY, RIGHT_ONLY = "same", "different", "left only", "right only"
MAX_TEXT_BYTES = 8 * 1024 * 1024               # bigger files are compared byte for byte only
BUF = 1 << 16


@dataclass
class Entry:
    rel: str                        # path relative to the compared folders, with "/" separators
    status: str
    is_dir: bool = False
    left_size: int = -1
    right_size: int = -1


def _same_bytes(a, b):
    if os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            x, y = fa.read(BUF), fb.read(BUF)
            if x != y:
                return False
            if not x:
                return True


def _lines(path):
    text, _enc, _eol, binary = util.read_text_file(path)
    return None if binary else text.split("\n")


def _same_text(a, b, o):
    """True when the files only differ in ways the options say do not matter (white space, case, line endings, ...)."""
    if os.path.getsize(a) > MAX_TEXT_BYTES or os.path.getsize(b) > MAX_TEXT_BYTES:
        return False
    la, lb = _lines(a), _lines(b)
    return la is not None and lb is not None and cc.compare(la, lb, o).identical


def _walk(root, recursive, excludes):
    out = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not any(fnmatch.fnmatch(d, p) for p in excludes))
        rel_base = os.path.relpath(base, root).replace("\\", "/")
        rel_base = "" if rel_base == "." else rel_base + "/"
        for d in dirs:
            out[rel_base + d] = True
        for f in sorted(files):
            if not any(fnmatch.fnmatch(f, p) for p in excludes):
                out[rel_base + f] = False
        if not recursive:
            break
    return out


def compare_folders(left, right, options=None, recursive=True, excludes=(".git", "__pycache__", "node_modules"), cancelled=lambda: False):
    """-> [Entry] sorted by path. `options` (comparecore.Options) makes files that only differ in ignorable ways count as the same."""
    excludes = list(excludes)
    lw, rw = _walk(left, recursive, excludes), _walk(right, recursive, excludes)
    out = []
    for rel in sorted(set(lw) | set(rw), key=lambda r: r.lower()):
        if cancelled():
            break
        in_l, in_r = rel in lw, rel in rw
        is_dir = lw.get(rel, rw.get(rel))
        pl, pr = os.path.join(left, rel), os.path.join(right, rel)
        if in_l and in_r:
            if lw[rel] != rw[rel]:                      # a folder on one side, a file on the other
                out.append(Entry(rel, DIFFERENT, False))
                continue
            if is_dir:
                continue
            try:
                same = _same_bytes(pl, pr) or (options is not None and _same_text(pl, pr, options))
            except OSError:
                same = False
            out.append(Entry(rel, SAME if same else DIFFERENT, False, os.path.getsize(pl), os.path.getsize(pr)))
        elif in_l:
            out.append(Entry(rel, LEFT_ONLY, is_dir, -1 if is_dir else os.path.getsize(pl)))
        else:
            out.append(Entry(rel, RIGHT_ONLY, is_dir, -1, -1 if is_dir else os.path.getsize(pr)))
    return out


def summary(entries):
    counts = {SAME: 0, DIFFERENT: 0, LEFT_ONLY: 0, RIGHT_ONLY: 0}
    for e in entries:
        if not e.is_dir:
            counts[e.status] += 1
    return counts


def report_text(left, right, entries, show_same=False):
    c = summary(entries)
    out = ["Folder compare report", f"  left : {left}", f"  right: {right}",
           f"  {c[DIFFERENT]} different, {c[LEFT_ONLY]} only in left, {c[RIGHT_ONLY]} only in right, {c[SAME]} identical", ""]
    for e in entries:
        if e.status == SAME and not show_same:
            continue
        out.append(f"{e.status:11s} {e.rel}{'/' if e.is_dir else ''}")
    return "\n".join(out) + "\n"
