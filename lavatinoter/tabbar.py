"""The document tab bar: file-type badges, a close button that turns into an unsaved dot, edge fades instead of scroll arrows,
middle-click to close, and the tab list popup (find, close empty tabs, close others, reopen)."""
from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTabBar,
                               QTabWidget, QToolButton, QVBoxLayout, QWidget)

from . import theme

FADE = 28


STATE_COLORS = {"dirty": "#e5484d", "saved": "#2e9e5b"}


def badge_icon(is_markdown, size=16, state=None):
    """MD on a tint for Markdown files, a small document for everything else; red when it has unsaved changes, green when saved."""
    from PySide6.QtGui import QIcon
    color = STATE_COLORS.get(state)
    if not is_markdown:
        return theme.icon("file", color or theme.c("FAINT"), size)
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    acc = QColor(color or theme.c("ACCENT"))
    tint = QColor(acc)
    tint.setAlphaF(0.16)
    p.setPen(Qt.NoPen)
    p.setBrush(tint)
    p.drawRoundedRect(QRectF(0, 1, size, size - 2), 4, 4)
    f = QFont(theme.mono_family())
    f.setPixelSize(8)
    f.setBold(True)
    p.setFont(f)
    p.setPen(acc)
    p.drawText(QRectF(0, 1, size, size - 2), Qt.AlignCenter, "MD")
    p.end()
    return QIcon(pm)


class TabClose(QToolButton):
    """20x20 slot at the end of a tab: nothing, an x, or (unsaved and not hovered) an orange dot."""

    def __init__(self, bar, info):
        super().__init__()
        self.bar, self.info = bar, info              # info() -> (dirty, saved, active, tab_hovered)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Close (Ctrl+W)")
        self.setAttribute(Qt.WA_Hover, True)

    def paintEvent(self, e):
        dirty, saved, active, hovered = self.info()
        over = self.underMouse()
        has_dot = dirty or saved
        show_x = over or hovered or (active and not has_dot)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if over:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.c("HOVER")))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 5, 5)
        if has_dot and not show_x:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.c("RED") if dirty else "#2e9e5b"))        # red: unsaved changes, green: saved file
            p.drawEllipse(QRectF(6, 6, 8, 8))
        elif show_x:
            p.setPen(QPen(QColor(theme.c("TEXT") if over else theme.c("MUTED")), 1.5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(7, 7, 13, 13)
            p.drawLine(13, 7, 7, 13)
        p.end()


class TabBar(QTabBar):
    middleClicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.hover = -1
        self._arrows = []

    def hide_arrows(self, keep=()):
        """The strip scrolls with the mouse wheel; the arrow buttons are squeezed to nothing."""
        self._arrows = [b for b in self.findChildren(QToolButton) if b not in keep][:2]
        for b in self._arrows:
            b.setFixedSize(0, 0)
            b.hide()

    def _set_hover(self, i):
        if i != self.hover:
            self.hover = i
            for k in range(self.count()):
                w = self.tabButton(k, QTabBar.RightSide)
                if w is not None:
                    w.update()

    def mouseMoveEvent(self, e):
        self._set_hover(self.tabAt(e.position().toPoint()))
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self._set_hover(-1)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton:
            i = self.tabAt(e.position().toPoint())
            if i >= 0:
                self.middleClicked.emit(i)
                return
        super().mouseReleaseEvent(e)

    def wheelEvent(self, e):
        d = e.angleDelta().y() or e.angleDelta().x()
        if self._arrows and d:
            self._arrows[0 if d > 0 else 1].click()             # the (hidden) arrows still do the scrolling
            e.accept()
            return
        super().wheelEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        n = self.count()
        if not n:
            return
        p = QPainter(self)
        bg = QColor(theme.c("BG"))
        clear = QColor(bg)
        clear.setAlpha(0)
        if self.tabRect(0).left() < 0:
            g = QLinearGradient(0, 0, FADE, 0)
            g.setColorAt(0, bg)
            g.setColorAt(1, clear)
            p.fillRect(0, 0, FADE, self.height(), g)
        if self.tabRect(n - 1).right() > self.width():
            g = QLinearGradient(self.width() - FADE, 0, self.width(), 0)
            g.setColorAt(0, clear)
            g.setColorAt(1, bg)
            p.fillRect(self.width() - FADE, 0, FADE, self.height(), g)
        p.end()


class DocTabs(QTabWidget):
    """The document tabs, built on the custom tab bar."""

    def __init__(self):
        super().__init__()
        self.bar = TabBar()
        self.setTabBar(self.bar)


class TabCorner(QWidget):
    """Right end of the tab bar: [+ when the tabs overflow] [list N v] [panel toggle]."""

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 4, 8, 0)
        lay.setSpacing(2)
        self.lay = lay
        self.listbtn = QToolButton()
        self.listbtn.setToolTip("All open tabs (Ctrl+Alt+B)")
        self.listbtn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.listbtn.setCursor(Qt.PointingHandCursor)
        self.panelbtn = QToolButton()
        self.panelbtn.setToolTip("Show or hide the side panel")
        self.panelbtn.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self.listbtn)
        lay.addWidget(self.panelbtn)
        self.restyle()

    def set_plus(self, plus):
        """Puts the + button at the left of this corner (overflow), or removes it again (None)."""
        old = getattr(self, "_plus", None)
        if old is not None:
            self.lay.removeWidget(old)
        self._plus = plus
        if plus is not None:
            self.lay.insertWidget(0, plus)
            plus.show()

    def set_count(self, n):
        self.listbtn.setText(f" {n}")

    def restyle(self):
        self.listbtn.setIcon(theme.icon("list", theme.c("MUTED"), 18, dropdown=True))
        self.panelbtn.setIcon(theme.icon("minimap", theme.c("MUTED"), 18))


class _Row(QWidget):
    closeClicked = Signal()

    def __init__(self, name, markdown, meta, current):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 6, 0)
        lay.setSpacing(10)
        ico = QLabel()
        ico.setPixmap(badge_icon(markdown).pixmap(16, 16))
        lay.addWidget(ico)
        lab = QLabel(name)
        f = lab.font()
        f.setBold(bool(current))
        lab.setFont(f)
        lay.addWidget(lab, 1)
        m = QLabel(meta)
        color = theme.c("ORANGE") if meta == "unsaved" else theme.c("FAINT")
        m.setStyleSheet(f"color: {color}; font-size: 12px;")
        lay.addWidget(m)
        x = QToolButton()
        x.setText("×")
        x.setFixedSize(22, 22)
        x.setCursor(Qt.PointingHandCursor)
        x.clicked.connect(self.closeClicked)
        lay.addWidget(x)
        for w in (ico, lab, m):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            if w is not ico:
                w.setStyleSheet(w.styleSheet() + "background: transparent;")


class TabListPopup(QFrame):
    """Find, switch to and close any open tab, even with dozens open."""
    chosen = Signal(object)
    closeTab = Signal(object)
    closeEmpty = Signal()
    closeOthers = Signal()
    reopen = Signal()

    def __init__(self, parent, entries, empty_count, can_reopen, reopen_name):
        """entries: [(page, name, is_markdown, meta, is_current)]."""
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.entries = entries
        self.setObjectName("tablist")
        self.setFixedWidth(340)
        self.setStyleSheet(
            f"QFrame#tablist {{ background: {theme.c('PANEL')}; border: 1px solid {theme.c('BORDER')}; border-radius: 10px; }} "
            f"QLabel {{ color: {theme.c('TEXT')}; background: transparent; }} "
            f"QListWidget {{ background: transparent; border: none; outline: none; }} "
            f"QListWidget::item:selected {{ background: {theme.c('HOVER')}; border-radius: 6px; }} "
            f"QPushButton {{ text-align: left; padding: 7px 10px; border: none; border-radius: 6px; background: transparent; color: {theme.c('TEXT')}; }} "
            f"QPushButton:hover {{ background: {theme.c('HOVER')}; }} QPushButton:disabled {{ color: {theme.c('FAINT')}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find an open tab")
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        lay.addWidget(self.search)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.itemActivated.connect(lambda it: self._pick(it))
        self.list.itemClicked.connect(lambda it: self._pick(it))
        lay.addWidget(self.list)
        for page, name, md, meta, cur in entries:
            it = QListWidgetItem(self.list)
            it.setData(Qt.UserRole, page)
            it.setData(Qt.UserRole + 1, name.lower())
            it.setSizeHint(QSize(0, 34))
            row = _Row(name, md, meta, cur)
            row.closeClicked.connect(lambda p=page: self._close(p))
            self.list.setItemWidget(it, row)
            if cur:
                self.list.setCurrentItem(it)
        self.list.setFixedHeight(min(len(entries), 9) * 34 + 4)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {theme.c('BORDER')};")
        lay.addWidget(line)
        for text, sig, enabled in ((f"Close empty untitled tabs ({empty_count})", self.closeEmpty, empty_count > 0),
                                   ("Close other tabs", self.closeOthers, len(entries) > 1),
                                   (f"Reopen {reopen_name}   (Ctrl+Shift+T)" if can_reopen else "Reopen closed tab   (Ctrl+Shift+T)",
                                    self.reopen, can_reopen)):
            b = QPushButton(text)
            b.setEnabled(enabled)
            b.clicked.connect(lambda _=False, s=sig: (self.close(), s.emit()))
            lay.addWidget(b)
        self.search.setFocus()

    def _pick(self, item):
        self.close()
        self.chosen.emit(item.data(Qt.UserRole))

    def _close(self, page):
        self.closeTab.emit(page)
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) is page:
                self.list.takeItem(i)
                break

    def _filter(self, text):
        t = text.strip().lower()
        first = None
        for i in range(self.list.count()):
            it = self.list.item(i)
            hide = bool(t) and t not in it.data(Qt.UserRole + 1)
            it.setHidden(hide)
            if not hide and first is None:
                first = it
        if first is not None:
            self.list.setCurrentItem(first)

    def eventFilter(self, obj, e):
        if obj is self.search and e.type() == QEvent.KeyPress:
            k = e.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                step = 1 if k == Qt.Key_Down else -1
                i = self.list.currentRow()
                while 0 <= i + step < self.list.count():
                    i += step
                    if not self.list.item(i).isHidden():
                        self.list.setCurrentRow(i)
                        break
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                it = self.list.currentItem()
                if it is not None and not it.isHidden():
                    self._pick(it)
                return True
        return super().eventFilter(obj, e)

    def show_under(self, widget):
        self.adjustSize()
        pos = widget.mapToGlobal(QPoint(widget.width() - self.width(), widget.height() + 2))
        self.move(pos)
        self.show()
