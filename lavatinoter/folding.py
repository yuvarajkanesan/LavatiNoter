"""Where code can be folded: matching brackets for brace languages, indentation for Python / YAML, headings for Markdown
and matching tags for HTML / XML. Pure functions (no Qt), so they are easy to test."""
import re

INDENT_LANGS = ("Python", "YAML", "Makefile")
MARKUP_LANGS = ("HTML / XML",)
NO_FOLD = ("Plain text", "Log", "Diff / Patch")
PY_BLOCK = re.compile(r"^\s*(?:async\s+)?(?:def|class|if|elif|else|for|while|try|except|finally|with|match|case)\b.*:\s*(?:#.*)?$")


def compute_regions(lang_name, text):
    """-> {first line: last line} (0-based) for every foldable block that spans more than one line."""
    if lang_name in NO_FOLD or len(text) > 3_000_000:
        return {}
    if lang_name in INDENT_LANGS:
        return _by_indent(text, python=lang_name == "Python")
    if lang_name == "Markdown":
        return _markdown(text)
    if lang_name in MARKUP_LANGS:
        return _tags(text)
    return _brackets(text, hash_comments=lang_name in ("Ruby", "Perl", "R", "PowerShell / Shell", "Dockerfile"),
                     single_quotes=lang_name not in ("Rust", "Lua"))


def _brackets(text, hash_comments=False, single_quotes=True):
    regions, stack = {}, []
    pairs = {")": "(", "]": "[", "}": "{"}
    line, i, n = 0, 0, len(text)
    quotes = "\"'`" if single_quotes else "\"`"
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
        elif ch == "/" and text.startswith("//", i) or (hash_comments and ch == "#") or text.startswith("--", i) and False:
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif ch == "/" and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            line += text.count("\n", i, j)
            i = j
            continue
        elif ch in quotes:
            j = i + 1
            while j < n and text[j] != ch and (text[j] != "\n" or ch == "`"):
                j += 2 if text[j] == "\\" else 1
            line += text.count("\n", i, min(j, n))
            i = j + 1
            continue
        elif ch in "([{":
            stack.append((ch, line))
        elif ch in ")]}":
            if stack and stack[-1][0] == pairs[ch]:
                _, start = stack.pop()
                if line > start:
                    regions[start] = max(regions.get(start, 0), line)
        i += 1
    return regions


def _by_indent(text, python):
    lines = text.split("\n")
    n = len(lines)
    indents = [(len(l) - len(l.lstrip(" \t"))) if l.strip() else None for l in lines]
    regions = {}
    for i, l in enumerate(lines):
        if indents[i] is None:
            continue
        if python and not PY_BLOCK.match(l):
            continue
        if not python and not l.rstrip().endswith(":") and not l.rstrip().endswith("|"):
            continue
        j, last = i + 1, None
        while j < n and (indents[j] is None or indents[j] > indents[i]):
            if indents[j] is not None:
                last = j
            j += 1
        if last is not None and last > i:
            regions[i] = last
    return regions


def _markdown(text):
    lines = text.split("\n")
    heads = [(i, len(m.group(1))) for i, l in enumerate(lines) if (m := re.match(r"^(#{1,6})\s", l))]
    regions = {}
    for k, (i, level) in enumerate(heads):
        end = len(lines) - 1
        for i2, level2 in heads[k + 1:]:
            if level2 <= level:
                end = i2 - 1
                break
        while end > i and not lines[end].strip():
            end -= 1
        if end > i:
            regions[i] = end
    return regions


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr", "!doctype"}


def _tags(text):
    regions, stack = {}, []
    for m in re.finditer(r"<!--.*?-->|<(/?)([A-Za-z][\w:-]*)[^>]*?(/?)>", text, flags=re.S):
        if m.group(2) is None:
            continue
        line = text.count("\n", 0, m.start())
        name = m.group(2).lower()
        if m.group(3) == "/" or name in VOID:
            continue
        if not m.group(1):
            stack.append((name, line))
        else:
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == name:
                    _, start = stack[k]
                    del stack[k:]
                    end = text.count("\n", 0, m.end())
                    if end > start:
                        regions[start] = max(regions.get(start, 0), end)
                    break
    return regions
