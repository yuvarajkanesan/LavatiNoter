"""Run the current file: which command to use for each language."""
import os
import shutil
import sys

# {file} is the (quoted) path of the script. Everything runs through the system shell, in the file's folder.
DEFAULTS = {
    "Python": 'python "{file}"',
    "JavaScript": 'node "{file}"',
    "TypeScript": 'npx --yes tsx "{file}"',
    "PowerShell / Shell": None,                 # chosen by extension below
    "Batch": '"{file}"',
    "Ruby": 'ruby "{file}"',
    "PHP": 'php "{file}"',
    "Lua": 'lua "{file}"',
    "Perl": 'perl "{file}"',
    "R": 'Rscript "{file}"',
    "Go": 'go run "{file}"',
    "Java": 'java "{file}"',
    "Dart": 'dart run "{file}"',
    "Groovy / Gradle": 'groovy "{file}"',
    "Kotlin": 'kotlin "{file}"',
    "Makefile": None,
}


def command_for(lang_name, path, overrides=None):
    """The shell command that runs `path`, or None when the language has no runner."""
    table = dict(DEFAULTS)
    table.update(overrides or {})
    tpl = table.get(lang_name)
    ext = os.path.splitext(path)[1].lower()
    if lang_name == "PowerShell / Shell" and tpl is None:
        if ext == ".ps1":
            tpl = 'powershell -NoProfile -ExecutionPolicy Bypass -File "{file}"'
        elif ext in (".sh", ".bash", ".zsh"):
            tpl = 'bash "{file}"'
    if lang_name == "Python" and "python" in (tpl or "") and not shutil.which("python") and shutil.which("py"):
        tpl = tpl.replace("python", "py -3", 1)
    if not tpl:
        return None
    return tpl.replace("{file}", path)


def shell_args(command):
    """(program, args, native command line) that run `command` through the platform shell. On Windows the command line is
    passed as-is, because Qt would otherwise escape the quotes around paths."""
    if sys.platform == "win32":
        return "cmd.exe", [], f'/d /s /c "{command}"'
    return "/bin/sh", ["-c", command], ""


def parse_overrides(text):
    """'Python = py -3 "{file}"' lines -> {lang: template}."""
    out = {}
    for line in text.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out
