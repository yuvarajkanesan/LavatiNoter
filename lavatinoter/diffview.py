"""Side-by-side file comparison with editing: both sides can be changed, differences can be copied across, and the result
can be applied back to the tab or file it came from."""
import difflib

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout)

from . import theme
from .editor import CodeEditor

MAX_LINES = 40000


def opcodes(a_lines, b_lines):
    """The differing blocks only: [(tag, i1, i2, j1, j2)] with tag 'add', 'del' or 'chg'."""
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a_lines, b_lines, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append(({"insert": "add", "delete": "del", "replace": "chg"}[tag], i1, i2, j1, j2))
    return out


def align(old, new):
    """-> (left lines, right lines, kinds, summary). kinds[i] is 'same' | 'add' | 'del' | 'chg' for row i; padding rows are None."""
    a, b = old.split("\n"), new.split("\n")
    if len(a) > MAX_LINES or len(b) > MAX_LINES:
        raise ValueError(f"The files are too long to compare here (limit {MAX_LINES:,} lines).")
    left, right, kinds = [], [], []
    added = removed = changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for x, y in zip(a[i1:i2], b[j1:j2]):
                left.append(x)
                right.append(y)
                kinds.append("same")
        elif tag == "delete":
            for x in a[i1:i2]:
                left.append(x)
                right.append(None)
                kinds.append("del")
            removed += i2 - i1
        elif tag == "insert":
            for y in b[j1:j2]:
                left.append(None)
                right.append(y)
                kinds.append("add")
            added += j2 - j1
        else:
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                left.append(a[i1 + k] if i1 + k < i2 else None)
                right.append(b[j1 + k] if j1 + k < j2 else None)
                kinds.append("chg")
            changed += n
    return left, right, kinds, (added, removed, changed)


class DiffWindow(QDialog):
    """`left_apply` / `right_apply` (optional): callables that take the side's edited text and put it where it came from (a tab, a
    file). A side without one is read-only (for example the committed version in Git)."""

    def __init__(self, parent, left_title, right_title, old, new, left_apply=None, right_apply=None, lang=None, font_size=11,
                 left_apply_label="Apply to its tab", right_apply_label="Apply to its tab"):
        super().__init__(parent)
        self.setWindowTitle(f"Compare: {left_title}  ↔  {right_title}")
        self.setWindowFlag(Qt.Window, True)
        self.resize(1250, 740)
        if len(old.split("\n")) > MAX_LINES or len(new.split("\n")) > MAX_LINES:
            raise ValueError(f"The files are too long to compare here (limit {MAX_LINES:,} lines).")
        self.applies = [left_apply, right_apply]
        self.blocks = []
        self.cur = -1
        self._syncing = False
        self._applied = [old, new]                   # the text each side had when last applied / opened
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        top.addWidget(self.summary, 1)
        for text, tip, fn in (("Previous", "Previous difference", lambda: self.step(-1)),
                              ("Next", "Next difference", lambda: self.step(1)),
                              ("Copy to right", "Replace the right side of this difference with the left side's version", lambda: self.copy_block(True)),
                              ("Copy to left", "Replace the left side of this difference with the right side's version", lambda: self.copy_block(False))):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            top.addWidget(b)
        lay.addLayout(top)
        heads = QHBoxLayout()
        self.apply_btns = []
        for side, (t, label, ap) in enumerate(((left_title, left_apply_label, left_apply), (right_title, right_apply_label, right_apply))):
            row = QHBoxLayout()
            lab = QLabel(t + ("" if ap else "   (read-only)"))
            lab.setProperty("heading", True)
            row.addWidget(lab, 1)
            btn = QPushButton(label)
            btn.setProperty("primary", True)
            btn.setVisible(ap is not None)
            btn.clicked.connect(lambda _=False, s=side: self.apply(s))
            row.addWidget(btn)
            self.apply_btns.append(btn)
            heads.addLayout(row, 1)
        lay.addLayout(heads)
        panes = QHBoxLayout()
        panes.setSpacing(2)
        self.edits = []
        for side, text in enumerate((old, new)):
            ed = CodeEditor()
            ed.apply_font(font_size)
            ed.set_word_wrap(False)
            if lang is not None:
                ed.set_language(lang)
            ed.setPlainText(text)
            ed.document().setModified(False)
            ed.setReadOnly(self.applies[side] is None)
            ed.read_only_window = False
            ed.show_guides = False
            panes.addWidget(ed, 1)
            self.edits.append(ed)
        lay.addLayout(panes, 1)
        # scrolling one side scrolls the other to the matching line
        self.edits[0].verticalScrollBar().valueChanged.connect(lambda v: self._sync(0))
        self.edits[1].verticalScrollBar().valueChanged.connect(lambda v: self._sync(1))
        for a, b in ((0, 1), (1, 0)):
            self.edits[a].horizontalScrollBar().valueChanged.connect(self.edits[b].horizontalScrollBar().setValue)
        self._timer = QTimer(self, singleShot=True, interval=350)
        self._timer.timeout.connect(self.refresh)
        for ed in self.edits:
            ed.document().contentsChanged.connect(self._timer.start)
        self.refresh()

    # ---- the comparison ----------------------------------------------------------------------------------------------
    def _lines(self, side):
        return self.edits[side].toPlainText().split("\n")

    def refresh(self):
        a, b = self._lines(0), self._lines(1)
        if len(a) > MAX_LINES or len(b) > MAX_LINES:
            self.summary.setText("Too long to compare while editing.")
            return
        self.blocks = opcodes(a, b)
        self.starts = [blk[1] for blk in self.blocks]
        added = sum(j2 - j1 for t, i1, i2, j1, j2 in self.blocks if t == "add")
        removed = sum(i2 - i1 for t, i1, i2, j1, j2 in self.blocks if t == "del")
        changed = sum(max(i2 - i1, j2 - j1) for t, i1, i2, j1, j2 in self.blocks if t == "chg")
        self.summary.setText("The two sides are identical." if not self.blocks else
                             f"{len(self.blocks)} difference block{'s' if len(self.blocks) != 1 else ''}:  "
                             f"{added} added, {removed} removed, {changed} changed lines")
        col = {"add": theme.c("ACCENT"), "del": theme.c("RED"), "chg": theme.c("ORANGE")}
        tints = [{}, {}]
        for t, i1, i2, j1, j2 in self.blocks:
            c = QColor(col[t])
            c.setAlpha(80)
            for i in range(i1, i2):
                tints[0][i] = c
            for j in range(j1, j2):
                tints[1][j] = c
        for ed, tint in zip(self.edits, tints):
            ed.line_tint = tint
            ed.refresh_selections()
        if self.cur >= len(self.blocks):
            self.cur = len(self.blocks) - 1

    def _map_line(self, side, line):
        """The line on the other side that matches `line` of `side` (equal stretches line up exactly)."""
        a, b = len(self._lines(0)), len(self._lines(1))
        shift = 0                                           # other = line + shift, accumulated over the blocks above
        for t, i1, i2, j1, j2 in self.blocks:
            s1, s2, o1, o2 = (i1, i2, j1, j2) if side == 0 else (j1, j2, i1, i2)
            if line < s1:
                break
            if line < s2:
                return max(0, min(o1, (a if side == 1 else b) - 1))
            shift = o2 - s2
        return max(0, line + shift)

    def _sync(self, side):
        if self._syncing:
            return
        self._syncing = True
        try:
            first = self.edits[side].firstVisibleBlock().blockNumber()
            other = self.edits[1 - side]
            other.verticalScrollBar().setValue(self._map_line(side, first))
        finally:
            self._syncing = False

    def step(self, d):
        if not self.blocks:
            return
        self.cur = (self.cur + d) % len(self.blocks)
        t, i1, i2, j1, j2 = self.blocks[self.cur]
        for ed, row in zip(self.edits, (i1, j1)):
            c = QTextCursor(ed.document().findBlockByNumber(min(row, ed.blockCount() - 1)))
            ed.setTextCursor(c)
            ed.centerCursor()

    def _current_block(self):
        """The difference the caret is in (else the one last stepped to)."""
        for side in (0, 1):
            if self.edits[side].hasFocus():
                line = self.edits[side].textCursor().blockNumber()
                for k, blk in enumerate(self.blocks):
                    lo, hi = (blk[1], blk[2]) if side == 0 else (blk[3], blk[4])
                    if lo <= line < max(hi, lo + 1):
                        return k
        return self.cur if 0 <= self.cur < len(self.blocks) else None

    # ---- editing -----------------------------------------------------------------------------------------------------------
    def copy_block(self, to_right):
        """Makes the other side's version of the current difference the same as this side's."""
        k = self._current_block()
        if k is None:
            return
        t, i1, i2, j1, j2 = self.blocks[k]
        a, b = self._lines(0), self._lines(1)
        target = 1 if to_right else 0
        if self.edits[target].isReadOnly():
            QMessageBox.information(self, "Compare", "That side is read-only.")
            return
        if to_right:
            new = b[:j1] + a[i1:i2] + b[j2:]
        else:
            new = a[:i1] + b[j1:j2] + a[i2:]
        self.edits[target].replace_document_text("\n".join(new))
        self.refresh()

    def apply(self, side):
        fn = self.applies[side]
        if fn is None:
            return
        text = self.edits[side].toPlainText()
        try:
            fn(text)
        except OSError as e:
            QMessageBox.warning(self, "Compare", f"Could not apply the changes:\n{e}")
            return
        self._applied[side] = text
        base = self.apply_btns[side].text().split("  (done)")[0]
        self.apply_btns[side].setText(base + "  (done)")

    def _unapplied(self):
        return [s for s in (0, 1) if self.applies[s] is not None and self.edits[s].toPlainText() != self._applied[s]]

    def closeEvent(self, e):
        pending = self._unapplied()
        if pending:
            box = QMessageBox(QMessageBox.Question, "Compare", "You changed text in the comparison that is not applied yet.")
            apply_b = box.addButton("Apply and close", QMessageBox.AcceptRole)
            box.addButton("Discard changes", QMessageBox.DestructiveRole)
            cancel = box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is cancel:
                e.ignore()
                return
            if box.clickedButton() is apply_b:
                for s in pending:
                    self.apply(s)
        super().closeEvent(e)
