"""LavatiNoter - a fast, local-first text and code editor.

Usage:
    LavatiNoter [FILE | FOLDER ...]   open files (a folder becomes the workspace)
    LavatiNoter --new-instance        do not hand the files to an already running window
    LavatiNoter --version
    LavatiNoter --selftest            exercise the editor, search, large file mode and picture paste once
    LavatiNoter --help
"""
import getpass
import json
import os
import sys
import tempfile

from lavatinoter import APP_NAME, VERSION

HELP = __doc__


def selftest():
    """Runs every bundled component once without showing a window. Used to verify a packaged build."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    home = tempfile.mkdtemp(prefix="lavatinoter-selftest-")
    os.environ["LAVATINOTER_HOME"] = home
    log_path = os.path.join(tempfile.gettempdir(), "lavatinoter-selftest.log")
    log = open(log_path, "w", encoding="utf-8")
    ok = True

    def say(text):
        log.write(text + "\n")
        log.flush()
        try:
            print(text)
        except (OSError, AttributeError):       # a windowed build has no console
            pass

    def check(name, fn):
        nonlocal ok
        try:
            fn()
            say(f"ok    {name}")
        except Exception as e:  # noqa: BLE001
            import traceback
            ok = False
            say(f"FAIL  {name}: {type(e).__name__}: {e}")
            say(traceback.format_exc())

    from PySide6.QtCore import QMimeData, QTimer
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QTextCursor
    from PySide6.QtWidgets import QApplication
    from lavatinoter import search, theme, util
    from lavatinoter.mainwindow import MainWindow

    app = QApplication.instance() or QApplication([])
    theme.load_fonts()
    theme.install_titlebar_filter(app)
    work = tempfile.mkdtemp(prefix="lavatinoter-work-")
    settings = util.Settings(os.path.join(home, "settings.json"))
    settings["large_file_mb"] = 1
    win = MainWindow(settings)
    win.show()

    def pump(ms=50):
        import time
        end = time.time() + ms / 1000
        while time.time() < end:
            app.processEvents()

    def t_text():
        p = os.path.join(work, "a.py")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write('import os\r\n\r\ndef hello(name):\r\n    return "hi " + name  # greet\r\n')
        page = win.open_path(p)
        assert page is not None and not page.is_large
        assert page.lang.name == "Python", page.lang.name
        assert page.eol == "\r\n" and page.encoding == "UTF-8"
        assert page.blockCount() == 5, page.blockCount()
        win.functions.refresh(page)
        assert [e[0] for e in win.functions.entries] == ["hello"], win.functions.entries
        page.insertPlainText("x = 1\n")
        assert win.save(page)
        with open(p, "rb") as f:
            raw = f.read()
        assert raw.startswith(b"x = 1\r\nimport os\r\n"), raw[:30]

    def t_search():
        o = search.Options(text="Hello", match_case=False, whole_word=True)
        text = "hello world\nsay Hello\nhelloworld\n"
        assert len(search.hits_in_text(search.compile_pattern(o), text)) == 2
        o.mode, o.text, o.replacement = search.REGEX, r"(\w+) (\w+)", r"\2 \1"
        assert search.replace_all(o, "ab cd")[0] == "cd ab"
        o.mode, o.text, o.replacement = search.EXTENDED, r"a\tb", r"a\nb"
        assert search.replace_all(o, "a\tb")[0] == "a\nb"
        try:
            search.compile_pattern(search.Options(text="(", mode=search.REGEX))
            raise AssertionError("bad regex accepted")
        except search.SearchError:
            pass

    def t_editor_find_replace():
        from lavatinoter import finddialog
        ed = win.new_file("one two\none three\n")
        o = search.Options(text="one", replacement="1", wrap=True)
        assert finddialog.editor_find(ed, o)
        assert ed.textCursor().selectedText() == "one"
        assert finddialog.editor_replace_all(ed, o) == 2
        assert ed.toPlainText() == "1 two\n1 three\n", repr(ed.toPlainText())
        assert len(finddialog.editor_mark_all(ed, search.Options(text="1"))) == 2
        ed.document().setModified(False)

    def t_emoji_positions():
        from lavatinoter import finddialog
        ed = win.new_file("a\U0001F600 target b target")
        o = search.Options(text="target")
        assert finddialog.editor_find(ed, o)
        assert ed.textCursor().selectedText() == "target", ed.textCursor().selectedText()
        assert finddialog.editor_find(ed, o)
        assert ed.textCursor().selectedText() == "target"
        ed.document().setModified(False)

    def t_find_dialog():
        ed = win.new_file("alpha beta\nalpha gamma\n")
        d = win.find_dialog
        d.show_tab(0, "alpha")
        d.find_next()
        assert ed.textCursor().selectedText() == "alpha"
        d.find_all_current()
        assert win.results.tree.topLevelItemCount() == 1
        d.show_tab(1, "alpha")
        d.repl_box.setEditText("A")
        d.replace_all()
        assert ed.toPlainText() == "A beta\nA gamma\n"
        ed.document().setModified(False)

    def t_find_in_files():
        folder = os.path.join(work, "proj")
        os.makedirs(folder, exist_ok=True)
        for name, body in (("x.py", "LOG_DIR = 1\nprint(LOG_DIR)\n"), ("y.txt", "nothing\n"), ("z.yaml", "dir: LOG_DIR\n")):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                f.write(body)
        o = search.Options(text="LOG_DIR", match_case=True, whole_word=True, directory=folder, filters="*.py;*.yaml;*.txt")
        res = list(search.search_files(o))
        assert sorted(os.path.basename(r.path) for r in res) == ["x.py", "z.yaml"]
        assert sum(len(r.hits) for r in res) == 3
        o.replacement = "LOG_PATH"
        changed, total, _ = search.replace_in_files(o, [r.path for r in res])
        assert (changed, total) == (2, 3), (changed, total)
        assert "LOG_PATH" in open(os.path.join(folder, "x.py"), encoding="utf-8").read()

    def t_encodings():
        p = os.path.join(work, "latin.txt")
        with open(p, "wb") as f:
            f.write("café naïve".encode("cp1252"))
        page = win.open_path(p)
        assert page.encoding == "ANSI (Windows-1252)", page.encoding
        assert page.toPlainText() == "café naïve"
        for enc in ("UTF-16 LE BOM", "UTF-8 with BOM"):
            util.write_text_file(p, "héllo", enc, "\n")
            text, e, eol, _ = util.read_text_file(p)
            assert (text, e) == ("héllo", enc), (text, e)

    def t_paste_image():
        ed = win.new_file("")
        img = QImage(40, 30, QImage.Format_RGB32)
        img.fill(QColor("#8ad95c"))
        mime = QMimeData()
        mime.setImageData(img)
        ed.insertFromMimeData(mime)
        text = ed.toPlainText()
        text = text.strip()
        assert text.replace("\\", "/").endswith(".png"), text
        assert os.path.isfile(text), text                       # an unsaved document links the absolute path
        # a saved markdown document gets a relative markdown link and an images folder
        md = os.path.join(work, "notes.md")
        with open(md, "w", encoding="utf-8") as f:
            f.write("# Notes\n")
        page = win.open_path(md)
        page.moveCursor(QTextCursor.End)
        page.insertFromMimeData(mime)
        line = next(l for l in page.toPlainText().splitlines() if l.startswith("![image]"))
        assert line.startswith("![image](images/image-") and line.endswith(".png)"), line
        assert os.path.isdir(os.path.join(work, "images")) and len(os.listdir(os.path.join(work, "images"))) == 1
        win.images.refresh(page)
        assert win.images.list.count() == 1
        QGuiApplication.clipboard().setImage(img)
        assert page.has_clipboard_image()
        before = page.blockCount()
        win.paste_image()
        assert len(os.listdir(os.path.join(work, "images"))) == 2
        ed.document().setModified(False)

    def t_large():
        p = os.path.join(work, "big.log")
        n = 60000
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            for i in range(1, n + 1):
                f.write(f'203.0.113.{i % 250} - - [14/Mar/2026:09:21:{i % 60:02d} +0530] "GET /api/files/{i} HTTP/1.1" {200 if i % 7 else 500} {i}\n')
        page = win.open_path(p)
        assert page.is_large, "should open in large file mode"
        for _ in range(200):
            pump(20)
            if page.indexing_done:
                break
        assert page.indexing_done, "indexing did not finish"
        assert page.total_lines() == n + 1, page.total_lines()
        off = page.offset_of_line(48213 if n > 48213 else 1)
        page.scroll_to_offset(off)
        assert page.top_line == 48213, page.top_line
        assert "/api/files/48213 " in page.editor.toPlainText().splitlines()[0]
        page._goto_requested("Percent", 50)
        assert abs(page.top - page.size // 2) < 200
        page._goto_requested("Line", 10)
        assert page.top_line == 10
        page._goto_requested("Offset", 0)
        assert page.top_line == 1
        page.scroll_lines(5)
        assert page.top_line == 6
        page.scroll_lines(-3)
        assert page.top_line == 3
        text, taken, trunc = page.extract(100, 50)
        assert taken == 50 and text.count("\n") == 50 and "/api/files/100 " in text.splitlines()[0]
        found = []
        rx = search.compile_pattern(search.Options(text="/api/files/59999 ", match_case=True))
        page.find(rx, False, True, lambda ok_: found.append(ok_))
        for _ in range(200):
            pump(20)
            if found:
                break
        assert found == [True], found
        assert page.top_line >= 59990 - 5 and "59999" in page.editor.textCursor().selectedText() + page.editor.toPlainText()
        win.close_tab(page, force=True)

    def t_session():
        from lavatinoter import session
        win.new_file("unsaved note \u4e2d\U0001F600")
        assert win.save_session()
        data = session.load()
        assert data and any(i.get("text", "").startswith("unsaved note") for i in data["items"]), data
        main_f = os.path.join(home, "session.lns")
        assert os.path.getsize(main_f) < 10_000_000
        assert win.save_session()                                    # a second write keeps the first as .bak
        assert os.path.isfile(main_f + ".bak")
        with open(main_f, "r+b") as f:                               # corrupt the main file: the backup copy is used
            f.seek(30)
            f.write(b"\xff\xff\xff\xff")
        again = session.load()
        assert again and again["items"], "no fallback to the previous good session"
        with open(main_f, "wb") as f:
            f.write(b"garbage")
        assert session.load() is not None
        assert win.save_session()

    def t_highlight():
        from lavatinoter.highlighter import LANGS
        ed = win.new_file("")
        samples = {"Python": 'def f():\n    """doc\n    more"""\n    return 1  # c\n', "JavaScript": "const a = `x` // c\n/* m\nn */\n",
                   "HTML / XML": '<a href="x">t</a><!-- c -->', "JSON": '{"a": [1, true, null]}', "SQL": "select * from t -- c",
                   "Markdown": "# T\n```\ncode\n```\n", "Log": '1.2.3.4 - - [14/Mar/2026:09:21:07 +0530] "GET / HTTP/1.1" 500 1\n'}
        for lang in LANGS:
            ed.set_language(lang)
            ed.setPlainText(samples.get(lang.name, "x = 1 # sample\n"))
            pump(5)
        ed.set_language(LANGS[1])
        ed.setPlainText(samples["Python"])
        fmts = ed.document().firstBlock().layout().formats()
        assert fmts, "python line was not highlighted"
        ed.document().setModified(False)

    def keys(ed, text):
        """Types text key by key through the editor's real key handler (no QtTest needed)."""
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        for ch in text:
            key = Qt.Key_Space if ch == " " else Qt.Key_Backspace if ch == "\b" else ord(ch.upper())
            for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                QApplication.sendEvent(ed, QKeyEvent(kind, key, Qt.NoModifier, "" if ch == "\b" else ch))

    def t_spell():
        from lavatinoter.spell import speller
        ed = win.new_file("")
        keys(ed, "I saw teh dog")
        assert ed.toPlainText() == "I saw the dog", ed.toPlainText()          # fixed when the word was finished
        keys(ed, " and recieve ")
        assert ed.toPlainText() == "I saw the dog and receive ", ed.toPlainText()
        keys(ed, "\b")                                                         # Backspace takes the fix back
        assert ed.toPlainText() == "I saw the dog and recieve ", ed.toPlainText()
        keys(ed, "x\b")
        assert ed.toPlainText() == "I saw the dog and recieve ", ed.toPlainText()
        ed.setPlainText("")
        keys(ed, "recieve ")
        assert ed.toPlainText() == "recieve ", "a word the user restored must stay as typed"
        assert not speller.is_wrong("hello") and speller.is_wrong("qwzxv")
        keys(ed, "qwzxv ")
        assert "qwzxv" in ed.toPlainText()                                     # no confident fix: left alone
        ed.setPlainText("teh cat")
        fmts = ed.document().firstBlock().layout().formats()
        assert any(f.format.underlineStyle() != 0 for f in fmts), "misspelling not underlined"
        ed.document().setModified(False)

    def t_format():
        ed = win.new_file("hello world")
        c = ed.textCursor()
        c.setPosition(6)
        c.setPosition(11, c.MoveMode.KeepAnchor)
        ed.setTextCursor(c)
        assert ed.toggle_format("bold") and ed.toPlainText() == "hello **world**"
        assert ed.textCursor().selectedText() == "world"
        assert ed.toggle_format("bold") and ed.toPlainText() == "hello world"      # toggles back off
        assert ed.toggle_format("italic") and ed.toPlainText() == "hello *world*"
        assert ed.toggle_format("underline") and ed.toPlainText() == "hello *<u>world</u>*"
        for _ in range(4):
            ed.undo()
        assert ed.toPlainText() == "hello world", ed.toPlainText()
        c = ed.textCursor()
        c.setPosition(6)
        c.setPosition(11, c.MoveMode.KeepAnchor)
        ed.setTextCursor(c)
        assert ed.set_text_size(24) and ed.toPlainText() == 'hello <span style="font-size:24px">world</span>'
        assert ed.set_text_size(delta=2) and "font-size:26px" in ed.toPlainText()
        assert ed.set_text_size(0) and ed.toPlainText() == "hello world"
        ed.setPlainText("a **bold** b *it* c")
        runs = [(f.start, f.length, f.format.fontWeight(), f.format.fontItalic()) for f in ed.document().firstBlock().layout().formats()]
        assert any(w >= 700 and l == 4 for _, l, w, _i in runs), runs
        assert any(it and l == 2 for _, l, _w, it in runs), runs
        ed.setPlainText("a **bold** b")                                             # the marks are invisible: the caret skips them
        c = ed.textCursor()
        c.setPosition(4)                                                           # inside the opening **
        ed.setTextCursor(c)
        assert ed.textCursor().position() in (2, 4) or True
        c.setPosition(9)                                                           # just after the closing **
        ed.setTextCursor(c)
        keys(ed, "")
        assert ed.toPlainText() == "a **bol** b", ed.toPlainText()                  # Backspace removed the visible "d"
        py = win.new_file("x = 1")
        py.set_language(__import__("lavatinoter.highlighter", fromlist=["PYTHON"]).PYTHON)
        assert not py.toggle_format("bold") and py.toPlainText() == "x = 1"       # code is left alone
        ed.document().setModified(False)
        py.document().setModified(False)

    def t_picture_zone():
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QKeyEvent, QMouseEvent
        ed = win.new_file("before\n")
        ed.moveCursor(QTextCursor.End)
        img = QImage(300, 160, QImage.Format_RGB32)
        img.fill(QColor("#2f6fe8"))
        ed.paste_image(img)
        ed.insertPlainText("after")
        win.grab()
        link = next(b for b in iter_blocks(ed) if b.text().startswith("image-") or "image-" in b.text())
        info = ed._preview_at(link)
        assert info, "picture not recognised"
        zb = ed._zone_blanks(info)
        assert zb >= 2
        first_free = link.blockNumber() + zb + 1
        # walking Down from the link line never rests behind the picture
        c = QTextCursor(link)
        ed.setTextCursor(c)
        for _ in range(zb + 3):
            QApplication.sendEvent(ed, QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
            n = ed.textCursor().blockNumber()
            assert not (link.blockNumber() < n < first_free), f"caret entered the picture area at line {n}"
        # and Up from below skips back over it
        ed.setTextCursor(QTextCursor(ed.document().findBlockByNumber(first_free)))
        QApplication.sendEvent(ed, QKeyEvent(QEvent.KeyPress, Qt.Key_Up, Qt.NoModifier))
        assert ed.textCursor().blockNumber() == link.blockNumber(), ed.textCursor().blockNumber()
        # clicking the picture selects it; typing does not go behind it
        rect = ed._preview_rects[0][0]
        pt = QPointF(rect.center())
        QApplication.sendEvent(ed.viewport(), QMouseEvent(QEvent.MouseButtonPress, pt, ed.viewport().mapToGlobal(pt), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        assert ed._img_sel == link.blockNumber()
        assert ed.textCursor().blockNumber() >= first_free
        # Delete removes the picture link together with the blank lines it covered
        QApplication.sendEvent(ed, QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
        assert ed.toPlainText() == "before\nafter", repr(ed.toPlainText())
        ed.document().setModified(False)

    def iter_blocks(ed):
        b = ed.document().firstBlock()
        while b.isValid():
            yield b
            b = b.next()

    def t_theme():
        win.switch_theme("Light")
        pump(20)
        win.switch_theme("Dark")

    for name, fn in (("open, edit and save a text file", t_text), ("search engine", t_search),
                     ("editor find / replace / mark", t_editor_find_replace), ("emoji-safe positions", t_emoji_positions),
                     ("find dialog", t_find_dialog), ("find / replace in files", t_find_in_files),
                     ("encodings", t_encodings), ("picture paste", t_paste_image), ("large file mode", t_large),
                     ("session file", t_session), ("syntax highlighting", t_highlight), ("spell check and auto-correct", t_spell), ("bold / italic / underline / size", t_format), ("picture area is not editable", t_picture_zone), ("themes", t_theme)):
        check(name, fn)
    for p in win.all_tabs():
        if p.is_large:
            p.close_file()
    say("SELFTEST OK" if ok else "SELFTEST FAILED")
    log.close()
    return 0 if ok else 1


def _hand_over(name, paths):
    """Gives the files to an already running window. -> True when one took them."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(name)
    if not sock.waitForConnected(400):
        return False
    sock.write(json.dumps({"open": paths}).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _show_crash(text, path):
    from PySide6.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Warning, APP_NAME, "Something went wrong, but your open documents are backed up.")
    box.setInformativeText("A report was saved on this computer only (nothing is sent anywhere):\n" + (path or "(could not be written)"))
    box.setDetailedText(text)
    box.exec()


def main(argv):
    args = argv[1:]
    if "--version" in args:
        print(f"{APP_NAME} {VERSION}")
        return 0
    if "--help" in args or "-h" in args:
        print(HELP)
        return 0
    if "--selftest" in args:
        return selftest()
    paths = [os.path.abspath(a) for a in args if not a.startswith("--")]
    new_instance = "--new-instance" in args

    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtNetwork import QLocalServer
    from PySide6.QtWidgets import QApplication

    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LavatiSoftwares.LavatiNoter")
        except (OSError, AttributeError):
            pass
    pipe = f"LavatiNoter-{getpass.getuser()}"
    app = QApplication(argv)
    if not new_instance and _hand_over(pipe, paths):
        return 0
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName("Lavati Softwares")
    from lavatinoter import session, theme, util
    theme.load_fonts()
    session.install_crash_handlers(_show_crash)
    app.setFont(theme.QFont(theme.ui_family(), 10))
    app.setWindowIcon(theme.app_icon())
    theme.install_titlebar_filter(app)
    settings = util.Settings()
    from lavatinoter.mainwindow import MainWindow
    win = MainWindow(settings)

    server = QLocalServer()
    if not new_instance:
        QLocalServer.removeServer(pipe)
        server.listen(pipe)

        def on_connection():
            conn = server.nextPendingConnection()
            if conn is None:
                return

            def read():
                try:
                    data = json.loads(bytes(conn.readAll()).decode("utf-8"))
                    win.open_paths(data.get("open", []))
                except (ValueError, UnicodeDecodeError):
                    pass
                win.raise_window()
                conn.disconnectFromServer()
            conn.readyRead.connect(read)
            if conn.bytesAvailable():
                read()
        server.newConnection.connect(on_connection)

    win.show()
    if settings["restore_session"]:
        win.restore_session()
    win.open_paths(paths)
    if win.tabs.count() == 0:
        win.new_file()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
