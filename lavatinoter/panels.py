"""Side and bottom panels: workspace tree, minimap, function list, images, search results, console, document list."""
import math
import os
import subprocess
import sys

from PySide6.QtCore import QDir, QFileInfo, QModelIndex, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileIconProvider, QFileSystemModel, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton,
                               QScrollArea, QStyle, QStyledItemDelegate, QTabWidget, QToolButton, QTreeView, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import theme, util


def reveal_in_explorer(path):
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path)])
    except OSError:
        pass


def heading(text):
    lab = QLabel(text)
    lab.setProperty("heading", True)
    lab.setContentsMargins(16, 12, 12, 8)
    return lab


class _Icons(QFileIconProvider):
    def icon(self, arg):
        if isinstance(arg, QFileInfo):
            if arg.isDir():
                return theme.icon("folder", theme.c("MUTED"), 18)
            if arg.suffix().lower() in ("png", "jpg", "jpeg", "gif", "bmp", "webp", "ico", "svg"):
                return theme.icon("image", theme.c("BLUE"), 18)
            return theme.icon("file", theme.c("FAINT"), 18)
        return super().icon(arg)


class WorkspacePanel(QWidget):
    openFile = Signal(str)
    findInFolder = Signal(str)
    folderChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(heading("FOLDER AS WORKSPACE"))
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(16, 8, 16, 8)
        msg = QLabel("No folder open. Open a folder to browse its files here.")
        msg.setWordWrap(True)
        msg.setProperty("muted", True)
        el.addWidget(msg)
        btn = QPushButton("Open folder...")
        btn.clicked.connect(self.choose_folder)
        el.addWidget(btn)
        el.addStretch()
        lay.addWidget(self.empty)
        self.model = QFileSystemModel(self)
        self.model.setIconProvider(_Icons())
        self.model.setFilter(QDir.AllEntries | QDir.NoDotAndDotDot | QDir.AllDirs)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        for col in (1, 2, 3):
            self.tree.hideColumn(col)
        self.tree.setIndentation(16)
        self.tree.setAnimated(False)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.activated.connect(self._activated)
        self.tree.doubleClicked.connect(self._activated)
        self.tree.setIconSize(QSize(18, 18))
        lay.addWidget(self.tree, 1)
        self.tree.hide()

    def choose_folder(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, "Open folder as workspace", self.root or os.path.expanduser("~"))
        if d:
            self.set_root(d)

    def set_root(self, path):
        if not path or not os.path.isdir(path):
            self.root = ""
            self.tree.hide()
            self.empty.show()
            return
        self.root = path
        idx = self.model.setRootPath(path)
        self.tree.setRootIndex(idx)
        self.tree.show()
        self.empty.hide()
        self.folderChanged.emit(path)

    def restyle(self):
        self.model.setIconProvider(_Icons())

    def _activated(self, idx):
        path = self.model.filePath(idx)
        if os.path.isfile(path):
            self.openFile.emit(path)

    def _menu(self, pos):
        idx = self.tree.indexAt(pos)
        path = self.model.filePath(idx) if idx.isValid() else self.root
        m = QMenu(self)
        if os.path.isfile(path):
            m.addAction("Open", lambda: self.openFile.emit(path))
        folder = path if os.path.isdir(path) else os.path.dirname(path)
        m.addAction("Find in this folder...", lambda: self.findInFolder.emit(folder))
        m.addAction("Show in Explorer", lambda: reveal_in_explorer(path))
        m.addAction("Copy path", lambda: QGuiApplication.clipboard().setText(os.path.normpath(path)))
        m.addSeparator()
        m.addAction("Open another folder...", self.choose_folder)
        m.exec(self.tree.viewport().mapToGlobal(pos))


class MinimapWidget(QWidget):
    """A scaled-down picture of the whole document with the visible part marked; click or drag to scroll."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ed = None
        self.setMinimumWidth(120)
        self.setCursor(Qt.PointingHandCursor)
        self._dirty = QTimer(self, singleShot=True, interval=120)
        self._dirty.timeout.connect(self.update)

    def set_editor(self, ed):
        if self.ed is not None:
            try:
                self.ed.document().contentsChanged.disconnect(self._dirty.start)
                self.ed.verticalScrollBar().valueChanged.disconnect(self._dirty.start)
            except (RuntimeError, TypeError):
                pass
        self.ed = ed if (ed is not None and not getattr(ed, "is_large", False)) else None
        if self.ed is not None:
            self.ed.document().contentsChanged.connect(self._dirty.start)
            self.ed.verticalScrollBar().valueChanged.connect(self._dirty.start)
        self.update()

    def _metrics(self):
        n = max(1, self.ed.blockCount())
        per = 3 if n * 3 <= self.height() else self.height() / n
        return n, per

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.c("PANEL")))
        if self.ed is None:
            p.setPen(QColor(theme.c("FAINT")))
            p.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignTop | Qt.TextWordWrap,
                       "The map is not available in large file mode.")
            return
        doc = self.ed.document()
        n, per = self._metrics()
        width = self.width() - 16
        step = max(1, int(1 / per)) if per < 1 else 1
        cw = 1.6
        p.setPen(Qt.NoPen)
        text_c = QColor(theme.c("MUTED"))
        text_c.setAlpha(150)
        dim_c = QColor(theme.c("FAINT"))
        dim_c.setAlpha(150)
        comment = self.ed.lang.comment
        i = 0
        while i < n:
            b = doc.findBlockByNumber(i)
            if not b.isValid():
                break
            t = b.text()
            s = t.lstrip()
            if s:
                x = 8 + min(width * 0.5, (len(t) - len(s)) * cw)
                w = min(width - (x - 8), len(s) * cw)
                p.setBrush(dim_c if comment and s.startswith(comment) else text_c)
                p.drawRect(int(x), int(i * per) + 1, max(2, int(w)), max(1, int(min(2, per * 0.7 + 0.5))))
            i += step
        # the part of the document that is on screen
        vsb = self.ed.verticalScrollBar()
        first = vsb.value()
        visible = max(1, self.ed.viewport().height() // max(1, self.ed.fontMetrics().lineSpacing()))
        r = QRect(0, int(first * per), self.width(), max(6, int(visible * per)))
        fill = QColor(theme.c("ACCENT"))
        fill.setAlpha(34)
        p.fillRect(r, fill)
        p.setPen(QPen(QColor(theme.c("ACCENT")), 1))
        p.drawLine(r.left(), r.top(), r.right(), r.top())
        p.drawLine(r.left(), r.bottom(), r.right(), r.bottom())

    def _scroll_to(self, y):
        if self.ed is None:
            return
        n, per = self._metrics()
        line = int(y / per)
        visible = max(1, self.ed.viewport().height() // max(1, self.ed.fontMetrics().lineSpacing()))
        self.ed.verticalScrollBar().setValue(max(0, line - visible // 2))

    def mousePressEvent(self, e):
        self._scroll_to(e.position().y())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._scroll_to(e.position().y())


class FunctionsPanel(QWidget):
    jump = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter functions...")
        self.filter.textChanged.connect(self._apply_filter)
        lay.addWidget(self.filter)
        self.list = QListWidget()
        self.list.itemActivated.connect(self._go)
        self.list.itemClicked.connect(self._go)
        lay.addWidget(self.list, 1)
        self.note = QLabel("")
        self.note.setProperty("muted", True)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.entries = []

    def refresh(self, ed):
        self.entries = []
        self.list.clear()
        if ed is None or getattr(ed, "is_large", False) or ed.lang.funcs is None:
            self.note.setText("No function list for this document type." if ed is not None else "")
            return
        text = ed.toPlainText() if ed.length() < 2_000_000 else ""
        for m in ed.lang.funcs.finditer(text):
            name = next((g for g in m.groups() if g), None)
            if not name:
                continue
            line = text.count("\n", 0, m.start()) + 1
            indent = len(m.group()) - len(m.group().lstrip())
            self.entries.append((name.strip()[:80], line, indent))
            if len(self.entries) > 3000:
                break
        self._apply_filter()
        self.note.setText("" if self.entries else "No functions found.")

    def _apply_filter(self):
        q = self.filter.text().lower()
        self.list.clear()
        for name, line, indent in self.entries:
            if q and q not in name.lower():
                continue
            it = QListWidgetItem(("   " * min(indent // 4, 3)) + name)
            it.setData(Qt.UserRole, line)
            it.setToolTip(f"Line {line}")
            self.list.addItem(it)

    def _go(self, item):
        self.jump.emit(item.data(Qt.UserRole))


class ImagePreview(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(os.path.basename(path))
        lay = QVBoxLayout(self)
        pm = QPixmap(path)
        area = QScrollArea()
        lab = QLabel()
        lab.setAlignment(Qt.AlignCenter)
        if pm.isNull():
            lab.setText("This file could not be shown as an image.")
        else:
            lab.setPixmap(pm)
            lab.setToolTip(f"{pm.width()} x {pm.height()}")
        area.setWidget(lab)
        area.setWidgetResizable(True)
        lay.addWidget(area, 1)
        info = QLabel(f"{os.path.normpath(path)}  -  {pm.width()} x {pm.height()}  -  {util.human_size(os.path.getsize(path))}")
        info.setProperty("muted", True)
        lay.addWidget(info)
        self.resize(min(1000, max(420, pm.width() + 60)), min(760, max(320, pm.height() + 110)))


class ImagesPanel(QWidget):
    jump = Signal(int)
    pasteRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        btn = QPushButton("Paste image from clipboard")
        btn.setToolTip("Saves the clipboard picture next to the document and inserts a link (Ctrl+Shift+V)")
        btn.clicked.connect(self.pasteRequested)
        lay.addWidget(btn)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)            # a picture on top, its name below
        self.list.setFlow(QListWidget.TopToBottom)
        self.list.setWrapping(False)
        self.list.setMovement(QListWidget.Static)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setIconSize(QSize(190, 110))
        self.list.setSpacing(6)
        self.list.setTextElideMode(Qt.ElideMiddle)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(self._preview)
        self.list.itemDoubleClicked.connect(self._preview)
        self.list.itemClicked.connect(lambda it: self.jump.emit(it.data(Qt.UserRole + 1)))
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list, 1)
        self.note = QLabel("")
        self.note.setProperty("muted", True)
        self.note.setWordWrap(True)
        lay.addWidget(self.note)

    def refresh(self, ed):
        self.list.clear()
        if ed is None or getattr(ed, "is_large", False):
            self.note.setText("")
            return
        base = os.path.dirname(ed.path) if ed.path else None
        seen = set()
        doc = ed.document()
        b = doc.firstBlock()
        scanned = 0
        while b.isValid() and scanned < 20000:
            for _, _, ref in util.find_image_refs(b.text()):
                full = util.resolve_image(ref, base)
                key = full or ref
                if key in seen:
                    continue
                seen.add(key)
                it = QListWidgetItem(os.path.basename(ref.replace("%20", " ")) if full else f"{ref}  (missing)")
                it.setData(Qt.UserRole, full)
                it.setData(Qt.UserRole + 1, b.blockNumber() + 1)
                it.setToolTip(full or ref)
                if full:
                    pm = QPixmap(full)
                    if not pm.isNull():
                        it.setIcon(pm.scaled(190, 110, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    it.setIcon(theme.icon("image", theme.c("RED"), 40))
                self.list.addItem(it)
            b = b.next()
            scanned += 1
        self.note.setText("" if self.list.count() else "No pictures are linked in this document. Paste one with Ctrl+Shift+V.")

    def _preview(self, item):
        path = item.data(Qt.UserRole)
        if path:
            ImagePreview(path, self).exec()

    def _menu(self, pos):
        it = self.list.itemAt(pos)
        if not it or not it.data(Qt.UserRole):
            return
        path = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction("Preview", lambda: self._preview(it))
        m.addAction("Open with default app", lambda: os.startfile(path) if sys.platform == "win32" else None)
        m.addAction("Show in Explorer", lambda: reveal_in_explorer(path))
        m.addAction("Copy path", lambda: QGuiApplication.clipboard().setText(os.path.normpath(path)))
        m.exec(self.list.viewport().mapToGlobal(pos))


class _ResultDelegate(QStyledItemDelegate):
    """Paints search hits as 'Line 12:  text' with the match highlighted."""

    def paint(self, painter, option, index):
        info = index.data(Qt.UserRole + 2)
        if not info:
            return super().paint(painter, option, index)
        line, col, length, shift, text = info
        painter.save()
        if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
            painter.fillRect(option.rect, QColor(theme.c("SELECTED")))
        font = theme.mono(max(9, QGuiApplication.font().pointSize()))
        painter.setFont(font)
        fm = QFontMetrics(font)
        x = option.rect.x() + 4
        y = option.rect.y()
        h = option.rect.height()
        prefix = f"Line {line}:"
        painter.setPen(QColor(theme.c("FAINT")))
        painter.drawText(QRect(x, y, 90, h), Qt.AlignVCenter | Qt.AlignLeft, prefix)
        x += max(fm.horizontalAdvance("Line 00000:") + 8, fm.horizontalAdvance(prefix) + 8)
        s = max(0, col - shift)
        before, hit, after = text[:s], text[s:s + length], text[s + length:]
        painter.setPen(QColor(theme.c("TEXT")))
        painter.drawText(QRect(x, y, option.rect.right() - x, h), Qt.AlignVCenter | Qt.AlignLeft, before)
        x += fm.horizontalAdvance(before)
        w = fm.horizontalAdvance(hit)
        painter.fillRect(QRect(x - 1, y + 3, w + 2, h - 6), QColor(theme.c("MARK_BG")))
        painter.setPen(QColor(theme.c("MARK_FG")))
        painter.drawText(QRect(x, y, w + 4, h), Qt.AlignVCenter | Qt.AlignLeft, hit)
        x += w
        painter.setPen(QColor(theme.c("TEXT")))
        painter.drawText(QRect(x, y, max(0, option.rect.right() - x), h), Qt.AlignVCenter | Qt.AlignLeft, after)
        painter.restore()

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        return QSize(sh.width(), max(sh.height(), 24))


class ResultsPanel(QWidget):
    openHit = Signal(str, int, int, int)             # path, line (1-based), column, length
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        lay.addWidget(self.tabs)
        # search results
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setItemDelegate(_ResultDelegate(self.tree))
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(14)
        self.tree.itemActivated.connect(self._activated)
        self.tree.itemDoubleClicked.connect(self._activated)
        pl.addWidget(self.tree, 1)
        self.tabs.addTab(page, "Search results")
        # console
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(theme.mono(10))
        self.console.setMaximumBlockCount(2000)
        self.tabs.addTab(self.console, "Console")
        # document list
        self.docs = QTreeWidget()
        self.docs.setHeaderLabels(["Name", "Path", "Type", "Size"])
        self.docs.setRootIsDecorated(False)
        self.docs.setUniformRowHeights(True)
        self.tabs.addTab(self.docs, "Document list")
        # corner actions
        corner = QWidget()
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 0, 8, 0)
        for text, fn in (("Collapse all", self.tree.collapseAll), ("Expand all", self.tree.expandAll),
                         ("Copy results", self.copy_results), ("Clear", self.clear)):
            b = QPushButton(text)
            b.setFlat(True)
            b.setStyleSheet(f"QPushButton {{ border: none; background: transparent; color: {theme.c('MUTED')}; padding: 4px 8px; }}"
                            f"QPushButton:hover {{ color: {theme.c('TEXT')}; }}")
            b.clicked.connect(fn)
            cl.addWidget(b)
        x = QToolButton()
        x.setIcon(theme.icon("close", theme.c("MUTED"), 16))
        x.setToolTip("Close results (Ctrl+Shift+J)")
        x.setAutoRaise(True)
        x.clicked.connect(self.closeRequested)
        cl.addWidget(x)
        self.close_btn = x
        self.tabs.setCornerWidget(corner)
        self.tree_status = ""

    def log(self, text):
        import datetime
        self.console.appendPlainText(f"[{datetime.datetime.now():%H:%M:%S}] {text}")

    def clear(self):
        self.tree.clear()

    def show_results(self, title, results, searched_files=None, truncated=False):
        """`results` = [FileResult]; fills the tree and brings the tab to the front."""
        self.tree.clear()
        hits = sum(len(r.hits) for r in results)
        scope = f" in {len(results)} file{'s' if len(results) != 1 else ''}"
        if searched_files is not None:
            scope += f" of {searched_files} searched"
        head = QTreeWidgetItem([f"{title} ({hits} hit{'s' if hits != 1 else ''}{scope}){'  - list truncated' if truncated else ''}"])
        f = head.font(0)
        f.setBold(True)
        head.setFont(0, f)
        self.tree.addTopLevelItem(head)
        for r in results:
            fi = QTreeWidgetItem([f"{r.path}  ({len(r.hits)} hit{'s' if len(r.hits) != 1 else ''})"])
            fi.setIcon(0, theme.icon("file", theme.c("MUTED"), 16))
            head.addChild(fi)
            for h in r.hits:
                it = QTreeWidgetItem([""])
                it.setData(0, Qt.UserRole, (r.path, h.line, h.col, h.length))
                it.setData(0, Qt.UserRole + 2, (h.line, h.col, h.length, h.shift, h.text))
                fi.addChild(it)
            fi.setExpanded(True)
        head.setExpanded(True)
        self.tabs.setCurrentIndex(0)
        self.tree_status = head.text(0)

    def _activated(self, item, *_):
        data = item.data(0, Qt.UserRole)
        if data:
            self.openHit.emit(*data)

    def copy_results(self):
        lines = []

        def walk(it, depth):
            data = it.data(0, Qt.UserRole + 2)
            lines.append("    " * depth + (f"Line {data[0]}: {data[4]}" if data else it.text(0)))
            for i in range(it.childCount()):
                walk(it.child(i), depth + 1)
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), 0)
        QGuiApplication.clipboard().setText("\n".join(lines))

    def set_documents(self, rows, current):
        """rows = [(name, path, type, size text)]"""
        self.docs.clear()
        for i, r in enumerate(rows):
            it = QTreeWidgetItem(list(r))
            it.setData(0, Qt.UserRole, i)
            self.docs.addTopLevelItem(it)
            if i == current:
                self.docs.setCurrentItem(it)
        for c in range(4):
            self.docs.resizeColumnToContents(c)
