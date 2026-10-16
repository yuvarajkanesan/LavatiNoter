"""A small Language Server Protocol client (stdio, JSON-RPC): go to definition, hover and diagnostics from any language server
that is installed (pyright, pylsp, typescript-language-server, gopls, rust-analyzer, clangd ...). Off until enabled in Settings."""
import json
import os
import shlex
import shutil
import urllib.parse
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QProcess, QTimer, Signal

DEFAULT_SERVERS = {   # language -> candidate commands, the first whose program is on PATH is used
    "Python": [["pyright-langserver", "--stdio"], ["pylsp"], ["jedi-language-server"]],
    "TypeScript": [["typescript-language-server", "--stdio"]],
    "JavaScript": [["typescript-language-server", "--stdio"]],
    "Go": [["gopls"]],
    "Rust": [["rust-analyzer"]],
    "C / C++": [["clangd"]],
    "Java": [["jdtls"]],
    "C#": [["csharp-ls"]],
    "PHP": [["intelephense", "--stdio"]],
    "Ruby": [["solargraph", "stdio"]],
    "Lua": [["lua-language-server"]],
    "Kotlin": [["kotlin-language-server"]],
    "CSS": [["vscode-css-language-server", "--stdio"]],
    "JSON": [["vscode-json-language-server", "--stdio"]],
    "HTML / XML": [["vscode-html-language-server", "--stdio"]],
    "YAML": [["yaml-language-server", "--stdio"]],
}
LANGUAGE_ID = {"Python": "python", "TypeScript": "typescript", "JavaScript": "javascript", "Go": "go", "Rust": "rust", "C / C++": "cpp",
               "Java": "java", "C#": "csharp", "PHP": "php", "Ruby": "ruby", "Lua": "lua", "Kotlin": "kotlin", "CSS": "css", "JSON": "json",
               "HTML / XML": "html", "YAML": "yaml"}


def split_command(text):
    """'pyright-langserver --stdio' or '"C:\\Program Files\\x.exe" --arg' -> argv list."""
    import re
    return [a or b for a, b in re.findall(r'"([^"]*)"|(\S+)', text)]


def detect_server(lang_name, overrides=None):
    """The command to start for a language: the user's choice, else the first installed default, else None."""
    custom = (overrides or {}).get(lang_name)
    if custom:
        return split_command(custom) if isinstance(custom, str) else list(custom)
    for cmd in DEFAULT_SERVERS.get(lang_name, []):
        if shutil.which(cmd[0]):
            return cmd
    return None


def path_to_uri(path):
    return Path(path).resolve().as_uri()


def uri_to_path(uri):
    p = urllib.parse.unquote(urllib.parse.urlparse(uri).path)
    if os.name == "nt" and len(p) > 2 and p[0] == "/" and p[2] == ":":
        p = p[1:]
    return os.path.normpath(p)


def encode(msg):
    body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


class Parser:
    """Turns the byte stream from a server into messages (headers + JSON bodies)."""

    def __init__(self):
        self.buf = b""

    def feed(self, data):
        self.buf += data
        out = []
        while True:
            head_end = self.buf.find(b"\r\n\r\n")
            if head_end < 0:
                break
            length = None
            for line in self.buf[:head_end].split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1])
            if length is None:
                self.buf = self.buf[head_end + 4:]
                continue
            if len(self.buf) < head_end + 4 + length:
                break
            body = self.buf[head_end + 4:head_end + 4 + length]
            self.buf = self.buf[head_end + 4 + length:]
            try:
                out.append(json.loads(body.decode("utf-8")))
            except ValueError:
                pass
        return out


def hover_text(result):
    """Plain text from a hover response (string, MarkedString, MarkupContent or a list of them)."""
    if not result:
        return ""
    c = result.get("contents") if isinstance(result, dict) else result
    if isinstance(c, list):
        return "\n\n".join(filter(None, (hover_text({"contents": x}) for x in c)))
    if isinstance(c, dict):
        return (c.get("value") or "").strip()
    return str(c or "").strip()


class LspClient(QObject):
    ready = Signal()
    diagnostics = Signal(str, list)             # uri, [LSP diagnostic dicts]
    stopped = Signal()

    def __init__(self, command, root, lang_id, parent=None):
        super().__init__(parent)
        self.command, self.root, self.lang_id = command, root, lang_id
        self.proc = QProcess(self)
        self.parser = Parser()
        self.next_id = 1
        self.callbacks = {}
        self.pending = []            # notifications queued until the server answered `initialize`
        self.is_ready = False
        self.error = ""
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.errorOccurred.connect(lambda e: setattr(self, "error", self.proc.errorString()))
        self.proc.finished.connect(lambda *_: self.stopped.emit())

    def start(self):
        self.proc.setWorkingDirectory(self.root if self.root and os.path.isdir(self.root) else os.path.expanduser("~"))
        self.proc.start(self.command[0], self.command[1:])
        self.request("initialize", {
            "processId": os.getpid(), "rootUri": path_to_uri(self.root) if self.root else None, "clientInfo": {"name": "LavatiNoter"},
            "capabilities": {"textDocument": {"synchronization": {"didSave": False}, "hover": {"contentFormat": ["plaintext", "markdown"]},
                                              "definition": {"linkSupport": False}, "publishDiagnostics": {}}}}, self._initialized)

    def _initialized(self, result):
        self.is_ready = True
        self._write({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        for m in self.pending:
            self._write(m)
        self.pending = []
        self.ready.emit()

    def _write(self, msg):
        if self.proc.state() != QProcess.NotRunning:
            self.proc.write(encode(msg))

    def request(self, method, params, callback=None):
        i = self.next_id
        self.next_id += 1
        if callback:
            self.callbacks[i] = callback
        self._write({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        return i

    def notify(self, method, params):
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        if self.is_ready or method == "initialized":
            self._write(msg)
        else:
            self.pending.append(msg)

    def call(self, method, params, timeout_ms=1500):
        """Sends a request and waits (keeping the window alive) for the answer. -> the result, or None on timeout / error."""
        holder = {}
        loop = QEventLoop()

        def done(result):
            holder["r"] = result
            loop.quit()
        if not self.is_ready:                                   # give a starting server a moment
            wait = QEventLoop()
            self.ready.connect(wait.quit)
            QTimer.singleShot(timeout_ms, wait.quit)
            wait.exec()
            if not self.is_ready:
                return None
        self.request(method, params, done)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        return holder.get("r")

    def _read(self):
        for msg in self.parser.feed(bytes(self.proc.readAllStandardOutput())):
            if "id" in msg and ("result" in msg or "error" in msg) and "method" not in msg:
                cb = self.callbacks.pop(msg["id"], None)
                if cb:
                    cb(msg.get("result"))
            elif msg.get("method") == "textDocument/publishDiagnostics":
                p = msg.get("params", {})
                self.diagnostics.emit(p.get("uri", ""), p.get("diagnostics", []))
            elif "id" in msg and "method" in msg:                # a request from the server we do not support: answer politely
                self._write({"jsonrpc": "2.0", "id": msg["id"], "result": None})

    # ---- documents ---------------------------------------------------------------------------------------------------
    def open_doc(self, uri, text, version=1):
        self.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": self.lang_id, "version": version, "text": text}})

    def change_doc(self, uri, text, version):
        self.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": version}, "contentChanges": [{"text": text}]})

    def close_doc(self, uri):
        self.notify("textDocument/didClose", {"textDocument": {"uri": uri}})

    def definition(self, uri, line, col):
        """-> [(path, line0, col0)] locations of the definition."""
        res = self.call("textDocument/definition", {"textDocument": {"uri": uri}, "position": {"line": line, "character": col}})
        if not res:
            return []
        items = res if isinstance(res, list) else [res]
        out = []
        for it in items:
            u = it.get("uri") or it.get("targetUri")
            r = it.get("range") or it.get("targetSelectionRange") or {}
            if u:
                s = r.get("start", {})
                out.append((uri_to_path(u), s.get("line", 0), s.get("character", 0)))
        return out

    def hover(self, uri, line, col, timeout_ms=700):
        return hover_text(self.call("textDocument/hover", {"textDocument": {"uri": uri}, "position": {"line": line, "character": col}}, timeout_ms))

    def stop(self):
        if self.proc.state() == QProcess.NotRunning:
            return
        self.request("shutdown", None)
        self.notify("exit", None)
        if not self.proc.waitForFinished(600):
            self.proc.kill()
            self.proc.waitForFinished(500)
