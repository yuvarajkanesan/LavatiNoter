"""Card-style popups that open from the toolbar: line spacing."""
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QToolButton, QVBoxLayout, QWidget)

from . import theme

SPACINGS = (("Single", 1.0, "1.0"), ("Comfortable", 1.15, "1.15"), ("Relaxed", 1.5, "1.5"), ("Double", 2.0, "2.0"))
TABLE_COLS, TABLE_ROWS = 10, 8


def _font(px, weight=QFont.Medium):
    f = QFont(theme.ui_family())
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


class PopupCard(QWidget):
    """A rounded white card with a soft shadow that closes when you click elsewhere."""
    closed = Signal()
    SHADOW = 16

    def __init__(self, parent=None, width=300):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(self.SHADOW, self.SHADOW - 6, self.SHADOW, self.SHADOW + 6)
        self.card = QFrame()
        self.card.setObjectName("popupcard")
        self.card.setStyleSheet(f"QFrame#popupcard {{ background: {theme.c('PANEL')}; border: 1px solid {theme.c('BORDER')}; border-radius: 16px; }}"
                                f"QLabel {{ background: transparent; border: none; }}")
        sh = QGraphicsDropShadowEffect(self.card)
        sh.setBlurRadius(34)
        sh.setOffset(0, 8)
        sh.setColor(QColor(70, 50, 150, 55))
        self.card.setGraphicsEffect(sh)
        outer.addWidget(self.card)
        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(14, 14, 14, 12)
        self.body.setSpacing(2)
        self.card.setFixedWidth(width)

    def separator(self):
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.c('BORDER')}; border: none;")
        self.body.addSpacing(6)
        self.body.addWidget(line)
        self.body.addSpacing(6)

    def show_under(self, button):
        self.adjustSize()
        pos = button.mapToGlobal(QPoint(0, button.height())) - QPoint(self.SHADOW, self.SHADOW - 6 - 4)
        screen = QApplication.screenAt(button.mapToGlobal(QPoint(0, 0))) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        pos.setX(max(area.left(), min(pos.x(), area.right() - self.width())))
        self.move(pos)
        self.show()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.closed.emit()


class Row(QWidget):
    """One clickable line of a popup: optional check mark, text, optional value on the right, optional icon on the left."""
    clicked = Signal()

    def __init__(self, text, value="", checked=False, icon=None, indent=True):
        super().__init__()
        self.text, self.value, self.checked, self.icon, self.indent = text, value, checked, icon, indent
        self._hover = False
        self.setFixedHeight(38)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.checked or self._hover:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.c("ACCENT_BG") if self.checked else theme.c("HOVER")))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(0, 0, 0, 0), 9, 9)
        accent = QColor(theme.c("ACCENT"))
        if self.checked:
            p.setPen(QPen(accent, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolyline([QPointF(15, 19.5), QPointF(19, 23.5), QPointF(26, 14.5)])
        x = 46 if self.indent else 14
        if self.icon is not None:
            self.icon(p, QRectF(14, 8, 22, 22))
            x = 46
        p.setPen(QColor(theme.c("TEXT")))
        p.setFont(_font(15))
        p.drawText(QRectF(x, 0, self.width() - x - 60, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        if self.value:
            p.setPen(QColor(theme.c("MUTED")))
            p.setFont(_font(14))
            p.drawText(QRectF(self.width() - 70, 0, 56, self.height()), Qt.AlignVCenter | Qt.AlignRight, self.value)


class LineSpacingPopup(PopupCard):
    chosen = Signal(float)
    spaceBefore = Signal()
    options = Signal()

    def __init__(self, current=1.0, parent=None):
        super().__init__(parent, 330)
        for name, value, label in SPACINGS:
            row = Row(name, label, checked=abs(value - current) < 0.001)
            row.clicked.connect(lambda v=value: (self.close(), self.chosen.emit(v)))
            self.body.addWidget(row)
        self.separator()
        for text, sig in (("Add space before paragraph", self.spaceBefore), ("Line spacing options...", self.options)):
            row = Row(text, indent=False)
            row.clicked.connect(lambda s=sig: (self.close(), s.emit()))
            self.body.addWidget(row)


def _icon_table(p, r):
    p.drawPixmap(r.toRect(), theme.icon("borders", theme.c("MUTED"), 22).pixmap(22, 22))


class TableGrid(QWidget):
    """Word's table picker: hover to pick columns x rows (rows include the header), click to insert."""
    sizeChanged = Signal(int, int)
    picked = Signal(int, int)
    S = 20
    GAP = 4

    def __init__(self, cols=3, rows=2):
        super().__init__()
        self.cols, self.rows = cols, rows
        self.setMouseTracking(True)
        step = self.S + self.GAP
        self.setFixedSize(TABLE_COLS * step - self.GAP + 4, TABLE_ROWS * step - self.GAP + 4)

    def _cell(self, i, j):
        step = self.S + self.GAP
        return QRectF(2 + i * step, 2 + j * step, self.S, self.S)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for j in range(TABLE_ROWS):
            for i in range(TABLE_COLS):
                on = i < self.cols and j < self.rows
                p.setPen(QPen(QColor(theme.c("ACCENT") if on else theme.c("BORDER")), 1.3))
                p.setBrush(QColor(theme.c("SELECTED") if on else theme.c("PANEL")))
                p.drawRoundedRect(self._cell(i, j), 3, 3)

    def _at(self, pos):
        step = self.S + self.GAP
        i, j = int((pos.x() - 2) // step), int((pos.y() - 2) // step)
        if 0 <= i < TABLE_COLS and 0 <= j < TABLE_ROWS:
            return i + 1, j + 1
        return None

    def mouseMoveEvent(self, e):
        at = self._at(e.position().toPoint())
        if at and at != (self.cols, self.rows):
            self.cols, self.rows = at
            self.sizeChanged.emit(*at)
            self.update()

    def mouseReleaseEvent(self, e):
        at = self._at(e.position().toPoint())
        if at:
            self.picked.emit(*at)


class TablePopup(PopupCard):
    chosen = Signal(int, int)           # columns, rows (the header row counts)
    custom = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, 280)
        self.size_label = QLabel("Insert Table")
        self.size_label.setFont(_font(15, QFont.DemiBold))
        self.size_label.setStyleSheet(f"color: {theme.c('TEXT')}; padding: 2px 2px 8px 2px;")
        self.body.addWidget(self.size_label)
        self.grid = TableGrid()
        self.grid.sizeChanged.connect(lambda c, r: self.size_label.setText(f"Table {c} × {r}"))
        self.grid.picked.connect(lambda c, r: (self.close(), self.chosen.emit(c, r)))
        self.body.addWidget(self.grid)
        self.separator()
        row = Row("Insert Table...", icon=_icon_table)
        row.clicked.connect(lambda: (self.close(), self.custom.emit()))
        self.body.addWidget(row)


class PopupButton(QToolButton):
    """A toolbar button with an icon and a small arrow that opens a card popup; it turns into a lavender pill while open."""

    def __init__(self, icon_name, tip, make_popup):
        super().__init__()
        self.icon_name, self.make_popup, self._open = icon_name, make_popup, False
        self.setToolTip(tip)
        self.setIconSize(QSize(20, 20))
        self.setStyleSheet("QToolButton { padding-right: 18px; }")
        self.setCursor(Qt.PointingHandCursor)
        self.restyle()
        self.clicked.connect(self._toggle)

    def restyle(self):
        self.setIcon(theme.icon(self.icon_name, theme.c("ACCENT") if self._open else theme.c("MUTED"), 20))
        self.update()

    def _toggle(self):
        popup = self.make_popup()
        self._open = True
        self.setProperty("open", True)
        self.restyle()
        popup.closed.connect(self._closed)
        self._popup = popup
        popup.show_under(self)

    def _closed(self):
        self._open = False
        self.setProperty("open", False)
        self.restyle()

    def paintEvent(self, e):
        if self._open:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.c("ACCENT_BG")))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 10, 10)
            p.end()
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.c("ACCENT") if self._open else theme.c("MUTED")), 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x, y = self.width() - 13, self.height() / 2
        if self._open:
            p.drawPolyline([QPointF(x - 3.5, y + 2), QPointF(x, y - 2), QPointF(x + 3.5, y + 2)])
        else:
            p.drawPolyline([QPointF(x - 3.5, y - 2), QPointF(x, y + 2), QPointF(x + 3.5, y - 2)])
        p.end()
