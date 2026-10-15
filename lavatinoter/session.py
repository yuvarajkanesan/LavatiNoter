"""Crash-safe, compressed session storage and the crash log.

The whole session (open tabs plus the text of every unsaved document) is one zlib-compressed file with a magic header and
a checksum. It is written to a temp file and renamed into place, the previous good copy is kept as .bak, and loading falls
back to it, so a power cut or crash in the middle of a write can never leave you without a readable session."""
import faulthandler
import hashlib
import json
import os
import sys
import threading
import time
import traceback
import zlib

from . import APP_NAME, VERSION, util

MAGIC = b"LNS1"
MAX_BACKUP_BYTES = 400 * 1024 * 1024        # uncompressed text of unsaved documents beyond this is not backed up


def _path(name="session.lns"):
    return os.path.join(util.data_dir(), name)


def save(data):
    """Writes the session atomically. -> True on success."""
    payload = zlib.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"), 6)
    blob = MAGIC + hashlib.sha256(payload).digest()[:16] + payload
    main, tmp, bak = _path(), _path("session.lns.tmp"), _path("session.lns.bak")
    try:
        with open(tmp, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(main):
            try:
                os.replace(main, bak)           # keep the last good copy
            except OSError:
                pass
        os.replace(tmp, main)
        return True
    except OSError:
        return False


def _read(path):
    with open(path, "rb") as f:
        blob = f.read()
    if blob[:4] != MAGIC or len(blob) < 21:
        raise ValueError("not a session file")
    payload = blob[20:]
    if hashlib.sha256(payload).digest()[:16] != blob[4:20]:
        raise ValueError("checksum mismatch")
    return json.loads(zlib.decompress(payload).decode("utf-8"))


def load():
    """The newest readable session (the main file, else the .bak), or None."""
    for name in ("session.lns", "session.lns.bak"):
        p = _path(name)
        if os.path.exists(p):
            try:
                return _read(p)
            except (OSError, ValueError, zlib.error):
                continue
    return None


# ---- crash log ----------------------------------------------------------------------------------------------------
def log_dir():
    d = os.path.join(util.data_dir(), "logs")
    os.makedirs(d, exist_ok=True)
    return d


def _prune_logs(keep=10):
    try:
        files = sorted((os.path.join(log_dir(), f) for f in os.listdir(log_dir()) if f.endswith(".log")), key=os.path.getmtime)
        for f in files[:-keep]:
            os.remove(f)
    except OSError:
        pass


def write_crash_report(text):
    _prune_logs()
    path = os.path.join(log_dir(), time.strftime("crash-%Y%m%d-%H%M%S.log"))
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"{APP_NAME} {VERSION}\nPython {sys.version}\nPlatform {sys.platform}\n\n{text}")
    except OSError:
        return None
    return path


def install_crash_handlers(on_error=None):
    """Logs unhandled Python errors (and native crashes) to %APPDATA%\\LavatiNoter\\logs. Nothing is ever sent anywhere."""
    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        path = write_crash_report(text)
        if on_error:
            try:
                on_error(text, path)
            except Exception:  # noqa: BLE001
                pass
    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
    try:
        _prune_logs()
        fh = open(os.path.join(log_dir(), "native-crash.log"), "a", encoding="utf-8")
        fh.write(f"\n--- {time.ctime()} {APP_NAME} {VERSION}\n")
        fh.flush()
        faulthandler.enable(file=fh)
        install_crash_handlers._fh = fh          # keep the file open for the life of the process
    except OSError:
        pass
