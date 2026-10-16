"""Go to definition / find references / symbol lists without a language server: definitions are found with each language's
function / class pattern (and simple assignments), in the current file first and then across the workspace folder."""
import os
import re
import time

from . import search, util
from .highlighter import lang_for_path

MAX_FILES = 4000
MAX_FILE_BYTES = 2 * 1024 * 1024
CODE_FILTER = ("*.py;*.js;*.jsx;*.mjs;*.ts;*.tsx;*.java;*.cs;*.c;*.h;*.cpp;*.hpp;*.cc;*.go;*.rs;*.kt;*.swift;*.dart;*.scala;"
               "*.php;*.rb;*.lua;*.pl;*.r;*.sh;*.ps1;*.css;*.scss;*.sql;*.md;*.html;*.vue;*.json;*.yaml;*.yml;*.toml;*.cfg;*.ini;*.txt")


def symbols_in_text(lang, text):
    """[(name, 1-based line, kind line text)] for every function / class / section the language's pattern finds."""
    if lang is None or lang.funcs is None:
        return []
    out = []
    for m in lang.funcs.finditer(text):
        name = next((g for g in m.groups() if g), None)
        if name:
            line = text.count("\n", 0, m.start(1) if m.lastindex and m.start(1) >= 0 else m.start()) + 1
            start = text.rfind("\n", 0, m.start()) + 1
            end = text.find("\n", m.start())
            out.append((name.strip(), line, text[start:end if end >= 0 else len(text)].strip()[:200]))
    return out


def _assignment_rx(name):
    return re.compile(rf"^[ \t]*(?:(?:export|const|let|var|final|static|public|private|protected|readonly|val|var|auto)\s+)*"
                      rf"(?:[\w<>\[\]*&:]+\s+)?{re.escape(name)}\s*(?::[^=\n]+)?=(?!=)", re.M)


def definitions_in_text(lang, text, name):
    """[(line, line text)] of definitions of `name` in one file."""
    hits = [(ln, t) for n, ln, t in symbols_in_text(lang, text) if n == name]
    if hits:
        return hits
    lines = text.split("\n")
    out = []
    for m in _assignment_rx(name).finditer(text):
        ln = text.count("\n", 0, m.start()) + 1
        out.append((ln, lines[ln - 1].strip()[:200]))
    return out


def find_definitions(name, root, current_path=None, budget=4.0):
    """-> [(path, line, text)] over the workspace, the file at `current_path` first."""
    results, t0, files = [], time.monotonic(), 0
    paths = list(search.iter_files(root, CODE_FILTER, True, True)) if root and os.path.isdir(root) else []
    if current_path and current_path in paths:
        paths.remove(current_path)
        paths.insert(0, current_path)
    for p in paths:
        files += 1
        if files > MAX_FILES or time.monotonic() - t0 > budget:
            break
        try:
            if os.path.getsize(p) > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        lang = lang_for_path(p)
        if lang.funcs is None and lang.name in ("Plain text", "JSON", "Log"):
            continue
        data = search.read_for_search(p)
        if data is None or name not in data[0]:
            continue
        for ln, t in definitions_in_text(lang, data[0], name):
            results.append((p, ln, t))
    return results


def find_references(name, root, budget=6.0):
    """Whole-word hits of `name` across the workspace -> [search.FileResult]."""
    o = search.Options(text=name, match_case=True, whole_word=True, directory=root, filters=CODE_FILTER)
    out, t0, total = [], time.monotonic(), 0
    for r in search.search_files(o, cancelled=lambda: time.monotonic() - t0 > budget):
        out.append(r)
        total += len(r.hits)
        if total > 5000:
            break
    return out
