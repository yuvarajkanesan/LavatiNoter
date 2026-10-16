""".editorconfig support (https://editorconfig.org): indent style / size, end of line, trailing whitespace, final newline."""
import fnmatch
import os
import re

KNOWN = ("indent_style", "indent_size", "tab_width", "end_of_line", "charset", "trim_trailing_whitespace", "insert_final_newline")


def _expand_braces(pattern):
    m = re.search(r"\{([^{}]*)\}", pattern)
    if not m:
        return [pattern]
    out = []
    for opt in m.group(1).split(","):
        out += _expand_braces(pattern[:m.start()] + opt + pattern[m.end():])
    return out


def _matches(section, rel_path):
    """True when an .editorconfig section glob matches the path (relative to the file that holds the section)."""
    rel_path = rel_path.replace("\\", "/")
    for pat in _expand_braces(section):
        if "/" not in pat:
            if fnmatch.fnmatchcase(os.path.basename(rel_path), pat):
                return True
        else:
            glob = pat.lstrip("/").replace("**", "\0")
            rx = re.escape(glob).replace(re.escape("\0"), ".*").replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
            if re.fullmatch(rx, rel_path):
                return True
    return False


def _parse(path):
    sections, root, cur = [], False, None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line[0] in "#;":
                    continue
                if line.startswith("[") and line.endswith("]"):
                    cur = (line[1:-1], {})
                    sections.append(cur)
                elif "=" in line:
                    k, v = (x.strip() for x in line.split("=", 1))
                    if cur is None:
                        if k.lower() == "root" and v.lower() == "true":
                            root = True
                    else:
                        cur[1][k.lower()] = v.lower()
    except OSError:
        pass
    return sections, root


def properties_for(file_path):
    """The merged settings that apply to `file_path` (nearest .editorconfig wins), as a dict of lower-case strings."""
    file_path = os.path.abspath(file_path)
    folder = os.path.dirname(file_path)
    chain = []
    while True:
        cfg = os.path.join(folder, ".editorconfig")
        if os.path.isfile(cfg):
            sections, root = _parse(cfg)
            chain.append((folder, sections))
            if root:
                break
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    props = {}
    for base, sections in reversed(chain):                     # farthest first, so nearer files override
        rel = os.path.relpath(file_path, base)
        for glob, values in sections:
            if _matches(glob, rel):
                props.update({k: v for k, v in values.items() if k in KNOWN})
    return props


def apply_on_save(props, text):
    """The text as it should be written: trailing whitespace trimmed and the final newline set, as asked."""
    if props.get("trim_trailing_whitespace") == "true":
        text = "\n".join(l.rstrip(" \t") for l in text.split("\n"))
    final = props.get("insert_final_newline")
    if final == "true" and text and not text.endswith("\n"):
        text += "\n"
    elif final == "false":
        text = text.rstrip("\n") if text.endswith("\n") and text.strip() else text
    return text
