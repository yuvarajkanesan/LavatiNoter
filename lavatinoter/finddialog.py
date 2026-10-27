"""The Find / Replace / Find in Files / Mark dialog and the editor operations behind it."""
import bisect
import os
import re

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QTabBar,
                               QVBoxLayout, QWidget)

from . import dialogs, search, theme


from .finddialog_pos import PosMap  # noqa: E402


def editor_find(ed, o, backward=None):
    """Finds the next match and selects it. -> True / False, raises SearchError."""
    rx = search.compile_pattern(o)
    text = ed.toPlainText()
    pm = PosMap(text)
    back = o.backward if backward is None else backward
    cur = ed.textCursor()
    start = pm.to_py(cur.selectionStart() if back else cur.selectionEnd())
    m = search.find_next(rx, text, start, back, o.wrap)
    if m is None:
        return False
    ed.select_range(pm.to_q(m.start()), pm.to_q(m.end()) - pm.to_q(m.start()))
    return True


def editor_replace_current(ed, o):
    """Replaces the selection if it is a match, then moves on to the next one. -> number replaced (0 or 1)."""
    rx = search.compile_pattern(o)
    cur = ed.textCursor()
    text = ed.toPlainText()
    pm = PosMap(text)
    done = 0
    if cur.hasSelection():
        s, e = pm.to_py(cur.selectionStart()), pm.to_py(cur.selectionEnd())
        m = rx.match(text, s)
        if m and m.end() == e:
            cur.insertText(search.expand_replacement(o, m))
            ed.setTextCursor(cur)
            done = 1
    editor_find(ed, o, backward=False if not o.backward else True)
    return done


def editor_replace_all(ed, o):
    text = ed.toPlainText()
    new, n = search.replace_all(o, text)
    if n:
        cur = ed.textCursor()
        line, col = cur.blockNumber(), cur.positionInBlock()
        bar = ed.verticalScrollBar().value()
        cur.beginEditBlock()
        cur.select(QTextCursor.Document)
        cur.insertText(new)
        cur.endEditBlock()
        ed.goto_line(line + 1, col)
        ed.verticalScrollBar().setValue(bar)
    return n


def editor_hits(ed, o):
    rx = search.compile_pattern(o)
    return search.hits_in_text(rx, ed.toPlainText())


def editor_mark_all(ed, o):
    rx = search.compile_pattern(o)
    text = ed.toPlainText()
    pm = PosMap(text)
    marks = []
    for m in rx.finditer(text):
        if m.end() > m.start():
            marks.append((pm.to_q(m.start()), pm.to_q(m.end()) - pm.to_q(m.start())))
        if len(marks) >= 20000:
            break
    ed.marks = marks
    ed.refresh_selections()
    return marks


class FilesSearchThread(QThread):
    progress = Signal(int)
    done = Signal(list, int, bool)           # results, files searched, cancelled
    failed = Signal(str)

    def __init__(self, opts, parent=None):
        super().__init__(parent)
        self.opts = opts
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        results, count = [], [0]
        try:
            total_hits = 0
            for r in search.search_files(self.opts, lambda: self._cancel, lambda n: (count.__setitem__(0, n), self.progress.emit(n))):
                results.append(r)
                total_hits += len(r.hits)
                if total_hits > search.MAX_HITS:
                    break
        except search.SearchError as e:
            self.failed.emit(str(e))
            return
        self.done.emit(results, count[0], self._cancel)


class FindDialog(QDialog):
    TABS = ["Find", "Replace", "Find in Files", "Mark"]

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Find")
        self.setWindowFlag(Qt.Tool, True)
        self.setModal(False)
        self.setMinimumWidth(780)
        self.thread = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.bar = QTabBar()
        self.bar.setExpanding(False)
        self.bar.setDrawBase(False)
        for t in self.TABS:
            self.bar.addTab(t)
        self.bar.currentChanged.connect(self._set_tab)
        outer.addWidget(self.bar)
        body = QWidget()
        outer.addWidget(body)
        grid = QGridLayout(body)
        grid.setContentsMargins(18, 16, 18, 14)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)

        def label(text):
            lab = QLabel(text)
            lab.setProperty("muted", True)
            return lab
        self.find_box = QComboBox(editable=True)
        self.repl_box = QComboBox(editable=True)
        for b in (self.find_box, self.repl_box):
            b.setInsertPolicy(QComboBox.NoInsert)
            b.setMaxCount(25)
        self.find_box.lineEdit().returnPressed.connect(lambda: self.primary())
        self.repl_box.lineEdit().returnPressed.connect(lambda: self.primary())
        self.filters = QLineEdit("*.*")
        self.directory = QLineEdit()
        self.browse = QPushButton("...")
        self.browse.setFixedWidth(40)
        self.browse.clicked.connect(self._browse)
        self.labels = {k: label(k) for k in ("Find what", "Replace with", "Filters", "Directory")}
        grid.addWidget(self.labels["Find what"], 0, 0)
        grid.addWidget(self.find_box, 0, 1, 1, 2)
        grid.addWidget(self.labels["Replace with"], 1, 0)
        grid.addWidget(self.repl_box, 1, 1, 1, 2)
        grid.addWidget(self.labels["Filters"], 2, 0)
        grid.addWidget(self.filters, 2, 1, 1, 2)
        grid.addWidget(self.labels["Directory"], 3, 0)
        grid.addWidget(self.directory, 3, 1)
        grid.addWidget(self.browse, 3, 2)

        # search mode + options
        opts = QWidget()
        og = QGridLayout(opts)
        og.setContentsMargins(0, 8, 0, 0)
        og.setHorizontalSpacing(30)
        og.setVerticalSpacing(6)
        mode_lab = QLabel("SEARCH MODE")
        mode_lab.setProperty("heading", True)
        opt_lab = QLabel("OPTIONS")
        opt_lab.setProperty("heading", True)
        og.addWidget(mode_lab, 0, 0)
        og.addWidget(opt_lab, 0, 1)
        self.mode_normal = QRadioButton("Normal")
        self.mode_ext = QRadioButton("Extended (\\n, \\r, \\t, \\0)")
        self.mode_re = QRadioButton("Regular expression")
        self.mode_normal.setChecked(True)
        self.dotall = QCheckBox(". matches newline")
        self.dotall.setEnabled(False)
        self.mode_re.toggled.connect(self.dotall.setEnabled)
        for r in (self.mode_normal, self.mode_ext, self.mode_re):
            r.setCursor(Qt.PointingHandCursor)
        og.addWidget(self.mode_normal, 1, 0)
        og.addWidget(self.mode_ext, 2, 0)
        og.addWidget(self.mode_re, 3, 0)
        og.addWidget(self.dotall, 4, 0)
        self.backward = QCheckBox("Backward direction")
        self.whole = QCheckBox("Match whole word only")
        self.case = QCheckBox("Match case")
        self.wrap = QCheckBox("Wrap around")
        self.subs = QCheckBox("In all sub-folders")
        self.hidden = QCheckBox("Skip hidden files and folders")
        self.wrap.setChecked(True)
        self.subs.setChecked(True)
        self.hidden.setChecked(True)
        for i, cb in enumerate((self.backward, self.whole, self.case, self.wrap, self.subs, self.hidden)):
            og.addWidget(cb, 1 + i, 1)
        grid.addWidget(opts, 4, 0, 1, 3)

        # buttons
        self.btns = {}
        col = QVBoxLayout()
        col.setSpacing(8)
        spec = [("next", "Find Next", self.find_next, True), ("count", "Count", self.count, False),
                ("all_cur", "Find All in Current", self.find_all_current, False),
                ("all_open", "Find All in Opened", self.find_all_opened, False),
                ("files", "Find All in Files", self.find_in_files, False),
                ("replace", "Replace", self.replace, False), ("replace_all", "Replace All", self.replace_all, False),
                ("replace_open", "Replace All in Opened", self.replace_all_opened, False),
                ("replace_files", "Replace in Files", self.replace_in_files, False),
                ("mark", "Mark All", self.mark_all, True), ("clear", "Clear all marks", self.clear_marks, False),
                ("copy", "Copy marked text", self.copy_marked, False), ("stop", "Stop", self.stop, False)]
        for key, text, fn, primary in spec:
            b = QPushButton(text)
            b.setProperty("primary", primary)
            b.clicked.connect(lambda _=False, f=fn: f())
            self.btns[key] = b
            col.addWidget(b)
        col.addStretch()
        grid.addLayout(col, 0, 3, 5, 1)
        self.status = QLabel("")
        self.status.setProperty("muted", True)
        self.status.setWordWrap(True)
        grid.addWidget(self.status, 5, 0, 1, 4)
        grid.setColumnStretch(1, 1)
        self.layout_for = {
            0: dict(rows=["Find what"], btns=["next", "count", "all_cur", "all_open"]),
            1: dict(rows=["Find what", "Replace with"], btns=["next", "count", "all_cur", "all_open", "replace", "replace_all", "replace_open"]),
            2: dict(rows=["Find what", "Replace with", "Filters", "Directory"], btns=["files", "replace_files", "stop"]),
            3: dict(rows=["Find what"], btns=["mark", "clear", "copy"]),
        }
        self._set_tab(0)

    # ---- tab handling ---------------------------------------------------------------------------------------------
    def _set_tab(self, i):
        spec = self.layout_for[i]
        for name, lab in self.labels.items():
            on = name in spec["rows"]
            lab.setVisible(on)
        self.repl_box.setVisible("Replace with" in spec["rows"])
        self.filters.setVisible("Filters" in spec["rows"])
        self.directory.setVisible("Directory" in spec["rows"])
        self.browse.setVisible("Directory" in spec["rows"])
        for key, b in self.btns.items():
            b.setVisible(key in spec["btns"])
        in_files = i == 2
        self.subs.setVisible(in_files)
        self.hidden.setVisible(in_files)
        self.backward.setVisible(i in (0, 1))
        self.wrap.setVisible(i in (0, 1))
        self.setWindowTitle(self.TABS[i])
        if self.bar.currentIndex() != i:
            self.bar.setCurrentIndex(i)
        self.status.setText("")
        self.adjustSize()

    def show_tab(self, i, text=None, directory=None):
        self._set_tab(i)
        if text:
            self.find_box.setEditText(text)
        if directory:
            self.directory.setText(directory)
        elif i == 2 and not self.directory.text():
            self.directory.setText(self.win.default_directory())
        self.show()
        self.raise_()
        self.activateWindow()
        self.find_box.setFocus()
        self.find_box.lineEdit().selectAll()
        g = self.win.geometry()
        if not self.property("placed"):
            self.move(g.right() - self.width() - 40, g.top() + 110)
            self.setProperty("placed", True)

    def primary(self):
        i = self.bar.currentIndex()
        {0: self.find_next, 1: self.find_next, 2: self.find_in_files, 3: self.mark_all}[i]()

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Search in folder", self.directory.text() or os.path.expanduser("~"))
        if d:
            self.directory.setText(d)

    # ---- options -------------------------------------------------------------------------------------------------------
    def options(self):
        o = search.Options()
        o.text = self.find_box.currentText()
        o.replacement = self.repl_box.currentText()
        o.mode = search.REGEX if self.mode_re.isChecked() else search.EXTENDED if self.mode_ext.isChecked() else search.NORMAL
        o.match_case = self.case.isChecked()
        o.whole_word = self.whole.isChecked()
        o.wrap = self.wrap.isChecked()
        o.backward = self.backward.isChecked()
        o.dotall = self.dotall.isChecked()
        o.filters = self.filters.text().strip() or "*.*"
        o.directory = self.directory.text().strip()
        o.subfolders = self.subs.isChecked()
        o.skip_hidden = self.hidden.isChecked()
        return o

    def _remember(self):
        for box in (self.find_box, self.repl_box):
            t = box.currentText()
            if t and box.findText(t) < 0:
                box.insertItem(0, t)
            box.setEditText(t)

    def _say(self, text, error=False):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.c('RED') if error else theme.c('MUTED')};")
        self.win.flash(text)

    def _guard(self, fn):
        try:
            return fn()
        except search.SearchError as e:
            self._say(str(e), True)
            return None

    # ---- actions on the current document ----------------------------------------------------------------------------
    def _target(self):
        return self.win.current()

    def find_next(self, backward=None):
        tab = self._target()
        if tab is None:
            return

        def go():
            o = self.options()
            self._remember()
            if getattr(tab, "is_large", False):
                rx = search.compile_pattern(o)
                self._say("Searching the file...")
                back = o.backward if backward is None else backward
                tab.find(rx, back, o.wrap, lambda ok: self._say("" if ok else "Phrase not found.", not ok))
                return
            if editor_find(tab, o, backward):
                self._say("")
            else:
                self._say("Phrase not found.", True)
        self._guard(go)

    def count(self):
        tab = self._target()
        if tab is None:
            return
        if getattr(tab, "is_large", False):
            self._say("Count is not available in large file mode. Use Find Next.", True)
            return

        def go():
            n = len(editor_hits(tab, self.options()))
            self._say(f"Count: {n} match{'es' if n != 1 else ''} in the current document.")
        self._guard(go)

    def _result_for(self, tab, o):
        hits = editor_hits(tab, o)
        return search.FileResult(self.win.tab_key(tab), hits) if hits else None

    def find_all_current(self):
        tab = self._target()
        if tab is None or getattr(tab, "is_large", False):
            self._say("Find All is not available in large file mode.", True)
            return

        def go():
            o = self.options()
            self._remember()
            r = self._result_for(tab, o)
            self.win.results.show_results(f'Search "{o.text}"', [r] if r else [], 1)
            self.win.show_results_dock()
            self._say(f"{len(r.hits) if r else 0} hits in the current document.")
        self._guard(go)

    def find_all_opened(self):
        def go():
            o = self.options()
            self._remember()
            tabs = [t for t in self.win.all_tabs() if not getattr(t, "is_large", False)]
            res = [r for r in (self._result_for(t, o) for t in tabs) if r]
            self.win.results.show_results(f'Search "{o.text}"', res, len(tabs))
            self.win.show_results_dock()
            self._say(f"{sum(len(r.hits) for r in res)} hits in {len(res)} of {len(tabs)} opened documents.")
        self._guard(go)

    def replace(self):
        tab = self._target()
        if tab is None or getattr(tab, "is_large", False) or tab.isReadOnly():
            self._say("This document is read-only.", True)
            return

        def go():
            o = self.options()
            self._remember()
            editor_replace_current(tab, o)
            self._say("")
        self._guard(go)

    def replace_all(self):
        tab = self._target()
        if tab is None or getattr(tab, "is_large", False) or tab.isReadOnly():
            self._say("This document is read-only.", True)
            return

        def go():
            o = self.options()
            self._remember()
            n = editor_replace_all(tab, o)
            self._say(f"Replaced {n} occurrence{'s' if n != 1 else ''}.")
        self._guard(go)

    def replace_all_opened(self):
        def go():
            o = self.options()
            self._remember()
            total = docs = 0
            for t in self.win.all_tabs():
                if getattr(t, "is_large", False) or t.isReadOnly():
                    continue
                n = editor_replace_all(t, o)
                total += n
                docs += 1 if n else 0
            self._say(f"Replaced {total} occurrence{'s' if total != 1 else ''} in {docs} document{'s' if docs != 1 else ''}.")
        self._guard(go)

    # ---- marks --------------------------------------------------------------------------------------------------------------
    def mark_all(self):
        tab = self._target()
        if tab is None or getattr(tab, "is_large", False):
            self._say("Marking is not available in large file mode.", True)
            return

        def go():
            o = self.options()
            self._remember()
            marks = editor_mark_all(tab, o)
            self._say(f"Marked {len(marks)} match{'es' if len(marks) != 1 else ''}.")
        self._guard(go)

    def clear_marks(self):
        tab = self._target()
        if tab is not None and not getattr(tab, "is_large", False):
            tab.marks = []
            tab.refresh_selections()
            self._say("Marks cleared.")

    def copy_marked(self):
        tab = self._target()
        if tab is None or getattr(tab, "is_large", False) or not tab.marks:
            self._say("Nothing is marked.", True)
            return
        text = tab.toPlainText()
        pm = PosMap(text)
        parts = [text[pm.to_py(s):pm.to_py(s + n)] for s, n in tab.marks]
        QGuiApplication.clipboard().setText("\n".join(parts))
        self._say(f"Copied {len(parts)} marked text{'s' if len(parts) != 1 else ''}.")

    # ---- files ---------------------------------------------------------------------------------------------------------------
    def _check_dir(self, o):
        if not o.directory or not os.path.isdir(o.directory):
            self._say("Choose an existing folder in Directory.", True)
            return False
        return True

    def find_in_files(self):
        def go():
            o = self.options()
            search.compile_pattern(o)
            if not self._check_dir(o):
                return
            self._remember()
            self.stop()
            self.btns["files"].setEnabled(False)
            self._say("Searching...")
            t = FilesSearchThread(o, self)
            t.progress.connect(lambda n: self._say(f"Searching... {n} files"))
            t.failed.connect(lambda m: (self._say(m, True), self.btns["files"].setEnabled(True)))
            t.done.connect(lambda res, n, cancelled: self._files_done(o, res, n, cancelled))
            self.thread = t
            t.start()
        self._guard(go)

    def _files_done(self, o, results, n, cancelled):
        self.btns["files"].setEnabled(True)
        hits = sum(len(r.hits) for r in results)
        self.win.results.show_results(f'Search "{o.text}"', results, n, truncated=hits > search.MAX_HITS)
        self.win.show_results_dock()
        self._say(("Stopped. " if cancelled else "") + f"{hits} hits in {len(results)} files of {n} searched.")

    def stop(self):
        if self.thread is not None and self.thread.isRunning():
            self.thread.cancel()
            self.thread.wait(3000)

    def replace_in_files(self):
        def go():
            o = self.options()
            search.compile_pattern(o)
            if not self._check_dir(o):
                return
            if not dialogs.show(self, "Replace in Files", f"Replace “{o.text}” with “{o.replacement}”?",
                                f"In every {o.filters} file under {o.directory}. This changes the files on disk and cannot be undone. "
                                "Open documents with unsaved changes are skipped.", "warning",
                                (("Cancel", False, "normal"), ("Replace", True, "danger")), 0):
                return
            self._remember()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                paths = list(search.iter_files(o.directory, o.filters, o.subfolders, o.skip_hidden))
                dirty = self.win.modified_paths()
                changed, total, skipped = search.replace_in_files(o, paths, skip=lambda p: os.path.normcase(p) in dirty)
            finally:
                QApplication.restoreOverrideCursor()
            self.win.reload_unmodified(paths)
            self._say(f"Replaced {total} occurrence{'s' if total != 1 else ''} in {changed} file{'s' if changed != 1 else ''}."
                      + (f" {len(skipped)} skipped (binary, too large or unsaved in the editor)." if skipped else ""))
            self.win.results.log(f'Replace in Files: "{o.text}" -> "{o.replacement}": {total} in {changed} files under {o.directory}')
        self._guard(go)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)
