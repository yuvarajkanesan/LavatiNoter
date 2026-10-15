"""Renders the main window offscreen with sample content into PNG files (used to check the UI against the design).

Run from the project folder:  python tools/make_screenshots.py [output folder]
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "screenshots")
home = tempfile.mkdtemp(prefix="lavatinoter-shots-")
os.environ["LAVATINOTER_HOME"] = home

from PySide6.QtGui import QColor, QImage, QTextCursor                      # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

from lavatinoter import search, theme, util                   # noqa: E402
from lavatinoter.mainwindow import MainWindow                 # noqa: E402

SERVER = '''from flask import Flask, jsonify, request
from pathlib import Path
import logging

app = Flask(__name__)
LOG_DIR = Path("C:/logs")

@app.route("/api/files")
def list_files():
    """Return every log file with its size."""
    files = []
    for p in sorted(LOG_DIR.glob("*.log")):
        size_mb = p.stat().st_size / 1_048_576
        files.append({"name": p.name, "mb": round(size_mb, 1)})
    return jsonify(files)

@app.route("/api/tail/<name>")
def tail(name):
    lines = int(request.args.get("lines", 200))
    with open(LOG_DIR / name, "rb") as fh:
        fh.seek(0, 2)
        # TODO: read backwards in blocks
        return jsonify(read_back(fh, lines))

if __name__ == "__main__":
    app.run(port=5050, debug=True)
'''


def pump(app, n=8):
    for _ in range(n):
        app.processEvents()


def main():
    app = QApplication([])
    theme.load_fonts()
    app.setFont(theme.QFont(theme.ui_family(), 10))
    theme.apply("Dark")
    work = tempfile.mkdtemp(prefix="lavatinoter-demo-")
    proj = os.path.join(work, "api", "app")
    os.makedirs(os.path.join(proj, "logs"), exist_ok=True)
    for name, body in (("server.py", SERVER), ("models.py", "class User:\n    pass\n"), ("utils.py", "from .server import LOG_DIR\n")):
        with open(os.path.join(proj, name), "w", encoding="utf-8", newline="") as f:
            f.write(body.replace("\n", "\r\n"))
    for name in ("config.yaml", "notes.txt", "requirements.txt"):
        with open(os.path.join(work, "api", name), "w", encoding="utf-8") as f:
            f.write("log_dir: C:/logs\nport: 5050\n" if name.endswith("yaml") else "notes\n")
    log = os.path.join(work, "access.log")
    with open(log, "w", encoding="utf-8", newline="\n") as f:
        for i in range(1, 120001):
            code = 500 if i % 23 == 0 else 404 if i % 31 == 0 else 200
            f.write(f'203.0.113.{i % 250} - - [14/Mar/2026:09:21:{i % 60:02d} +0530] "GET /api/files/{i} HTTP/1.1" {code} {1843 + i % 90}\n')
    s = util.Settings(os.path.join(home, "settings.json"))
    s["large_file_mb"] = 2
    win = MainWindow(s)
    win.resize(1440, 900)
    win.workspace.set_root(os.path.join(work, "api"))
    win.show()
    page = win.open_path(os.path.join(proj, "server.py"))
    for n in ("config.yaml", "notes.txt"):
        win.open_path(os.path.join(work, "api", n))
    win.new_file("")
    win.tabs.setCurrentWidget(page)
    page.goto_line(22, 35)
    win.workspace.tree.expandAll()
    pump(app, 30)
    os.makedirs(OUT, exist_ok=True)
    win.grab().save(os.path.join(OUT, "editor.png"))

    win.find_dialog.show_tab(1, "LOG_DIR")
    win.find_dialog.repl_box.setEditText("LOG_PATH")
    win.find_dialog.case.setChecked(True)
    win.find_dialog.whole.setChecked(True)
    win.find_dialog.directory.setText(os.path.join(work, "api"))
    win.find_dialog.filters.setText("*.py;*.yaml;*.txt")
    win.find_dialog.find_in_files()
    for _ in range(100):
        pump(app, 3)
        if win.find_dialog.thread is not None and not win.find_dialog.thread.isRunning():
            break
    pump(app, 20)
    win.find_dialog.show_tab(1)
    pump(app, 20)
    win.grab().save(os.path.join(OUT, "find.png"))
    win.find_dialog.grab().save(os.path.join(OUT, "find-dialog.png"))
    win.find_dialog.hide()

    big = win.open_path(log)
    for _ in range(300):
        pump(app, 3)
        if big.indexing_done:
            break
    big.scroll_to_offset(big.offset_of_line(60000))
    big.show_goto("Line")
    pump(app, 20)
    win.grab().save(os.path.join(OUT, "large-file.png"))
    big.goto.hide()

    # picture paste
    img = QImage(480, 240, QImage.Format_RGB32)
    img.fill(QColor("#2f6fe8"))
    md = win.new_file("# Release notes\n\nThe new dashboard:\n\n")
    md.path = os.path.join(work, "notes.md")
    md.detect_language()
    md.moveCursor(QTextCursor.End)
    md.paste_image(img)
    md.insertPlainText("\n\nMore text after the picture.\n")
    win.side.setCurrentIndex(2)
    pump(app, 30)
    win._content_settled()
    win.grab().save(os.path.join(OUT, "paste-image.png"))
    md.document().setModified(False)
    for p in win.all_tabs():
        if p.is_large:
            p.close_file()
    print("screenshots written to", OUT)


if __name__ == "__main__":
    main()
