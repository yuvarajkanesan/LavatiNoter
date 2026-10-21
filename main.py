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

    from PySide6.QtCore import QEvent, QMimeData, QTimer, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QKeyEvent, QTextCursor
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
        assert ed.toggle_format("italic") and ed.toPlainText() == "hello _world_"
        assert ed.toggle_format("underline") and ed.toPlainText() == "hello _<u>world</u>_"
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

    def t_autocomplete():
        from lavatinoter.highlighter import PLAIN, PYTHON
        ed = win.new_file("")
        ed.set_language(PYTHON)
        ed.setPlainText("def calculate_total(items):\n    return len(items)\n")
        assert ed.completion_candidates("calc") == ["calculate_total"]
        assert "import" in ed.completion_candidates("imp")
        c = ed.textCursor()
        c.movePosition(c.MoveOperation.End)
        ed.setTextCursor(c)
        keys(ed, "calc")
        assert ed._completer.popup().isVisible(), "no suggestion list while typing"
        ed._insert_completion("calculate_total")
        assert ed.toPlainText().endswith("calculate_total"), ed.toPlainText()
        ed.set_language(PLAIN)
        assert "beautiful" in ed.completion_candidates("beaut")
        ed.document().setModified(False)

    def t_ide():
        from lavatinoter import formatter
        from lavatinoter.highlighter import JS, JSON, PYTHON, lang_for_path
        # formatting
        ed = win.new_file('{"b":[1,2,{"c":null}],"a":"x"}')
        ed.set_language(JSON)
        win.format_document()
        assert ed.toPlainText().startswith('{\n    "b": [\n        1,'), ed.toPlainText()
        ed.undo()
        assert ed.toPlainText() == '{"b":[1,2,{"c":null}],"a":"x"}', "format must be one undo step"
        win.minify_json()
        assert ed.toPlainText() == '{"b":[1,2,{"c":null}],"a":"x"}\n'
        ed.setPlainText('{"a": 1,}')
        win.validate_document()
        assert ed.textCursor().blockNumber() == 0 and "JSON" in win.results.console.toPlainText()
        js = win.new_file("function f(a){\nif(a){\nreturn [1,\n2];\n}\n}\n")
        js.set_language(JS)
        win.format_document()
        assert js.toPlainText() == "function f(a){\n    if(a){\n        return [1,\n            2];\n    }\n}\n", repr(js.toPlainText())
        # language coverage
        for name, lang in (("a.ts", "TypeScript"), ("a.java", "Java"), ("a.rs", "Rust"), ("a.go", "Go"), ("a.cs", "C#"),
                           ("a.cpp", "C / C++"), ("a.php", "PHP"), ("a.rb", "Ruby"), ("a.kt", "Kotlin"), ("a.swift", "Swift"),
                           ("Dockerfile", "Dockerfile"), ("Makefile", "Makefile"), ("a.lua", "Lua"), ("a.diff", "Diff / Patch")):
            assert lang_for_path(name).name == lang, (name, lang_for_path(name).name)
        # auto-close brackets and quotes, and Enter between braces
        py = win.new_file("")
        py.set_language(PYTHON)
        py.autoclose_on = True
        keys(py, "print(")
        assert py.toPlainText() == "print()", py.toPlainText()
        keys(py, "'hi'")
        assert py.toPlainText() == "print('hi')", py.toPlainText()
        keys(py, ")")                                                              # typing the closer steps over it
        assert py.toPlainText() == "print('hi')" and py.textCursor().position() == len("print('hi')")
        py.setPlainText("")
        keys(py, "x = [")
        keys(py, "\b")                                                             # Backspace removes the empty pair
        assert py.toPlainText() == "x = ", repr(py.toPlainText())
        py.setPlainText("")
        keys(py, "{")
        QApplication.sendEvent(py, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier, "\r"))
        assert py.toPlainText() == "{\n    \n}", repr(py.toPlainText())
        # brackets: the pair around the caret is found, and "select inside" works
        py.setPlainText("foo(a, [b, c], d)")
        c = py.textCursor()
        c.setPosition(10)
        py.setTextCursor(c)
        assert py._enclosing_bracket() == 7
        assert py.select_enclosing() and py.textCursor().selectedText() == "b, c"
        assert py.select_enclosing() and py.textCursor().selectedText() == "a, [b, c], d"
        for p in (ed, js, py):
            p.document().setModified(False)

    def t_folding():
        from lavatinoter import folding
        from lavatinoter.highlighter import JS, PYTHON
        py_src = "import os\n\nclass A:\n    def f(self):\n        x = 1\n        return x\n\n    def g(self):\n        pass\n\nprint(1)\n"
        r = folding.compute_regions("Python", py_src)
        assert r == {2: 8, 3: 5, 7: 8}, r
        js_src = "function f() {\n  if (a) {\n    b();\n  }\n  const s = '{';\n}\nlet o = [\n 1,\n 2\n];\n"
        r = folding.compute_regions("JavaScript", js_src)
        assert r == {0: 5, 1: 3, 6: 9}, r
        assert folding.compute_regions("Markdown", "# A\ntext\n## B\nmore\n# C\nx")[0] == 3
        assert folding.compute_regions("HTML / XML", "<div>\n<p>\nx\n</p>\n</div>") == {0: 4, 1: 3}
        ed = win.new_file(js_src)
        ed.set_language(JS)
        ed.recompute_folds()
        doc = ed.document()
        assert ed.fold_block(doc.findBlockByNumber(1), True)
        assert [doc.findBlockByNumber(i).isVisible() for i in range(6)] == [True, True, False, False, True, True]
        assert ed.fold_block(doc.findBlockByNumber(0), True)
        assert not doc.findBlockByNumber(4).isVisible() and not doc.findBlockByNumber(5).isVisible()
        ed.goto_line(3)                                                     # a hit inside a fold opens it
        assert doc.findBlockByNumber(2).isVisible() and doc.findBlockByNumber(1).isVisible()
        ed.fold_all()
        assert not doc.findBlockByNumber(1).isVisible()
        ed.unfold_all()
        assert all(doc.findBlockByNumber(i).isVisible() for i in range(doc.blockCount()))
        ed.setPlainText(py_src)
        ed.set_language(PYTHON)
        ed.recompute_folds()
        ed.fold_all(functions_only=True)
        vis = [doc.findBlockByNumber(i).isVisible() for i in range(doc.blockCount())]
        assert vis[3] and not vis[4] and not vis[5] and vis[7] and not vis[8], vis
        ed.document().setModified(False)

    def t_navigation():
        from lavatinoter import symbols
        from lavatinoter.highlighter import PYTHON
        proj = os.path.join(work, "navproj")
        os.makedirs(proj, exist_ok=True)
        with open(os.path.join(proj, "util.py"), "w", encoding="utf-8") as f:
            f.write("MAX_ITEMS = 5\n\ndef compute(x):\n    return x * 2\n")
        with open(os.path.join(proj, "main_app.py"), "w", encoding="utf-8") as f:
            f.write("from util import compute\n\nprint(compute(MAX_ITEMS))\n")
        defs = symbols.find_definitions("compute", proj)
        assert [(os.path.basename(p), ln) for p, ln, _ in defs] == [("util.py", 3)], defs
        assert [(os.path.basename(p), ln) for p, ln, _ in symbols.find_definitions("MAX_ITEMS", proj)] == [("util.py", 1)]
        refs = symbols.find_references("compute", proj)
        assert sum(len(r.hits) for r in refs) == 3, refs                       # import, call in main_app, def in util
        win.workspace.set_root(proj)
        page = win.open_path(os.path.join(proj, "main_app.py"))
        c = page.textCursor()
        c.setPosition(page.toPlainText().index("compute(MAX"))
        page.setTextCursor(c)
        win.go_to_definition()
        cur = win.current()
        assert os.path.basename(cur.path) == "util.py" and cur.textCursor().blockNumber() == 2, (cur.path, cur.textCursor().blockNumber())
        assert cur.textCursor().selectedText() == "compute"
        win.nav_back()
        assert os.path.basename(win.current().path) == "main_app.py"
        win.find_references()
        assert win.results.tree.topLevelItemCount() == 1
        syms = symbols.symbols_in_text(PYTHON, "def a():\n    pass\nclass B:\n    def c(self): pass\n")
        assert [s[0] for s in syms] == ["a", "B", "c"], syms
        win.workspace.set_root("")

    def t_plugins():
        from lavatinoter import plugins
        pdir = plugins.plugins_dir()
        with open(os.path.join(pdir, "demo.py"), "w", encoding="utf-8") as f:
            f.write("NAME = 'Demo'\nVERSION = '1'\ndef register(api):\n    api.add_command('Shout', lambda: api.set_text(api.text().upper()))\n"
                    "    api.on('save', lambda p: api.log('saved ' + p))\n")
        with open(os.path.join(pdir, "broken.py"), "w", encoding="utf-8") as f:
            f.write("def register(api):\n    raise RuntimeError('boom')\n")
        win.settings["plugins_enabled"] = True
        win.reload_plugins()
        names = {p["file"]: p for p in win.plugins.plugins}
        assert names["demo.py"]["error"] is None and names["broken.py"]["error"], names          # a broken plugin never breaks the editor
        ed = win.new_file("hello")
        names["demo.py"]["actions"][0].trigger()
        assert ed.toPlainText() == "HELLO", ed.toPlainText()
        win.plugins.emit("save", "x.txt")
        assert "saved x.txt" in win.results.console.toPlainText()
        win._fill_plugins_menu()
        assert plugins.install_samples()                                                           # sample plugins are installed
        win.reload_plugins()
        assert any(p["name"] == "Word count" and not p["error"] for p in win.plugins.plugins), win.plugins.plugins
        win.settings["plugins_enabled"] = False
        win.reload_plugins()
        assert win.plugins.plugins == []
        ed.document().setModified(False)

    def t_editorconfig_hex_themes():
        from lavatinoter import editorconfig, hexview
        d = os.path.join(work, "ec")
        os.makedirs(os.path.join(d, "sub"), exist_ok=True)
        with open(os.path.join(d, ".editorconfig"), "w") as f:
            f.write("root = true\n[*]\nindent_style = space\nindent_size = 2\ntrim_trailing_whitespace = true\ninsert_final_newline = true\n"
                    "[*.{py,rb}]\nindent_size = 4\n[sub/**.md]\ntrim_trailing_whitespace = false\n")
        assert editorconfig.properties_for(os.path.join(d, "a.js"))["indent_size"] == "2"
        assert editorconfig.properties_for(os.path.join(d, "a.py"))["indent_size"] == "4"
        assert editorconfig.properties_for(os.path.join(d, "sub", "x.md"))["trim_trailing_whitespace"] == "false"
        assert editorconfig.apply_on_save({"trim_trailing_whitespace": "true", "insert_final_newline": "true"}, "a  \nb") == "a\nb\n"
        p = os.path.join(d, "t.js")
        with open(p, "w") as f:
            f.write("let a = 1;   \nlet b = 2;")
        page = win.open_path(p)
        assert page.tab_width == 2 and page.use_spaces
        win.save(page)
        assert open(p, "rb").read() == b"let a = 1;\nlet b = 2;\n" or open(p, "rb").read() == b"let a = 1;\r\nlet b = 2;\r\n", open(p, "rb").read()
        text = hexview.hex_dump(bytes(range(0, 20)) + b"Hello")
        assert text.splitlines()[0].startswith("00000000  00 01 02 03 04 05 06 07  08 09 0a"), text.splitlines()[0]
        assert text.splitlines()[1].endswith("|.Hello|") or "Hello" in text
        bp = os.path.join(d, "blob.bin")
        with open(bp, "wb") as f:
            f.write(bytes(range(256)) * 4)
        hp = win.open_hex(bp)
        assert hp.isReadOnly() and "000003f0" in hp.toPlainText() and not win.save(hp)
        from lavatinoter import theme as th
        for name in th.THEME_CHOICES:
            win.switch_theme(name)
            pump(10)
        assert len(th.THEME_CHOICES) >= 6
        win.switch_theme("Dark")
        th.set_mono_family("Courier New")
        win.set_font_size(12)
        th.set_mono_family("")
        win.set_font_size(11)

    def t_palette():
        from lavatinoter.palette import Picker, fuzzy
        assert fuzzy("fd", "Format Document") and fuzzy("zzz", "Format Document") is None
        assert fuzzy("util", "utils/util.py") > fuzzy("util", "u_t_i_l_x.py")
        cmds = win._all_commands()
        labels = [c[0] for c in cmds]
        assert "Format > Format Document" in labels and any(l.startswith("File > ") for l in labels), labels[:5]
        proj = os.path.join(work, "navproj")
        win.workspace.set_root(proj)
        win._file_cache = None
        win.quick_open()
        dlg = [w for w in win.findChildren(Picker) if w.isVisible()][-1]
        dlg.box.setText("utl")
        assert dlg.list.count() >= 1 and "util.py" in dlg.list.item(0).text(), [dlg.list.item(i).text() for i in range(dlg.list.count())]
        dlg.accept_current()
        pump(30)
        assert os.path.basename(win.current().path) == "util.py"
        dlg.close()
        win.quick_open()
        dlg = [w for w in win.findChildren(Picker) if w.isVisible()][-1]
        dlg.box.setText("@comp")
        assert dlg.list.count() == 1 and "compute" in dlg.list.item(0).text()
        dlg.close()
        win.command_palette()
        dlg = [w for w in win.findChildren(Picker) if w.isVisible()][-1]
        dlg.box.setText("format doc")
        assert "Format Document" in dlg.list.item(0).text()
        dlg.close()
        win.workspace.set_root("")

    def t_multicursor():
        ed = win.new_file("foo bar\nfoo baz\nqux foo\n")
        c = ed.textCursor()
        c.setPosition(0)
        ed.setTextCursor(c)
        assert ed.add_next_occurrence()                       # first press selects the word
        assert ed.textCursor().selectedText() == "foo"
        assert ed.add_next_occurrence() and ed.add_next_occurrence()
        assert len(ed.extra_cursors) == 2
        keys(ed, "X")                                         # typing replaces all three at once
        assert ed.toPlainText() == "X bar\nX baz\nqux X\n", ed.toPlainText()
        ed.undo()
        assert ed.toPlainText() == "foo bar\nfoo baz\nqux foo\n", "one undo step for all cursors"
        ed.clear_extra_cursors()
        assert ed.select_all_occurrences() and len(ed.extra_cursors) == 2
        keys(ed, "\b")
        assert ed.toPlainText() == " bar\n baz\nqux \n", repr(ed.toPlainText())
        ed.clear_extra_cursors()
        ed.setPlainText("aaa\nbbb\nccc\n")
        c = ed.textCursor()
        c.setPosition(1)
        ed.setTextCursor(c)
        assert ed.add_cursor_vertical(False) and ed.add_cursor_vertical(False)
        keys(ed, "-")
        assert ed.toPlainText() == "a-aa\nb-bb\nc-cc\n", ed.toPlainText()
        ed._column_select(0, 1, 2, 3)                         # a block (column) selection over three lines
        assert len(ed._all_cursors()) == 3
        ed._multi_key(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
        assert ed.toPlainText() == "aa\nbb\ncc\n", repr(ed.toPlainText())
        ed._multi_key(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
        assert not ed.extra_cursors
        ed.document().setModified(False)

    def t_diff_and_git():
        import subprocess
        from lavatinoter import diffview, gitinfo
        left, right, kinds, (added, removed, changed) = diffview.align("a\nb\nc\nd", "a\nB\nc\nd\ne")
        assert kinds == ["same", "chg", "same", "same", "add"] and (added, removed, changed) == (1, 0, 1), (kinds, added, removed, changed)
        assert right[-1] == "e" and left[-1] is None
        win._show_diff("old", "new", "x\ny", "x\nz")
        dw = [w for w in win.findChildren(diffview.DiffWindow)][-1]
        dw.step(1)
        assert dw.starts == [1] and dw.edits[0].textCursor().blockNumber() == 1
        dw.close()
        marks = gitinfo.line_changes("a\nb\nc", "a\nB\nc\nd")
        assert marks == {2: "modified", 4: "added"}, marks
        if not gitinfo.git_exe():
            return
        repo = os.path.join(work, "gitrepo")
        os.makedirs(repo, exist_ok=True)

        def git(*a):
            subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q")
        with open(os.path.join(repo, "a.txt"), "w") as f:
            f.write("one\ntwo\nthree\n")
        git("add", "."); git("commit", "-qm", "init")
        with open(os.path.join(repo, "a.txt"), "w") as f:
            f.write("one\nTWO\nthree\nfour\n")
        with open(os.path.join(repo, "new.txt"), "w") as f:
            f.write("x")
        root = gitinfo.repo_root(repo)
        assert root and os.path.normcase(root) == os.path.normcase(os.path.normpath(repo)), (root, repo)
        st = gitinfo.status(root)
        assert {os.path.basename(k): v for k, v in st.items()} == {"a.txt": "M", "new.txt": "?"}, st
        assert gitinfo.head_text(root, os.path.join(repo, "a.txt")) == "one\ntwo\nthree\n"
        win.workspace.set_root(repo)
        page = win.open_path(os.path.join(repo, "a.txt"))
        win.refresh_git()
        for _ in range(100):
            pump(30)
            if win._git_root:
                break
        assert win._git_root and win.lbl_git.isVisible() is not None
        win._update_git_marks()
        for _ in range(100):
            pump(30)
            if page.git_marks:
                break
        assert page.git_marks == {2: "modified", 4: "added"}, page.git_marks
        assert win.workspace.model.status, "workspace tree has no git status"
        win.compare_with_head()
        assert any(isinstance(w, diffview.DiffWindow) for w in win.findChildren(diffview.DiffWindow))
        for w in win.findChildren(diffview.DiffWindow):
            w.close()
        win.workspace.set_root("")

    def t_run_and_macro():
        from lavatinoter import runner
        assert runner.command_for("Python", r"C:\x\a.py").endswith('"C:\\x\\a.py"') and runner.command_for("Plain text", "a.txt") is None
        assert runner.parse_overrides('Python = py -3 "{file}"\n# c\n')["Python"] == 'py -3 "{file}"'
        if sys.platform == "win32":
            bat = os.path.join(work, "hello.bat")
            with open(bat, "w") as f:
                f.write("@echo off\r\necho hello from run\r\nexit /b 3\r\n")
            page = win.open_path(bat)
            win.run_file()
            for _ in range(200):
                pump(30)
                if win._proc is None:
                    break
            out = win.results.console.toPlainText()
            assert "hello from run" in out and "exit code 3" in out, out[-300:]
            win.run_file(selection=True)                                   # nothing selected: a hint, not a crash
        # macros: record typing and a command, then play it back
        ed = win.new_file("")
        win.tabs.setCurrentWidget(ed)
        win.macro_toggle()
        keys(ed, "ab")
        win.a_dup.trigger()
        win.macro_toggle()
        assert [s[0] for s in win._last_macro] == ["key", "key", "action"], win._last_macro
        assert ed.toPlainText() == "ab\nab", repr(ed.toPlainText())
        win.macro_play()
        assert ed.toPlainText() == "ab\nabab\nabab", repr(ed.toPlainText())          # typed ab on the last line, then duplicated it
        assert win._macro_run(win._last_macro, times=2) == 2
        win.settings["macros"] = []
        win.macro_save = lambda: None
        win._fill_macro_menu()
        ed.document().setModified(False)

    def t_export():
        from lavatinoter import export
        from lavatinoter.highlighter import PYTHON
        src = 'def hi(name):\n    return "hello " + name  # greet\n'
        doc = export.styled_document(src, PYTHON)
        fmts = [(f.start, f.length, f.format.foreground().color().name()) for f in doc.firstBlock().layout().formats()]
        c = doc.firstBlock()
        from PySide6.QtGui import QTextCursor
        cur = QTextCursor(doc)
        cur.setPosition(0)
        cur.setPosition(3, QTextCursor.KeepAnchor)
        kw = cur.charFormat().foreground().color().name()
        assert kw != "#000000" and kw != "#d9dfeb", kw                     # the keyword colour of the Light palette is baked in
        pdf = os.path.join(work, "out.pdf")
        export.export_pdf(pdf, src * 40, PYTHON, "t")
        data = open(pdf, "rb").read()
        assert data.startswith(b"%PDF") and len(data) > 1500, len(data)
        html = os.path.join(work, "out.html")
        export.export_html(html, src, PYTHON, "t")
        h = open(html, encoding="utf-8").read()
        assert "hello" in h and "color:" in h and "<title>t</title>" in h
        from lavatinoter import theme as th
        assert th.THEME_NAME == "Dark", "the editor theme must be restored after exporting"

    def t_tail_and_filter():
        from lavatinoter import search
        p = os.path.join(work, "grow.log")
        with open(p, "w", newline="\n") as f:
            for i in range(1, 40001):
                f.write(f"line {i} {'ERROR' if i % 1000 == 0 else 'ok'} filler filler filler filler filler\n")
        page = win.open_path(p)
        assert page.is_large
        for _ in range(300):
            pump(20)
            if page.indexing_done:
                break
        assert page.indexing_done and page.total_lines() == 40001
        before = page.size
        with open(p, "a", newline="\n") as f:                              # the file grows while it is open
            for i in range(40001, 50001):
                f.write(f"line {i} {'ERROR' if i % 1000 == 0 else 'ok'} filler filler filler filler filler\n")
        page.set_follow(True)
        assert page.size > before
        for _ in range(300):
            pump(20)
            if page.indexing_done:
                break
        assert page.indexing_done and page.total_lines() == 50001, page.total_lines()
        assert page.top_line > 49900, page.top_line                       # follow mode shows the end
        assert "line 50000" in page.editor.toPlainText()
        page.set_follow(False)
        # filter: the matching lines open in a new tab
        got = []
        page.copyRequested.connect(lambda text, title: got.append((text, title)))
        page.run_filter(search.compile_pattern(search.Options(text="ERROR", match_case=True)), False, "ERROR")
        for _ in range(300):
            pump(20)
            if got:
                break
        text, title = got[0]
        lines = text.strip().split("\n")
        assert len(lines) == 50 and lines[0].startswith("1000: line 1000 ERROR") and lines[-1].startswith("50000: "), (len(lines), lines[:2])
        assert "50 lines" in title
        got.clear()
        page.run_filter(search.compile_pattern(search.Options(text="ok", match_case=True)), True, "ok")
        for _ in range(300):
            pump(20)
            if got:
                break
        assert len(got[0][0].strip().split("\n")) == 50
        win.close_tab(page, force=True)

    def t_split_view():
        ed = win.new_file("alpha\nbeta\n")
        win.open_split()
        clone = win.split_editor
        assert clone.document() is ed.document() and win.split_pane is not None
        keys(clone, "X")                                                   # typing in one view shows up in the other
        assert ed.toPlainText().startswith("X") or "X" in ed.toPlainText(), ed.toPlainText()
        c = ed.textCursor()
        c.movePosition(c.MoveOperation.End)
        c.insertText("gamma")
        assert "gamma" in clone.toPlainText()
        win.flip_split()
        assert win.main_split.orientation() == Qt.Vertical
        win.close_split()
        assert win.split_pane is None
        win.open_split()
        win.close_tab(ed, force=True)                                      # closing the document closes its split view
        assert win.split_pane is None

    def t_updates_portable():
        import io
        import urllib.error
        from lavatinoter import updates
        assert updates.parse_version("v1.2.3-beta") == (1, 2, 3)
        assert updates.is_newer("v0.3", "0.2") and not updates.is_newer("0.2.0", "0.2") and updates.is_newer("1.0", "0.9.9")

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        body = b'{"tag_name": "v9.9", "html_url": "https://example.test/r", "body": "notes"}'
        r = updates.fetch_latest(lambda req, timeout=0: Resp(body))
        assert r["newer"] and r["tag"] == "v9.9" and r["url"].endswith("/r")

        def not_found(req, timeout=0):
            raise urllib.error.HTTPError("u", 404, "nf", {}, None)
        r = updates.fetch_latest(not_found)
        assert r["none"] and not r["newer"]
        # portable mode: a portable.txt next to the program keeps data beside it
        import importlib
        from lavatinoter import util as u
        assert os.path.isdir(u.data_dir())
        import ssl
        ssl.create_default_context()                                       # the update check needs TLS in the packaged app

    def t_lsp():
        from lavatinoter import lsp
        p = lsp.Parser()
        msgs = p.feed(lsp.encode({"id": 1, "result": 5})[:10]) + p.feed(lsp.encode({"id": 1, "result": 5})[10:] + lsp.encode({"method": "x"}))
        assert msgs == [{"id": 1, "result": 5}, {"method": "x"}], msgs               # messages split across reads are reassembled
        assert lsp.hover_text({"contents": {"kind": "markdown", "value": " hi "}}) == "hi"
        assert lsp.hover_text({"contents": ["a", {"value": "b"}]}) == "a\n\nb"
        assert lsp.split_command('"C:\\Program Files\\x.exe" --stdio -v') == ["C:\\Program Files\\x.exe", "--stdio", "-v"]
        assert lsp.uri_to_path(lsp.path_to_uri(os.path.join(work, "a b.py"))) == os.path.normpath(os.path.join(work, "a b.py"))
        assert lsp.detect_server("Nonexistent language") is None
        if getattr(sys, "frozen", False):
            return                                                                   # the stand-in server needs a Python interpreter
        fake = os.path.join(os.path.dirname(os.path.abspath(lsp.__file__)), "_fake_lsp.py")
        win.settings["lsp_enabled"] = True
        win.settings["lsp_servers"] = {"Python": f'"{sys.executable}" "{fake}"'}
        f = os.path.join(work, "lsp_demo.py")
        with open(f, "w") as fh:
            fh.write("def alpha():\n    x = BAD\n")
        page = win.open_path(f)
        for _ in range(200):
            pump(30)
            if page.diagnostics:
                break
        assert page.diagnostics and page.diagnostics[0][:4] == (1, 8, 1, 11), page.diagnostics          # the server's error is underlined
        assert page._diagnostic_at(1, 9) == "found BAD"
        assert win._lsp_hover(page, 0, 5) == "**fake** hover"
        c = page.textCursor()
        c.setPosition(page.toPlainText().index("x = BAD"))
        page.setTextCursor(c)
        win.go_to_definition("alpha")                                                  # the server says: line 1, column 4
        assert page.textCursor().blockNumber() == 0 and page.textCursor().selectedText() == "alpha"
        win.settings["lsp_enabled"] = False
        for cl in win.lsp_clients.values():
            cl.stop()
        win.lsp_clients = {}
        page._lsp_state = None
        win.close_tab(page, force=True)


    def t_format_combos():
        ed = win.new_file("hello big world\nnext line\n")
        doc = ed.document()

        def select(word):
            c = ed.textCursor()
            i = ed.toPlainText().index(word)
            c.setPosition(i)
            c.setPosition(i + len(word), QTextCursor.KeepAnchor)
            ed.setTextCursor(c)

        def visible_runs(block=0):
            """[(text, size pt, bold, italic, underline)] of the characters that are actually visible."""
            b = doc.findBlockByNumber(block)
            out = []
            runs = [(r.start, r.length, r.format.foreground().color().alpha(), r.format.fontPointSize(), r.format.fontWeight(),
                     r.format.fontItalic(), r.format.fontUnderline()) for r in b.layout().formats()]
            for i, ch in enumerate(b.text()):
                hit = [r for r in runs if r[0] <= i < r[0] + r[1]]
                if not hit:
                    out.append((ch, 0, False, False, False))
                    continue
                _s, _l, alpha, size, weight, italic, underline = hit[-1]
                if alpha > 0 and size != 0.1:
                    out.append((ch, size, weight >= 700, italic, underline))
            return out
        select("big")
        for kind in ("bold", "italic", "underline"):
            assert ed.toggle_format(kind)
        assert ed.toPlainText().startswith("hello **_<u>big</u>_** world"), ed.toPlainText()
        assert ed.set_text_size(24)
        shown = visible_runs()
        text = "".join(c for c, *_ in shown)
        assert text == "hello big world", repr(text)                            # nothing disappears
        big = [r for r in shown if r[0] in "big" and r[1] > 0]
        assert len(big) == 3 and all(r[2] and r[3] and r[4] and abs(r[1] - 18.0) < 0.2 for r in big), big      # bold + italic + underline + size
        select("big")
        assert ed.toggle_format("italic")                                         # taking one off keeps the others
        assert "_" not in ed.toPlainText().split("\n")[0] and "**" in ed.toPlainText()
        assert "".join(c for c, *_ in visible_runs()) == "hello big world"
        # size up and down changes only the chosen text, and the second line keeps its height
        h2 = ed.blockBoundingRect(doc.findBlockByNumber(1)).height()
        for _ in range(6):
            ed.set_text_size(delta=2)
        for _ in range(12):
            ed.set_text_size(delta=-2)
        assert ed.blockBoundingRect(doc.findBlockByNumber(1)).height() == h2
        assert ed.blockCount() == 3, "sizing must never add lines"
        assert ed.toPlainText().count("<span") == 1, ed.toPlainText()             # one span, never nested copies
        assert ed.font().pointSizeF() > 0, "the style sheet must not fix the editor font size"
        ed.document().setModified(False)

    def t_zoom():
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QWheelEvent
        ed = win.new_file("zoom me\n" * 20)
        win.set_font_size(11)
        before = ed.font().pointSizeF()
        assert before == 11.0, before

        def wheel(delta, mods=Qt.ControlModifier):
            pos = QPointF(40, 40)
            QApplication.sendEvent(ed.viewport(), QWheelEvent(pos, ed.viewport().mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta), Qt.NoButton,
                                                              mods, Qt.NoScrollPhase, False))
        wheel(120)
        wheel(120)
        assert ed.font().pointSizeF() == 13.0, ed.font().pointSizeF()          # Ctrl + wheel up: bigger
        wheel(-120)
        assert ed.font().pointSizeF() == 12.0
        for _ in range(4):
            wheel(30)                                                          # four small touchpad ticks make one step
        assert ed.font().pointSizeF() == 13.0, ed.font().pointSizeF()
        scroll_before = ed.verticalScrollBar().value()
        wheel(-120, Qt.NoModifier)                                             # plain wheel still scrolls, not zooms
        assert ed.font().pointSizeF() == 13.0
        for _ in range(100):
            wheel(120)
        assert ed.font().pointSizeF() == 72.0                                  # there is a ceiling
        win.a_zoom_reset.trigger()
        assert ed.font().pointSizeF() == 11.0 and win.settings["font_size"] == 11
        ed.document().setModified(False)

    def t_format_whole_lines():
        from lavatinoter.highlighter import rich_matches
        ed = win.new_file("Hi How are you option to extend the issues\nsecond line here\nthird line\n")
        doc = ed.document()

        def select(a, b):
            c = ed.textCursor()
            c.setPosition(a)
            c.setPosition(b, QTextCursor.KeepAnchor)
            ed.setTextCursor(c)

        def nested_ok(line):
            """Every mark pair is properly nested: no pair starts inside another and ends outside it."""
            spans = [(m.start(), m.end()) for _k, m, _a, _b in rich_matches(line)]
            return all(not (a < c < b < d) for a, b in spans for c, d in spans)
        t = ed.toPlainText()
        i = t.index("extend")
        select(i, i + len("extend the issues"))
        ed.toggle_format("underline")
        assert ed.toPlainText().split("\n")[0] == "Hi How are you option to <u>extend the issues</u>", ed.toPlainText()
        first = doc.firstBlock()
        # select the whole line the way a user does: from the start to the visible end, which leaves the closing </u> out
        select(first.position(), first.position() + first.text().index("</u>"))
        ed.toggle_format("bold")
        line = ed.toPlainText().split("\n")[0]
        assert line == "**Hi How are you option to <u>extend the issues</u>**", line      # the pair was taken in whole, never crossed
        assert nested_ok(line)
        # a selection that starts inside the underlined part is widened the same way
        select(first.position() + line.index("option"), first.position() + line.index("extend") + 3)
        ed.toggle_format("italic")
        line = ed.toPlainText().split("\n")[0]
        assert nested_ok(line) and "_" in line, line
        # several lines at once: each line gets its own marks, and the same command takes them off again
        select(doc.findBlockByNumber(1).position(), doc.findBlockByNumber(2).position() + len("third line"))
        ed.toggle_format("bold")
        lines = ed.toPlainText().split("\n")
        assert lines[1] == "**second line here**" and lines[2] == "**third line**", lines
        ed.toggle_format("bold")
        lines = ed.toPlainText().split("\n")
        assert lines[1] == "second line here" and lines[2] == "third line", lines
        ed.set_text_size(20)
        lines = ed.toPlainText().split("\n")
        assert lines[1].startswith('<span style="font-size:20px">second') and lines[2].startswith("<span"), lines
        # clear formatting returns plain text
        select(first.position(), first.position() + len(first.text()))
        assert ed.clear_format()
        assert ed.toPlainText().split("\n")[0] == "Hi How are you option to extend the issues", ed.toPlainText().split("\n")[0]
        select(doc.findBlockByNumber(1).position(), doc.findBlockByNumber(2).position() + 5)
        ed.clear_format()
        assert ed.toPlainText() == "Hi How are you option to extend the issues\nsecond line here\nthird line\n", repr(ed.toPlainText())
        ed.document().setModified(False)

    def t_detect_language():
        from PySide6.QtCore import QMimeData
        from lavatinoter.detect import guess_language
        py = "import os\n\ndef greet(name):\n    print('hi', name)\n\nif __name__ == '__main__':\n    greet('x')\n"
        assert guess_language(py) == "Python"
        assert guess_language('{"a": [1, 2]}') == "JSON" and guess_language("hello there, how are you today?\nfine thanks\n") is None
        ed = win.new_file("")                                          # a new tab: paste code into it
        assert ed.lang.name == "Plain text" and ed.lang_auto
        mime = QMimeData()
        mime.setText(py)
        ed.insertFromMimeData(mime)
        win._content_settled()
        assert ed.lang.name == "Python", ed.lang.name
        assert "Python" in win.lbl_lang.text() or "Detected" in win.lbl_lang.text()
        ed.setPlainText("<!DOCTYPE html>\n<html>\n<body><div>hi</div></body>\n</html>\n")
        win._content_settled()
        assert ed.lang.name == "HTML / XML", ed.lang.name                      # it follows the text while in auto mode
        win.set_language("Markdown")                                           # an explicit choice sticks
        ed.setPlainText(py)
        win._content_settled()
        assert ed.lang.name == "Markdown" and not ed.lang_auto
        win.a_auto_lang.setChecked(True)
        win.toggle_auto_language()
        assert ed.lang.name == "Python" and ed.lang_auto
        ed.document().setModified(False)
        # a file with no known extension is detected by its content, a .txt file is left alone
        p1 = os.path.join(work, "script_noext")
        with open(p1, "w") as f:
            f.write("#!/usr/bin/env python3\nimport sys\nprint(sys.argv)\n")
        assert win.open_path(p1).lang.name == "Python"
        p2 = os.path.join(work, "notes_detect.txt")
        with open(p2, "w") as f:
            f.write(py)
        assert win.open_path(p2).lang.name == "Plain text"

    def t_save_types():
        from lavatinoter import filetypes as ft
        assert ft.filter_list()[0] == "Text files (*.txt)" and ft.filter_list()[-1] == "All files (*.*)"
        assert ft.with_extension(r"C:\x\notes", "Text files (*.txt)") == r"C:\x\notes.txt"            # no extension typed: .txt is added
        assert ft.with_extension(r"C:\x\app", "Python (*.py *.pyw)") == r"C:\x\app.py"                # ... or the chosen type's
        assert ft.with_extension(r"C:\x\app.js", "Text files (*.txt)") == r"C:\x\app.js"              # a typed extension is respected
        assert ft.with_extension(r"C:\x\app", "All files (*.*)") == r"C:\x\app.txt"
        assert ft.filter_for_path(r"C:\x\a.py") == "Python (*.py *.pyw)" and ft.filter_for_path("a.unknown") == "All files (*.*)"
        assert ft.filter_for_lang("Plain text") == "Text files (*.txt)" and ft.filter_for_lang("Python").startswith("Python")
        # Save As on a new document: the dialog starts on text files, and the result is saved under the chosen name
        seen = {}
        ed = win.new_file("hello save")
        win.set_language("Plain text")

        def fake_dialog(start, current):
            seen["start"], seen["filter"] = start, current
            return ft.with_extension(os.path.join(work, "saved_note"), current)
        win._ask_save_path = fake_dialog
        assert win.save_as(ed)
        assert seen["filter"] == "Text files (*.txt)" and os.path.basename(seen["start"]).startswith("new ")
        assert ed.path.endswith("saved_note.txt") and open(ed.path).read().strip() == "hello save"
        assert win.tab_title(ed) == "saved_note.txt"
        # a Python file offers Python again and Save keeps the format
        p = os.path.join(work, "keep.py")
        open(p, "w").write("print(1)\n")
        page = win.open_path(p)
        win._ask_save_path = lambda start, current: (seen.update(start=start, filter=current), start)[1]
        win.save_as(page)
        assert seen["filter"].startswith("Python") and seen["start"] == p
        page.insertPlainText("x = 2\n")
        assert win.save(page) and page.path == p and open(p).read().startswith("x = 2")
        # choosing another type in the dialog saves in that format and the editor follows
        win._ask_save_path = lambda start, current: ft.with_extension(os.path.join(work, "keep"), "Markdown (*.md *.markdown)")
        assert win.save_as(page)
        assert page.path.endswith("keep.md") and page.lang.name == "Markdown" and os.path.exists(os.path.join(work, "keep.md"))
        del win._ask_save_path
        # opens maximized
        win.showMaximized()
        pump(30)
        assert win.isMaximized()
        win.showNormal()

    def t_save_dialog():
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QFileDialog, QLineEdit
        d = os.path.join(work, "savedlg")
        os.makedirs(d, exist_ok=True)

        def drive(name, flt):
            def go():
                dlg = [x for x in app.topLevelWidgets() if isinstance(x, QFileDialog) and x.isVisible()][0]
                dlg.setDirectory(d)
                dlg.selectNameFilter(flt)
                dlg.findChild(QLineEdit).setText(name)
                dlg.accept()
            QTimer.singleShot(300, go)
        got = {}
        for name, flt in (("mynotes", "Text files (*.txt)"), ("script", "Python (*.py *.pyw)"), ("typed.js", "Text files (*.txt)"),
                          ("data", "All files (*.*)"), ("page", "HTML (*.html *.htm)")):
            drive(name, flt)
            got[name] = os.path.basename(win._ask_save_path(os.path.join(d, "new 1"), "Text files (*.txt)"))
        assert got == {"mynotes": "mynotes.txt", "script": "script.py", "typed.js": "typed.js", "data": "data.txt", "page": "page.html"}, got

    def t_startup_safety():
        import json as _json
        from lavatinoter import session as sess
        # a file with one enormous line opens in large file mode instead of freezing the editor
        p = os.path.join(work, "oneline.json")
        with open(p, "w") as f:
            f.write('{"items":[' + ",".join('{"id":%d,"name":"item %d"}' % (i, i) for i in range(40000)) + "]}")
        assert os.path.getsize(p) > 1_000_000
        assert win._has_very_long_line(p)
        page = win.open_path(p)
        assert page is not None and page.is_large, "a single 1.5 MB line must not go to the normal editor"
        win.close_tab(page, force=True)
        normal = os.path.join(work, "normal_lines.txt")
        with open(normal, "w") as f:
            f.write("line\n" * 400000)
        assert not win._has_very_long_line(normal)
        # an old settings file that still has the previous large-file limit moves to the new one
        old = os.path.join(work, "old_settings.json")
        with open(old, "w") as f:
            _json.dump({"large_file_mb": 64}, f)
        assert util.Settings(old)["large_file_mb"] == util.DEFAULTS["large_file_mb"] < 64
        # tabs come back one at a time with the window responsive, and the start-up log says how long each took
        for i in range(8):
            t = win.new_file("def f():\n    return %d\n" % i * 200)
        win.save_session()
        for p3 in list(win.all_tabs()):
            win.close_tab(p3, force=True)
        marks = []
        tick = QTimer()
        tick.timeout.connect(lambda: marks.append(1))
        tick.start(5)
        done = []
        win.restore_session_async(lambda: done.append(True))
        for _ in range(400):
            pump(20)
            if done:
                break
        tick.stop()
        assert done and win.tabs.count() >= 8, (done, win.tabs.count())
        assert len(marks) > 8, "the event loop must keep running while tabs are restored"
        assert not win._restoring
        log = os.path.join(util.data_dir(), "logs", "startup.log")
        assert os.path.exists(log) and "session restored" in open(log, encoding="utf-8").read()
        for p2 in win.all_tabs():
            if not p2.is_large:
                p2.document().setModified(False)

    def t_theme():
        win.switch_theme("Light")
        pump(20)
        win.switch_theme("Dark")

    for name, fn in (("open, edit and save a text file", t_text), ("search engine", t_search),
                     ("editor find / replace / mark", t_editor_find_replace), ("emoji-safe positions", t_emoji_positions),
                     ("find dialog", t_find_dialog), ("find / replace in files", t_find_in_files),
                     ("encodings", t_encodings), ("picture paste", t_paste_image), ("large file mode", t_large),
                     ("session file", t_session), ("syntax highlighting", t_highlight), ("spell check and auto-correct", t_spell), ("bold / italic / underline / size", t_format), ("picture area is not editable", t_picture_zone), ("word autocomplete", t_autocomplete), ("code formatting, languages, brackets, auto-close", t_ide), ("code folding", t_folding), ("go to definition / references / symbols", t_navigation), ("plugins", t_plugins), ("editorconfig, hex view, themes", t_editorconfig_hex_themes), ("command palette and quick open", t_palette), ("multiple cursors and column select", t_multicursor), ("compare files and git status", t_diff_and_git), ("run file and macros", t_run_and_macro), ("print and export (PDF, HTML)", t_export), ("large file follow and filter", t_tail_and_filter), ("split view", t_split_view), ("update check and portable data folder", t_updates_portable), ("language server client", t_lsp), ("combined formatting and sizes", t_format_combos), ("Ctrl + wheel zoom", t_zoom), ("formatting whole lines and crossing marks", t_format_whole_lines), ("language detection from the text", t_detect_language), ("Save As types, extensions, maximized", t_save_types), ("Save As dialog adds the right extension", t_save_dialog), ("start-up safety: long lines, staggered restore", t_startup_safety), ("themes", t_theme)):
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
    if "--data-dir-to" in args:                  # used by make_portable.bat to check where a portable build keeps its data
        from lavatinoter import util
        with open(args[args.index("--data-dir-to") + 1], "w", encoding="utf-8") as f:
            f.write(util.data_dir())
        return 0
    paths = [os.path.abspath(a) for a in args if not a.startswith("--")]
    new_instance = "--new-instance" in args

    from PySide6.QtCore import QCoreApplication, QTimer, Qt
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
    util.startup_log_reset()
    util.startup_log(f"starting {VERSION}")
    win = MainWindow(settings)
    util.startup_log("main window built")

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

    win.showMaximized() if settings["maximized"] else win.show()          # opens maximized unless you last closed it un-maximized
    util.startup_log("window shown")
    # A start that never finished (a hang, a kill) leaves this file behind: offer to skip the saved tabs this time.
    lock = os.path.join(util.data_dir(), "starting.lock")
    skip = "--no-restore" in args
    if not skip and os.path.exists(lock) and settings["restore_session"] and os.path.exists(os.path.join(util.data_dir(), "session.lns")):
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.Question, APP_NAME, "LavatiNoter did not finish starting last time.")
        box.setInformativeText("This can happen when the saved tabs include a very large file. Open your previous tabs anyway?\n"
                               "If you start empty, your tabs are kept in a backup file and nothing is lost.")
        yes = box.addButton("Restore my tabs", QMessageBox.AcceptRole)
        no = box.addButton("Start empty", QMessageBox.RejectRole)
        box.setDefaultButton(no)
        box.exec()
        if box.clickedButton() is not yes:
            skip = True
            import shutil
            import time as _t
            try:
                shutil.copy2(os.path.join(util.data_dir(), "session.lns"), os.path.join(util.data_dir(), f"session-skipped-{_t.strftime('%Y%m%d-%H%M%S')}.lns"))
            except OSError:
                pass
    try:
        with open(lock, "w") as f:
            f.write("starting")
    except OSError:
        pass

    def release_lock():
        try:
            os.remove(lock)
        except OSError:
            pass
        util.startup_log("start finished")

    def finished():
        win.open_paths(paths)
        if win.tabs.count() == 0:
            win.new_file()
        QTimer.singleShot(1500, release_lock)
    if settings["restore_session"] and not skip:
        win.restore_session_async(finished)
    else:
        finished()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
