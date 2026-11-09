"""The Insert Table dialog: size, header row, a style and an alignment for every column, with a live preview."""
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from . import tablemodel as tm
from . import theme

STYLE_NAMES = (("Markdown pipe table", "markdown"), ("ASCII box  +---+", "ascii"), ("Unicode box  ┌─┬─┐", "unicode"),
               ("Plain, tab / space aligned", "plain"))
PREVIEW_ROWS, PREVIEW_COLS = 12, 8


class TableDialog(QDialog):
    def __init__(self, parent=None, style="markdown"):
        super().__init__(parent)
        self.setWindowTitle("Insert table")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.cols, self.rows = QSpinBox(), QSpinBox()
        self.cols.setRange(1, 100)
        self.cols.setValue(3)
        self.rows.setRange(1, 5000)
        self.rows.setValue(3)
        self.header = QCheckBox("Header row")
        self.header.setChecked(True)
        self.style = QComboBox()
        for label, key in STYLE_NAMES:
            self.style.addItem(label, key)
        self.style.setCurrentIndex(max(0, [k for _l, k in STYLE_NAMES].index(style)) if style in [k for _l, k in STYLE_NAMES] else 0)
        form.addRow("Columns", self.cols)
        form.addRow("Rows (below the header)", self.rows)
        form.addRow("", self.header)
        form.addRow("Style", self.style)
        lay.addLayout(form)
        lay.addWidget(QLabel("Alignment of each column"))
        self.align_host = QWidget()
        self.align_row = QHBoxLayout(self.align_host)
        self.align_row.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(58)
        scroll.setWidget(self.align_host)
        lay.addWidget(scroll)
        self.align_boxes = []
        lay.addWidget(QLabel("Preview"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        f = QFont(theme.mono_family(), 11)
        f.setStyleHint(QFont.Monospace)
        self.preview.setFont(f)
        self.preview.setMinimumHeight(170)
        lay.addWidget(self.preview)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.cols.valueChanged.connect(self._columns_changed)
        for w in (self.rows,):
            w.valueChanged.connect(self._refresh)
        self.header.toggled.connect(self._refresh)
        self.style.currentIndexChanged.connect(self._refresh)
        self._columns_changed()

    def _columns_changed(self):
        n = self.cols.value()
        while len(self.align_boxes) < n:
            cb = QComboBox()
            for name in tm.ALIGNS:
                cb.addItem(name.capitalize(), name)
            cb.currentIndexChanged.connect(self._refresh)
            self.align_boxes.append(cb)
            self.align_row.addWidget(cb)
        while len(self.align_boxes) > n:
            cb = self.align_boxes.pop()
            self.align_row.removeWidget(cb)
            cb.deleteLater()
        self._refresh()

    def aligns(self):
        return [cb.currentData() for cb in self.align_boxes]

    def values(self):
        """(columns, rows below the header, header, style, aligns)."""
        return self.cols.value(), self.rows.value(), self.header.isChecked(), self.style.currentData(), self.aligns()

    def _refresh(self, *_):
        cols, rows, header, style, aligns = self.values()
        c, r = min(cols, PREVIEW_COLS), min(rows, PREVIEW_ROWS)
        model = tm.TableModel.blank(r + (1 if header else 0), c, header, aligns[:c], style)
        text = model.render().rstrip("\n")
        more = []
        if cols > c:
            more.append(f"{cols - c} more columns")
        if rows > r:
            more.append(f"{rows - r} more rows")
        self.preview.setPlainText(text + (f"\n… {', '.join(more)}" if more else ""))
