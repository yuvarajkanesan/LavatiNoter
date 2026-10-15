"""Settings, text file IO (encoding / line-ending detection), image helpers and small system helpers."""
import base64
import json
import os
import re
import sys
import urllib.parse

from . import APP_NAME


# ---- paths --------------------------------------------------------------------------------------
def data_dir():
    """Per-user data folder (settings, session backups, pasted images of unsaved documents)."""
    base = os.environ.get("LAVATINOTER_HOME") or os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"),
                                                              APP_NAME)
    os.makedirs(base, exist_ok=True)
    return base


def sub_dir(name):
    d = os.path.join(data_dir(), name)
    os.makedirs(d, exist_ok=True)
    return d


def resource(*parts):
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else (f"{n:.2f} {unit}" if n < 100 else f"{n:.1f} {unit}")
        n /= 1024


def short_count(n):
    """78_400_000 -> '78.4 M'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} M"
    if n >= 10_000:
        return f"{n / 1000:.0f} K"
    return f"{n:,}"


def rss_mb():
    """Working set of this process in MB (0 when unknown)."""
    if sys.platform != "win32":
        return 0
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        if ctypes.windll.psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return int(pmc.WorkingSetSize / (1024 * 1024))
    except (OSError, AttributeError, ValueError):
        pass
    return 0


# ---- settings -----------------------------------------------------------------------------------
DEFAULTS = {
    "theme": "Dark",
    "font_size": 11,
    "tab_width": 4,
    "use_spaces": True,
    "word_wrap": False,
    "show_whitespace": False,
    "show_minimap": True,
    "show_workspace": True,
    "large_file_mb": 64,
    "image_folder": "images",
    "recent_files": [],
    "workspace": "",
    "geometry": "",
    "restore_session": True,
    "spellcheck": True,
    "autocorrect": True,
}


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "settings.json")
        self.values = dict(DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self.values.update(loaded)
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.values.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value):
        self.values[key] = value

    def save(self):
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.values, f, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def add_recent(self, path):
        recent = [p for p in self.values.get("recent_files", []) if os.path.normcase(p) != os.path.normcase(path)]
        self.values["recent_files"] = ([path] + recent)[:15]


# ---- text files ---------------------------------------------------------------------------------
ENCODINGS = {   # menu label -> python codec
    "UTF-8": "utf-8",
    "UTF-8 with BOM": "utf-8-sig",
    "UTF-16 LE BOM": "utf-16-le-bom",
    "UTF-16 BE BOM": "utf-16-be-bom",
    "ANSI (Windows-1252)": "cp1252",
    "Latin-1 (ISO-8859-1)": "latin-1",
    "Central European (Windows-1250)": "cp1250",
    "Cyrillic (Windows-1251)": "cp1251",
    "Greek (Windows-1253)": "cp1253",
    "Japanese (Shift-JIS)": "shift_jis",
    "Chinese Simplified (GB18030)": "gb18030",
    "Chinese Traditional (Big5)": "big5",
    "Korean (EUC-KR)": "euc_kr",
}
EOLS = {"Windows (CR LF)": "\r\n", "Unix (LF)": "\n", "Old Mac (CR)": "\r"}


def decode_bytes(data, encoding):
    """Returns text for `data` in the named encoding label. Undecodable bytes become U+FFFD."""
    codec = ENCODINGS.get(encoding, encoding)
    if codec == "utf-16-le-bom":
        return data[2:].decode("utf-16-le", "replace") if data[:2] == b"\xff\xfe" else data.decode("utf-16-le", "replace")
    if codec == "utf-16-be-bom":
        return data[2:].decode("utf-16-be", "replace") if data[:2] == b"\xfe\xff" else data.decode("utf-16-be", "replace")
    return data.decode(codec, "replace")


def encode_text(text, encoding, errors="replace"):
    codec = ENCODINGS.get(encoding, encoding)
    if codec == "utf-16-le-bom":
        return b"\xff\xfe" + text.encode("utf-16-le", errors)
    if codec == "utf-16-be-bom":
        return b"\xfe\xff" + text.encode("utf-16-be", errors)
    return text.encode(codec, errors)


def detect_encoding(data):
    if data.startswith(b"\xef\xbb\xbf"):
        return "UTF-8 with BOM"
    if data.startswith(b"\xff\xfe"):
        return "UTF-16 LE BOM"
    if data.startswith(b"\xfe\xff"):
        return "UTF-16 BE BOM"
    try:
        data.decode("utf-8")
        return "UTF-8"
    except UnicodeDecodeError:
        # a file cut in the middle of a multi-byte character at the very end is still UTF-8
        try:
            data[:-3].decode("utf-8")
            return "UTF-8"
        except UnicodeDecodeError:
            return "ANSI (Windows-1252)"


def detect_eol(text):
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    cr = text.count("\r") - crlf
    if crlf == lf == cr == 0:
        return "\r\n" if sys.platform == "win32" else "\n"
    return max((crlf, "\r\n"), (lf, "\n"), (cr, "\r"))[1]


def normalize_newlines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text_file(path, encoding=None):
    """-> (text with \\n newlines, encoding label, eol string, looks_binary)."""
    with open(path, "rb") as f:
        data = f.read()
    enc = encoding or detect_encoding(data)
    binary = b"\x00" in data[:8192] and not enc.startswith("UTF-16")
    text = decode_bytes(data, enc)
    if text.startswith("﻿"):
        text = text[1:]
    eol = detect_eol(text)
    return normalize_newlines(text), enc, eol, binary


def write_text_file(path, text, encoding, eol, errors="replace"):
    """Writes via a temp file, so a crash never leaves half a file. errors="strict" raises UnicodeEncodeError
    (before anything is touched) when the encoding cannot hold the text."""
    data = encode_text(text.replace("\n", eol) if eol != "\n" else text, encoding, errors)
    tmp = path + ".lnoter-tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        with open(path, "wb") as f:           # e.g. a file another program keeps locked for replacing
            f.write(data)


# ---- images referenced from text ------------------------------------------------------------------
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".svg", ".tif", ".tiff")
# ![alt](path)  <img src="path">  url(path)  or a bare path / file name ending with an image extension
IMG_REF = re.compile(
    r"!\[[^\]]*\]\(\s*<?([^)>\n]+?)>?\s*(?:\"[^\"]*\")?\)"
    r"|<img\b[^>]*?\bsrc\s*=\s*[\"']([^\"']+)[\"']"
    r"|url\(\s*[\"']?([^)\"'\n]+?)[\"']?\s*\)"
    r"|((?:[A-Za-z]:[\\/]|\.{0,2}[\\/])?[\w\-. %\\/:]*\.(?:png|jpe?g|gif|bmp|webp|ico|svg|tiff?))\b", re.I)


def find_image_refs(line):
    """-> [(start, end, reference text)] for every image reference found in one line."""
    out = []
    for m in IMG_REF.finditer(line):
        ref = next((g for g in m.groups() if g), None)
        if ref and ref.lower().split("?")[0].endswith(IMAGE_EXTS):
            out.append((m.start(), m.end(), ref.strip()))
    return out


def resolve_image(ref, base_dir):
    ref = urllib.parse.unquote(ref.strip())
    if ref.lower().startswith("file:///"):
        ref = ref[8:]
    ref = ref.split("?")[0].replace("/", os.sep)
    if not os.path.isabs(ref) and base_dir:
        ref = os.path.join(base_dir, ref)
    ref = os.path.normpath(ref)
    return ref if os.path.isfile(ref) else None


def image_data_uri(path, max_w=360):
    """A scaled PNG as a data: URI for tooltips and previews (None when the file is not a readable image)."""
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QImage
    img = QImage(path)
    if img.isNull():
        return None
    if img.width() > max_w:
        img = img.scaledToWidth(max_w, Qt.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(bytes(buf.data())).decode("ascii")
