"""The file types offered by the Save As dialog, and how a typed name gets its extension."""
import os

# (label shown in the dialog, extensions - the first one is added to a name typed without one)
FILE_TYPES = [
    ("Text files", [".txt"]),
    ("Markdown", [".md", ".markdown"]),
    ("Python", [".py", ".pyw"]),
    ("JavaScript", [".js", ".mjs", ".cjs"]),
    ("TypeScript", [".ts", ".tsx"]),
    ("JSON", [".json"]),
    ("HTML", [".html", ".htm"]),
    ("XML", [".xml"]),
    ("CSS", [".css"]),
    ("YAML", [".yaml", ".yml"]),
    ("SQL", [".sql"]),
    ("C / C++", [".c", ".cpp", ".h", ".hpp"]),
    ("C#", [".cs"]),
    ("Java", [".java"]),
    ("Go", [".go"]),
    ("Rust", [".rs"]),
    ("PHP", [".php"]),
    ("Ruby", [".rb"]),
    ("Shell script", [".sh"]),
    ("PowerShell", [".ps1"]),
    ("Batch file", [".bat", ".cmd"]),
    ("INI / config", [".ini", ".cfg", ".conf"]),
    ("CSV", [".csv"]),
    ("Log files", [".log"]),
]
ALL_FILES = "All files (*.*)"
# the language of a document -> the file type to preselect
LANG_TO_TYPE = {"Plain text": "Text files", "Markdown": "Markdown", "Python": "Python", "JavaScript": "JavaScript", "TypeScript": "TypeScript",
                "JSON": "JSON", "HTML / XML": "HTML", "CSS": "CSS", "YAML": "YAML", "SQL": "SQL", "C / C++": "C / C++", "C#": "C#",
                "Java": "Java", "Go": "Go", "Rust": "Rust", "PHP": "PHP", "Ruby": "Ruby", "PowerShell / Shell": "Shell script",
                "Batch": "Batch file", "INI / TOML / Properties": "INI / config", "Log": "Log files"}


def label(name, exts):
    return f"{name} ({' '.join('*' + e for e in exts)})"


def filter_list():
    """The name filters for a QFileDialog, text first and 'All files' last."""
    return [label(n, e) for n, e in FILE_TYPES] + [ALL_FILES]


def filter_for_ext(ext):
    ext = (ext or "").lower()
    for n, exts in FILE_TYPES:
        if ext in exts:
            return label(n, exts)
    return ALL_FILES


def filter_for_path(path):
    return filter_for_ext(os.path.splitext(path)[1])


def filter_for_lang(lang_name):
    name = LANG_TO_TYPE.get(lang_name)
    for n, exts in FILE_TYPES:
        if n == name:
            return label(n, exts)
    return label(*FILE_TYPES[0])


def ext_of_filter(filter_label):
    """'Python (*.py *.pyw)' -> '.py'; 'All files (*.*)' -> ''."""
    for n, exts in FILE_TYPES:
        if label(n, exts) == filter_label:
            return exts[0]
    return ""


def with_extension(path, filter_label, fallback=".txt"):
    """Adds the extension of the chosen file type to a name typed without one. A name that has an extension is left as typed,
    so typing `notes.py` while 'Text files' is selected saves `notes.py`."""
    base = os.path.basename(path)
    if os.path.splitext(base)[1] or base.endswith("."):
        return path
    return path + (ext_of_filter(filter_label) or fallback)
