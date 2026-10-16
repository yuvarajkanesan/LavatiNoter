"""Document formatting and validation for the common developer languages (no Qt in here, so it is easy to test).

Formatting is deliberately conservative: JSON, XML, HTML, CSS and SQL are re-laid-out; brace languages (JavaScript,
TypeScript, Java, C#, C/C++, Go, Rust, PHP ...) are re-indented by bracket depth without moving any token, so code
can never change meaning; Python and others get whitespace clean-up plus a syntax check."""
import ast
import json
import re
import xml.dom.minidom
import xml.parsers.expat


class FormatError(ValueError):
    def __init__(self, message, line=None, col=None):
        super().__init__(message)
        self.line, self.col = line, col


BRACE_LANGS = {"JavaScript", "TypeScript", "C / C++", "C#", "Java", "Go", "Rust", "Kotlin", "Swift", "PHP", "Dart", "Scala",
               "C-family (other)", "Groovy / Gradle"}


def _unit(indent, tabs):
    return "\t" if tabs else " " * indent


def _tidy(text):
    lines = [l.rstrip() for l in text.split("\n")]
    return "\n".join(lines).rstrip("\n") + "\n"


# ---- JSON -----------------------------------------------------------------------------------------------------
def format_json(text, indent=4, tabs=False):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise FormatError(f"Invalid JSON: {e.msg}", e.lineno, e.colno) from None
    return json.dumps(data, indent="\t" if tabs else indent, ensure_ascii=False) + "\n"


def minify_json(text):
    try:
        return json.dumps(json.loads(text), separators=(",", ":"), ensure_ascii=False) + "\n"
    except json.JSONDecodeError as e:
        raise FormatError(f"Invalid JSON: {e.msg}", e.lineno, e.colno) from None


# ---- XML / HTML -----------------------------------------------------------------------------------------------------
def format_xml(text, indent=4, tabs=False):
    try:
        dom = xml.dom.minidom.parseString(text.encode("utf-8"))
    except xml.parsers.expat.ExpatError as e:
        raise FormatError(f"Invalid XML: {xml.parsers.expat.ErrorString(e.code)}", e.lineno, e.offset + 1) from None
    pretty = dom.toprettyxml(indent=_unit(indent, tabs))
    lines = [l for l in pretty.split("\n") if l.strip()]
    return "\n".join(lines) + "\n"


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
RAW = {"script", "style", "pre", "textarea"}
INLINE = {"a", "b", "i", "u", "em", "strong", "span", "code", "small", "sub", "sup", "label", "abbr", "mark", "s", "q"}


def format_html(text, indent=4, tabs=False):
    unit = _unit(indent, tabs)
    tokens = re.split(r"(<!--.*?-->|<![^>]*>|<[^>]+>)", text, flags=re.S)
    out, depth, raw_until, raw_buf = [], 0, None, []
    pending, space_before = "", False                      # inline text and tags that share one output line

    def flush():
        nonlocal pending
        if pending.strip():
            out.append(unit * depth + pending.strip())
        pending = ""
    for tok in tokens:
        if not tok:
            continue
        if raw_until:
            if re.match(rf"</{raw_until}\s*>", tok, re.I):
                body = [l.strip() for l in "".join(raw_buf).split("\n") if l.strip()]
                out.extend(unit * depth + l for l in body)
                depth = max(0, depth - 1)
                out.append(unit * depth + tok)
                raw_until, raw_buf = None, []
            else:
                raw_buf.append(tok)
            continue
        if not tok.startswith("<"):
            t = " ".join(tok.split())
            if t:
                if pending and (tok[:1].isspace() or space_before) and not pending.endswith(" "):
                    pending += " "
                pending += t
            space_before = tok[-1:].isspace()
            continue
        m = re.match(r"</?\s*([A-Za-z][\w:-]*)", tok)
        name = m.group(1).lower() if m else ""
        closing = tok.startswith("</")
        if name in INLINE:
            if pending and space_before and not pending.endswith(" "):
                pending += " "
            pending += tok
            space_before = False
            continue
        flush()
        space_before = False
        selfclose = tok.endswith("/>") or name in VOID or tok.startswith("<!") or tok.startswith("<?")
        if closing:
            depth = max(0, depth - 1)
            out.append(unit * depth + tok)
        elif selfclose:
            out.append(unit * depth + tok)
        else:
            out.append(unit * depth + tok)
            depth += 1
            if name in RAW:
                raw_until = name
    flush()
    res = "\n".join(out)
    # <title>\n  T\n</title>  ->  <title>T</title>
    res = re.sub(r"^([ \t]*)(<([\w:-]+)(?:\s[^>]*)?>)\n[ \t]*([^<\n]+)\n[ \t]*(</\3>)$", r"\1\2\4\5", res, flags=re.M)
    return res + "\n"


# ---- brace languages: re-indent by depth ---------------------------------------------------------------------------------
def _scan_depth_changes(line, state):
    """-> (opens, closes_at_start, state) for one line; `state` tracks /* */ comments and template strings across lines."""
    opens = closes = 0
    leading_closes = 0
    seen_code = False
    i, n = 0, len(line)
    in_block, in_tpl = state
    while i < n:
        ch = line[i]
        if in_block:
            if line.startswith("*/", i):
                in_block, i = False, i + 2
                continue
            i += 1
            continue
        if in_tpl:
            if ch == "\\":
                i += 2
                continue
            if ch == "`":
                in_tpl = False
            i += 1
            continue
        if line.startswith("//", i):
            break
        if line.startswith("/*", i):
            in_block, i = True, i + 2
            continue
        if ch in "\"'":
            j = i + 1
            while j < n and line[j] != ch:
                j += 2 if line[j] == "\\" else 1
            i = j + 1
            seen_code = True
            continue
        if ch == "`":
            in_tpl = True
            i += 1
            seen_code = True
            continue
        if ch in "{[(":
            opens += 1
            seen_code = True
        elif ch in "}])":
            closes += 1
            if not seen_code:
                leading_closes += 1
            seen_code = True
        elif not ch.isspace():
            seen_code = True
        i += 1
    return opens, closes, leading_closes, (in_block, in_tpl)


def reindent_braces(text, indent=4, tabs=False):
    unit = _unit(indent, tabs)
    out, depth, state = [], 0, (False, False)
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            out.append("")
            continue
        was_in_comment_or_tpl = state[0] or state[1]
        opens, closes, lead, state = _scan_depth_changes(line, state)
        d = max(0, depth - lead)
        if was_in_comment_or_tpl:
            out.append(raw.rstrip())                      # inside a template string / block comment: leave exactly as is
        else:
            extra = 1 if line.startswith((".", "?", ":", "&&", "||", "+", "-", "*", "=>")) and not line.startswith(("--", "++", "//", "/*", "*/")) and False else 0
            if line.startswith("*") and out and out[-1].lstrip().startswith(("/*", "*")):
                out.append(unit * d + " " + line)          # continuation line of a /** doc comment
            else:
                out.append(unit * (d + extra) + line)
        depth = max(0, depth + opens - closes)
    return "\n".join(out).rstrip("\n") + "\n"


# ---- CSS ----------------------------------------------------------------------------------------------------------------------
def format_css(text, indent=4, tabs=False):
    unit = _unit(indent, tabs)
    out, depth, cur, paren = [], 0, "", 0
    i, n = 0, len(text)

    def decl(c):
        c = re.sub(r"\s+", " ", c.strip())
        m = re.match(r"^([\w-]+)\s*:\s*(.+?);?$", c)
        return f"{m.group(1)}: {m.group(2)};" if m and depth > 0 else c

    def flush():
        nonlocal cur
        if cur.strip():
            out.append(unit * depth + decl(cur))
        cur = ""
    while i < n:
        ch = text[i]
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            flush()
            out.append(unit * depth + text[i:j].strip())
            i = j
            continue
        if ch in "\"'":
            j = i + 1
            while j < n and text[j] != ch:
                j += 2 if text[j] == "\\" else 1
            cur += text[i:j + 1]
            i = j + 1
            continue
        if ch == "(":
            paren += 1
        elif ch == ")":
            paren = max(0, paren - 1)
        if ch == "{":
            out.append(unit * depth + re.sub(r"\s+", " ", cur.strip()) + " {")
            cur = ""
            depth += 1
        elif ch == "}":
            flush()
            depth = max(0, depth - 1)
            out.append(unit * depth + "}")
        elif ch == ";" and paren == 0:
            flush()
        else:
            cur += ch
        i += 1
    flush()
    res = []
    for l in out:                                         # a blank line between top-level rules reads better
        res.append(l)
        if l.strip() == "}" and not l.startswith((" ", "\t")):
            res.append("")
    return "\n".join(res).rstrip("\n") + "\n"


# ---- SQL ---------------------------------------------------------------------------------------------------------------------------
_SQL_KW = ("select", "from", "where", "group by", "order by", "having", "limit", "offset", "union all", "union", "insert into",
           "values", "update", "set", "delete from", "left join", "right join", "inner join", "full join", "cross join", "join",
           "on", "and", "or", "as", "in", "not", "null", "is", "like", "between", "case", "when", "then", "else", "end", "distinct",
           "create table", "alter table", "drop table", "primary key", "foreign key", "references", "asc", "desc", "with", "exists")
_SQL_BREAK = ("select", "from", "where", "group by", "order by", "having", "limit", "union all", "union", "insert into", "values",
              "update", "set", "delete from", "left join", "right join", "inner join", "full join", "cross join", "join")


def format_sql(text, indent=4, tabs=False):
    def split_strings(sql):
        return re.split(r"('(?:[^']|'')*'|\"[^\"]*\"|--[^\n]*|/\*.*?\*/)", sql, flags=re.S)
    parts = split_strings(text)
    for k in range(0, len(parts), 2):                     # outside strings and comments only
        seg = re.sub(r"\s+", " ", parts[k])
        for kw in sorted(_SQL_KW, key=len, reverse=True):
            seg = re.sub(rf"(?<![\w.]){kw}(?![\w.])", kw.upper(), seg, flags=re.I)
        brk = "|".join(sorted((k.upper() for k in _SQL_BREAK), key=len, reverse=True))
        seg = re.sub(rf"\s*(?<![\w.])({brk})(?![\w.])", lambda m: "\n" + m.group(1), seg)
        parts[k] = seg
    sql = "".join(parts).strip()
    unit = _unit(indent, tabs)
    lines = [l.strip() for l in sql.split("\n") if l.strip()]
    out = []
    for l in lines:
        up = l.upper()
        out.append(l if up.startswith(("SELECT", "FROM", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "UNION", "INSERT", "VALUES",
                                       "UPDATE", "SET", "DELETE", "CREATE", "ALTER", "DROP", "WITH", "--", "/*")) else unit + l)
    return "\n".join(out) + "\n"


# ---- Python / everything else ---------------------------------------------------------------------------------------------------------
def check_python(text):
    try:
        ast.parse(text)
    except SyntaxError as e:
        raise FormatError(f"Python syntax error: {e.msg}", e.lineno, (e.offset or 1)) from None


def format_python(text, indent=4, tabs=False):
    check_python(text)
    try:                                                    # the real formatter when it is installed
        import black
        return black.format_str(text, mode=black.Mode())
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        pass
    lines = [l.rstrip() for l in text.expandtabs(4).split("\n")]
    out, blank = [], 0
    for l in lines:
        blank = blank + 1 if not l else 0
        if blank <= 2:
            out.append(l)
    return "\n".join(out).strip("\n") + "\n"


# ---- entry points ---------------------------------------------------------------------------------------------------------------------------
def can_format(lang_name):
    return lang_name in ("JSON", "XML", "HTML / XML", "HTML", "CSS", "SQL", "Python", "YAML", "Markdown", "Plain text") or lang_name in BRACE_LANGS


def format_text(lang_name, text, indent=4, tabs=False):
    """The formatted text for a document of the given language. Raises FormatError (with line / column) when the text is invalid."""
    if lang_name == "JSON":
        return format_json(text, indent, tabs)
    if lang_name in ("XML",):
        return format_xml(text, indent, tabs)
    if lang_name in ("HTML / XML", "HTML"):
        stripped = text.lstrip()
        return format_xml(text, indent, tabs) if stripped.startswith("<?xml") else format_html(text, indent, tabs)
    if lang_name == "CSS":
        return format_css(text, indent, tabs)
    if lang_name == "SQL":
        return format_sql(text, indent, tabs)
    if lang_name == "Python":
        return format_python(text, indent, tabs)
    if lang_name in BRACE_LANGS:
        return reindent_braces(text, indent, tabs)
    return _tidy(text)


def validate_text(lang_name, text):
    """Returns None when the document is valid, or raises FormatError with the position of the first problem."""
    if lang_name == "JSON":
        format_json(text)
    elif lang_name in ("XML", "HTML / XML") and text.lstrip().startswith("<?xml"):
        format_xml(text)
    elif lang_name == "Python":
        check_python(text)
    elif lang_name in BRACE_LANGS or lang_name in ("CSS", "SQL"):
        problem = check_brackets(text)
        if problem:
            raise FormatError(*problem)
    else:
        raise FormatError(f"No checker for {lang_name} documents.")
    return None


def check_brackets(text):
    """(message, line, col) of the first unmatched bracket outside strings and comments, or None."""
    stack = []
    pairs = {")": "(", "]": "[", "}": "{"}
    line, col, i, n = 1, 0, 0, len(text)
    while i < n:
        ch = text[i]
        col += 1
        if ch == "\n":
            line, col = line + 1, 0
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            seg = text[i:j]
            line += seg.count("\n")
            col = len(seg) - seg.rfind("\n") - 1 if "\n" in seg else col + len(seg)
            i = j
            continue
        elif ch in "\"'`":
            j = i + 1
            while j < n and text[j] != ch and (text[j] != "\n" or ch == "`"):
                j += 2 if text[j] == "\\" else 1
            seg = text[i:j + 1]
            line += seg.count("\n")
            i = j + 1
            col += len(seg) - 1
            continue
        elif ch in "([{":
            stack.append((ch, line, col))
        elif ch in ")]}":
            if not stack or stack[-1][0] != pairs[ch]:
                return (f"Unmatched '{ch}'", line, col)
            stack.pop()
        i += 1
    if stack:
        ch, l, c = stack[-1]
        return (f"'{ch}' is never closed", l, c)
    return None
