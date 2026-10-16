"""The command palette (Ctrl+Shift+P) and Quick Open (Ctrl+P): one type-to-filter picker with fuzzy matching."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


def fuzzy(query, text):
    """A match score (higher is better) when the characters of `query` appear in order in `text`, else None."""
    if not query:
        return 0
    q, t = query.lower(), text.lower()
    pos, score, last = 0, 0, -2
    for ch in q:
        i = t.find(ch, pos)
        if i < 0:
            return None
        score += 10
        if i == last + 1:
            score += 15                                   # consecutive letters
        if i == 0 or t[i - 1] in " /\\_-.>:":
            score += 12                                   # start of a word or path part
        score -= min(i - pos, 8)
        last, pos = i, i + 1
    if q in t:
        score += 40
    return score - len(t) // 12


class Picker(QDialog):
    """items: [(label, detail, payload)]. `chosen(payload)` is emitted on Enter / double click."""
    chosen = Signal(object)

    def __init__(self, parent, title, placeholder, items_fn, limit=60):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setMinimumWidth(640)
        self.items_fn = items_fn
        self.limit = limit
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        self.box = QLineEdit()
        self.box.setPlaceholderText(placeholder)
        self.box.textChanged.connect(self.refill)
        self.box.returnPressed.connect(self.accept_current)
        lay.addWidget(self.box)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.itemActivated.connect(lambda *_: self.accept_current())
        self.list.itemClicked.connect(lambda *_: self.accept_current())
        lay.addWidget(self.list, 1)
        self.hint = QLabel("")
        self.hint.setProperty("muted", True)
        lay.addWidget(self.hint)
        self.setMinimumHeight(380)
        self.refill()

    def showEvent(self, e):
        super().showEvent(e)
        p = self.parentWidget()
        if p is not None:
            g = p.geometry()
            self.move(g.center().x() - self.width() // 2, g.top() + 90)
        self.box.setFocus()

    def refill(self, *_):
        q = self.box.text()
        rows = self.items_fn(q)
        if rows is None:
            rows = []
        scored = []
        for item in rows:
            label, detail, payload = item[:3]
            s = fuzzy(q, label + " " + detail) if not item[3:4] or not item[3] else 0     # item[3] = "already filtered"
            if s is not None:
                scored.append((s, label, detail, payload))
        if q and not any(len(i) > 3 and i[3] for i in rows):
            scored.sort(key=lambda t: -t[0])
        self.list.clear()
        for s, label, detail, payload in scored[:self.limit]:
            it = QListWidgetItem(f"{label}        {detail}" if detail else label)
            it.setData(Qt.UserRole, payload)
            self.list.addItem(it)
        if self.list.count():
            self.list.setCurrentRow(0)
        self.hint.setText(f"{len(scored)} match{'es' if len(scored) != 1 else ''}" if q else "")

    def accept_current(self):
        it = self.list.currentItem()
        if it is None:
            return
        payload = it.data(Qt.UserRole)
        self.accept()
        QTimer.singleShot(0, lambda: self.chosen.emit(payload))

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.list.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.list.setCurrentRow(max(0, min(self.list.count() - 1, row)))
            return
        if e.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)
