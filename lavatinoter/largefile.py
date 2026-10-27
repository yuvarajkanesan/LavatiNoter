"""Large file mode: opens multi-gigabyte files instantly.

Only a window of the file (about one screen of lines) is ever turned into text. The file itself is memory mapped, a
background thread counts lines into a sparse index (one entry per MB), and the scroll bar maps to byte offsets, so
scrolling, Go To (line / offset / percent) and Find stay fast and use a few tens of MB of RAM whatever the file size."""
import bisect
import mmap
import os
import re
import threading
import time
from array import array

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QCursor, QTextCursor
from PySide6.QtWidgets import (QMessageBox, QToolTip, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QProgressBar, QPushButton, QScrollBar, QSpinBox, QVBoxLayout, QWidget)

from . import dialogs, theme, util
from .editor import CodeEditor
from .highlighter import PLAIN, lang_for_path

BLOCK = 1 << 20                     # index granularity: one checkpoint per MB
SB_MAX = 1_000_000                  # scroll bar resolution
MAX_LINE_CHARS = 3000               # longer lines are cut for display
COPY_LIMIT = 64 * 1024 * 1024       # largest piece "Make editable copy" will extract


class Indexer(QThread):
    """Counts newlines block by block. cum[i] = number of newlines before block i."""
    progress = Signal(int, int)             # newlines so far, bytes so far
    finished_ok = Signal(int)               # total newlines

    def __init__(self, path, cum, parent=None, start_block=0, start_lines=0):
        super().__init__(parent)
        self.path = path
        self.cum = cum
        self.start_block = start_block
        self.lines = start_lines
        self.done_bytes = start_block * BLOCK
        self._run = threading.Event()
        self._run.set()
        self._stop = False

    def pause(self):
        self._run.clear()

    def resume(self):
        self._run.set()

    def stop(self):
        self._stop = True
        self._run.set()

    def run(self):
        try:
            with open(self.path, "rb", buffering=0) as f:
                f.seek(self.start_block * BLOCK)
                n = 0
                while True:
                    self._run.wait()
                    if self._stop:
                        return
                    blk = f.read(BLOCK)
                    if not blk:
                        break
                    self.cum.append(self.lines)
                    self.lines += blk.count(b"\n")
                    self.done_bytes += len(blk)
                    n += 1
                    if n % 24 == 0:
                        self.progress.emit(self.lines, self.done_bytes)
            self.progress.emit(self.lines, self.done_bytes)
            self.finished_ok.emit(self.lines)
        except OSError:
            self._stop = True


class ByteSearch(QThread):
    """Searches the mapped file for a regex in chunks (forward or backward) without loading it."""
    found = Signal(int, int)                # absolute byte offset, length
    missing = Signal()
    progress = Signal(float)

    CHUNK = 16 * 1024 * 1024
    OVERLAP = 64 * 1024

    def __init__(self, mm, size, rx, start, backward, wrap, parent=None):
        super().__init__(parent)
        self.mm, self.size, self.start_at, self.backward, self.wrap = mm, size, start, backward, wrap
        self.rx = re.compile(rx.pattern.encode("utf-8"), rx.flags & ~re.UNICODE)
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def _forward(self, lo, hi):
        pos = lo
        while pos < hi and not self._cancel:
            end = min(hi, pos + self.CHUNK)
            m = self.rx.search(self.mm[pos:min(self.size, end + self.OVERLAP)])
            if m and pos + m.start() < end:
                return pos + m.start(), max(1, m.end() - m.start())
            pos = end
            self.progress.emit(pos / max(1, self.size))
        return None

    def _backward(self, lo, hi):
        pos = hi
        while pos > lo and not self._cancel:
            begin = max(lo, pos - self.CHUNK)
            last = None
            for m in self.rx.finditer(self.mm[begin:pos]):
                last = m
            if last:
                return begin + last.start(), max(1, last.end() - last.start())
            pos = begin
            self.progress.emit(1 - pos / max(1, self.size))
        return None

    def run(self):
        if not self.backward:
            r = self._forward(self.start_at, self.size) or (self.wrap and self._forward(0, self.start_at))
        else:
            r = self._backward(0, self.start_at) or (self.wrap and self._backward(self.start_at, self.size))
        if self._cancel:
            return
        if r:
            self.found.emit(*r)
        else:
            self.missing.emit()


class LineFilter(QThread):
    """Collects the lines that match a regex ('grep'), streaming through the file in chunks. Output: 'lineno: text' lines."""
    done = Signal(str, int, bool)           # text, matching lines, truncated
    progress = Signal(float)

    CHUNK = 16 * 1024 * 1024
    MAX_LINES = 200_000
    MAX_BYTES = 64 * 1024 * 1024

    def __init__(self, path, rx, invert=False, parent=None):
        super().__init__(parent)
        self.path = path
        self.rx = re.compile(rb"^[^\n]*?(?:" + rx.pattern.encode("utf-8") + rb")[^\n]*$", (rx.flags & ~re.UNICODE) | re.M)
        self.invert = invert
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        out, out_bytes, count, lineno, truncated = [], 0, 0, 1, False
        try:
            size = os.path.getsize(self.path)
            with open(self.path, "rb") as f:
                carry, read = b"", 0
                while not self._cancel and not truncated:
                    block = f.read(self.CHUNK)
                    last = not block
                    data = carry + block
                    if not last:
                        cut = data.rfind(b"\n")
                        if cut < 0:
                            carry = data
                            continue
                        data, carry = data[:cut + 1], data[cut + 1:]
                    read += len(block)
                    pos, ln = 0, lineno
                    if self.invert:
                        rows = data.split(b"\n")
                        if data.endswith(b"\n") or not data:
                            rows.pop()                                # the empty piece after the last newline is not a line
                        for line in rows:
                            if not self.rx.search(line):
                                if count >= self.MAX_LINES or out_bytes > self.MAX_BYTES:
                                    truncated = True
                                    break
                                txt = line.decode("utf-8", "replace").rstrip("\r")
                                out.append(f"{ln}: {txt}")
                                out_bytes += len(txt) + 12
                                count += 1
                            ln += 1
                    else:
                        for m in self.rx.finditer(data):
                            ln += data.count(b"\n", pos, m.start())
                            pos = m.start()
                            if count >= self.MAX_LINES or out_bytes > self.MAX_BYTES:
                                truncated = True
                                break
                            txt = m.group().decode("utf-8", "replace").rstrip("\r")
                            out.append(f"{ln}: {txt}")
                            out_bytes += len(txt) + 12
                            count += 1
                    lineno += data.count(b"\n")
                    self.progress.emit(min(1.0, read / max(1, size)))
                    if last:
                        break
        except OSError:
            pass
        self.done.emit("\n".join(out) + ("\n" if out else ""), count, truncated)


class GoToPanel(QFrame):
    """The floating 'Go to' card: Line / Offset / Percent."""
    requested = Signal(str, float)

    def __init__(self, parent, kinds=("Line", "Offset", "Percent")):
        super().__init__(parent)
        self.setProperty("card", True)
        self.setFixedWidth(330)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel("GO TO")
        t.setProperty("heading", True)
        head.addWidget(t)
        head.addStretch()
        close = QPushButton("✕")
        close.setFlat(True)
        close.setFixedSize(24, 24)
        close.setStyleSheet("QPushButton { border: none; background: transparent; } QPushButton:hover { background: %s; }" % theme.c("HOVER"))
        close.clicked.connect(self.hide)
        head.addWidget(close)
        lay.addLayout(head)
        seg = QHBoxLayout()
        seg.setSpacing(0)
        self.buttons = {}
        for i, k in enumerate(kinds):
            b = QPushButton(k)
            b.setCheckable(True)
            b.setProperty("seg", "first" if i == 0 else "last" if i == len(kinds) - 1 else "mid")
            b.clicked.connect(lambda _=False, name=k: self.set_kind(name))
            self.buttons[k] = b
            seg.addWidget(b)
        lay.addLayout(seg)
        self.label = QLabel("Line number")
        self.label.setProperty("muted", True)
        lay.addWidget(self.label)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.returnPressed.connect(self._go)
        row.addWidget(self.edit, 1)
        go = QPushButton("Go")
        go.setProperty("primary", True)
        go.clicked.connect(self._go)
        row.addWidget(go)
        lay.addLayout(row)
        self.info = QLabel("")
        self.info.setProperty("muted", True)
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.kind = kinds[0]
        self.set_kind(self.kind)
        self.hide()

    def set_kind(self, kind):
        self.kind = kind
        for k, b in self.buttons.items():
            b.setChecked(k == kind)
        self.label.setText({"Line": "Line number", "Offset": "Byte offset", "Percent": "Percent of file (0 - 100)"}[kind])
        self.edit.setFocus()
        self.edit.selectAll()

    def open(self, kind=None, value="", info=""):
        if kind:
            self.set_kind(kind)
        self.edit.setText(value)
        self.info.setText(info)
        self.show()
        self.raise_()
        self.edit.setFocus()
        self.edit.selectAll()

    def _go(self):
        txt = self.edit.text().strip().replace(",", "").replace("_", "").replace(" ", "")
        try:
            val = float(txt)
        except ValueError:
            self.info.setText("Type a number.")
            return
        self.requested.emit(self.kind, val)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(e)


class _Filter(QObject):
    """Routes wheel and navigation keys of the inner editor to the large file view."""

    def __init__(self, view):
        super().__init__(view)
        self.view = view

    def eventFilter(self, obj, e):
        v = self.view
        if e.type() == QEvent.Wheel:
            if e.modifiers() & Qt.ControlModifier:
                v.editor.zoomRequested.emit(1 if e.angleDelta().y() > 0 else -1)
            else:
                v.scroll_lines(-int(e.angleDelta().y() / 120 * 3) or (-1 if e.angleDelta().y() > 0 else 1))
            return True
        if e.type() == QEvent.KeyPress and obj is v.editor:
            return v.handle_key(e)
        return False


class LargeFileView(QWidget):
    cursorStatus = Signal()
    copyRequested = Signal(str, str)        # text, suggested title
    is_large = True
    _closed = False

    def __init__(self, path, threshold_mb=64, parent=None):
        super().__init__(parent)
        t0 = time.perf_counter()
        self.path = path
        self.size = os.path.getsize(path)
        self._file = open(path, "rb")
        self.mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        head = bytes(self.mm[:65536])
        self.encoding = "UTF-8 with BOM" if head.startswith(b"\xef\xbb\xbf") else util.detect_encoding(head)
        self.eol = util.detect_eol(head.decode("utf-8", "replace"))
        self.lang = lang_for_path(path)
        self.cum = array("Q")
        self.indexing_done = False
        self.paused = False
        self.top = 0 if not head.startswith(b"\xef\xbb\xbf") else 3
        self.top_line = 1
        self.row = 0
        self.win = []                       # [(start, end)] byte spans of the lines shown
        self._syncing = False
        self._searcher = None
        self.last_match = None              # (offset, length)
        self.note = ""

        self.editor = CodeEditor(self)
        self.editor.setReadOnly(True)
        self.editor.read_only_window = True
        self.editor.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.editor.set_language(self.lang if self.lang is not PLAIN else PLAIN)
        self.editor.cursorStatus.connect(self._on_editor_caret)
        self.filter = _Filter(self)
        self.editor.installEventFilter(self.filter)
        self.editor.viewport().installEventFilter(self.filter)
        self.sb = QScrollBar(Qt.Vertical)
        self.sb.setRange(0, SB_MAX)
        self.sb.setPageStep(SB_MAX // 200)
        self.sb.valueChanged.connect(self._sb_changed)
        self.sb.sliderMoved.connect(self._sb_tip)

        # banner
        self.banner = QFrame()
        self.banner.setProperty("banner", True)
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(16, 10, 16, 10)
        bl.setSpacing(14)
        self.banner_text = QLabel()
        self.banner_text.setWordWrap(True)
        self.banner_text.setTextFormat(Qt.RichText)
        bl.addWidget(self.banner_text, 1)
        self.index_label = QLabel("Indexing lines 0%")
        self.index_label.setProperty("muted", True)
        bl.addWidget(self.index_label)
        self.index_bar = QProgressBar()
        self.index_bar.setRange(0, 1000)
        self.index_bar.setTextVisible(False)
        self.index_bar.setFixedWidth(150)
        bl.addWidget(self.index_bar)
        self.pause_btn = QPushButton("Pause indexing")
        self.pause_btn.clicked.connect(self.toggle_pause)
        bl.addWidget(self.pause_btn)
        self.follow_btn = QPushButton("Follow")
        self.follow_btn.setCheckable(True)
        self.follow_btn.setToolTip("Keep the end of the file in view as it grows (like tail -f)")
        self.follow_btn.toggled.connect(self.set_follow)
        bl.addWidget(self.follow_btn)
        self.filter_btn = QPushButton("Filter lines...")
        self.filter_btn.setToolTip("Open the lines that contain some text (or match a regular expression) in a new tab")
        self.filter_btn.clicked.connect(self.filter_dialog)
        bl.addWidget(self.filter_btn)
        self.copy_btn = QPushButton("Make editable copy...")
        self.copy_btn.setProperty("primary", True)
        self.copy_btn.clicked.connect(self.make_copy_dialog)
        bl.addWidget(self.copy_btn)

        body = QWidget()
        bh = QHBoxLayout(body)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(0)
        bh.addWidget(self.editor, 1)
        bh.addWidget(self.sb)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.banner)
        lay.addWidget(body, 1)
        self.body = body
        self.goto = GoToPanel(self)
        self.goto.requested.connect(self._goto_requested)

        self.following = False
        self._closed = False
        self._grow_timer = QTimer(self, interval=800)
        self._grow_timer.timeout.connect(self.refresh_growth)
        self._grow_timer.start()
        self._filter = None
        self.indexer = Indexer(path, self.cum, self)
        self.indexer.progress.connect(self._on_progress)
        self.indexer.finished_ok.connect(self._on_indexed)
        self.indexer.start()
        self.open_seconds = time.perf_counter() - t0
        self._avg_line = self._sample_avg_line()
        self.refresh_banner()
        QTimer.singleShot(0, self.show_window)

    # ---- lifecycle ---------------------------------------------------------------------------------------------
    # ---- growing files: follow, re-index ------------------------------------------------------------------------------
    def set_follow(self, on):
        self.following = on
        if on:
            self.refresh_growth()
            self.scroll_to_end()

    def scroll_to_end(self):
        self.scroll_to_offset(self.size)
        self.scroll_lines(-max(1, self.visible_rows() - 2))

    def refresh_growth(self):
        if self._closed:
            return
        """Notices that the file grew (or was truncated / rotated), re-maps it and indexes only the new part."""
        try:
            new_size = os.path.getsize(self.path)
        except OSError:
            return
        if new_size == self.size:
            return
        shrunk = new_size < self.size
        try:
            self.mm.close()
            self._file.close()
            self._file = open(self.path, "rb")
            self.mm = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ) if new_size else None
        except (OSError, ValueError):
            return
        self.size = new_size
        if self.mm is None:
            return
        if shrunk:                                              # the file was replaced: start again
            self.top = 0
            self.indexer.stop()
            self.indexer.wait(3000)
            self.cum = array("Q")
            self.indexing_done = False
            self.indexer = Indexer(self.path, self.cum, self)
            self.indexer.progress.connect(self._on_progress)
            self.indexer.finished_ok.connect(self._on_indexed)
            self.pause_btn.show()
            self.indexer.start()
        elif self.indexing_done and self.cum:
            last = len(self.cum) - 1
            lines_before = self.cum[last]
            del self.cum[last:]
            self.indexing_done = False
            self.indexer = Indexer(self.path, self.cum, self, start_block=last, start_lines=lines_before)
            self.indexer.progress.connect(self._on_progress)
            self.indexer.finished_ok.connect(self._on_indexed)
            self.indexer.start()
        self.refresh_banner()
        if self.following:
            self.scroll_to_end()
        else:
            self.show_window()

    # ---- filter ('grep') ------------------------------------------------------------------------------------------------------
    def filter_dialog(self):
        from PySide6.QtWidgets import QCheckBox
        d = QDialog(self)
        d.setWindowTitle("Filter lines")
        d.setMinimumWidth(460)
        form = QFormLayout(d)
        box = QLineEdit()
        box.setPlaceholderText("Text to look for, e.g. ERROR")
        regex = QCheckBox("Regular expression")
        case = QCheckBox("Match case")
        invert = QCheckBox("Show the lines that do NOT match")
        form.addRow("Lines containing", box)
        form.addRow("", regex)
        form.addRow("", case)
        form.addRow("", invert)
        note = QLabel("The matching lines open in a new tab as 'line number: text'. Up to 200,000 lines.")
        note.setProperty("muted", True)
        note.setWordWrap(True)
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        form.addRow(bb)
        box.setFocus()
        if d.exec() != QDialog.Accepted or not box.text():
            return
        from . import search
        try:
            rx = search.compile_pattern(search.Options(text=box.text(), mode=search.REGEX if regex.isChecked() else search.NORMAL,
                                                       match_case=case.isChecked()))
        except search.SearchError as e:
            dialogs.warning(self, "Filter lines", str(e))
            return
        self.run_filter(rx, invert.isChecked(), box.text())

    def run_filter(self, rx, invert=False, label=""):
        if self._filter is not None and self._filter.isRunning():
            self._filter.cancel()
            self._filter.wait(2000)
        t = LineFilter(self.path, rx, invert, self)
        self._filter = t
        self.index_label.setText("Filtering...")
        t.progress.connect(lambda f: self.index_label.setText(f"Filtering {f * 100:.0f}%"))

        def done(text, count, truncated):
            self.index_label.setText(f"{count:,} lines matched" + (" (stopped at the limit)" if truncated else ""))
            base = os.path.splitext(os.path.basename(self.path))
            if count:
                self.copyRequested.emit(text, f"{base[0]} - {'not ' if invert else ''}{label} ({count:,} lines){base[1]}")
        t.done.connect(done)
        t.start()

    def close_file(self):
        self._closed = True                            # queued signals from the indexer may still arrive: they must do nothing
        self._grow_timer.stop()
        for sig, slot in ((self.indexer.progress, self._on_progress), (self.indexer.finished_ok, self._on_indexed)):
            try:
                sig.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        if self._filter is not None and self._filter.isRunning():
            self._filter.cancel()
            self._filter.wait(2000)
        if self._searcher:
            self._searcher.cancel()
            self._searcher.wait(2000)
        self.indexer.stop()
        self.indexer.wait(3000)
        try:
            self.mm.close()
            self._file.close()
        except (OSError, ValueError, BufferError):
            pass

    def _sample_avg_line(self):
        sample = bytes(self.mm[:min(self.size, 512 * 1024)])
        n = sample.count(b"\n")
        return max(1.0, len(sample) / n) if n else max(1.0, float(self.size))

    # ---- sizes ---------------------------------------------------------------------------------------------------
    def total_lines(self):
        if self.indexing_done:
            return self.indexer.lines + 1
        done_b = max(1, self.indexer.done_bytes)
        if self.indexer.lines:
            return int(self.size / (done_b / max(1, self.indexer.lines))) + 1
        return int(self.size / self._avg_line) + 1

    def refresh_banner(self):
        mem = util.rss_mb()
        self.banner_text.setText(
            f"<b>Large file mode.</b> Opened in {self.open_seconds:.1f} s. Only the visible window is loaded"
            f"{f' ({mem} MB in memory)' if mem else ''}, so scrolling stays instant. "
            f"Editing happens on a streamed copy.")

    def _on_progress(self, lines, done_bytes):
        if self._closed:
            return
        pct = done_bytes / max(1, self.size)
        self.index_bar.setValue(int(pct * 1000))
        self.index_label.setText(f"Indexing lines {pct * 100:.0f}%")
        self.cursorStatus.emit()

    def _on_indexed(self, lines):
        if self._closed:
            return
        self.indexing_done = True
        self.index_label.setText(f"{lines + 1:,} lines indexed")
        self.index_bar.setValue(1000)
        self.pause_btn.hide()
        self.show_window()

    def toggle_pause(self):
        if self.paused:
            self.indexer.resume()
            self.pause_btn.setText("Pause indexing")
        else:
            self.indexer.pause()
            self.pause_btn.setText("Resume indexing")
        self.paused = not self.paused

    # ---- line <-> offset ---------------------------------------------------------------------------------------------
    def line_at(self, off):
        """Exact 1-based line number of the line containing byte `off`, or None when that part is not indexed yet."""
        i = off // BLOCK
        if i < len(self.cum):
            return self.cum[i] + self.mm[i * BLOCK:off].count(b"\n") + 1
        return None

    def estimate_line(self, off):
        return int(off / max(1.0, self._avg_line)) + 1

    def offset_of_line(self, n):
        """Byte offset where 1-based line `n` starts; None when it lies in a part that is not indexed yet."""
        t = n - 1
        if t <= 0:
            return 0
        i = bisect.bisect_left(self.cum, t) - 1
        if i < 0:
            return 0
        last_open = i == len(self.cum) - 1 and not self.indexing_done
        if last_open and t - self.cum[i] > 300_000:
            return None
        pos = i * BLOCK
        for _ in range(t - self.cum[i]):
            nl = self.mm.find(b"\n", pos)
            if nl < 0:
                return self.line_start(self.size)
            pos = nl + 1
        return pos

    def line_start(self, off):
        off = max(0, min(off, self.size))
        return self.mm.rfind(b"\n", 0, off) + 1 if off > 0 else 0

    # ---- window -------------------------------------------------------------------------------------------------------
    def visible_rows(self):
        return max(5, self.editor.viewport().height() // max(1, self.editor.fontMetrics().lineSpacing()) + 1)

    def show_window(self, keep_row=None):
        if self._closed:
            return
        rows = self.visible_rows()
        pos = self.top
        spans = []
        while len(spans) < rows:
            nl = self.mm.find(b"\n", pos)
            if nl < 0:
                spans.append((pos, self.size))
                break
            spans.append((pos, nl))
            pos = nl + 1
        self.win = spans
        parts = []
        for s, e in spans:
            raw = bytes(self.mm[s:min(e, s + MAX_LINE_CHARS)])
            line = raw.decode("utf-8" if self.encoding.startswith("UTF-8") else "cp1252", "replace").rstrip("\r")
            if e - s > MAX_LINE_CHARS:
                line += f"  … (+{e - s - MAX_LINE_CHARS:,} more bytes)"
            parts.append(line)
        exact = self.line_at(self.top)
        self.top_line = exact if exact is not None else self.estimate_line(self.top)
        self.editor.line_base = self.top_line - 1
        self.editor.line_prefix = "" if exact is not None else "~"
        row = self.row if keep_row is None else keep_row
        self.row = max(0, min(row, len(spans) - 1))
        ed = self.editor
        ed.blockSignals(True)
        ed.setPlainText("\n".join(parts))
        ed.blockSignals(False)
        cur = QTextCursor(ed.document().findBlockByNumber(self.row))
        ed.setTextCursor(cur)
        ed.horizontalScrollBar().setValue(0)
        ed.verticalScrollBar().setValue(0)
        ed.gutter.update()
        ed._update_gutter_width()
        ed.refresh_selections()
        self._sync_sb()
        self.cursorStatus.emit()

    def _sync_sb(self):
        self._syncing = True
        self.sb.setValue(int(self.top / max(1, self.size) * SB_MAX))
        self._syncing = False

    def _sb_changed(self, v):
        if self._syncing:
            return
        self.scroll_to_offset(int(v / SB_MAX * self.size))

    def _sb_tip(self, v):
        off = int(v / SB_MAX * self.size)
        line = self.line_at(self.line_start(off))
        txt = f"Line {line:,}" if line else f"Line ~{self.estimate_line(off):,}"
        QToolTip.showText(QCursor.pos() + QPoint(-190, 0),
                          f"<b>{txt}</b><br>{util.human_size(off)} of {util.human_size(self.size)}", self.sb)

    def scroll_to_offset(self, off, row=0):
        self.top = self.line_start(min(max(0, off), self.size))
        self.show_window(keep_row=row)

    def scroll_lines(self, n):
        pos = self.top
        if n > 0:
            for _ in range(n):
                nl = self.mm.find(b"\n", pos)
                if nl < 0:
                    break
                pos = nl + 1
        elif n < 0:
            for _ in range(-n):
                if pos <= 0:
                    break
                pos = self.mm.rfind(b"\n", 0, pos - 1) + 1
        if pos != self.top:
            self.top = pos
            self.show_window(keep_row=self.row - n)

    def handle_key(self, e):
        k, m = e.key(), e.modifiers()
        rows = len(self.win)
        if k == Qt.Key_Down and self.row >= rows - 1 and not m & Qt.ShiftModifier:
            self.scroll_lines(1)
            return True
        if k == Qt.Key_Up and self.row <= 0 and not m & Qt.ShiftModifier:
            self.scroll_lines(-1)
            return True
        if k == Qt.Key_PageDown:
            self.scroll_lines(max(1, rows - 2))
            return True
        if k == Qt.Key_PageUp:
            self.scroll_lines(-max(1, rows - 2))
            return True
        if k == Qt.Key_Home and m & Qt.ControlModifier:
            self.scroll_to_offset(0)
            return True
        if k == Qt.Key_End and m & Qt.ControlModifier:
            self.scroll_to_offset(self.size)
            self.scroll_lines(-max(1, rows - 2))
            return True
        return False

    def _on_editor_caret(self):
        self.row = self.editor.textCursor().blockNumber()
        self.cursorStatus.emit()

    # ---- caret info ---------------------------------------------------------------------------------------------------
    def caret_info(self):
        """-> (line number, column, byte offset) of the caret."""
        cur = self.editor.textCursor()
        row = min(cur.blockNumber(), max(0, len(self.win) - 1))
        col = cur.positionInBlock()
        start = self.win[row][0] if self.win else 0
        line_text = cur.block().text()[:col]
        return self.top_line + row, col + 1, start + len(line_text.encode("utf-8", "replace"))

    def goto_info(self):
        done = self.indexer.lines + (1 if self.indexing_done else 0)
        total = self.total_lines()
        if self.indexing_done:
            return f"{total:,} lines in this file."
        return f"Indexed so far: {util.short_count(done)} of about {util.short_count(total)} lines"

    # ---- go to ----------------------------------------------------------------------------------------------------------
    def show_goto(self, kind="Line"):
        line, _, off = self.caret_info()
        value = {"Line": f"{line:,}", "Offset": f"{off:,}", "Percent": f"{off / max(1, self.size) * 100:.1f}"}[kind]
        self.goto.open(kind, value, self.goto_info())
        self._place_goto()

    def _place_goto(self):
        self.goto.adjustSize()
        self.goto.move(self.width() - self.goto.width() - 28, self.banner.height() + 18)

    def resizeEvent(self, e):
        if self._closed:
            return super().resizeEvent(e)
        super().resizeEvent(e)
        self._place_goto()
        QTimer.singleShot(0, self.show_window)

    def _goto_requested(self, kind, value):
        if kind == "Line":
            off = self.offset_of_line(int(value))
            if off is None:
                self.goto.info.setText("That line is not indexed yet. " + self.goto_info())
                return
            self.scroll_to_offset(off)
        elif kind == "Offset":
            self.scroll_to_offset(int(value))
        else:
            self.scroll_to_offset(int(self.size * max(0.0, min(100.0, value)) / 100))
        self.goto.hide()
        self.editor.setFocus()

    # ---- find ------------------------------------------------------------------------------------------------------------
    def find(self, rx, backward=False, wrap=True, on_done=None):
        """Searches from the caret / last match. `on_done(found: bool)` is called when the search ends."""
        if self._searcher and self._searcher.isRunning():
            self._searcher.cancel()
            self._searcher.wait(2000)
        if self.last_match and self.editor.textCursor().hasSelection():
            start = self.last_match[0] if backward else self.last_match[0] + self.last_match[1]
        else:
            start = self.caret_info()[2]
        s = ByteSearch(self.mm, self.size, rx, max(0, min(start, self.size)), backward, wrap, self)
        s.found.connect(lambda off, ln: (self._show_match(off, ln), on_done and on_done(True)))
        s.missing.connect(lambda: on_done and on_done(False))
        self._searcher = s
        s.start()

    def _show_match(self, off, length):
        self.last_match = (off, length)
        ls = self.line_start(off)
        self.top = ls
        # show the hit a few lines below the top of the window
        for _ in range(3):
            if self.top <= 0:
                break
            self.top = self.mm.rfind(b"\n", 0, self.top - 1) + 1
        self.row = 0
        self.show_window()
        row = next((i for i, (s, e) in enumerate(self.win) if s <= off <= e), None)
        if row is not None:
            start_b = self.win[row][0]
            col = len(bytes(self.mm[start_b:off]).decode("utf-8", "replace"))
            n = len(bytes(self.mm[off:off + length]).decode("utf-8", "replace"))
            block = self.editor.document().findBlockByNumber(row)
            cur = QTextCursor(self.editor.document())
            cur.setPosition(block.position() + col)
            cur.setPosition(block.position() + col + max(1, n), QTextCursor.KeepAnchor)
            self.editor.setTextCursor(cur)
            self.row = row
        self.cursorStatus.emit()

    def cancel_search(self):
        if self._searcher and self._searcher.isRunning():
            self._searcher.cancel()

    # ---- editable copy -----------------------------------------------------------------------------------------------------
    def extract(self, start_line, count):
        """Text of `count` lines from `start_line` (at most COPY_LIMIT bytes). -> (text, lines taken, truncated)."""
        off = self.offset_of_line(start_line)
        if off is None:
            return None, 0, False
        pos = off
        taken = 0
        while taken < count and pos <= self.size and pos - off < COPY_LIMIT:
            nl = self.mm.find(b"\n", pos)
            taken += 1
            if nl < 0:
                pos = self.size
                break
            pos = nl + 1
        truncated = pos - off >= COPY_LIMIT
        end = min(pos, off + COPY_LIMIT)
        text = bytes(self.mm[off:end]).decode("utf-8" if self.encoding.startswith("UTF-8") else "cp1252", "replace")
        return util.normalize_newlines(text), taken, truncated

    def make_copy_dialog(self):
        d = QDialog(self)
        d.setWindowTitle("Make editable copy")
        d.setMinimumWidth(420)
        form = QFormLayout(d)
        start = QSpinBox()
        start.setRange(1, 2_000_000_000)
        start.setValue(self.top_line if self.indexing_done or self.line_at(self.top) else 1)
        start.setGroupSeparatorShown(True)
        count = QSpinBox()
        count.setRange(1, 2_000_000_000)
        count.setValue(100_000)
        count.setGroupSeparatorShown(True)
        note = QLabel(f"A copy of up to {util.human_size(COPY_LIMIT)} opens in a normal tab (unsaved, so Save As keeps it). "
                      f"The original file is never changed.")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        form.addRow("Start at line", start)
        form.addRow("Number of lines", count)
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Open copy")
        bb.button(QDialogButtonBox.Ok).setProperty("primary", True)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        form.addRow(bb)
        if d.exec() != QDialog.Accepted:
            return
        text, taken, truncated = self.extract(start.value(), count.value())
        if text is None:
            self.goto.open("Line", f"{start.value():,}", "That line is not indexed yet. " + self.goto_info())
            self._place_goto()
            return
        base = os.path.splitext(os.path.basename(self.path))
        self.copyRequested.emit(text, f"{base[0]} (lines {start.value():,}-{start.value() + taken - 1:,}){base[1]}")
