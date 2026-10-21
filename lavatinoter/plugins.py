"""Plugin system: small Python files in %APPDATA%\\LavatiNoter\\plugins that add commands to the Plugins menu.

A plugin is any ``*.py`` file with a ``register(api)`` function (optional NAME / VERSION / DESCRIPTION constants):

    NAME = "Word count"
    def register(api):
        api.add_command("Count words", lambda: api.flash(str(len(api.text().split()))), shortcut="Ctrl+Alt+W")
        api.on("save", lambda path: api.log("saved " + path))

Plugins run with the same rights as the editor, so they are off until the user turns them on (Plugins > Enable Plugins)."""
import importlib.util
import os
import shutil
import traceback

from . import VERSION, util


def plugins_dir():
    d = os.path.join(util.data_dir(), "plugins")
    os.makedirs(d, exist_ok=True)
    return d


def builtin_dir():
    """The plugins that come with the program (always on: they ship with it and are part of what you installed)."""
    return util.resource("builtin_plugins")


def ensure_user_folder():
    """Creates the folder for your own plugins on first use, with a short README and a template."""
    d = plugins_dir()
    readme = os.path.join(d, "README.txt")
    if not os.path.exists(readme):
        with open(readme, "w", encoding="utf-8") as f:
            f.write("Put your own plugins here (.py files with a register(api) function) and turn them on with Plugins > Enable My Plugins.\n"
                    "Plugins > Install Sample Plugins copies a commented template.\nThe tools that come with LavatiNoter need no setup: "
                    "they are in the Plugins menu under 'Built-in'.\n")
    return d


def install_samples():
    """Copies the bundled example plugins into the plugins folder (never overwriting). -> names copied."""
    src = util.resource("sample_plugins")
    copied = []
    if os.path.isdir(src):
        for name in sorted(os.listdir(src)):
            if name.endswith(".py") and not os.path.exists(os.path.join(plugins_dir(), name)):
                shutil.copy2(os.path.join(src, name), os.path.join(plugins_dir(), name))
                copied.append(name)
    return copied


class PluginAPI:
    """What a plugin may use. Everything goes through the window, so plugins never touch Qt objects directly by accident."""
    app_version = VERSION

    def __init__(self, manager, plugin):
        self._m, self._p = manager, plugin

    # commands and events
    # helpers for small tools
    def transform(self, fn):
        """Replaces the selection (the whole document when nothing is selected) with fn(text), as one undo step."""
        ed = self._ed()
        if ed is not None and not ed.isReadOnly() and not self._m.win.current().is_large:
            ed.transform_all_or_selection(fn)

    def ask(self, prompt, default=""):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self._m.win, self._p["name"], prompt, text=default)
        return text if ok else None

    def show(self, title, text):
        from PySide6.QtWidgets import QDialog, QPlainTextEdit, QPushButton, QVBoxLayout
        d = QDialog(self._m.win)
        d.setWindowTitle(title)
        d.resize(560, 380)
        lay = QVBoxLayout(d)
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        lay.addWidget(box)
        b = QPushButton("Close")
        b.clicked.connect(d.accept)
        lay.addWidget(b)
        d.exec()

    def copy(self, text):
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(text)

    def add_command(self, title, fn, shortcut=None):
        self._p["commands"].append((title, fn, shortcut))

    def on(self, event, fn):
        """event: "open", "save" or "close"; fn(path_or_title)."""
        self._m.handlers.setdefault(event, []).append((self._p["name"], fn))

    # documents
    def _ed(self):
        return self._m.win.editor_of(self._m.win.current())

    def text(self):
        ed = self._ed()
        return ed.toPlainText() if ed is not None and not self._m.win.current().is_large else ""

    def set_text(self, text):
        ed = self._ed()
        if ed is not None and not ed.isReadOnly():
            ed.replace_document_text(text)

    def selection(self):
        ed = self._ed()
        return ed.textCursor().selectedText().replace(" ", "\n") if ed is not None else ""

    def replace_selection(self, text):
        ed = self._ed()
        if ed is not None and not ed.isReadOnly():
            ed.textCursor().insertText(text)

    def insert(self, text):
        self.replace_selection(text)

    def path(self):
        page = self._m.win.current()
        return page.path if page is not None else None

    def language(self):
        ed = self._ed()
        return ed.lang.name if ed is not None else ""

    def line(self):
        ed = self._ed()
        return ed.textCursor().blockNumber() + 1 if ed is not None else 0

    def new_document(self, text="", title=None):
        self._m.win.new_file(text, title)

    def open_file(self, path):
        self._m.win.open_path(path)

    # feedback
    def flash(self, message):
        self._m.win.flash(str(message))

    def log(self, message):
        self._m.win.results.log(f"[{self._p['name']}] {message}")


class PluginManager:
    def __init__(self, win):
        self.win = win
        self.plugins = []
        self.handlers = {}

    def load_all(self, include_user=True):
        """Loads the built-in plugins always, and the ones in your plugins folder when `include_user` is on."""
        self.plugins, self.handlers = [], {}
        sources = [(builtin_dir(), True)]
        if include_user:
            sources.append((ensure_user_folder(), False))
        for folder, builtin in sources:
            self._load_folder(folder, builtin)
        return self.plugins

    def _load_folder(self, folder, builtin):
        if not os.path.isdir(folder):
            return
        for fname in sorted(os.listdir(folder)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            path = os.path.join(folder, fname)
            plugin = {"file": fname, "name": os.path.splitext(fname)[0], "commands": [], "error": None, "description": "", "version": "",
                      "builtin": builtin}
            try:
                spec = importlib.util.spec_from_file_location(f"lavatinoter_plugin_{'b' if builtin else 'u'}_{plugin['name']}", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                plugin["name"] = getattr(mod, "NAME", plugin["name"])
                plugin["description"] = getattr(mod, "DESCRIPTION", "")
                plugin["version"] = str(getattr(mod, "VERSION", ""))
                if not hasattr(mod, "register"):
                    raise AttributeError("the file has no register(api) function")
                mod.register(PluginAPI(self, plugin))
            except Exception:  # noqa: BLE001 - a broken plugin must never take the editor down
                plugin["error"] = traceback.format_exc()
                self.win.results.log(f"Plugin {fname} failed to load:\n{plugin['error']}")
            self.plugins.append(plugin)

    def run(self, plugin_name, title, fn):
        try:
            fn()
        except Exception:  # noqa: BLE001
            self.win.results.log(f"Plugin {plugin_name} - {title} failed:\n{traceback.format_exc()}")
            self.win.flash(f"Plugin {plugin_name} failed: see the Console")

    def emit(self, event, arg):
        for name, fn in self.handlers.get(event, []):
            try:
                fn(arg)
            except Exception:  # noqa: BLE001
                self.win.results.log(f"Plugin {name} ({event}) failed:\n{traceback.format_exc()}")
