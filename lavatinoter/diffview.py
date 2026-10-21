"""The Compare window: two (or three) editable panes with a centre gutter of connectors and copy arrows, a difference map, line and
word level highlighting, comparison options, merge output with conflict handling, reports, sessions and printing."""
import difflib
import json
import os
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen, QTextCursor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QToolButton, QVBoxLayout,
                               QWidget)

from . import comparecore as cc
from . import theme, util
from .editor import CodeEditor

MAX_LINES = cc.MAX_EXACT_LINES


def align(old, new):
    """-> (left lines, right lines, kinds, summary). kinds[i] is 'same' | 'add' | 'del' | 'chg' for row i; padding rows are None."""
    a, b = old.split("\n"), new.split("\n")
    if len(a) > MAX_LINES or len(b) > MAX_LINES:
        raise ValueError(f"The files are too long to compare here (limit {MAX_LINES:,} lines).")
    left, right, kinds = [], [], []
    added = removed = changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for x, y in zip(a[i1:i2], b[j1:j2]):
                left.append(x)
                right.append(y)
                kinds.append("same")
        elif tag == "delete":
            for x in a[i1:i2]:
                left.append(x)
                right.append(None)
                kinds.append("del")
            removed += i2 - i1
        elif tag == "insert":
            for y in b[j1:j2]:
                left.append(None)
                right.append(y)
                kinds.append("add")
            added += j2 - j1
        else:
            n = max(i2 - i1, j2 - j1)
            for k in range(n):
                left.append(a[i1 + k] if i1 + k < i2 else None)
                right.append(b[j1 + k] if j1 + k < j2 else None)
                kinds.append("chg")
            changed += n
    return left, right, kinds, (added, removed, changed)


@dataclass
class Side:
    title: str
    text: str
    apply: object = None             # callable(text): put the edited text back where it came from (None = read-only side)
    apply_label: str = "Apply"
    path: str = None
    raw: bytes = None                # the file's bytes, so the encoding can be changed
    encoding: str = "UTF-8"
    eol: str = "\n"


def file_side(path, title=None):
    """A side that reads and writes a file on disk."""
    with open(path, "rb") as f:
        raw = f.read()
    enc = util.detect_encoding(raw)
    text = util.normalize_newlines(util.decode_bytes(raw, enc).lstrip("﻿"))
    eol = util.detect_eol(util.decode_bytes(raw[:200000], enc))

    def apply(t, p=path, e=enc, o=eol):
        util.write_text_file(p, t, e, o)
    return Side(title or os.path.basename(path), text, apply, f"Save {os.path.basename(path)}", path, raw, enc, eol)


COLORS = {"chg": "ORANGE", "add": "ACCENT", "del": "RED"}


def tint(tag, alpha=80):
    c = QColor(theme.c(COLORS[tag]))
    c.setAlpha(alpha)
    return c


class RulesDialog(QDialog):
    """Regular expressions for text that does not matter, and replacements applied before comparing."""

    def __init__(self, parent, ignore_rules, replace_rules):
        super().__init__(parent)
        self.setWindowTitle("Comparison rules")
        self.resize(640, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Unimportant text</b> - regular expressions, one per line. Text that matches is left out of the comparison; "
                             "a line that differs only there is shown as an unimportant difference.<br>"
                             "Examples: <code>\\d{4}-\\d{2}-\\d{2}</code> (dates), <code>\\b[0-9a-f]{7,40}\\b</code> (commit ids), <code>v\\d+\\.\\d+\\.\\d+</code>"))
        self.ign = QPlainTextEdit("\n".join(ignore_rules))
        self.ign.setFont(theme.mono(10))
        lay.addWidget(self.ign, 1)
        lay.addWidget(QLabel("<b>Replace before comparing</b> - <code>regex =&gt; replacement</code>, one per line. "
                             "Example: <code>colou?r =&gt; color</code> makes colour and color count as the same."))
        self.rep = QPlainTextEdit("\n".join(f"{a} => {b}" for a, b in replace_rules))
        self.rep.setFont(theme.mono(10))
        lay.addWidget(self.rep, 1)
        self.msg = QLabel("")
        self.msg.setStyleSheet(f"color: {theme.c('RED')};")
        lay.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _ok(self):
        ign = [l for l in self.ign.toPlainText().split("\n") if l.strip()]
        rep = []
        for l in self.rep.toPlainText().split("\n"):
            if l.strip():
                a, _, b = l.partition("=>")
                rep.append((a.strip(), b.strip()))
        for rx in ign + [a for a, _ in rep]:
            err = cc.check_regex(rx)
            if err:
                self.msg.setText(f"'{rx}' is not a valid regular expression: {err}")
                return
        self.ignore_rules, self.replace_rules = ign, rep
        self.accept()


class Gutter(QWidget):
    """Draws the connectors between matching changed blocks and the copy arrows."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.hits = []
        self.setFixedWidth(52)
        self.setMouseTracking(True)

    def _y(self, ed, line, bottom=False):
        doc = ed.document()
        blk = doc.findBlockByNumber(min(line, doc.blockCount() - 1))
        geo = ed.blockBoundingGeometry(blk).translated(ed.contentOffset())
        y = geo.bottom() if (bottom or line >= doc.blockCount()) else geo.top()
        return ed.viewport().mapTo(self, QPoint(0, int(y))).y()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.c("PANEL")))
        self.hits = []
        w = self.win
        if w.mode == "3way" or not w.result:
            return
        L, R = w.edits
        h = self.height()
        for k, (tag, i1, i2, j1, j2) in enumerate(w.result.blocks):
            lt = self._y(L, i1)
            lb = self._y(L, i2 - 1, True) if i2 > i1 else lt
            rt = self._y(R, j1)
            rb = self._y(R, j2 - 1, True) if j2 > j1 else rt
            if max(lt, lb, rt, rb) < 0 or min(lt, lb, rt, rb) > h:
                continue
            col = tint(tag, 120)
            path = QPainterPath()
            W = self.width()
            path.moveTo(0, lt)
            path.cubicTo(W / 2, lt, W / 2, rt, W, rt)
            path.lineTo(W, max(rb, rt + 2))
            path.cubicTo(W / 2, max(rb, rt + 2), W / 2, max(lb, lt + 2), 0, max(lb, lt + 2))
            path.closeSubpath()
            sel = (k == w.cur)
            p.setPen(QPen(QColor(theme.c(COLORS[tag])), 2 if sel else 1))
            p.setBrush(col)
            p.drawPath(path)
            # copy arrows: ">" takes the left version to the right, "<" the right version to the left
            for to_right, x in ((True, 3), (False, W - 17)):
                src_ed, dst_ed = (L, R) if to_right else (R, L)
                can = not dst_ed.isReadOnly()
                top = (lt if to_right else rt) + 2
                rect = QRect(x, max(2, min(h - 16, top)), 14, 14)
                p.setPen(QPen(QColor(theme.c("BORDER2")), 1))
                p.setBrush(QColor(theme.c("PANEL2")) if can else QColor(theme.c("PANEL")))
                p.drawRoundedRect(rect, 3, 3)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.c("TEXT") if can else theme.c("FAINT")))
                cx, cy = rect.center().x() + 0.5, rect.center().y() + 0.5
                tri = QPainterPath()
                if to_right:
                    tri.moveTo(cx - 2.5, cy - 4)
                    tri.lineTo(cx + 3, cy)
                    tri.lineTo(cx - 2.5, cy + 4)
                else:
                    tri.moveTo(cx + 2.5, cy - 4)
                    tri.lineTo(cx - 3, cy)
                    tri.lineTo(cx + 2.5, cy + 4)
                tri.closeSubpath()
                p.drawPath(tri)
                if can:
                    self.hits.append((rect, k, to_right))
        p.end()

    def mousePressEvent(self, e):
        for rect, k, to_right in self.hits:
            if rect.contains(e.position().toPoint()):
                self.win.copy_blocks([k], to_right)
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        over = any(r.contains(e.position().toPoint()) for r, _k, _t in self.hits)
        self.setCursor(Qt.PointingHandCursor if over else Qt.ArrowCursor)


class DiffMap(QWidget):
    """A narrow strip showing where every difference sits in the file; click it to jump."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setFixedWidth(16)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.c("PANEL")))
        w = self.win
        if not w.result:
            return
        n = max(w.result.n_left, w.result.n_right, 1)
        H = self.height()
        for k, (tag, i1, i2, j1, j2) in enumerate(w.result.blocks):
            y = int(H * (i1 if tag != "add" else j1) / n)
            hh = max(3, int(H * max(i2 - i1, j2 - j1) / n))
            p.fillRect(2, y, self.width() - 4, hh, tint(tag, 255 if k == w.cur else 200))
        ed = w.edits[0]
        first = ed.firstVisibleBlock().blockNumber()
        vis = max(1, ed.viewport().height() // max(1, ed.fontMetrics().lineSpacing()))
        r = QRect(0, int(H * first / n), self.width() - 1, max(6, int(H * vis / n)))
        c = QColor(theme.c("TEXT"))
        c.setAlpha(40)
        p.fillRect(r, c)
        p.setPen(QPen(QColor(theme.c("MUTED")), 1))
        p.drawRect(r)
        p.end()

    def _go(self, e):
        w = self.win
        n = max(w.result.n_left if w.result else 1, 1)
        line = int(e.position().y() / max(1, self.height()) * n)
        w.edits[0].verticalScrollBar().setValue(max(0, line - 5))

    def mousePressEvent(self, e):
        self._go(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._go(e)


class DiffWindow(QDialog):
    def __init__(self, parent, left, right, base=None, lang=None, font_size=11, options=None, host=None, anchors=None, mode="2way"):
        super().__init__(parent)
        self.host = host or parent
        self.sides = [left, right]
        self.base_side = base
        self.lang = lang
        self.font_size = font_size
        self.opts = options or cc.Options()
        self.anchors = list(anchors or [])
        self.lock_anchors = bool(self.anchors)
        self.mode = "3way" if base is not None else mode
        self.result = None
        self.result_b = None            # 3-way: the right side against the base
        self.blocks = []
        self.starts = []
        self.cur = -1
        self._syncing = False
        self._busy = False
        self.sync_scroll = True
        self._applied = [left.text, right.text]
        self.setWindowTitle(f"Compare: {left.title}  ↔  {right.title}")
        self.setWindowFlag(Qt.Window, True)
        self.resize(1320, 800)
        for s in (left, right):
            if len(s.text.split("\n")) > MAX_LINES:
                raise ValueError(f"The files are too long to compare here (limit {MAX_LINES:,} lines).")
        self._timer = QTimer(self, singleShot=True, interval=350)
        self._timer.timeout.connect(self.refresh)
        self._build()
        self.refresh()
        if self.mode != "2way":
            self._set_mode(self.mode, rebuild=True)

    # ---- building the window --------------------------------------------------------------------------------------------------
    def _btn(self, text, tip, fn, primary=False):
        b = QPushButton(text)
        b.setToolTip(tip)
        b.setProperty("primary", primary)
        b.clicked.connect(lambda _=False, f=fn: f())
        return b

    def _menu_btn(self, text, items):
        b = QToolButton()
        b.setText(text + "  v")
        b.setPopupMode(QToolButton.InstantPopup)
        b.setStyleSheet("QToolButton { padding: 5px 10px; border: 1px solid %s; border-radius: 6px; }" % theme.c("BORDER2"))
        m = QMenu(b)
        for it in items:
            if it is None:
                m.addSeparator()
            else:
                m.addAction(it[0], it[1])
        b.setMenu(m)
        return b

    def _pane(self, side, ed_index):
        box = QFrame()
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        head = QHBoxLayout()
        lab = QLabel(side.title + ("" if side.apply else "   (read-only)"))
        lab.setProperty("heading", True)
        head.addWidget(lab, 1)
        enc = QComboBox()
        enc.addItem("Auto")
        enc.addItems(list(util.ENCODINGS))
        enc.setCurrentText("Auto")
        enc.setEnabled(side.raw is not None)
        enc.setToolTip("How the bytes of this file are read" if side.raw is not None else "Only files read from disk have an encoding to choose")
        enc.currentTextChanged.connect(lambda t, i=ed_index: self._set_encoding(i, t))
        head.addWidget(enc)
        btn = self._btn(side.apply_label, "Put this side's text back where it came from", lambda i=ed_index: self.apply(i), True)
        btn.setVisible(side.apply is not None)
        head.addWidget(btn)
        lay.addLayout(head)
        ed = CodeEditor()
        ed.apply_font(self.font_size)
        ed.set_word_wrap(False)
        ed.folding_on = False
        ed.show_guides = False
        if self.lang is not None:
            ed.lang_auto = False
            ed.set_language(self.lang)
        ed.setPlainText(side.text)
        ed.document().setModified(False)
        ed.setReadOnly(side.apply is None)
        ed.context_provider = self._context_items
        if hasattr(self.host, "wire_editor"):
            self.host.wire_editor(ed)
        lay.addWidget(ed, 1)
        return box, ed, btn, enc

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(4)
        # row 1: what changed, moving around, copying, layout, reports
        r1 = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setProperty("muted", True)
        r1.addWidget(self.summary, 1)
        r1.addWidget(self._btn("Previous", "Previous difference (Shift+F8)", lambda: self.step(-1)))
        r1.addWidget(self._btn("Next", "Next difference (F8)", lambda: self.step(1)))
        r1.addWidget(self._btn("Copy to right", "Copy this difference to the right side (Ctrl+Alt+Right)", lambda: self.copy_blocks(None, True)))
        r1.addWidget(self._btn("Copy to left", "Copy this difference to the left side (Ctrl+Alt+Left)", lambda: self.copy_blocks(None, False)))
        r1.addWidget(self._menu_btn("All", [("Copy every difference to the right", lambda: self.copy_blocks("all", True)),
                                            ("Copy every difference to the left", lambda: self.copy_blocks("all", False))]))
        self.mode_box = QComboBox()
        self.mode_box.addItems(["Two sides", "Two sides with merged output", "Three-way merge"])
        self.mode_box.setCurrentIndex({"2way": 0, "2way_out": 1, "3way": 2}[self.mode if self.mode in ("2way", "2way_out", "3way") else "2way"])
        self.mode_box.currentIndexChanged.connect(lambda i: self._set_mode(("2way", "2way_out", "3way")[i]))
        r1.addWidget(self.mode_box)
        r1.addWidget(self._btn("Layout", "Side by side or one above the other", self.flip_layout))
        r1.addWidget(self._menu_btn("Report", [("Save report as HTML...", lambda: self.save_report("html")), ("Save report as text...", lambda: self.save_report("text")),
                                               None, ("Save patch (unified)...", lambda: self.save_patch("unified")),
                                               ("Save patch (context)...", lambda: self.save_patch("context")), ("Save patch (normal)...", lambda: self.save_patch("normal")),
                                               None, ("Copy as HTML", self.copy_html), ("Print...", lambda: self.print_report(False)),
                                               ("Print preview...", lambda: self.print_report(True))]))
        r1.addWidget(self._menu_btn("Session", [("Save comparison session...", self.save_session_dialog), ("Open comparison session...", self.open_session_dialog)]))
        root.addLayout(r1)
        # row 2: options
        r2 = QHBoxLayout()
        self.ws_box = QComboBox()
        for k, v in cc.WS_MODES.items():
            self.ws_box.addItem(v, k)
        self.ws_box.setCurrentIndex(max(0, self.ws_box.findData(self.opts.ws)))
        self.ws_box.currentIndexChanged.connect(self._opts_changed)
        r2.addWidget(self.ws_box)
        self.cb = {}
        for key, text, tip in (("ignore_case", "Ignore case", ""), ("ignore_eol", "Ignore line endings", "CRLF and LF count as the same"),
                               ("ignore_blank_lines", "Ignore blank lines", ""), ("syntax_aware", "Syntax aware", "Ignore blank lines, comment-only lines and trailing comments")):
            c = QCheckBox(text)
            c.setToolTip(tip)
            c.setChecked(bool(getattr(self.opts, key)))
            c.toggled.connect(self._opts_changed)
            self.cb[key] = c
            r2.addWidget(c)
        self.gran = QComboBox()
        for k, v in cc.GRANULARITY.items():
            self.gran.addItem("Inside changed lines: " + v.lower(), k)
        self.gran.setCurrentIndex(max(0, self.gran.findData(self.opts.granularity)))
        self.gran.currentIndexChanged.connect(self._opts_changed)
        r2.addWidget(self.gran)
        r2.addWidget(self._btn("Rules...", "Unimportant text and replace rules", self.edit_rules))
        r2.addStretch(1)
        r2.addWidget(QLabel("Tab"))
        self.tab_spin = QSpinBox()
        self.tab_spin.setRange(1, 16)
        self.tab_spin.setValue(4)
        self.tab_spin.valueChanged.connect(self._view_changed)
        r2.addWidget(self.tab_spin)
        self.ws_cb = QCheckBox("Show whitespace")
        self.ws_cb.toggled.connect(self._view_changed)
        r2.addWidget(self.ws_cb)
        self.wrap_cb = QCheckBox("Wrap")
        self.wrap_cb.toggled.connect(self._view_changed)
        r2.addWidget(self.wrap_cb)
        self.sync_cb = QCheckBox("Sync scrolling")
        self.sync_cb.setChecked(True)
        self.sync_cb.toggled.connect(lambda on: setattr(self, "sync_scroll", on))
        r2.addWidget(self.sync_cb)
        self.collapse_cb = QCheckBox("Only differences")
        self.collapse_cb.setToolTip("Hide the matching parts, keeping a few lines around every difference")
        self.collapse_cb.toggled.connect(self._collapse_changed)
        r2.addWidget(self.collapse_cb)
        self.ctx_spin = QSpinBox()
        self.ctx_spin.setRange(0, 50)
        self.ctx_spin.setValue(3)
        self.ctx_spin.setToolTip("Lines of context around each difference")
        self.ctx_spin.valueChanged.connect(self._collapse_changed)
        r2.addWidget(self.ctx_spin)
        self.lock_cb = QCheckBox("Lock alignment")
        self.lock_cb.setToolTip("Keep the lines you aligned by hand (right-click a line > Align with the other side's cursor line)")
        self.lock_cb.setChecked(self.lock_anchors)
        self.lock_cb.toggled.connect(self._lock_changed)
        r2.addWidget(self.lock_cb)
        root.addLayout(r2)
        # find bar
        self.find_row = QWidget()
        fr = QHBoxLayout(self.find_row)
        fr.setContentsMargins(0, 0, 0, 0)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("Find in the pane you are working in...")
        self.find_edit.returnPressed.connect(lambda: self.find(False))
        fr.addWidget(self.find_edit, 1)
        self.find_regex = QCheckBox("Regex")
        self.find_case = QCheckBox("Match case")
        fr.addWidget(self.find_regex)
        fr.addWidget(self.find_case)
        fr.addWidget(self._btn("Previous", "Find previous (Shift+F3)", lambda: self.find(True)))
        fr.addWidget(self._btn("Next", "Find next (F3)", lambda: self.find(False)))
        fr.addWidget(self._btn("Go to line...", "Go to a line in the current pane (Ctrl+G)", self.goto_line))
        fr.addWidget(self._btn("Close", "", lambda: self.find_row.setVisible(False)))
        self.find_row.setVisible(False)
        root.addWidget(self.find_row)
        # panes
        self.outer = QSplitter(Qt.Vertical)
        self.outer.setChildrenCollapsible(False)
        self.top = QSplitter(Qt.Horizontal)
        self.top.setChildrenCollapsible(False)
        self.base_box = None
        self.base_edit = None
        left_box, self.left_ed, self.apply_l, self.enc_l = self._pane(self.sides[0], 0)
        right_box, self.right_ed, self.apply_r, self.enc_r = self._pane(self.sides[1], 1)
        self.edits = [self.left_ed, self.right_ed]
        self.apply_btns = [self.apply_l, self.apply_r]
        self.left_box, self.right_box = left_box, right_box
        self.gutter = Gutter(self)
        self.dmap = DiffMap(self)
        if self.base_side is not None:
            self.base_box, self.base_edit, _b, _e = self._pane(self.base_side, 2)
            self.base_edit.setReadOnly(False)
            self.top.addWidget(self.base_box)
        self.top.addWidget(left_box)
        self.top.addWidget(self.gutter)
        self.top.addWidget(right_box)
        self.top.addWidget(self.dmap)
        self.outer.addWidget(self.top)
        # merged output
        self.out_box = QFrame()
        ol = QVBoxLayout(self.out_box)
        ol.setContentsMargins(0, 0, 0, 0)
        oh = QHBoxLayout()
        self.out_label = QLabel("MERGED OUTPUT")
        self.out_label.setProperty("heading", True)
        oh.addWidget(self.out_label, 1)
        for text, tip, fn in (("Prev conflict", "Previous conflict", lambda: self.next_conflict(-1)), ("Next conflict", "Next conflict", lambda: self.next_conflict(1)),
                              ("Take left", "Use the left version of this conflict", lambda: self.resolve("left")),
                              ("Take right", "Use the right version of this conflict", lambda: self.resolve("right")),
                              ("Take both", "Left, then right", lambda: self.resolve("both")), ("Take base", "The original (three-way only)", lambda: self.resolve("base"))):
            oh.addWidget(self._btn(text, tip, fn))
        oh.addWidget(self._menu_btn("All", [("Resolve every conflict with left", lambda: self.resolve_all("left")), ("Resolve every conflict with right", lambda: self.resolve_all("right"))]))
        oh.addWidget(self._btn("Re-merge", "Build the merged text again from the panes above", self.build_output))
        oh.addWidget(self._btn("Save output...", "Save the merged text to a file", self.save_output))
        oh.addWidget(self._btn("Open in tab", "Open the merged text in a new tab", self.output_to_tab, True))
        ol.addLayout(oh)
        self.out_ed = CodeEditor()
        self.out_ed.apply_font(self.font_size)
        self.out_ed.folding_on = False
        if self.lang is not None:
            self.out_ed.lang_auto = False
            self.out_ed.set_language(self.lang)
        self.out_ed.document().contentsChanged.connect(self._timer.start)
        ol.addWidget(self.out_ed, 1)
        self.out_box.setVisible(False)
        self.outer.addWidget(self.out_box)
        root.addWidget(self.outer, 1)
        self.top.setSizes([52 if self.top.widget(i) is self.gutter else 16 if self.top.widget(i) is self.dmap else 600 for i in range(self.top.count())])
        for fixed in (self.gutter, self.dmap):
            self.top.setStretchFactor(self.top.indexOf(fixed), 0)
        # behaviour: scrolling, editing, shortcuts
        for i in (0, 1):
            self.edits[i].verticalScrollBar().valueChanged.connect(lambda v, i=i: self._scrolled(i))
            self.edits[i].horizontalScrollBar().valueChanged.connect(lambda v, i=i: self._hscrolled(i))
            self.edits[i].document().contentsChanged.connect(self._timer.start)
        if self.base_edit is not None:
            self.base_edit.document().contentsChanged.connect(self._timer.start)
        from PySide6.QtGui import QAction, QKeySequence
        for seq, fn in (("F8", lambda: self.step(1)), ("Shift+F8", lambda: self.step(-1)), ("Ctrl+Alt+Right", lambda: self.copy_blocks(None, True)),
                        ("Ctrl+Alt+Left", lambda: self.copy_blocks(None, False)), ("Ctrl+F", self.show_find), ("F3", lambda: self.find(False)),
                        ("Shift+F3", lambda: self.find(True)), ("Ctrl+G", self.goto_line), ("F2", lambda: self._bookmark(True)),
                        ("Shift+F2", lambda: self._bookmark(False))):
            a = QAction(self)
            a.setShortcut(QKeySequence(seq))
            a.triggered.connect(lambda _=False, f=fn: f())
            self.addAction(a)
        self._view_changed()

    # ---- running the comparison ------------------------------------------------------------------------------------------------------
    def _read_opts(self):
        o = self.opts
        o.ws = self.ws_box.currentData()
        for k, c in self.cb.items():
            setattr(o, k, c.isChecked())
        o.granularity = self.gran.currentData()
        o.comment_prefix = (self.lang.comment if self.lang is not None and self.lang.comment else "") if o.syntax_aware else ""
        return o

    def _opts_changed(self, *_):
        self._read_opts()
        if hasattr(self.host, "settings"):
            try:
                self.host.settings["compare_options"] = self.opts.to_dict()
            except Exception:  # noqa: BLE001
                pass
        self._timer.start()

    def _lines(self, side):
        return self.edits[side].toPlainText().split("\n")

    def _anchors(self):
        return self.anchors if self.lock_anchors or self.anchors else []

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        try:
            a, b = self._lines(0), self._lines(1)
            self._read_opts()
            if len(a) > MAX_LINES or len(b) > MAX_LINES:
                self.summary.setText("Too long to compare while editing.")
                return
            if self.mode == "3way" and self.base_edit is not None:
                base = self.base_edit.toPlainText().split("\n")
                self.result = cc.compare(base, a, self.opts)           # base (left of the pair) against the left version
                self.result_b = cc.compare(base, b, self.opts)
                self._paint_three(base, a, b)
                self.blocks = []
                self.starts = []
                n = len(self.result.blocks) + len(self.result_b.blocks)
                self.summary.setText(f"Three-way: left changes {len(self.result.blocks)} block(s), right changes {len(self.result_b.blocks)} block(s) against the base")
            else:
                self.result = cc.compare(a, b, self.opts, self._anchors())
                self.result_b = None
                self.blocks = list(self.result.blocks)
                self.starts = [blk[1] for blk in self.blocks]
                self._paint_two(a, b)
                self._summarise()
            if self.cur >= len(self.blocks):
                self.cur = len(self.blocks) - 1
            self._apply_collapse()
            self.gutter.update()
            self.dmap.update()
        finally:
            self._busy = False

    def _summarise(self):
        r = self.result
        added, removed, changed = r.stats()
        if r.identical:
            text = "The two sides are identical." if not (r.unimportant_left or r.unimportant_right) else \
                f"No real differences ({len(r.unimportant_left)} unimportant line difference(s))."
        else:
            text = (f"{len(r.blocks)} difference block{'s' if len(r.blocks) != 1 else ''}:  {added} only in right, {removed} only in left, "
                    f"{changed} changed lines" + (f",  {len(r.unimportant_left)} unimportant" if r.unimportant_left else ""))
        if not self.opts.ignore_eol and self.sides[0].eol != self.sides[1].eol:
            names = {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}
            text += f"   |   line endings differ: {names.get(self.sides[0].eol, '?')} / {names.get(self.sides[1].eol, '?')}"
        self.summary.setText(text)

    def _paint_two(self, a, b):
        res = self.result
        tints = [{}, {}]
        spans = [{}, {}]
        unimp = QColor(theme.c("FAINT"))
        unimp.setAlpha(45)
        for tag, i1, i2, j1, j2 in res.blocks:
            for i in range(i1, i2):
                tints[0][i] = tint("del" if tag == "del" else "chg")
            for j in range(j1, j2):
                tints[1][j] = tint("add" if tag == "add" else "chg")
        for i in res.unimportant_left:
            tints[0][i] = unimp
        for j in res.unimportant_right:
            tints[1][j] = unimp
        for i, sp in res.intra_left.items():
            spans[0][i] = [(s, e, tint("chg", 170)) for s, e in sp]
        for j, sp in res.intra_right.items():
            spans[1][j] = [(s, e, tint("chg", 170)) for s, e in sp]
        for ed, t, sp in zip(self.edits, tints, spans):
            ed.line_tint = t
            ed.span_tint = sp
            ed.refresh_selections()
        for ed in (self.base_edit,):
            if ed is not None:
                ed.line_tint, ed.span_tint = {}, {}
                ed.refresh_selections()

    def _paint_three(self, base, a, b):
        for ed, res, tg in ((self.edits[0], self.result, "chg"), (self.edits[1], self.result_b, "chg")):
            t, sp = {}, {}
            for tag, i1, i2, j1, j2 in res.blocks:
                for j in range(j1, j2):
                    t[j] = tint("add" if tag == "add" else "chg")
            for j, spl in res.intra_right.items():
                sp[j] = [(s, e, tint("chg", 170)) for s, e in spl]
            ed.line_tint, ed.span_tint = t, sp
            ed.refresh_selections()
        bt = {}
        for res in (self.result, self.result_b):
            for tag, i1, i2, j1, j2 in res.blocks:
                for i in range(i1, i2):
                    bt[i] = tint("del" if tag == "del" else "chg", 60)
        self.base_edit.line_tint, self.base_edit.span_tint = bt, {}
        self.base_edit.refresh_selections()

    # ---- viewing options ---------------------------------------------------------------------------------------------------------------
    def _view_changed(self, *_):
        for ed in self.edits + [e for e in (self.base_edit, self.out_ed) if e is not None]:
            ed.set_tab_width(self.tab_spin.value())
            ed.set_show_whitespace(self.ws_cb.isChecked())
            ed.set_word_wrap(self.wrap_cb.isChecked())
        self.gutter.update()

    def _scrolled(self, side):
        if self.sync_scroll and not self._syncing and self.result and self.mode != "3way":
            self._syncing = True
            try:
                first = self.edits[side].firstVisibleBlock().blockNumber()
                other = self.edits[1 - side]
                other.verticalScrollBar().setValue(cc.map_line(self.result, side, first))
            finally:
                self._syncing = False
        elif self.sync_scroll and not self._syncing and self.mode == "3way":
            self._syncing = True
            try:
                v = self.edits[side].verticalScrollBar().value()
                for e in [self.edits[1 - side], self.base_edit]:
                    if e is not None:
                        e.verticalScrollBar().setValue(v)
            finally:
                self._syncing = False
        self.gutter.update()
        self.dmap.update()

    def _hscrolled(self, side):
        if self.sync_scroll and not self._syncing:
            self._syncing = True
            self.edits[1 - side].horizontalScrollBar().setValue(self.edits[side].horizontalScrollBar().value())
            self._syncing = False

    def flip_layout(self):
        horizontal = self.top.orientation() == Qt.Horizontal
        self.top.setOrientation(Qt.Vertical if horizontal else Qt.Horizontal)
        self.gutter.setVisible(not horizontal and self.mode != "3way")
        self.gutter.setFixedWidth(52)
        self.dmap.setVisible(True)

    def _collapse_changed(self, *_):
        self._apply_collapse()

    def _apply_collapse(self):
        on = self.collapse_cb.isChecked() and self.result is not None and self.mode != "3way"
        hide = [[], []]
        if on:
            for i1, i2, j1, j2 in cc.hidden_ranges(self.result, self.ctx_spin.value()):
                hide[0].append((i1, i2))
                hide[1].append((j1, j2))
        for ed, ranges in zip(self.edits, hide):
            flags = set()
            for a, b in ranges:
                flags.update(range(a, b + 1))
            doc = ed.document()
            blk, i, changed = doc.firstBlock(), 0, False
            while blk.isValid():
                want = i not in flags
                if blk.isVisible() != want:
                    blk.setVisible(want)
                    blk.setLineCount(1 if want else 0)
                    changed = True
                blk, i = blk.next(), i + 1
            if changed:
                doc.markContentsDirty(0, max(1, doc.characterCount() - 1))
                ed.viewport().update()

    # ---- alignment ----------------------------------------------------------------------------------------------------------------------------
    def _lock_changed(self, on):
        self.lock_anchors = on
        self._timer.start()

    def align_here(self, side):
        """Forces the line under the caret in `side` to line up with the other side's caret line."""
        other = 1 - side
        mine, theirs = self.edits[side].textCursor().blockNumber(), self.edits[other].textCursor().blockNumber()
        pair = (mine, theirs) if side == 0 else (theirs, mine)
        self.anchors = [a for a in self.anchors if a[0] != pair[0] and a[1] != pair[1]] + [pair]
        self.anchors.sort()
        self.lock_cb.setChecked(True)
        self.lock_anchors = True
        self.refresh()

    def clear_alignment(self):
        self.anchors = []
        self.lock_cb.setChecked(False)
        self.refresh()

    # ---- moving through differences ----------------------------------------------------------------------------------------------------------
    def step(self, d):
        if self.mode == "3way" or not self.blocks:
            return
        self.cur = (self.cur + d) % len(self.blocks)
        t, i1, i2, j1, j2 = self.blocks[self.cur]
        self._syncing = True
        for ed, row in zip(self.edits, (i1, j1)):
            c = QTextCursor(ed.document().findBlockByNumber(min(row, ed.blockCount() - 1)))
            ed.setTextCursor(c)
            ed.centerCursor()
        self._syncing = False
        self.gutter.update()
        self.dmap.update()

    def _current_block(self):
        for side in (0, 1):
            if self.edits[side].hasFocus():
                line = self.edits[side].textCursor().blockNumber()
                for k, blk in enumerate(self.blocks):
                    lo, hi = (blk[1], blk[2]) if side == 0 else (blk[3], blk[4])
                    if lo <= line < max(hi, lo + 1):
                        return k
        return self.cur if 0 <= self.cur < len(self.blocks) else None

    def _focused(self):
        for e in self.edits + [x for x in (self.base_edit, self.out_ed) if x is not None]:
            if e.hasFocus():
                return e
        return self.edits[0]

    def _bookmark(self, forward):
        self._focused().goto_bookmark(forward)

    def show_find(self):
        self.find_row.setVisible(True)
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def find(self, backward):
        from . import finddialog, search
        text = self.find_edit.text()
        if not text:
            self.show_find()
            return
        o = search.Options(text=text, mode=search.REGEX if self.find_regex.isChecked() else search.NORMAL, match_case=self.find_case.isChecked())
        ed = self._focused() if any(e.hasFocus() for e in self.edits) else self._last_find_ed if getattr(self, "_last_find_ed", None) else self.edits[0]
        self._last_find_ed = ed
        try:
            if not finddialog.editor_find(ed, o, backward):
                self.summary.setText(f'"{text}" not found in this pane')
        except search.SearchError as e:
            self.summary.setText(str(e))

    def goto_line(self):
        ed = self._focused() if any(e.hasFocus() for e in self.edits) else getattr(self, "_last_find_ed", self.edits[0])
        n, ok = QInputDialog.getInt(self, "Go to line", f"Line (1 - {ed.blockCount()}):", ed.textCursor().blockNumber() + 1, 1, ed.blockCount())
        if ok:
            ed.goto_line(n)

    # ---- editing: copying differences across ----------------------------------------------------------------------------------------------
    def copy_blocks(self, which, to_right):
        """Makes one difference (or the listed ones, or "all") on the target side the same as on the source side."""
        if self.mode == "3way" or not self.blocks:
            return
        if which is None:
            k = self._current_block()
            if k is None:
                return
            which = [k]
        elif which == "all":
            which = list(range(len(self.blocks)))
        target = 1 if to_right else 0
        if self.edits[target].isReadOnly():
            QMessageBox.information(self, "Compare", "That side is read-only.")
            return
        a, b = self._lines(0), self._lines(1)
        src, dst = (a, b) if to_right else (b, a)
        out, pos = [], 0
        for k in sorted(which):
            t, i1, i2, j1, j2 = self.blocks[k]
            s1, s2, d1, d2 = (i1, i2, j1, j2) if to_right else (j1, j2, i1, i2)
            out += dst[pos:d1] + src[s1:s2]
            pos = d2
        out += dst[pos:]
        self.edits[target].replace_document_text("\n".join(out))
        self.refresh()

    def copy_block(self, to_right):
        self.copy_blocks(None, to_right)

    def _map_line(self, side, line):
        return cc.map_line(self.result, side, line) if self.result else line

    def copy_selected(self, to_right):
        """Copies every difference that the selected lines of the current pane touch."""
        side = 0 if self.edits[0].hasFocus() or not self.edits[1].hasFocus() else 1
        cur = self.edits[side].textCursor()
        first, last = cur.document().findBlock(cur.selectionStart()).blockNumber(), cur.document().findBlock(cur.selectionEnd()).blockNumber()
        hits = [k for k, blk in enumerate(self.blocks)
                if (blk[1] if side == 0 else blk[3]) <= last and first < max((blk[2] if side == 0 else blk[4]), (blk[1] if side == 0 else blk[3]) + 1)]
        if hits:
            self.copy_blocks(hits, to_right)

    def apply(self, side):
        fn = self.sides[side].apply
        if fn is None:
            return
        text = self.edits[side].toPlainText()
        try:
            fn(text)
        except OSError as e:
            QMessageBox.warning(self, "Compare", f"Could not apply the changes:\n{e}")
            return
        self._applied[side] = text
        b = self.apply_btns[side]
        b.setText(b.text().split("  (done)")[0] + "  (done)")

    def _unapplied(self):
        return [s for s in (0, 1) if self.sides[s].apply is not None and self.edits[s].toPlainText() != self._applied[s]]

    def closeEvent(self, e):
        pending = self._unapplied()
        if pending:
            box = QMessageBox(QMessageBox.Question, "Compare", "You changed text in the comparison that is not applied yet.")
            apply_b = box.addButton("Apply and close", QMessageBox.AcceptRole)
            box.addButton("Discard changes", QMessageBox.DestructiveRole)
            cancel = box.addButton(QMessageBox.Cancel)
            box.exec()
            if box.clickedButton() is cancel:
                e.ignore()
                return
            if box.clickedButton() is apply_b:
                for s in pending:
                    self.apply(s)
        super().closeEvent(e)

    def _set_encoding(self, index, label):
        side = self.sides[index]
        if side.raw is None:
            return
        enc = util.detect_encoding(side.raw) if label == "Auto" else label
        text = util.normalize_newlines(util.decode_bytes(side.raw, enc).lstrip("﻿"))
        side.encoding = enc
        self.edits[index].setPlainText(text)
        self.edits[index].document().setModified(False)
        self._applied[index] = text
        self.refresh()

    # ---- the right-click menu in the panes -----------------------------------------------------------------------------------------------------
    def _context_items(self, menu, editor):
        if editor not in self.edits:
            return False
        side = self.edits.index(editor)
        to_right = side == 0
        other = "right" if to_right else "left"
        menu.addAction("Next difference", lambda: self.step(1))
        menu.addAction("Previous difference", lambda: self.step(-1))
        k = self._current_block() if self.blocks and self.mode != "3way" else None
        a = menu.addAction(f"Copy this difference to the {other}", lambda: self.copy_blocks(None, to_right))
        a.setEnabled(k is not None and not self.edits[1 - side].isReadOnly())
        has_sel = editor.textCursor().hasSelection()
        a = menu.addAction(f"Copy the selected differences to the {other}", lambda: self.copy_selected(to_right))
        a.setEnabled(has_sel and not self.edits[1 - side].isReadOnly())
        menu.addSeparator()
        menu.addAction("Align this line with the other side's cursor line", lambda: self.align_here(side)).setEnabled(self.mode != "3way")
        menu.addAction("Remove alignment overrides", self.clear_alignment).setEnabled(bool(self.anchors))
        sel = editor.textCursor().selectedText().replace(" ", "\n")
        a = menu.addAction("Ignore the selected text (unimportant)", lambda: self.ignore_text(sel))
        a.setEnabled(bool(sel.strip()) and "\n" not in sel)
        menu.addAction("Only differences" + (" (on)" if self.collapse_cb.isChecked() else ""), lambda: self.collapse_cb.toggle())
        menu.addAction("Find...", self.show_find)
        return True

    def ignore_text(self, text):
        import re
        if text and re.escape(text) not in self.opts.ignore_rules:
            self.opts.ignore_rules.append(re.escape(text))
        self.refresh()

    def edit_rules(self):
        d = RulesDialog(self, self.opts.ignore_rules, self.opts.replace_rules)
        if d.exec() == QDialog.Accepted:
            self.opts.ignore_rules, self.opts.replace_rules = d.ignore_rules, d.replace_rules
            self._opts_changed()

    # ---- merging ---------------------------------------------------------------------------------------------------------------------------------------
    def _set_mode(self, mode, rebuild=False):
        self.mode = mode
        three = mode == "3way"
        if three and self.base_edit is None:
            QMessageBox.information(self, "Compare", "A three-way merge needs a base (the common original): use Tools > Compare > Three-way Merge...")
            self.mode_box.blockSignals(True)
            self.mode_box.setCurrentIndex(0)
            self.mode_box.blockSignals(False)
            self.mode = "2way"
            return
        if self.base_box is not None:
            self.base_box.setVisible(three)
        self.gutter.setVisible(not three and self.top.orientation() == Qt.Horizontal)
        self.out_box.setVisible(mode != "2way")
        self.mode_box.blockSignals(True)
        self.mode_box.setCurrentIndex({"2way": 0, "2way_out": 1, "3way": 2}[mode])
        self.mode_box.blockSignals(False)
        if mode != "2way":
            self.build_output()
        self.refresh()

    def build_output(self):
        a, b = self._lines(0), self._lines(1)
        if self.mode == "3way" and self.base_edit is not None:
            chunks = cc.merge3(self.base_edit.toPlainText().split("\n"), a, b)
            text, n = cc.render_merge(chunks, True)
        else:
            chunks = cc.two_way_conflicts(a, b, self.opts)
            text, n = cc.render_merge(chunks, False)
        self._busy = True
        self.out_ed.setPlainText(text)
        self._busy = False
        self.out_ed.document().setModified(False)
        self._mark_output()
        self.out_label.setText(f"MERGED OUTPUT   -   {n} conflict{'s' if n != 1 else ''} to resolve" if n else "MERGED OUTPUT   -   no conflicts")
        self.outer.setSizes([520, 280])

    def _mark_output(self):
        lines = self.out_ed.toPlainText().split("\n")
        t = {}
        red = tint("del", 70)
        for first, last, *_ in cc.find_conflicts(lines):
            for i in range(first, last + 1):
                t[i] = red
        self.out_ed.line_tint = t
        self.out_ed.refresh_selections()
        n = len(cc.find_conflicts(lines))
        self.out_label.setText(f"MERGED OUTPUT   -   {n} conflict{'s' if n != 1 else ''} left" if n else "MERGED OUTPUT   -   no conflicts left")

    def _conflict_at_caret(self):
        lines = self.out_ed.toPlainText().split("\n")
        cs = cc.find_conflicts(lines)
        row = self.out_ed.textCursor().blockNumber()
        for k, c in enumerate(cs):
            if c[0] <= row <= c[1]:
                return k
        return 0 if cs else None

    def next_conflict(self, d):
        lines = self.out_ed.toPlainText().split("\n")
        cs = cc.find_conflicts(lines)
        if not cs:
            return
        row = self.out_ed.textCursor().blockNumber()
        if d > 0:
            nxt = next((c for c in cs if c[0] > row), cs[0])
        else:
            nxt = next((c for c in reversed(cs) if c[0] < row), cs[-1])
        self.out_ed.goto_line(nxt[0] + 1)

    def resolve(self, choice):
        k = self._conflict_at_caret()
        if k is None:
            return
        lines = cc.resolve_conflict(self.out_ed.toPlainText().split("\n"), k, choice)
        self.out_ed.replace_document_text("\n".join(lines))
        self._mark_output()

    def resolve_all(self, choice):
        lines = self.out_ed.toPlainText().split("\n")
        while cc.find_conflicts(lines):
            lines = cc.resolve_conflict(lines, 0, choice)
        self.out_ed.replace_document_text("\n".join(lines))
        self._mark_output()

    def save_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save merged output", "", "All files (*.*)")
        if path:
            util.write_text_file(path, self.out_ed.toPlainText(), "UTF-8", self.sides[1].eol if self.sides[1].eol else "\n")

    def output_to_tab(self):
        if hasattr(self.host, "new_file"):
            self.host.new_file(self.out_ed.toPlainText(), "merged output")

    # ---- reports, patches, printing ------------------------------------------------------------------------------------------------------------------
    def _report_args(self):
        a, b = self._lines(0), self._lines(1)
        res = self.result if self.mode != "3way" else cc.compare(a, b, self.opts)
        return res, a, b

    def save_report(self, kind):
        res, a, b = self._report_args()
        ext, flt = ("html", "HTML (*.html)") if kind == "html" else ("txt", "Text (*.txt)")
        path, _ = QFileDialog.getSaveFileName(self, "Save report", f"compare-report.{ext}", flt)
        if not path:
            return
        body = (cc.report_html(res, a, b, self.sides[0].title, self.sides[1].title, self.ctx_spin.value()) if kind == "html"
                else cc.report_text(res, a, b, self.sides[0].title, self.sides[1].title))
        with open(path, "w", encoding="utf-8") as f:
            f.write(body)

    def save_patch(self, kind):
        a, b = self._lines(0), self._lines(1)
        fn = {"unified": cc.unified, "context": cc.context, "normal": lambda x, y, *r: cc.normal(x, y)}[kind]
        path, _ = QFileDialog.getSaveFileName(self, "Save patch", "changes.patch", "Patch (*.patch *.diff)")
        if path:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(fn(a, b, self.sides[0].title, self.sides[1].title))

    def copy_html(self):
        from PySide6.QtCore import QMimeData
        res, a, b = self._report_args()
        md = QMimeData()
        md.setHtml(cc.report_html(res, a, b, self.sides[0].title, self.sides[1].title, self.ctx_spin.value(), fragment=True))
        md.setText(cc.report_text(res, a, b, self.sides[0].title, self.sides[1].title))
        QGuiApplication.clipboard().setMimeData(md)
        self.summary.setText("The comparison was copied as HTML: paste it into an email or a document.")

    def print_report(self, preview):
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrintDialog, QPrintPreviewDialog
        from . import export
        res, a, b = self._report_args()
        doc = QTextDocument()
        doc.setHtml(cc.report_html(res, a, b, self.sides[0].title, self.sides[1].title, self.ctx_spin.value()))
        pr = export.make_printer()
        pr.setDocName("Compare report")
        if preview:
            dlg = QPrintPreviewDialog(pr, self)
            dlg.paintRequested.connect(lambda printer: doc.print_(printer))
            dlg.resize(1000, 750)
            dlg.exec()
        else:
            dlg = QPrintDialog(pr, self)
            if dlg.exec() == QDialog.Accepted:
                doc.print_(pr)

    # ---- sessions -------------------------------------------------------------------------------------------------------------------------------------------
    def session_data(self):
        def side(s, ed):
            d = {"title": s.title, "encoding": s.encoding}
            if s.path and os.path.exists(s.path) and ed.toPlainText() == self._applied_text(s):
                d["path"] = s.path
            else:
                d["text"] = ed.toPlainText()
                if s.path:
                    d["path"] = s.path
            return d
        data = {"version": 1, "left": side(self.sides[0], self.edits[0]), "right": side(self.sides[1], self.edits[1]),
                "options": self.opts.to_dict(), "anchors": [list(a) for a in self.anchors], "lock_anchors": self.lock_anchors,
                "mode": self.mode, "collapse": self.collapse_cb.isChecked(), "context": self.ctx_spin.value(),
                "language": self.lang.name if self.lang is not None else None}
        if self.base_side is not None and self.base_edit is not None:
            data["base"] = side(self.base_side, self.base_edit)
        return data

    @staticmethod
    def _applied_text(s):
        try:
            return util.read_text_file(s.path)[0]
        except OSError:
            return None

    def save_session_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save comparison session", "comparison.lncmp", "Comparison session (*.lncmp)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(cc.session_to_json(self.session_data()))

    def open_session_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open comparison session", "", "Comparison session (*.lncmp)")
        if path and hasattr(self.host, "open_comparison_session"):
            self.host.open_comparison_session(path)
            self.close()


def side_from_session(d):
    """A Side from a saved session entry: the file again when it is still there, else the text that was saved with it."""
    path = d.get("path")
    if path and os.path.exists(path) and "text" not in d:
        return file_side(path, d.get("title"))
    s = Side(d.get("title", "text"), d.get("text", ""), None, "Apply")
    s.path = path
    return s
