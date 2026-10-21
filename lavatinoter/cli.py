"""Command-line compare and merge, for scripts and build servers (no window is opened).

    LavatiNoter --compare A B [--report FILE] [--format html|text|unified|context|normal]
                [--ignore-case] [--ignore-ws none|leading|trailing|leading_trailing|amount|all] [--ignore-regex RX]
    LavatiNoter --merge BASE LEFT RIGHT --output FILE
    LavatiNoter --compare-folders A B [--report FILE] [--ignore-case] [--ignore-ws MODE]

Exit codes: 0 = identical / merged cleanly, 1 = differences / conflicts left, 2 = error."""
import os
import sys

from . import comparecore as cc
from . import foldercmp, util

FORMATS = ("html", "text", "unified", "context", "normal")
COMMANDS = ("--compare", "--merge", "--compare-folders")
WS_MODES = ("none", "leading", "trailing", "leading_trailing", "amount", "all")


class UsageError(Exception):
    pass


def wants_cli(args):
    return any(a in COMMANDS for a in args)


def _option(args, name, count=1, default=None):
    if name not in args:
        return default
    i = args.index(name)
    vals = args[i + 1:i + 1 + count]
    if len(vals) < count or any(v.startswith("--") for v in vals):
        raise UsageError(f"{name} needs {'a value' if count == 1 else f'{count} values'}")
    return vals[0] if count == 1 else vals


def _options(args):
    o = cc.Options()
    o.ignore_case = "--ignore-case" in args
    ws = _option(args, "--ignore-ws", default="none")
    if ws not in WS_MODES:
        raise UsageError(f"--ignore-ws must be one of {', '.join(WS_MODES)}")
    o.ws = ws
    for i, a in enumerate(args):
        if a == "--ignore-regex":
            rx = _option(args[i:], "--ignore-regex")
            err = cc.check_regex(rx)
            if err:
                raise UsageError(f"bad --ignore-regex: {err}")
            o.ignore_rules.append(rx)
    return o


def _read(path):
    if not os.path.isfile(path):
        raise UsageError(f"not a file: {path}")
    text, _enc, _eol, _binary = util.read_text_file(path)
    lines = text.split("\n")
    if len(lines) > 1 and lines[-1] == "":              # the newline that ends the last line is not a line
        lines.pop()
    return lines


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def run_compare(args, out):
    a, b = _option(args, "--compare", 2)
    fmt = _option(args, "--format", default=None)
    report = _option(args, "--report")
    if fmt is None:
        ext = os.path.splitext(report)[1].lower() if report else ""
        fmt = "html" if ext in (".htm", ".html") else "text"
    if fmt not in FORMATS:
        raise UsageError(f"--format must be one of {', '.join(FORMATS)}")
    o = _options(args)
    la, lb = _read(a), _read(b)
    res = cc.compare(la, lb, o)
    if fmt == "html":
        body = cc.report_html(res, la, lb, a, b)
    elif fmt == "text":
        body = cc.report_text(res, la, lb, a, b)
    elif fmt == "normal":
        body = cc.normal(la, lb)
    else:
        body = (cc.unified if fmt == "unified" else cc.context)(la, lb, a, b)
    if report:
        _write(report, body)
    else:
        out.write(body)
    return 0 if res.identical else 1


def run_merge(args, out):
    base, left, right = _option(args, "--merge", 3)
    target = _option(args, "--output")
    if not target:
        raise UsageError("--merge needs --output FILE")
    chunks = cc.merge3(_read(base), _read(left), _read(right))
    text, conflicts = cc.render_merge(chunks)
    _write(target, text + "\n")
    if conflicts:
        out.write(f"{conflicts} conflict{'s' if conflicts != 1 else ''} left in {target}\n")
        return 1
    return 0


def run_folders(args, out):
    a, b = _option(args, "--compare-folders", 2)
    for p in (a, b):
        if not os.path.isdir(p):
            raise UsageError(f"not a folder: {p}")
    entries = foldercmp.compare_folders(a, b, _options(args))
    body = foldercmp.report_text(a, b, entries)
    report = _option(args, "--report")
    if report:
        _write(report, body)
    else:
        out.write(body)
    counts = foldercmp.summary(entries)
    return 0 if not (counts[foldercmp.DIFFERENT] or counts[foldercmp.LEFT_ONLY] or counts[foldercmp.RIGHT_ONLY]) else 1


def _attach_console():
    """The packaged app has no console window, so sys.stdout is None: join the console it was started from (if any)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        import ctypes
        ctypes.windll.kernel32.AttachConsole(-1)
        sys.stdout = sys.stdout or open("CONOUT$", "w", encoding="utf-8")
        sys.stderr = sys.stderr or open("CONOUT$", "w", encoding="utf-8")
    except (OSError, AttributeError):
        import io
        sys.stdout = sys.stdout or io.StringIO()
        sys.stderr = sys.stderr or io.StringIO()


def run(args, out=None, err=None):
    if out is None or err is None:
        _attach_console()
    out, err = out or sys.stdout, err or sys.stderr
    try:
        if "--compare" in args:
            return run_compare(args, out)
        if "--merge" in args:
            return run_merge(args, out)
        return run_folders(args, out)
    except UsageError as e:
        err.write(f"LavatiNoter: {e}\n")
        return 2
    except (OSError, ValueError) as e:
        err.write(f"LavatiNoter: {e}\n")
        return 2
