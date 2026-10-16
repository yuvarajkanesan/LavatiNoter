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
        self._completions = None

    def completions(self):
        """Keywords and built-in names of this language, taken from its keyword rules (for the suggestion list)."""
        if self._completions is None:
            found = set()
            for rx, _kind in self.rules:
                for grp in re.findall(r"\b\(\?:([^)]*)\)\\b", rx):
                    found.update(w for w in grp.split("|") if w.isidentifier() and len(w) > 2)
            self._completions = found
        return self._completions

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

JS = Lang("JavaScript", [".js", ".jsx", ".mjs", ".cjs", ".json5"], [], [
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

def _clike(name, exts, kw, types="", funcs=None, names=(), extra=(), hash_comment=False, multi=None):
    """A brace language: // and /* */ comments, "strings", numbers, keywords, types and calls."""
    rules = [((r"#[^\n]*" if hash_comment else r"//[^\n]*"), "comment")] + list(extra) + [
        (STR_DQ, "string"), (r"'(?:[^'\\\n]|\\.){1,4}'?", "string"),
        (r"\b(?:fn|func|fun|def|function|struct|class|interface|trait|enum|object|protocol|impl)\s+(\w+)", "keyword_func"),
        (words(kw), "keyword"), (LITERALS, "literal")]
    if types:
        rules.append((words(types), "type"))
    rules += [(NUM, "number"), (r"\b[A-Za-z_]\w*(?=\s*\()", "func")]
    return Lang(name, exts, names, rules, multi if multi is not None else [(r"/\*", r"\*/", "comment")],
                comment="#" if hash_comment else "//", funcs=funcs)


JAVA_FUNCS = (r"^[ \t]*(?:(?:public|private|protected|static|final|abstract|synchronized|native|override|async|internal|virtual|sealed)\s+)*"
              r"[\w<>\[\],.?]+\s+(\w+)\s*\([^;{)]*\)?\s*(?:throws\s+[\w, .]+)?\s*(?:\{|$)")

TYPESCRIPT = Lang("TypeScript", [".ts", ".tsx", ".mts", ".cts"], [], JS.rules, JS.multi, comment="//", funcs=JS.funcs.pattern)
JAVA = _clike("Java", [".java"],
              "abstract assert break case catch class const continue default do else enum extends final finally for goto if implements "
              "import instanceof interface native new package private protected public return static strictfp super switch synchronized "
              "this throw throws transient try volatile while var record sealed permits yield",
              "int long short char float double void boolean byte String Object List Map Set Integer Long Double Boolean",
              JAVA_FUNCS, extra=[(r"@\w+", "decorator")])
CSHARP = _clike("C#", [".cs", ".csx"],
                "abstract as base break case catch checked class const continue default delegate do else enum event explicit extern "
                "finally fixed for foreach goto if implicit in interface internal is lock namespace new operator out override params "
                "private protected public readonly ref return sealed sizeof stackalloc static struct switch this throw try typeof "
                "unchecked unsafe using virtual volatile while async await var record init get set yield where partial",
                "int long short char float double decimal bool byte sbyte uint ulong ushort string object void dynamic Task List Dictionary",
                JAVA_FUNCS, extra=[(r'@"(?:[^"]|"")*"', "string"), (r"^\s*#\s*\w+", "decorator"), (r"\[\w+(?:\([^)]*\))?\]", "decorator")])
CPP = _clike("C / C++", [".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".ino"],
             "auto break case catch class const constexpr continue default delete do else enum explicit extern final for friend goto if "
             "inline namespace new noexcept nullptr operator override private protected public register return sizeof static struct "
             "switch template this throw try typedef typename union using virtual volatile while concept requires co_await co_return",
             "int long short char float double void bool signed unsigned size_t wchar_t uint8_t uint16_t uint32_t uint64_t int8_t "
             "int16_t int32_t int64_t string vector map set",
             r"^[ \t]*(?:(?:static|inline|virtual|extern|const|constexpr)\s+)*[\w:<>,*&\s]+?[\s*&]+(\w+)\s*\([^;{)]*\)?\s*(?:const\s*)?(?:\{|$)",
             extra=[(r"^\s*#\s*\w+", "decorator"), (r"<[\w./]+\.h>|<\w+>", "string")])
GO = _clike("Go", [".go"],
            "break case chan const continue default defer else fallthrough for func go goto if import interface map package range "
            "return select struct switch type var",
            "int int8 int16 int32 int64 uint uint8 uint16 uint32 uint64 uintptr float32 float64 complex64 complex128 string bool byte "
            "rune error any",
            r"^func\s+(?:\([^)]*\)\s*)?(\w+)", extra=[(r"`[^`]*`", "string")], multi=[(r"/\*", r"\*/", "comment"), (r"`", r"`", "string")])
RUST = _clike("Rust", [".rs"],
              "as async await break const continue crate dyn else enum extern fn for if impl in let loop match mod move mut pub ref "
              "return self static struct super trait type unsafe use where while macro_rules union",
              "i8 i16 i32 i64 i128 isize u8 u16 u32 u64 u128 usize f32 f64 bool char str String Vec Option Result Box Self",
              r"^[ \t]*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?(?:fn|struct|enum|trait|impl|mod)\s+(\w+)",
              extra=[(r"#!?\[[^\]]*\]", "decorator"), (r"'[a-z_]\w*(?!')", "attr"), (r"\b\w+!", "func")])
KOTLIN = _clike("Kotlin", [".kt", ".kts"],
                "abstract annotation as break by catch class companion const constructor continue crossinline data do else enum "
                "expect external final finally for fun get if import in infix init inline inner interface internal is lateinit noinline "
                "object open operator out override package private protected public reified return sealed set super suspend this throw "
                "try typealias val var vararg when where while",
                "Int Long Short Byte Float Double Boolean Char String Unit Any Nothing List Map Set Array",
                r"^[ \t]*(?:(?:public|private|protected|internal|override|open|suspend|inline|operator|abstract)\s+)*fun\s+(?:<[^>]*>\s*)?(?:[\w.]+\.)?(\w+)",
                extra=[(r"@\w+", "decorator")])
SWIFT = _clike("Swift", [".swift"],
               "actor associatedtype async await break case catch class continue default defer deinit do else enum extension fallthrough "
               "fileprivate final for func get guard if import in indirect init inout internal is lazy let mutating nonmutating open "
               "operator override private protocol public repeat required rethrows return self Self set some static struct subscript "
               "super switch throw throws try typealias var weak where while",
               "Int Int8 Int16 Int32 Int64 UInt Float Double Bool String Character Array Dictionary Set Optional Any AnyObject Void",
               r"^[ \t]*(?:(?:public|private|fileprivate|internal|open|static|final|override|mutating|class)\s+)*func\s+(\w+)",
               extra=[(r"@\w+", "decorator")])
DART = _clike("Dart", [".dart"],
              "abstract as assert async await break case catch class const continue covariant default deferred do dynamic else enum "
              "export extends extension external factory final finally for get hide if implements import in interface is late library "
              "mixin new on operator part required rethrow return set show static super switch sync this throw try typedef var while with yield",
              "int double num bool String List Map Set void Future Stream Object", JAVA_FUNCS, extra=[(r"@\w+", "decorator")])
SCALA = _clike("Scala", [".scala", ".sbt", ".sc"],
               "abstract case catch class def do else extends false final finally for forSome if implicit import lazy match new null "
               "object override package private protected return sealed super this throw trait try true type val var while with yield given using enum",
               "Int Long Short Byte Float Double Boolean Char String Unit Any AnyRef Nothing List Map Set Option Seq",
               r"^[ \t]*(?:(?:override|private|protected|final|implicit|lazy)\s+)*(?:def|class|object|trait)\s+(\w+)", extra=[(r"@\w+", "decorator")])
PHP = _clike("PHP", [".php", ".phtml", ".php5", ".inc"],
             "abstract and as break callable case catch class clone const continue declare default do echo else elseif empty enddeclare "
             "endfor endforeach endif endswitch endwhile enum extends final finally fn for foreach function global goto if implements "
             "include include_once instanceof insteadof interface isset list match namespace new or print private protected public readonly "
             "require require_once return static switch throw trait try unset use var while xor yield",
             "int float string bool array object callable iterable mixed void never",
             r"^[ \t]*(?:(?:public|private|protected|static|final|abstract)\s+)*function\s+&?(\w+)|^\s*(?:abstract\s+|final\s+)?class\s+(\w+)",
             extra=[(r"<\?php|<\?=|\?>", "decorator"), (r"\$\w+", "literal"), (r"#(?!\[)[^\n]*", "comment")])
GROOVY = _clike("Groovy / Gradle", [".groovy", ".gradle", ".gvy"],
                "abstract as assert break case catch class continue def default do else enum extends final finally for if implements import "
                "in instanceof interface new package private protected public return static super switch this throw throws trait try while",
                "int long short char float double void boolean byte String Object List Map", JAVA_FUNCS, extra=[(r"@\w+", "decorator")])

RUBY = Lang("Ruby", [".rb", ".rake", ".gemspec", ".ru", ".erb"], ["rakefile", "gemfile", "guardfile"], [
    (r"#[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"), (r":[A-Za-z_]\w*[?!]?", "literal"), (r"@@?\w+", "attr"),
    (r"\b(?:def|class|module)\s+(?:self\.)?(\w+)", "keyword_func"),
    (words("alias and begin BEGIN break case class def defined do else elsif end END ensure for if in module next not or redo rescue "
           "retry return self super then undef unless until when while yield require require_relative include extend attr_accessor "
           "attr_reader attr_writer private protected public lambda proc raise"), "keyword"),
    (r"\b(?:true|false|nil)\b", "literal"), (NUM, "number"),
], [(r"^=begin\b", r"^=end\b", "comment")], comment="#", funcs=r"^[ \t]*(?:def|class|module)\s+(?:self\.)?(\w+)")
LUA = Lang("Lua", [".lua"], [], [
    (r"--(?!\[\[)[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"),
    (r"\bfunction\s+([\w.:]+)", "keyword_func"),
    (words("and break do else elseif end for function goto if in local not or repeat return then until while"), "keyword"),
    (r"\b(?:true|false|nil)\b", "literal"), (NUM, "number"), (r"\b[A-Za-z_]\w*(?=\s*\()", "func"),
], [(r"--\[\[", r"\]\]", "comment"), (r"\[\[", r"\]\]", "string")], comment="--", funcs=r"function\s+([\w.:]+)")
PERL = Lang("Perl", [".pl", ".pm", ".t"], [], [
    (r"#[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"), (r"[$@%]\w+", "literal"), (r"\bsub\s+(\w+)", "keyword_func"),
    (words("if elsif else unless while until for foreach do last next redo return sub my our local use no package require "
           "print say die warn eval defined undef and or not qw"), "keyword"), (NUM, "number"),
], comment="#", funcs=r"^\s*sub\s+(\w+)")
RLANG = Lang("R", [".r", ".R", ".rmd"], [], [
    (r"#[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"),
    (words("if else for while repeat break next return function library require in"), "keyword"),
    (r"\b(?:TRUE|FALSE|NULL|NA|NaN|Inf)\b", "literal"), (NUM, "number"), (r"[A-Za-z_.][\w.]*(?=\()", "func"),
], comment="#", funcs=r"^\s*([A-Za-z_.][\w.]*)\s*(?:<-|=)\s*function")
DOCKER = Lang("Dockerfile", [".dockerfile"], ["dockerfile", "containerfile"], [
    (r"^\s*#[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"), (r"\$\{?\w+\}?", "literal"),
    (words("FROM RUN CMD LABEL MAINTAINER EXPOSE ENV ADD COPY ENTRYPOINT VOLUME USER WORKDIR ARG ONBUILD STOPSIGNAL HEALTHCHECK SHELL AS"), "keyword"),
    (NUM, "number"),
], comment="#", icase=True, funcs=r"(?i)^\s*FROM\s+(\S+)")
MAKE = Lang("Makefile", [".mk", ".mak"], ["makefile", "gnumakefile"], [
    (r"#[^\n]*", "comment"), (STR_DQ, "string"), (STR_SQ, "string"), (r"\$[({]\w+[)}]|\$[@<^?*%]", "literal"),
    (r"^[\w.%/ -]+(?=\s*:(?!=))", "func"), (r"^\s*(?:include|ifeq|ifneq|ifdef|ifndef|else|endif|define|endef|export|override)\b", "keyword"),
], comment="#", funcs=r"^([\w.%/-]+)\s*:(?!=)")
DIFF = Lang("Diff / Patch", [".diff", ".patch"], [], [
    (r"^(?:diff|index|---|\+\+\+)[^\n]*", "keyword"), (r"^@@[^\n]*", "decorator"), (r"^\+[^\n]*", "string"), (r"^-[^\n]*", "error"),
])

CLIKE.exts = (".m", ".mm", ".proto")                 # the specific languages above own all other extensions
CLIKE.name = "C-family (other)"

LANGS = [PLAIN, PYTHON, JS, TYPESCRIPT, JSON, HTML, CSS, CPP, CSHARP, JAVA, GO, RUST, KOTLIN, SWIFT, DART, SCALA, PHP, GROOVY, RUBY, LUA, PERL, RLANG, CLIKE, YAML, TOML, MARKDOWN, SQL, BATCH, POWERSHELL, DOCKER, MAKE, DIFF, LOG]
_BY_EXT = {e: l for l in LANGS for e in l.exts}
_BY_NAME = {n.lower(): l for l in LANGS for n in l.names}


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
SHOW_MARKS = False                          # View > Show Formatting Marks
_RICH_RULES = [
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*"), "bold"),
    (re.compile(r"<b>(.+?)</b>", re.I), "bold"),
    (re.compile(r"(?<![\*\w])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\*\w])"), "italic"),
    (re.compile(r"(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])"), "italic"),
    (re.compile(r"<i>(.+?)</i>", re.I), "italic"),
    (re.compile(r"<u>(.+?)</u>", re.I), "underline"),
    (re.compile(r"(<span style=\"font-size:\s*(\d+)px\">)(.+?)(</span>)", re.I), "size"),
]


def rich_matches(text):
    """[(kind, match, inner start, inner end)] for every formatting mark pair in a line."""
    if "*" not in text and "<" not in text and "_" not in text:
        return []
    out = []
    for rx, kind in _RICH_RULES:
        for m in rx.finditer(text):
            a, b = m.span(3) if kind == "size" else m.span(1)
            out.append((kind, m, a, b))
    return out


def mark_spans(text):
    """[(start, end)] of the formatting mark characters in a line (the opening and closing marks)."""
    spans = []
    for kind, m, a, b in rich_matches(text):
        spans += [(m.start(), a), (b, m.end())]
    return sorted(spans)


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
        """Shows **bold**, _italic_, <u>underline</u> and <span style="font-size:20px">size</span> as formatted text, in any
        combination. The marks stay in the file (so any Markdown viewer renders the same) but are hidden here, unless
        View > Show Formatting Marks is on."""
        if len(text) > 4000:
            return
        matches = rich_matches(text)
        if not matches:
            return
        marks = mark_spans(text)
        mark_chars = set()
        for a, b in marks:
            mark_chars.update(range(a, b))
        for kind, m, a, b in matches:                       # formatting of the visible text first ...
            px = int(m.group(2)) if kind == "size" else 0
            for i in range(a, b):
                if i in mark_chars:
                    continue
                fmt = self.format(i)
                if kind == "bold":
                    fmt.setFontWeight(QFont.Bold)
                elif kind == "italic":
                    fmt.setFontItalic(True)
                elif kind == "underline":
                    fmt.setFontUnderline(True)
                else:
                    fmt.setFontPointSize(max(6.0, min(80.0, px * 0.75)))
                self.setFormat(i, 1, fmt)
        hide = QColor(0, 0, 0, 0)
        for a, b in marks:                                  # ... then the marks themselves, last, so nothing inherits their look
            for i in range(a, b):
                fmt = self.format(i)
                if SHOW_MARKS:
                    fmt.setForeground(QColor(theme.c("FAINT")))
                    fmt.setFontWeight(QFont.Normal)
                    fmt.setFontItalic(False)
                    fmt.setFontUnderline(False)
                else:
                    fmt.setForeground(hide)
                    fmt.setFontPointSize(0.1)
                    fmt.setFontUnderline(False)
                    fmt.setFontWeight(QFont.Normal)
                    fmt.setFontItalic(False)
                self.setFormat(i, 1, fmt)

    def _spell(self, text):
        """Red squiggle under misspelled words: everywhere in plain text / Markdown, only in comments and strings in code."""
        prose = self.lang.name in ("Plain text", "Markdown")
        if not prose and self.lang.name in ("Log", "JSON"):
            return
        ok_colors = {self.fmts["comment"].foreground().color().name(), self.fmts["string"].foreground().color().name()}
        hidden = mark_spans(text) if self.lang.name in RICH_LANGS else []
        for m in WORD.finditer(text):
            if not speller.is_wrong(m.group()) or any(a <= m.start() < b for a, b in hidden):
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
