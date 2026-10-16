"""Read-only Git helpers (status for the workspace tree, HEAD text for the change bars and diff). Needs `git` on PATH."""
import difflib
import os
import shutil
import subprocess
import sys


def git_exe():
    return shutil.which("git")


def run(args, cwd, timeout=6):
    """Output of `git <args>` as bytes, or None when git is missing, fails or times out."""
    exe = git_exe()
    if not exe or not cwd or not os.path.isdir(cwd):
        return None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        r = subprocess.run([exe, "-c", "core.quotepath=false"] + list(args), cwd=cwd, capture_output=True, timeout=timeout, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def repo_root(folder):
    out = run(["rev-parse", "--show-toplevel"], folder)
    return os.path.normpath(out.decode("utf-8", "replace").strip()) if out else None


def branch(root):
    out = run(["rev-parse", "--abbrev-ref", "HEAD"], root)
    name = out.decode("utf-8", "replace").strip() if out else ""
    if name == "HEAD":
        out = run(["rev-parse", "--short", "HEAD"], root)
        name = "detached " + (out.decode().strip() if out else "")
    return name


def status(root):
    """{absolute path: 'M' modified | 'A' added | '?' untracked | 'D' deleted | 'R' renamed | 'U' conflict}."""
    out = run(["status", "--porcelain=v1", "-z", "--untracked-files=normal"], root)
    result = {}
    if not out:
        return result
    parts = out.decode("utf-8", "replace").split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        xy, rel = entry[:2], entry[3:]
        if xy[0] == "R" or xy[1] == "R":
            i += 1                                           # the old name follows
        code = "U" if "U" in xy or xy in ("AA", "DD") else "?" if xy == "??" else "D" if "D" in xy else "R" if "R" in xy else "A" if "A" in xy else "M"
        result[os.path.normpath(os.path.join(root, rel))] = code
    return result


def head_text(root, path):
    """The committed (HEAD) text of a file, or None when it is not tracked."""
    rel = os.path.relpath(path, root).replace("\\", "/")
    out = run(["show", f"HEAD:{rel}"], root)
    return out.decode("utf-8", "replace").replace("\r\n", "\n") if out is not None else None


def line_changes(old, new, limit=20000):
    """{1-based line in `new`: 'added' | 'modified' | 'deleted'} ('deleted' marks the line above a removed block)."""
    a, b = old.split("\n"), new.split("\n")
    if len(a) > limit or len(b) > limit:
        return {}
    marks = {}
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "insert":
            for j in range(j1, j2):
                marks[j + 1] = "added"
        elif tag == "replace":
            for j in range(j1, j2):
                marks[j + 1] = "modified"
        elif tag == "delete":
            marks[max(1, j1)] = marks.get(max(1, j1), "deleted")
    return marks
