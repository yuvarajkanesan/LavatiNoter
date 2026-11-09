"""Side and bottom panels: workspace tree, minimap, function list, images, search results, console, document list."""
import html as _html
import math
import os
import re
import subprocess
import sys
import tempfile

from PySide6.QtCore import QDir, QFileInfo, QModelIndex, QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QDesktopServices, QGuiApplication, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFileIconProvider, QFileSystemModel, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton,
                               QScrollArea, QStyle, QStyledItemDelegate, QTabWidget, QTextBrowser, QToolButton, QTreeView, QTreeWidget,
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


class GitModel(QFileSystemModel):
    """The file tree, with names coloured by Git status (modified / new / deleted) when the folder is a repository."""
    COLORS = {"M": "ORANGE", "A": "ACCENT", "?": "ACCENT", "D": "RED", "R": "BLUE", "U": "RED"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.status = {}
        self.dirs = set()

    def set_status(self, status):
        self.status = {os.path.normcase(os.path.normpath(p)): c for p, c in status.items()}
        self.dirs = set()
        for p in self.status:
            d = os.path.dirname(p)
            while d and d not in self.dirs and len(d) > 3:
                self.dirs.add(d)
                nd = os.path.dirname(d)
                if nd == d:
                    break
                d = nd
        if self.rowCount(self.index(self.rootPath())) >= 0:
            self.layoutChanged.emit()

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.ForegroundRole and self.status:
            path = os.path.normcase(os.path.normpath(self.filePath(index)))
            code = self.status.get(path)
            if code:
                return QColor(theme.c(self.COLORS.get(code, "MUTED")))
            if path in self.dirs:
                c = QColor(theme.c("ORANGE"))
                c.setAlpha(170)
                return c
        return super().data(index, role)


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
        self.model = GitModel(self)
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


def md_headings(text):
    """[(level, title, line)] of the Markdown headings, ignoring # lines inside fenced code blocks."""
    out, fence = [], False
    for n, line in enumerate(text.split("\n"), 1):
        t = line.lstrip()
        if t.startswith("```") or t.startswith("~~~"):
            fence = not fence
            continue
        if fence:
            continue
        m = re.match(r"(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m and m.group(2):
            out.append((len(m.group(1)), m.group(2), n))
    return out


class _HeadingRow(QWidget):
    def __init__(self, level, title, line):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6 + 14 * (level - 1), 0, 8, 0)
        lay.setSpacing(8)
        tag = QLabel(f"H{level}")
        tag.setStyleSheet(f"color: {theme.c('FAINT')}; font-family: {theme.mono_family()}; font-size: 10px; background: transparent;")
        tag.setFixedWidth(22)
        name = QLabel(title)
        name.setStyleSheet("background: transparent;")
        num = QLabel(str(line))
        num.setStyleSheet(f"color: {theme.c('FAINT')}; font-size: 12px; background: transparent;")
        lay.addWidget(tag)
        lay.addWidget(name, 1)
        lay.addWidget(num)
        for w in (tag, name, num):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)


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
        self.count = 0
        self.md = False

    def refresh(self, ed):
        self.entries = []
        self.list.clear()
        self.count = 0
        self.md = False
        if ed is not None and not getattr(ed, "is_large", False) and ed.lang.name == "Markdown":
            self.md = True
            self.filter.setPlaceholderText("Filter headings...")
            text = ed.toPlainText() if ed.length() < 2_000_000 else ""
            self.entries = [(title, line, level) for level, title, line in md_headings(text)]
            self.count = len(self.entries)
            self._apply_filter()
            self.note.setText("" if self.entries else "No outline: this document has no headings.")
            return
        self.filter.setPlaceholderText("Filter functions...")
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
        self.count = len(self.entries)
        self._apply_filter()
        self.note.setText("" if self.entries else "No functions found.")

    def set_caret(self, line):
        """Highlights the heading whose section holds the caret."""
        if not getattr(self, "md", False) or self.filter.text():
            return
        best = -1
        for i, (_n, ln, _lv) in enumerate(self.entries):
            if ln <= line:
                best = i
        if best >= 0 and self.list.currentRow() != best:
            self.list.blockSignals(True)
            self.list.setCurrentRow(best)
            self.list.blockSignals(False)

    def _apply_filter(self):
        q = self.filter.text().lower()
        self.list.clear()
        for name, line, indent in self.entries:
            if q and q not in name.lower():
                continue
            if getattr(self, "md", False):
                it = QListWidgetItem()
                it.setData(Qt.UserRole, line)
                it.setSizeHint(QSize(0, 30))
                self.list.addItem(it)
                self.list.setItemWidget(it, _HeadingRow(indent, name, line))
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

    def write(self, text):
        """Raw program output into the Console tab (no time stamps), keeping the view at the end."""
        c = self.console.textCursor()
        c.movePosition(c.MoveOperation.End)
        c.insertText(text)
        self.console.setTextCursor(c)
        self.console.ensureCursorVisible()

    def show_console(self):
        self.tabs.setCurrentIndex(1)

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


class MarkdownPreview(QTextBrowser):
    """The formatted output of a document, whatever its type: Markdown and HTML rendered, formatted text (bold, colours, sizes) with
    its marks hidden, and code with its syntax colours on a white page."""
    MAX_CHARS = 400_000
    FENCE = re.compile(r"^(```|~~~)[ \t]*mermaid[^\n]*\n(.*?)^\1[ \t]*$", re.S | re.M)
    diagramsChanged = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.diagrams = []
        self.setOpenLinks(False)
        self.anchorClicked.connect(self._link)
        self.setFrameShape(QFrame.NoFrame)
        self._last = None
        self._paper = False
        self.restyle()

    def restyle(self):
        c = theme.c
        f = QFont(theme.ui_family())
        f.setPixelSize(15)
        self.document().setDefaultFont(f)
        self.document().setDocumentMargin(22)
        self.document().setDefaultStyleSheet(
            f"body {{ color: {c('TEXT')}; }} a {{ color: {c('ACCENT')}; }} "
            f"h1 {{ font-size: 26px; font-weight: 600; margin-top: 18px; }} h2 {{ font-size: 21px; font-weight: 600; margin-top: 16px; }} "
            f"h3 {{ font-size: 17px; font-weight: 600; }} h4 {{ font-size: 15px; font-weight: 600; }} h5, h6 {{ font-size: 12px; color: {c('MUTED')}; }} "
            f"code, pre {{ font-family: Consolas, monospace; background: {c('HOVER')}; }} "
            f"blockquote {{ color: {c('MUTED')}; }} th {{ background: {c('HOVER')}; }}")
        self._apply_paper()
        self._last = None

    def _apply_paper(self):
        c = theme.c
        bg, fg = ("#ffffff", "#1e1b33") if self._paper else (c("PANEL"), c("TEXT"))
        self.setStyleSheet(f"QTextBrowser {{ background: {bg}; color: {fg}; padding: 8px; }}")

    @staticmethod
    def _hard_breaks(text):
        """A single line break inside a paragraph shows as a line break, like GitHub comments do."""
        out, fence = [], False
        lines = text.split("\n")
        plain = re.compile(r"^\s*(#|```|~~~|\||>|[-*+] |\d+[.)] |-{3,}|\*{3,}|_{3,})")
        for i, line in enumerate(lines):
            if line.lstrip().startswith(("```", "~~~")):
                fence = not fence
                out.append(line)
                continue
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if (not fence and line.strip() and not line.endswith("  ") and not plain.match(line)
                    and nxt.strip() and not plain.match(nxt)):
                line += "  "
            out.append(line)
        return "\n".join(out)

    def _diagram_placeholder(self, m):
        self.diagrams.append(m.group(2))
        n = len(self.diagrams)
        return f"> **Diagram {n} (Mermaid)** - [Open in your browser](diagram:{n})\n"

    def _link(self, url):
        if url.scheme() == "diagram":
            self.open_diagrams()
        else:
            QDesktopServices.openUrl(url)

    def open_diagrams(self):
        """Draws every Mermaid diagram of the document in the default browser, using the bundled mermaid.js (works offline)."""
        if not self.diagrams:
            return
        js = QUrl.fromLocalFile(util.resource("assets", "mermaid.min.js")).toString()
        blocks = "\n".join(f'<h3>Diagram {i}</h3><pre class="mermaid">{_html.escape(d)}</pre>' for i, d in enumerate(self.diagrams, 1))
        page = (f'<!doctype html><meta charset="utf-8"><title>Diagrams</title><style>body{{font-family:Segoe UI,sans-serif;margin:32px;color:#1e1b33}}'
                f'pre.mermaid{{background:#fff}}</style>{blocks}<script src="{js}"></script>'
                f'<script>mermaid.initialize({{startOnLoad:true}});</script>')
        path = os.path.join(tempfile.gettempdir(), "lavatinoter-diagrams.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def scroll_to_source_line(self, top_line, text):
        """Scrolls so the rendered heading section matches the editor's first visible line (headings are the anchors)."""
        heads = [ln for _lv, _t, ln in md_headings(text)]
        ys = self._heading_ys()
        if not heads or len(ys) != len(heads):
            return
        bar = self.verticalScrollBar()
        if top_line <= heads[0]:
            frac = top_line / max(heads[0], 1)
            y = ys[0] * min(frac, 1.0)
        else:
            i = max(k for k, ln in enumerate(heads) if ln <= top_line)
            if i + 1 < len(heads):
                f = (top_line - heads[i]) / max(heads[i + 1] - heads[i], 1)
                y = ys[i] + f * (ys[i + 1] - ys[i])
            else:
                total = max(text.count("\n") + 1 - heads[i], 1)
                f = min((top_line - heads[i]) / total, 1.0)
                y = ys[i] + f * (self.document().size().height() - ys[i])
        bar.setValue(int(y))

    def _heading_ys(self):
        doc, out = self.document(), []
        lay = doc.documentLayout()
        b = doc.begin()
        while b.isValid():
            if b.blockFormat().headingLevel() > 0:
                out.append(lay.blockBoundingRect(b).top())
            b = b.next()
        return out

    def _decorate_rendered(self):
        """Tables and code blocks of a rendered Markdown document: borders, padding, header shading, a tinted block for code."""
        from PySide6.QtGui import QBrush, QTextCursor, QTextFormat, QTextTable, QTextLength
        doc = self.document()
        line, tint = QColor(theme.c("BORDER")), QColor(theme.c("HOVER"))
        for fr in doc.rootFrame().childFrames():
            if isinstance(fr, QTextTable):
                fmt = fr.format()
                fmt.setBorder(1)
                fmt.setBorderBrush(QBrush(line))
                fmt.setCellPadding(7)
                fmt.setCellSpacing(0)
                fmt.setTopMargin(8)
                fmt.setBottomMargin(12)
                fr.setFormat(fmt)
                for c in range(fr.columns()):
                    cell = fr.cellAt(0, c)
                    cf = cell.format()
                    cf.setBackground(QBrush(tint))
                    cell.setFormat(cf)
        cur = QTextCursor(doc)
        b = doc.begin()
        while b.isValid():
            bf = b.blockFormat()
            if bf.hasProperty(QTextFormat.BlockCodeFence) or bf.hasProperty(QTextFormat.BlockCodeLanguage):
                bf.setBackground(QBrush(tint))
                bf.setLeftMargin(10)
                bf.setRightMargin(10)
                cur.setPosition(b.position())
                cur.setBlockFormat(bf)
            b = b.next()

    def show_document(self, text, lang, folder=""):
        """Renders `text` by its language; re-renders only when something changed and keeps the scroll position."""
        from . import richtext
        from .highlighter import PLAIN, RICH_LANGS
        lang = lang or PLAIN
        key = (text, lang.name, folder)
        if key == self._last:
            return
        self._last = key
        paper = lang.name != "Markdown"                             # Markdown follows the theme; everything else is a white page
        if paper != self._paper:
            self._paper = paper
            self._apply_paper()
        self.setSearchPaths([folder] if folder else [])
        bar = self.verticalScrollBar()
        pos = bar.value()
        if len(text) > self.MAX_CHARS:
            self.setPlainText("This document is too large to preview.")
        elif lang.name == "Markdown":
            self.diagrams = []
            self.document().setMarkdown(self._hard_breaks(self.FENCE.sub(self._diagram_placeholder, text)))
            self._decorate_rendered()
            self.diagramsChanged.emit(bool(self.diagrams))
        elif lang.name == "HTML / XML":
            self.document().setHtml(text)
        elif lang.name in RICH_LANGS and richtext.has_marks(text):   # formatted plain text
            self.document().setHtml(f'<div style="color:#1e1b33">{richtext.marks_to_html(text)}</div>')
        else:                                                       # code, logs, config: the syntax colours, ready to read
            from .export import styled_document
            self.document().setHtml(styled_document(text, lang, 11).toHtml())
        bar.setValue(pos)


class PreviewPanel(QWidget):
    """The Preview tab. The panel header owns expand / hide; a slim bar shows only when the document has diagrams."""
    fullScreenRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.diagram_btn = QToolButton()
        self.diagram_btn.setText("Open diagrams in browser")
        self.diagram_btn.hide()
        head = QHBoxLayout()
        head.setContentsMargins(12, 6, 8, 6)
        head.addStretch(1)
        head.addWidget(self.diagram_btn)
        lay.addLayout(head)
        self.view = MarkdownPreview()
        self.view.diagramsChanged.connect(self.diagram_btn.setVisible)
        self.diagram_btn.clicked.connect(self.view.open_diagrams)
        lay.addWidget(self.view, 1)

    def restyle(self):
        self.view.restyle()


class PreviewFullScreen(QWidget):
    """The formatted output filling the screen. Esc, F11 or the Exit button brings you back."""
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("Formatted output")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(16, 8, 12, 8)
        hint = QLabel("Formatted output")
        hint.setProperty("muted", True)
        head.addWidget(hint)
        head.addStretch(1)
        self.exit = QToolButton()
        self.exit.setText("Exit full screen (Esc)")
        self.exit.clicked.connect(self.close)
        head.addWidget(self.exit)
        lay.addLayout(head)
        self.view = MarkdownPreview()
        lay.addWidget(self.view, 1)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape or e.key() == Qt.Key_F11:
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e):
        super().closeEvent(e)
        self.closed.emit()
