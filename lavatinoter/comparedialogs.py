"""Windows around the compare window: three-way merge setup, folder compare, and compare for files too big to load."""
import os

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import comparecore as cc
from . import dialogs, foldercmp, theme, util
from .diffview import Side, file_side

FILE_CHOICE = "File on disk..."


class SourceRow(QHBoxLayout):
    """One input of a merge: an open tab, or a file picked from disk."""

    def __init__(self, parent, tabs, start_dir):
        super().__init__()
        self.parent_widget, self.start_dir = parent, start_dir
        self.box = QComboBox()
        self.box.setMinimumWidth(320)
        self.tabs = tabs                                    # [(label, Side factory)]
        for label, _make in tabs:
            self.box.addItem(label)
        self.box.addItem(FILE_CHOICE)
        self.file_side = None
        self.box.activated.connect(self._activated)
        self.addWidget(self.box, 1)

    def _activated(self, i):
        if self.box.itemText(i) != FILE_CHOICE:
            return
        path, _ = QFileDialog.getOpenFileName(self.parent_widget, "Choose a file", self.start_dir, "All files (*.*)")
        if not path:
            self.box.setCurrentIndex(0)
            return
        try:
            self.file_side = file_side(path)
        except OSError as e:
            dialogs.warning(self.parent_widget, "Open", str(e))
            self.box.setCurrentIndex(0)
            return
        self.box.setItemText(i, os.path.basename(path))
        self.box.addItem(FILE_CHOICE)

    def side(self):
        i = self.box.currentIndex()
        if i < len(self.tabs):
            return self.tabs[i][1]()
        return self.file_side


class MergeSetupDialog(QDialog):
    """Asks for the common ancestor and the two edited versions of a three-way merge."""

    def __init__(self, parent, tabs, start_dir=""):
        super().__init__(parent)
        self.setWindowTitle("Three-way Merge")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Pick the original (common ancestor) and the two versions that were edited from it.\n"
                             "Changes only one side made are taken automatically; changes both sides made to the same lines are conflicts."))
        form = QFormLayout()
        self.rows = {}
        for key, label, pos in (("base", "Original (base):", 0), ("left", "Left version:", 1), ("right", "Right version:", 2)):
            row = SourceRow(self, tabs, start_dir)
            if tabs:
                row.box.setCurrentIndex(min(pos, len(tabs) - 1))
            self.rows[key] = row
            form.addRow(label, row)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Merge")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.result_sides = None

    def _accept(self):
        sides = {k: r.side() for k, r in self.rows.items()}
        if any(s is None for s in sides.values()):
            dialogs.information(self, "Three-way Merge", "Choose a document or a file for each of the three inputs.")
            return
        self.result_sides = sides
        self.accept()


STATUS_COLORS = {foldercmp.DIFFERENT: "ORANGE", foldercmp.LEFT_ONLY: "RED", foldercmp.RIGHT_ONLY: "ACCENT"}


class _FolderWorker(QObject):
    done = Signal(list)

    def __init__(self, left, right, options, recursive):
        super().__init__()
        self.args = (left, right, options, recursive)
        self.stop = False

    def run(self):
        left, right, options, recursive = self.args
        try:
            self.done.emit(foldercmp.compare_folders(left, right, options, recursive, cancelled=lambda: self.stop))
        except OSError:
            self.done.emit([])


class FolderCompareDialog(QDialog):
    """Compares two folders; double-clicking a file that differs opens the two files in the compare window."""

    def __init__(self, parent, host, left="", right="", options=None):
        super().__init__(parent)
        self.host, self.options = host, options or cc.Options()
        self.entries, self.thread, self.worker = [], None, None
        self.setWindowTitle("Compare Folders")
        self.resize(900, 600)
        lay = QVBoxLayout(self)
        self.left_edit, self.right_edit = QLineEdit(left), QLineEdit(right)
        for edit, label in ((self.left_edit, "Left folder:"), (self.right_edit, "Right folder:")):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(edit, 1)
            b = QPushButton("Browse...")
            b.clicked.connect(lambda _=False, e=edit: self._browse(e))
            row.addWidget(b)
            lay.addLayout(row)
        opts = QHBoxLayout()
        self.sub_cb = QCheckBox("Include subfolders")
        self.sub_cb.setChecked(True)
        self.ignore_cb = QCheckBox("Ignore white space and case differences")
        self.same_cb = QCheckBox("Show identical files")
        self.same_cb.toggled.connect(self._fill)
        for w in (self.sub_cb, self.ignore_cb, self.same_cb):
            opts.addWidget(w)
        opts.addStretch(1)
        self.go_btn = QPushButton("Compare")
        self.go_btn.clicked.connect(self.start)
        self.report_btn = QPushButton("Save report...")
        self.report_btn.clicked.connect(self.save_report)
        opts.addWidget(self.go_btn)
        opts.addWidget(self.report_btn)
        lay.addLayout(opts)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Name", "Status", "Left size", "Right size"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setColumnWidth(0, 460)
        self.tree.itemDoubleClicked.connect(self._open_item)
        lay.addWidget(self.tree, 1)
        self.status = QLabel("Choose two folders and press Compare. Double-click a file to compare its two versions.")
        lay.addWidget(self.status)
        self.dir_label = None

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "Choose a folder", edit.text() or getattr(self.host, "default_directory", lambda: "")())
        if d:
            edit.setText(d)

    def _effective_options(self):
        if not self.ignore_cb.isChecked():
            return None
        o = cc.Options.from_dict(self.options.to_dict())
        o.ws = "amount" if o.ws == "none" else o.ws
        o.ignore_case = True
        return o

    def start(self):
        left, right = self.left_edit.text().strip(), self.right_edit.text().strip()
        if not (os.path.isdir(left) and os.path.isdir(right)):
            self.status.setText("Both folders must exist.")
            return
        self.go_btn.setEnabled(False)
        self.status.setText("Comparing...")
        self.thread = QThread(self)
        self.worker = _FolderWorker(left, right, self._effective_options(), self.sub_cb.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self.worker.deleteLater)
        self.worker.done.connect(self._finished)
        self.thread.start()

    def _finished(self, entries):
        self.thread.quit()
        self.thread.wait(2000)
        self.entries = entries
        self.go_btn.setEnabled(True)
        c = foldercmp.summary(entries)
        self.status.setText(f"{c[foldercmp.DIFFERENT]} different, {c[foldercmp.LEFT_ONLY]} only in left, "
                            f"{c[foldercmp.RIGHT_ONLY]} only in right, {c[foldercmp.SAME]} identical")
        self._fill()

    @staticmethod
    def _size(n):
        return "" if n < 0 else f"{n:,} bytes"

    def _fill(self, *_):
        self.tree.clear()
        for e in self.entries:
            if e.status == foldercmp.SAME and not self.same_cb.isChecked():
                continue
            it = QTreeWidgetItem([e.rel + ("/" if e.is_dir else ""), e.status, self._size(e.left_size), self._size(e.right_size)])
            it.setData(0, Qt.UserRole, e.rel)
            col = STATUS_COLORS.get(e.status)
            if col:
                it.setForeground(1, QColor(theme.c(col)))
            self.tree.addTopLevelItem(it)

    def _open_item(self, item, _col=0):
        entry = next((e for e in self.entries if e.rel == item.data(0, Qt.UserRole)), None)
        if entry is None or entry.is_dir or entry.status in (foldercmp.LEFT_ONLY, foldercmp.RIGHT_ONLY):
            return
        pa, pb = os.path.join(self.left_edit.text(), entry.rel), os.path.join(self.right_edit.text(), entry.rel)
        try:
            left, right = file_side(pa), file_side(pb)
        except OSError as e:
            dialogs.warning(self, "Open", str(e))
            return
        self.host._show_diff(None, None, None, None, left_side=left, right_side=right)

    def save_report(self):
        if not self.entries:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save folder report", "folder-report.txt", "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(foldercmp.report_text(self.left_edit.text(), self.right_edit.text(), self.entries, self.same_cb.isChecked()))

    def done(self, r):
        if self.worker is not None:
            self.worker.stop = True
        if self.thread is not None:
            self.thread.quit()
            self.thread.wait(2000)
        super().done(r)


class _StreamWorker(QObject):
    progress = Signal(float)
    done = Signal(object)

    def __init__(self, a, b, options):
        super().__init__()
        self.a, self.b, self.options = a, b, options
        self.stop = False

    def run(self):
        try:
            res = cc.diff_stream(self.a, self.b, self.options, cancelled=lambda: self.stop, progress=self.progress.emit)
        except OSError as e:
            res = str(e)
        self.done.emit(res)


class LargeCompareWindow(QDialog):
    """Compares files too big for the normal compare window by streaming them and showing only the differing places."""

    def __init__(self, parent, path_a, path_b, options=None, font_size=11):
        super().__init__(parent)
        self.setWindowTitle(f"Large file compare - {os.path.basename(path_a)} vs {os.path.basename(path_b)}")
        self.resize(1000, 650)
        self.paths = (path_a, path_b)
        lay = QVBoxLayout(self)
        self.info = QLabel("Comparing... the files are read as a stream and are never loaded whole.")
        lay.addWidget(self.info)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        lay.addWidget(self.bar)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.NoWrap)
        f = QFont(theme.mono_family())
        f.setPointSize(font_size)
        self.view.setFont(f)
        lay.addWidget(self.view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.save_btn = QPushButton("Save report...")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self.save_report)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        row.addWidget(self.save_btn)
        row.addWidget(close)
        lay.addLayout(row)
        self.text = ""
        self.thread = QThread(self)
        self.worker = _StreamWorker(path_a, path_b, options or cc.Options())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.thread.finished.connect(self.worker.deleteLater)
        self.worker.progress.connect(lambda f: self.bar.setValue(int(f * 1000)))
        self.worker.done.connect(self._finished)
        self.thread.start()

    def _finished(self, res):
        self.thread.quit()
        self.thread.wait(2000)
        self.bar.setVisible(False)
        if isinstance(res, str):
            self.info.setText(res)
            return
        excerpts, total, truncated = res
        self.text = self.render(excerpts, total, truncated)
        self.view.setPlainText(self.text)
        self.save_btn.setEnabled(True)
        self.info.setText("The files are identical." if not total else
                          f"{total:,} difference{'s' if total != 1 else ''}{' (stopped here; there are more)' if truncated else ''}.")

    @staticmethod
    def render(excerpts, total, truncated):
        out = []
        for k, e in enumerate(excerpts, 1):
            label = {"add": "only in right", "del": "only in left", "chg": "changed"}[e["tag"]]
            out.append(f"#{k} {label}  (left line {e['left_start'] + 1}, right line {e['right_start'] + 1})")
            import difflib
            for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, e["left"], e["right"], autojunk=False).get_opcodes():
                if tag == "equal":
                    out += [f"    {l}" for l in e["left"][i1:i2]]
                else:
                    out += [f"  - {l}" for l in e["left"][i1:i2]] + [f"  + {l}" for l in e["right"][j1:j2]]
            out.append("")
        if truncated:
            out.append(f"... more than {total - 1:,} differences; only the first ones are listed.")
        return "\n".join(out)

    def save_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save report", "large-compare.txt", "Text (*.txt)")
        if path:
            util.write_text_file(path, self.text, "UTF-8", "\n")

    def closeEvent(self, e):
        self.worker.stop = True
        self.thread.quit()
        self.thread.wait(3000)
        super().closeEvent(e)
