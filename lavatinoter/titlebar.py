"""The window's own title bar (the app icon, the name, the document in the middle and the window buttons)."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QToolButton, QWidget

from . import theme

HEIGHT = 46


class CaptionButton(QToolButton):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind                                  # "min" | "max" | "restore" | "close"
        self.setFixedSize(48, HEIGHT)
        self.setCursor(Qt.ArrowCursor)
        self._hover = False
        self.setStyleSheet("QToolButton { background: transparent; border: none; }")

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        close = self.kind == "close"
        if self._hover:
            p.fillRect(self.rect(), QColor("#e5484d") if close else QColor(theme.c("HOVER")))
        col = QColor("#ffffff") if close and self._hover else QColor(theme.c("TEXT"))
        p.setPen(QPen(col, 1.3))
        c = QPointF(self.width() / 2, self.height() / 2)
        s = 5.0
        if self.kind == "min":
            p.drawLine(QPointF(c.x() - s, c.y()), QPointF(c.x() + s, c.y()))
        elif self.kind == "max":
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(c.x() - s, c.y() - s, 2 * s, 2 * s))
        elif self.kind == "restore":
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(c.x() - s, c.y() - s + 2.5, 2 * s - 2.5, 2 * s - 2.5))
            p.drawPolyline([QPointF(c.x() - s + 2.5, c.y() - s + 2.5), QPointF(c.x() - s + 2.5, c.y() - s), QPointF(c.x() + s, c.y() - s),
                            QPointF(c.x() + s, c.y() + s - 2.5), QPointF(c.x() + s - 2.5, c.y() + s - 2.5)])
        else:
            p.drawLine(QPointF(c.x() - s, c.y() - s), QPointF(c.x() + s, c.y() + s))
            p.drawLine(QPointF(c.x() - s, c.y() + s), QPointF(c.x() + s, c.y() - s))


class TitleBar(QWidget):
    minimize = Signal()
    toggleMaximize = Signal()
    closeWindow = Signal()
    startMove = Signal()

    def __init__(self, window):
        super().__init__()
        self.window_ref = window
        self.setFixedHeight(HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(0)
        left = QWidget()
        left.setFixedWidth(180)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(10)
        self.icon = QLabel()
        self.icon.setFixedSize(28, 28)
        self.name = QLabel("")
        f = QFont(theme.ui_family())
        f.setPixelSize(15)
        f.setWeight(QFont.DemiBold)
        self.name.setFont(f)
        ll.addWidget(self.icon)
        ll.addWidget(self.name)
        ll.addStretch(1)
        self.title = QLabel("")
        self.title.setAlignment(Qt.AlignCenter)
        tf = QFont(theme.ui_family())
        tf.setPixelSize(14)
        tf.setWeight(QFont.Medium)
        self.title.setFont(tf)
        right = QWidget()
        right.setFixedWidth(180)
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addStretch(1)
        self.b_min, self.b_max, self.b_close = CaptionButton("min"), CaptionButton("max"), CaptionButton("close")
        self.b_min.clicked.connect(self.minimize)
        self.b_max.clicked.connect(self.toggleMaximize)
        self.b_close.clicked.connect(self.closeWindow)
        for b in (self.b_min, self.b_max, self.b_close):
            rl.addWidget(b)
        lay.addWidget(left)
        lay.addWidget(self.title, 1)
        lay.addWidget(right)
        self.restyle()

    def restyle(self):
        self.icon.setPixmap(theme.note_mark_pixmap(22))
        self.name.setStyleSheet(f"color: {theme.c('TEXT')}; background: transparent;")
        self.title.setStyleSheet(f"color: {theme.c('MUTED')}; background: transparent;")
        for b in (self.b_min, self.b_max, self.b_close):
            b.update()

    def set_title(self, text):
        text = text.replace(" — LavatiNoter", "")
        self.title.setText(text[len("Compare: "):] if text.startswith("Compare: ") else text)

    def set_name(self, text):
        self.name.setText(text)

    def set_maximized(self, on):
        self.b_max.kind = "restore" if on else "max"
        self.b_max.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.startMove.emit()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.toggleMaximize.emit()
