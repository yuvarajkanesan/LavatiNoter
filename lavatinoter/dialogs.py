"""Message dialogs in the app's own style: one stroke icon in a soft badge, a heading, a line of detail and a button row."""
from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)
from PySide6.QtWidgets import QMessageBox

from . import theme

# kind -> glyph colour on a light theme
_COLORS = {"save": None, "trash": "#b42318", "warning": "#b45309", "error": "#c4284a", "info": "#1d4ed8",
           "success": "#15803d", "reload": "#0f766e", "lock": "#4b5563"}


def _tint(kind):
    """(glyph colour, badge colour) for the active theme."""
    base = _COLORS[kind] or theme.c("ACCENT")
    glyph = QColor(base)
    if theme.is_dark():
        glyph = glyph.lighter(150)
    return glyph.name(), theme._mix(glyph.name(), theme.c("PANEL"), 0.16)


def _glyph(p, kind):
    """Draws the icon on a 24 x 24 grid."""
    def line(*pts):
        path = QPainterPath()
        path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
        p.drawPath(path)
    if kind == "save":
        p.drawRoundedRect(QRectF(5, 4, 14, 16), 2.2, 2.2)
        p.drawRect(QRectF(8.5, 4, 6, 4.5))
        p.drawRoundedRect(QRectF(8, 13, 8, 7), 1, 1)
    elif kind == "trash":
        line((4.5, 6.5), (19.5, 6.5))
        line((9, 6.5), (9, 4), (15, 4), (15, 6.5))
        line((6.5, 6.5), (7.5, 20), (16.5, 20), (17.5, 6.5))
        line((10, 10.5), (10, 16.5))
        line((14, 10.5), (14, 16.5))
    elif kind == "warning":
        path = QPainterPath()
        path.moveTo(12, 3.8)
        path.lineTo(21, 19.5)
        path.lineTo(3, 19.5)
        path.closeSubpath()
        p.drawPath(path)
        line((12, 9.5), (12, 14))
        line((12, 16.9), (12, 17.1))
    elif kind == "error":
        p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
        line((9, 9), (15, 15))
        line((15, 9), (9, 15))
    elif kind == "info":
        p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
        line((12, 11), (12, 16.5))
        line((12, 7.8), (12, 7.9))
    elif kind == "success":
        p.drawEllipse(QRectF(3.5, 3.5, 17, 17))
        line((8, 12.3), (11, 15.2), (16, 9.3))
    elif kind == "reload":
        p.drawArc(QRectF(4.5, 4.5, 15, 15), 30 * 16, 300 * 16)
        line((18.6, 4.2), (18.6, 8.4), (14.4, 8.4))
    elif kind == "lock":
        p.drawRoundedRect(QRectF(5.5, 11, 13, 9.5), 2, 2)
        path = QPainterPath()
        path.moveTo(8.5, 11)
        path.lineTo(8.5, 8.5)
        path.arcTo(QRectF(8.5, 5, 7, 7), 180, -180)
        path.lineTo(15.5, 11)
        p.drawPath(path)
        line((12, 15), (12, 17))


def badge_pixmap(kind, size=56, dot=False):
    glyph, bg = _tint(kind)
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(bg))
    p.drawEllipse(QRectF(0, 0, size, size))
    p.save()
    side = size * 0.5
    p.translate((size - side) / 2, (size - side) / 2)
    p.scale(side / 24, side / 24)
    pen = QPen(QColor(glyph), 1.8)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    _glyph(p, kind)
    p.restore()
    if dot:
        p.setPen(QPen(QColor(theme.c("PANEL")), 2))
        p.setBrush(QColor("#c2410c"))
        p.drawEllipse(QRectF(size * 0.74, size * 0.06, 12, 12))
    p.end()
    return pm


class MessageDialog(QDialog):
    def __init__(self, parent, title, heading, text, kind, buttons, default, dot=False):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("msgroot")
        self.setModal(True)
        self.value = None
        self._drag = None
        k = theme.PALETTES[theme.THEME_NAME]
        self.setStyleSheet("QDialog#msgroot { background: transparent; }")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 18, 26, 34)
        card = QFrame()
        card.setObjectName("msgcard")
        card.setStyleSheet(f"QFrame#msgcard {{ background: {k['PANEL']}; border: 1px solid {k['BORDER']}; border-radius: 14px; }} "
                           "QLabel { background: transparent; }")
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(30, 20, 80, 70))
        card.setGraphicsEffect(shadow)
        outer.addWidget(card)
        col = QVBoxLayout(card)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(16, 10, 10, 0)
        hl.setSpacing(8)
        mark = QLabel()
        mark.setPixmap(theme.note_mark_pixmap(16))
        t = QLabel(title)
        tf = QFont(theme.ui_family())
        tf.setPixelSize(13)
        tf.setWeight(QFont.Medium)
        t.setFont(tf)
        t.setStyleSheet(f"color: {k['TEXT']};")
        x = QToolButton()
        x.setIcon(theme.icon("close", k["MUTED"], 16))
        x.setIconSize(QSize(14, 14))
        x.setCursor(Qt.ArrowCursor)
        x.clicked.connect(self.reject)
        hl.addWidget(mark)
        hl.addWidget(t)
        hl.addStretch(1)
        hl.addWidget(x)
        col.addWidget(head)

        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(28, 18, 28, 26)
        bl.setSpacing(18)
        ic = QLabel()
        ic.setPixmap(badge_pixmap(kind, 56, dot))
        ic.setFixedSize(56, 56)
        bl.addWidget(ic, 0, Qt.AlignTop)
        tx = QVBoxLayout()
        tx.setSpacing(4)
        h = QLabel(heading)
        h.setWordWrap(True)
        hf = QFont(theme.ui_family())
        hf.setPixelSize(19)
        hf.setWeight(QFont.Bold)
        h.setFont(hf)
        h.setStyleSheet(f"color: {k['TEXT']};")
        tx.addWidget(h)
        if text:
            d = QLabel(text)
            d.setWordWrap(True)
            d.setTextInteractionFlags(Qt.TextSelectableByMouse)
            df = QFont(theme.ui_family())
            df.setPixelSize(14)
            d.setFont(df)
            d.setStyleSheet(f"color: {k['MUTED']};")
            tx.addWidget(d)
        tx.addStretch(1)
        bl.addLayout(tx, 1)
        col.addWidget(body, 1)

        foot = QFrame()
        foot.setStyleSheet(f"QFrame {{ background: {k['BG']}; border: none; border-top: 1px solid {k['BORDER']}; "
                           "border-bottom-left-radius: 13px; border-bottom-right-radius: 13px; }}")
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(24, 16, 24, 16)
        fl.setSpacing(10)
        fl.addStretch(1)
        self._buttons = []
        for i, (label, value, style) in enumerate(buttons):
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(40)
            b.setStyleSheet(self._button_qss(style, k))
            b.clicked.connect(lambda _=False, v=value: self._done(v))
            if i == default:
                b.setDefault(True)
                b.setAutoDefault(True)
            fl.addWidget(b)
            self._buttons.append(b)
        col.addWidget(foot)
        self.setFixedWidth(580)
        self._focus = self._buttons[default] if 0 <= default < len(self._buttons) else None
        self._head = head
        self.layout().activate()
        self.setFixedHeight(self.layout().totalHeightForWidth(580) if self.layout().hasHeightForWidth() else self.sizeHint().height())

    @staticmethod
    def _button_qss(style, k):
        base = "QPushButton { border-radius: 8px; padding: 8px 22px; font-weight: 600; %s } QPushButton:hover { %s } QPushButton:focus { %s }"
        if style == "primary":
            return base % (f"background: {k['ACCENT']}; color: {k['ON_ACCENT']}; border: 1px solid {k['ACCENT']};",
                           f"background: {k['ACCENT_HOVER']};", "outline: none;")
        if style == "danger":
            return base % ("background: #b42318; color: #ffffff; border: 1px solid #b42318;", "background: #9a1d14;", "outline: none;")
        color = "#b42318" if style == "dangertext" else k["TEXT"]
        return base % (f"background: {k['PANEL']}; color: {color}; border: 1px solid {k['BORDER2']};",
                       f"background: {k['HOVER']};", "outline: none;")

    def _done(self, value):
        self.value = value
        self.accept()

    def showEvent(self, e):
        super().showEvent(e)
        par = self.parentWidget().window() if self.parentWidget() else None
        if par is not None and par.isVisible():
            c = par.geometry().center()
            self.move(c.x() - self.width() // 2, c.y() - self.height() // 2)
        if self._focus is not None:
            self._focus.setFocus()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._head.geometry().translated(26, 18).contains(e.position().toPoint()):
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        self._drag = None


def show(parent, title, heading, text="", kind="info", buttons=(("OK", "ok", "primary"),), default=0, dot=False, cancel=None):
    """Shows the dialog; returns the value of the button that was clicked, or `cancel` when it was closed with Esc or the X."""
    d = MessageDialog(parent, title, heading, text, kind, list(buttons), default, dot)
    return d.value if d.exec() == QDialog.Accepted else cancel


# ---- drop-in replacements for the QMessageBox static helpers --------------------------------------------------------------------
_STD = (("Save", QMessageBox.Save), ("Yes", QMessageBox.Yes), ("OK", QMessageBox.Ok), ("Discard", QMessageBox.Discard),
        ("No", QMessageBox.No), ("Cancel", QMessageBox.Cancel))


def _split(text):
    head, _, rest = text.strip().partition("\n")
    return head.strip(), rest.strip()


def _standard(parent, title, text, kind, std, default, dot=False, heading=None, detail=None):
    if heading is None:
        heading, detail = _split(text)
    buttons, def_i = [], 0
    for label, flag in _STD:
        if std & flag:
            if flag == default:
                def_i = len(buttons)
            style = "dangertext" if flag == QMessageBox.Discard else "normal"
            buttons.append((label, flag, style))
    for i, (label, flag, style) in enumerate(buttons):
        if i == def_i:
            buttons[i] = (label, flag, "primary")
    cancel = QMessageBox.Cancel if std & QMessageBox.Cancel else QMessageBox.No if std & QMessageBox.No else QMessageBox.Ok
    return show(parent, title, heading, detail or "", kind, buttons, def_i, dot, cancel)


def information(parent, title, text, kind="info"):
    return _standard(parent, title, text, kind, QMessageBox.Ok, QMessageBox.Ok)


def warning(parent, title, text, std=QMessageBox.Ok, default=QMessageBox.Ok):
    return _standard(parent, title, text, "warning", std, default)


def critical(parent, title, text):
    return _standard(parent, title, text, "error", QMessageBox.Ok, QMessageBox.Ok)


def question(parent, title, text, std=QMessageBox.Yes | QMessageBox.No, default=QMessageBox.NoButton, kind=None, heading=None, detail=None):
    if kind is None:
        kind = "save" if std & QMessageBox.Save else "warning"
    return _standard(parent, title, text, kind, std, default, dot=(kind == "save"), heading=heading, detail=detail)
