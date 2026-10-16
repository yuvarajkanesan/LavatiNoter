"""Side-by-side file comparison window."""
import difflib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextEdit, QVBoxLayout)

from . import theme

MAX_LINES = 40000


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
    def __init__(self, parent, left_title, right_title, old, new):
        super().__init__(parent)
        self.setWindowTitle(f"Compare: {left_title}  ↔  {right_title}")
        self.setWindowFlag(Qt.Window, True)
        self.resize(1200, 700)
        self.left, self.right, self.kinds, (added, removed, changed) = align(old, new)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        prev_b, next_b = QPushButton("▲ Previous difference"), QPushButton("▼ Next difference")
        prev_b.clicked.connect(lambda: self.step(-1))
        next_b.clicked.connect(lambda: self.step(1))
        top.addWidget(self.summary, 1)
        top.addWidget(prev_b)
        top.addWidget(next_b)
        lay.addLayout(top)
        heads = QHBoxLayout()
        for t in (left_title, right_title):
            lab = QLabel(t)
            lab.setProperty("heading", True)
            heads.addWidget(lab, 1)
        lay.addLayout(heads)
        panes = QHBoxLayout()
        panes.setSpacing(2)
        self.edits = []
        for rows in (self.left, self.right):
            ed = QPlainTextEdit()
            ed.setReadOnly(True)
            ed.setLineWrapMode(QPlainTextEdit.NoWrap)
            ed.setFont(theme.mono(11))
            ed.setPlainText("\n".join("" if r is None else r for r in rows))
            panes.addWidget(ed, 1)
            self.edits.append(ed)
        lay.addLayout(panes, 1)
        a, b = (e.verticalScrollBar() for e in self.edits)
        a.valueChanged.connect(b.setValue)
        b.valueChanged.connect(a.setValue)
        ha, hb = (e.horizontalScrollBar() for e in self.edits)
        ha.valueChanged.connect(hb.setValue)
        hb.valueChanged.connect(ha.setValue)
        self.starts = [i for i, k in enumerate(self.kinds) if k != "same" and (i == 0 or self.kinds[i - 1] == "same")]
        self.cur = -1
        self.summary.setText("The files are identical." if not self.starts else
                             f"{len(self.starts)} difference block{'s' if len(self.starts) != 1 else ''}:  "
                             f"{added} added, {removed} removed, {changed} changed lines")
        self._paint()

    def _paint(self):
        colors = {"add": theme.c("ACCENT_BG"), "del": "#3a1d1d" if theme.is_dark() else "#fbdada", "chg": theme.c("MARK_BG")}
        pad = QColor(theme.c("FAINT"))
        pad.setAlpha(35)
        for side, (ed, rows) in enumerate(zip(self.edits, (self.left, self.right))):
            sels = []
            for i, k in enumerate(self.kinds):
                if k == "same":
                    continue
                s = QTextEdit.ExtraSelection()
                if rows[i] is None:
                    s.format.setBackground(pad)
                else:
                    col = QColor(colors[k])
                    col.setAlpha(150 if k == "chg" else 255)
                    s.format.setBackground(col)
                s.format.setProperty(QTextFormat.FullWidthSelection, True)
                s.cursor = QTextCursor(ed.document().findBlockByNumber(i))
                sels.append(s)
            ed.setExtraSelections(sels)

    def step(self, d):
        if not self.starts:
            return
        self.cur = (self.cur + d) % len(self.starts)
        row = self.starts[self.cur]
        for ed in self.edits:
            c = QTextCursor(ed.document().findBlockByNumber(row))
            ed.setTextCursor(c)
            ed.centerCursor()
