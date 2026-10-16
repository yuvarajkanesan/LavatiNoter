"""Opt-in update check against the project's GitHub Releases. Sends no data about you: it is one plain GET request."""
import json
import re
import urllib.error
import urllib.request

from PySide6.QtCore import QThread, Signal

from . import APP_NAME, VERSION

REPO = "yuvarajkanesan/LavatiNoter"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases"


def parse_version(text):
    """'v1.2.3-beta' -> (1, 2, 3). Anything non-numeric after the first number is ignored."""
    return tuple(int(x) for x in re.findall(r"\d+", (text or "").split("-")[0])[:4])


def is_newer(latest, current=VERSION):
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def fetch_latest(opener=urllib.request.urlopen, timeout=8):
    """-> {'tag', 'url', 'notes', 'newer'} for the newest release, or raises OSError / ValueError."""
    req = urllib.request.Request(API, headers={"User-Agent": f"{APP_NAME}/{VERSION}", "Accept": "application/vnd.github+json"})
    try:
        with opener(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"tag": "", "url": PAGE, "notes": "", "newer": False, "none": True}
        raise OSError(f"GitHub answered {e.code}") from None
    tag = data.get("tag_name", "")
    return {"tag": tag, "url": data.get("html_url") or PAGE, "notes": (data.get("body") or "")[:1500], "newer": is_newer(tag),
            "none": False}


class UpdateCheck(QThread):
    finished_check = Signal(object, str)        # result dict or None, error text

    def run(self):
        try:
            self.finished_check.emit(fetch_latest(), "")
        except (OSError, ValueError) as e:
            self.finished_check.emit(None, str(e) or "No connection")
