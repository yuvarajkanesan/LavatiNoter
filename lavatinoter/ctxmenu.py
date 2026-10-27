"""The right-click menu: a floating formatting bar card and, a little below it, the menu card, both with a soft shadow."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget, QWidgetAction

from . import theme

PAD = 14            # the menu's own padding (the widgets sit inside it)
INSET = 8           # where the cards start; the strip between INSET and PAD is the card's inner padding
GAP = 8             # between the bar card and the menu card
RADIUS = 14


def _card(p, rect):
    """A rounded card with a soft shadow, drawn in the active palette."""
    p.setPen(Qt.NoPen)
    for i in range(7, 0, -1):
        p.setBrush(QColor(50, 40, 110, 7))
        p.drawRoundedRect(rect.adjusted(-i, -i + 3, i, i + 3), RADIUS + i, RADIUS + i)
    p.setBrush(QColor(theme.c("PANEL")))
    p.setPen(QPen(QColor(theme.c("BORDER")), 1))
    p.drawRoundedRect(rect, RADIUS, RADIUS)


class BarHost(QWidget):
    """Holds the formatting bar inside the menu; the card behind it is painted by the menu."""

    def __init__(self, bar):
        super().__init__()
        from PySide6.QtWidgets import QVBoxLayout
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, INSET - 2 + 0, 0, INSET - 2 + GAP)
        lay.addWidget(bar)
        self.setAttribute(Qt.WA_TranslucentBackground, True)


class Spacer(QWidget):
    def __init__(self, h):
        super().__init__()
        self.setFixedHeight(h)
        self.setAttribute(Qt.WA_TranslucentBackground, True)


class ContextMenu(QMenu):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bar_action = None
        theme.round_menu(self, floating=True)

    def set_bar(self, bar):
        """Puts the formatting bar at the top as its own card."""
        wa = QWidgetAction(self)
        wa.setDefaultWidget(BarHost(bar))
        self.addAction(wa)
        self.bar_action = wa
        sp = QWidgetAction(self)
        sp.setDefaultWidget(Spacer(PAD - INSET))
        self.addAction(sp)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        top = INSET
        if self.bar_action is not None:
            g = self.actionGeometry(self.bar_action)
            _card(p, QRectF(INSET + 0.5, g.top() - (PAD - INSET) + 0.5, w - 2 * INSET - 1, g.height() - GAP + (PAD - INSET) - 2 + 2))
            top = g.bottom() + 1
        _card(p, QRectF(INSET + 0.5, top + 0.5, w - 2 * INSET - 1, h - INSET - top - 1))
        p.end()
        super().paintEvent(e)
        self._faint_shortcuts()

    def _faint_shortcuts(self):
        """The stylesheet paints shortcuts in the text colour; paint them again, fainter, over the right edge of each row."""
        p = QPainter(self)
        active = self.activeAction()
        maxw = max([p.fontMetrics().horizontalAdvance(a.shortcut().toString()) for a in self.actions()] + [0]) + 8
        for a in self.actions():
            sc = a.shortcut().toString()
            if not sc or a.isSeparator():
                continue
            g = self.actionGeometry(a)
            w = maxw
            r = QRectF(g.right() - INSET - 12 - w, g.top() + 1, w + 4, g.height() - 2)
            p.fillRect(r, QColor(theme.c("HOVER") if a is active and a.isEnabled() else theme.c("PANEL")))
            p.setPen(QColor(theme.c("FAINT")))
            p.drawText(r.adjusted(0, 0, -4, 0), Qt.AlignRight | Qt.AlignVCenter, sc)
        p.end()
