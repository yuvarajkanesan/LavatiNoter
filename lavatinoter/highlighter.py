"""Language definitions and a regex based syntax highlighter."""
import os
import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

from . import theme
from .spell import WORD, speller

MAX_HIGHLIGHT_CHARS = 3_000_000       # above this a document is shown without colours (keeps typing fast)


def words(s):
    return r"\b(?:" + "|".join(s.split()) + r")\b"


STR_DQ = r'"(?:[^"\\\n]|\\.)*"?'
STR_SQ = r"'(?:[^'\\\n]|\\.)*'?"
NUM = r"\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?)\b"


class Lang:
    def __init__(self, name, exts=(), names=(), rules=(), multi=(), comment=None, funcs=None, icase=False):
        self.name = name
        self.exts = tuple(exts)
        self.names = tuple(names)
        self.rules = list(rules)            # (regex, format key)
        self.multi = list(multi)            # (start regex, end regex, format key)
        self.comment = comment              # line comment prefix, used by Toggle Comment
        self.funcs = re.compile(funcs, re.M) if funcs else None   # group 1 = name shown in the function list
        self.icase = icase
        self._combined = None

    def combined(self):
        if self._combined is None:
            parts = [f"(?P<r{i}>{rx})" for i, (rx, _) in enumerate(self.rules)]
            parts += [f"(?P<m{i}>{s})" for i, (s, _, _) in enumerate(self.multi)]
            self._combined = re.compile("|".join(parts), re.I if self.icase else 0) if parts else None
            self._ends = [re.compile(e, re.I if self.icase else 0) for _, e, _ in self.multi]
        return self._combined


PY_KW = ("and as assert async await break class continue def del elif else except finally for from global if import "
         "in is lambda nonlocal not or pass raise return try while with yield match case")
PY_BUILTIN = ("print len range int str float list dict set tuple bool bytes open isinstance super type object "
              "enumerate zip map filter sorted sum min max abs any all self cls")
C_KW = ("if else for while do switch case default break continue return goto sizeof typedef struct union enum "
        "class public private protected static const volatile extern inline virtual override final new delete this "
        "namespace using template typename try catch throw throws finally import package interface extends implements "
        "abstract synchronized async await yield var let function fn func def impl trait pub mod use mut match loop "
        "in of as is not and or readonly get set export from default operator unsafe fixed lock where select")
C_TYPES = ("int long short char float double void bool boolean byte unsigned signed string String i8 i16 i32 i64 u8 "
           "u16 u32 u64 usize isize f32 f64 str object decimal uint size_t number any never unknown Object Array")
LITERALS = r"\b(?:True|False|None|true|false|null|nil|undefined|NaN|Infinity|NULL|nullptr)\b"

PYTHON = Lang("Python", [".py", ".pyw", ".pyi"], [], [
    (r"#[^\n]*", "comment"),
    (r'(?i:[rbuf]{0,2})"[^"\n]*(?:\\.[^"\n]*)*"?', "string"),
    (r"(?i:[rbuf]{0,2})'[^'\n]*(?:\\.[^'\n]*)*'?", "string"),
    (r"^\s*@[\w.]+", "decorator"),
    (r"\b(?:def|class)\s+(\w+)", "keyword_func"),
    (words(PY_KW), "keyword"),
    (LITERALS, "literal"),
    (words(PY_BUILTIN), "builtin"),
    (NUM, "number"),
], [(r'(?i:[rbuf]{0,2})"""', r'"""', "string"), (r"(?i:[rbuf]{0,2})'''", r"'''", "string")],
    comment="#", funcs=r"^[ \t]*(?:async\s+)?(?:def|class)\s+(\w+)")

JS = Lang("JavaScript", [".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json5"], [], [
    (r"//[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"), (r"`(?:[^`\\]|\\.)*`?", "string"),
    (r"/(?![/*])(?:[^/\\\n\[]|\\.|\[(?:[^\]\\\n]|\\.)*\])+/[gimsuy]*(?=\s*[,;)\n.])", "string"),
    (r"\b(?:function|class|interface|type|enum)\s+(\w+)", "keyword_func"),
    (words(C_KW), "keyword"), (LITERALS, "literal"), (words(C_TYPES), "type"), (NUM, "number"),
    (r"\b[A-Za-z_$][\w$]*(?=\s*\()", "func"),
], [(r"/\*", r"\*/", "comment")], comment="//",
    funcs=r"^[ \t]*(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function\*?\s+(\w+)|class\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>)")

CLIKE = Lang("C / C++ / C# / Java", [".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".cs", ".java", ".go", ".rs", ".kt",
                                    ".swift", ".dart", ".scala", ".php", ".m", ".mm", ".groovy", ".gradle", ".proto"], [], [
    (r"//[^\n]*", "comment"), (r"^\s*#\s*\w+", "decorator"), (STR_DQ, "string"), (r"'(?:[^'\\\n]|\\.){1,4}'?", "string"),
    (r"\b(?:fn|func|def|struct|class|interface|trait|enum)\s+(\w+)", "keyword_func"),
    (words(C_KW), "keyword"), (LITERALS, "literal"), (words(C_TYPES), "type"), (NUM, "number"),
    (r"\b[A-Za-z_]\w*(?=\s*\()", "func"),
], [(r"/\*", r"\*/", "comment")], comment="//",
    funcs=r"^[ \t]*(?:(?:public|private|protected|static|final|virtual|override|async|inline|extern|const|unsafe|pub)\s+)*"
          r"(?:fn|func|function|void|int|long|bool|string|String|auto|var|double|float|[A-Z]\w*(?:<[^>]*>)?)\s+(\w+)\s*\([^;{]*\)?\s*(?:\{|\n|$)")

JSON = Lang("JSON", [".json", ".jsonc", ".geojson", ".webmanifest", ".har"], [], [
    (r'"(?:[^"\\\n]|\\.)*"(?=\s*:)', "key"), (STR_DQ, "string"), (r"//[^\n]*", "comment"),
    (r"-?\b\d+\.?\d*(?:[eE][+-]?\d+)?\b", "number"), (r"\b(?:true|false|null)\b", "literal"),
], [(r"/\*", r"\*/", "comment")], comment=None)

HTML = Lang("HTML / XML", [".html", ".htm", ".xhtml", ".xml", ".svg", ".xaml", ".csproj", ".vcxproj", ".config", ".plist",
                           ".vue", ".svelte", ".rss", ".xsd", ".xsl", ".resx", ".manifest"], [], [
    (r"<!DOCTYPE[^>]*>|<\?[^>]*\?>", "decorator"),
    (r"</?[A-Za-z][\w:.-]*", "tag"), (r"/?>", "tag"),
    (r"[\w:.-]+(?=\s*=)", "attr"), (STR_DQ, "string"), (STR_SQ, "string"), (r"&#?\w+;", "literal"),
], [(r"<!--", r"-->", "comment")], funcs=None, icase=True)

CSS = Lang("CSS", [".css", ".scss", ".sass", ".less"], [], [
    (r"//[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"),
    (r"@[\w-]+", "keyword"), (r"#[0-9a-fA-F]{3,8}\b", "number"),
    (r"-?\b\d+\.?\d*(?:px|em|rem|%|vh|vw|s|ms|deg|pt|fr)?\b", "number"),
    (r"[\w-]+(?=\s*:(?!:))", "attr"), (r"[.#][A-Za-z_][\w-]*", "tag"), (r"\$[\w-]+", "literal"),
], [(r"/\*", r"\*/", "comment")], funcs=r"^[ \t]*([.#]?[A-Za-z_][\w .#>:,+~-]*?)\s*\{")

YAML = Lang("YAML", [".yaml", ".yml"], [], [
    (r"#[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"),
    (r"^\s*-?\s*[\w./-]+(?=\s*:(?:\s|$))", "key"), (r"\b(?:true|false|null|yes|no|on|off)\b", "literal"),
    (r"[&*]\w+", "decorator"), (r"-?\b\d+\.?\d*\b", "number"), (r"^---|^\.\.\.", "decorator"),
], comment="#", funcs=r"^([A-Za-z_][\w.-]*):")

TOML = Lang("INI / TOML / Properties", [".ini", ".cfg", ".conf", ".toml", ".properties", ".env", ".editorconfig", ".gitconfig",
                                        ".inf", ".reg", ".desktop"],
            [".env", ".gitconfig", ".editorconfig"], [
    (r"^\s*[#;][^\n]*", "comment"), (r"^\s*\[[^\]\n]+\]", "keyword"), (STR_DQ, "string"), (STR_SQ, "string"),
    (r"^\s*[\w.\-@$]+(?=\s*[=:])", "key"), (r"\b(?:true|false|yes|no|on|off)\b", "literal"), (NUM, "number"),
], comment="#", funcs=r"^\s*\[([^\]\n]+)\]")

MARKDOWN = Lang("Markdown", [".md", ".markdown", ".mdx", ".rst"], [], [
    (r"^#{1,6}\s[^\n]*", "keyword"), (r"^\s*(?:[-*+]|\d+\.)\s", "decorator"), (r"!?\[[^\]\n]*\]\([^)\n]*\)", "func"),
    (r"`[^`\n]+`", "string"), (r"\*\*[^*\n]+\*\*|__[^_\n]+__", "type"), (r"^>[^\n]*", "comment"),
    (r"^(?:-{3,}|\*{3,}|_{3,})\s*$", "decorator"), (r"<[^>\n]+>", "tag"),
], [(r"^```[^\n]*", r"^```", "string")], funcs=r"^(#{1,6}\s.+)$")

SQL = Lang("SQL", [".sql", ".ddl", ".psql"], [], [
    (r"--[^\n]*", "comment"), (STR_SQ, "string"), (r'"[^"\n]*"', "key"),
    (words("select from where and or not in is null insert into values update set delete create alter drop table view "
           "index primary key foreign references join left right inner outer full cross on group by order having limit "
           "offset union all distinct as case when then else end exists between like asc desc begin commit rollback "
           "grant revoke with over partition database schema if default unique check constraint trigger procedure "
           "function returns declare exec execute top use"), "keyword"),
    (words("int integer bigint smallint varchar nvarchar char text date datetime timestamp boolean bool float double "
           "decimal numeric serial uuid json jsonb blob"), "type"), (NUM, "number"), (r"\b(?:count|sum|avg|min|max|coalesce|now|upper|lower|length)(?=\()", "func"),
], [(r"/\*", r"\*/", "comment")], comment="--", icase=True, funcs=r"(?i)^\s*create\s+(?:or\s+replace\s+)?(?:table|view|function|procedure)\s+(?:if\s+not\s+exists\s+)?([\w.\[\]\"`]+)")

BATCH = Lang("Batch", [".bat", ".cmd"], [], [
    (r"^\s*(?:rem\b|::)[^\n]*", "comment"), (STR_DQ, "string"), (r"%[\w~:*]+%?|%%\w|!\w+!", "literal"), (r"^\s*:\w+", "decorator"),
    (words("echo set if else for in do goto call exit pause cd md mkdir rd rmdir copy xcopy move del type start setlocal "
           "endlocal not exist errorlevel defined shift title cls"), "keyword"),
], comment="REM", icase=True, funcs=r"^:(\w+)")

POWERSHELL = Lang("PowerShell / Shell", [".ps1", ".psm1", ".psd1", ".sh", ".bash", ".zsh", ".fish"], [], [
    (r"#[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"), (r"\$\{?[\w:]+\}?", "literal"),
    (r"\b[A-Z][a-z]+-[A-Z]\w+\b", "func"), (r"(?<=\s)--?[A-Za-z][\w-]*", "attr"),
    (words("if then elif else elseif fi for foreach while do done case esac function return in switch break continue "
           "try catch finally param begin process end exit export local readonly echo cd source alias unset trap"), "keyword"),
    (NUM, "number"),
], [(r"<#", r"#>", "comment")], comment="#", funcs=r"^\s*(?:function\s+)?([\w-]+)\s*(?:\(\s*\))?\s*\{")

LOG = Lang("Log", [".log", ".out", ".err"], [], [
    (r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?", "comment"),
    (r"\[\d{1,2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}[^\]]*\]", "comment"),
    (r"\b(?:ERROR|FATAL|CRITICAL|SEVERE|Exception|Traceback|FAILED?|panic)\b", "error"),
    (r"\b(?:WARN(?:ING)?)\b", "warn"), (r"\b(?:INFO|NOTICE)\b", "info"), (r"\b(?:DEBUG|TRACE)\b", "comment"),
    (r'"(?:GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b', "keyword"), (r"(?<=\s)5\d\d(?=\s)", "error"), (r"(?<=\s)4\d\d(?=\s)", "warn"),
    (r"(?<=\s)[23]\d\d(?=\s)", "string"), (STR_DQ, "string"), (r"\b\d{1,3}(?:\.\d{1,3}){3}\b", "number"),
], funcs=None)

PLAIN = Lang("Plain text", [".txt", ".text", ".nfo", ".csv", ".tsv"])

LANGS = [PLAIN, PYTHON, JS, JSON, HTML, CSS, CLIKE, YAML, TOML, MARKDOWN, SQL, BATCH, POWERSHELL, LOG]
_BY_EXT = {e: l for l in LANGS for e in l.exts}
_BY_NAME = {n.lower(): l for l in LANGS for n in l.names}
_BY_NAME["makefile"] = TOML
_BY_NAME["dockerfile"] = POWERSHELL


def lang_for_path(path):
    if not path:
        return PLAIN
    base = os.path.basename(path).lower()
    if base in _BY_NAME:
        return _BY_NAME[base]
    ext = os.path.splitext(base)[1]
    return _BY_EXT.get(ext, PLAIN)


def lang_by_name(name):
    return next((l for l in LANGS if l.name == name), PLAIN)


RICH_LANGS = ("Plain text", "Markdown", "HTML / XML")
_RICH_RULES = [
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"), "bold"),
    (re.compile(r"<b>(.+?)</b>", re.I), "bold"),
    (re.compile(r"(?<![\*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\*\w])"), "italic"),
    (re.compile(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])"), "italic"),
    (re.compile(r"<i>(.+?)</i>", re.I), "italic"),
    (re.compile(r"<u>(.+?)</u>", re.I), "underline"),
    (re.compile(r"(<span style=\"font-size:\s*(\d+)px\">)(.+?)(</span>)", re.I), "size"),
]


class Highlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.lang = PLAIN
        self.spell_on = False
        self.fmts = {}
        self.rebuild_formats()

    def rebuild_formats(self):
        def f(key, bold=False, italic=False):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(theme.c(key)))
            if bold:
                fmt.setFontWeight(QFont.DemiBold)
            fmt.setFontItalic(italic)
            return fmt
        self.fmts = {
            "keyword": f("SYN_KEYWORD"), "string": f("SYN_STRING"), "number": f("SYN_NUMBER"),
            "comment": f("SYN_COMMENT", italic=True), "func": f("SYN_FUNC"), "keyword_func": f("SYN_FUNC"),
            "decorator": f("SYN_DECOR"), "builtin": f("SYN_BUILTIN"), "type": f("SYN_TYPE"), "tag": f("SYN_TAG"),
            "attr": f("SYN_ATTR"), "key": f("SYN_KEY"), "literal": f("SYN_LITERAL"), "error": f("SYN_ERROR", bold=True),
            "warn": f("SYN_WARN", bold=True), "info": f("SYN_INFO"),
        }
        self.rehighlight()

    def set_lang(self, lang):
        self.lang = lang
        self.rehighlight()

    def highlightBlock(self, text):
        self._syntax(text)
        if self.lang.name in RICH_LANGS and text:
            self._rich(text)
        if self.spell_on and text and self.document().characterCount() < 1_000_000:
            self._spell(text)

    def _rich(self, text):
        """Shows **bold**, *italic*, <u>underline</u> and <span style="font-size:20px">size</span> as formatted text
        (the marks stay in the file, dimmed, so any Markdown viewer renders the same)."""
        if "*" not in text and "<" not in text and "_" not in text:
            return
        dim = QColor(theme.c("FAINT"))
        for rx, kind in _RICH_RULES:
            for m in rx.finditer(text):
                a, b = m.span(1)
                fmt = self.format(a)
                if kind == "bold":
                    fmt.setFontWeight(QFont.Bold)
                elif kind == "italic":
                    fmt.setFontItalic(True)
                elif kind == "underline":
                    fmt.setFontUnderline(True)
                elif kind == "size":
                    px = int(m.group(2))
                    fmt.setFontPointSize(max(6.0, min(80.0, px * 0.75)))
                    a, b = m.span(3)
                self.setFormat(a, b - a, fmt) if kind != "size" else self.setFormat(a, b - a, fmt)
                for ms, me in ((m.start(), a), (b, m.end())):
                    mark = self.format(ms)
                    mark.setForeground(dim)
                    mark.setFontWeight(QFont.Normal)
                    mark.setFontItalic(False)
                    mark.setFontUnderline(False)
                    mark.setFontPointSize(max(6.0, self.document().defaultFont().pointSizeF() * 0.8))
                    self.setFormat(ms, me - ms, mark)

    def _spell(self, text):
        """Red squiggle under misspelled words: everywhere in plain text / Markdown, only in comments and strings in code."""
        prose = self.lang.name in ("Plain text", "Markdown")
        if not prose and self.lang.name in ("Log", "JSON"):
            return
        ok_colors = {self.fmts["comment"].foreground().color().name(), self.fmts["string"].foreground().color().name()}
        for m in WORD.finditer(text):
            if not speller.is_wrong(m.group()):
                continue
            fmt = self.format(m.start())
            col = fmt.foreground().color().name() if fmt.foreground().style() else ""
            if prose and self.lang.name == "Markdown" and col in ok_colors:
                continue                            # code spans, links and URLs
            if not prose and col not in ok_colors:
                continue
            fmt.setUnderlineStyle(QTextCharFormat.SpellCheckUnderline)
            fmt.setUnderlineColor(QColor(theme.c("RED")))
            self.setFormat(m.start(), len(m.group()), fmt)

    def _syntax(self, text):
        lang = self.lang
        rx = lang.combined()
        if rx is None or self.document().characterCount() > MAX_HIGHLIGHT_CHARS:
            self.setCurrentBlockState(-1)
            return
        state = self.previousBlockState()
        pos = 0
        n = len(text)
        if state >= 0 and state < len(lang.multi):
            m = lang._ends[state].search(text)
            fmt = self.fmts[lang.multi[state][2]]
            if not m:
                self.setFormat(0, n, fmt)
                self.setCurrentBlockState(state)
                return
            self.setFormat(0, m.end(), fmt)
            pos = m.end()
        while pos < n:
            m = rx.search(text, pos)
            if not m:
                break
            kind = m.lastgroup
            if kind.startswith("m"):
                i = int(kind[1:])
                fmt = self.fmts[lang.multi[i][2]]
                e = lang._ends[i].search(text, m.end())
                if not e:
                    self.setFormat(m.start(), n - m.start(), fmt)
                    self.setCurrentBlockState(i)
                    return
                self.setFormat(m.start(), e.end() - m.start(), fmt)
                pos = e.end()
                continue
            key = lang.rules[int(kind[1:])][1]
            if key == "keyword_func":
                # colour the keyword and the name it defines differently
                inner = m.lastindex + 1            # the rule's own (name) group follows its wrapper group
                has_name = inner <= m.re.groups and m.start(inner) >= 0
                kw_end = m.start(inner) if has_name else m.end()
                self.setFormat(m.start(), kw_end - m.start(), self.fmts["keyword"])
                if has_name:
                    self.setFormat(m.start(inner), m.end(inner) - m.start(inner), self.fmts["func"])
            else:
                self.setFormat(m.start(), m.end() - m.start(), self.fmts[key])
            pos = m.end() if m.end() > m.start() else m.start() + 1
        self.setCurrentBlockState(-1)
