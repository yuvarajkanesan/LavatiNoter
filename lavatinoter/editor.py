"""The code editor widget: line numbers, bookmarks, smart highlight, bracket matching, indentation helpers
and picture paste (clipboard images are saved next to the document and linked in)."""
import datetime
import os
import re
import time

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import (QIcon, QGuiApplication, QAction, QColor, QPen, QFont, QFontMetricsF, QImage, QPainter, QPalette, QPixmap, QTextCharFormat, QTextCursor, QTextFormat,
                           QTextOption, QTextBlockUserData)
from PySide6.QtWidgets import (QApplication, QCompleter, QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QTextEdit, QToolButton, QToolTip, QVBoxLayout, QWidget,
                               QWidgetAction)

from . import folding, richtext
from .ctxmenu import ContextMenu
from . import spell as spellmod
from . import theme, util
from .finddialog_pos import PosMap
from .highlighter import PLAIN, RICH_LANGS, Highlighter, lang_for_path, mark_spans, para_style, rich_matches

BRACKETS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = {v: k for k, v in BRACKETS.items()}
WORD_RE = re.compile(r"\w+")


class BlockData(QTextBlockUserData):
    def __init__(self):
        super().__init__()
        self.bookmark = False
        self.folded = False


class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.ed = editor

    def sizeHint(self):
        return QSize(self.ed.gutter_width(), 0)

    def paintEvent(self, e):
        self.ed.paint_gutter(e)

    def mousePressEvent(self, e):
        self.ed.gutter_click(e)


class _SwatchRow(QWidget):
    """Colour swatches in a row inside a menu; a click runs fn(slot) and closes the menu."""

    def __init__(self, title, colors, fn, enabled=True):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 6, 12, 8)
        outer.setSpacing(6)
        label = QLabel(title.upper())
        label.setStyleSheet(f"color: {theme.c('FAINT')}; font-size: 10px; font-weight: 600; letter-spacing: 1px; background: transparent;")
        outer.addWidget(label)
        lay = QHBoxLayout()
        lay.setSpacing(6)
        outer.addLayout(lay)
        for slot, col in enumerate(colors):
            b = QToolButton()
            b.setFixedSize(22, 22)
            b.setEnabled(enabled)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"Style {slot + 1}")
            b.setStyleSheet(f"QToolButton {{ background: {col}; border: 1px solid rgba(0,0,0,40); border-radius: 6px; padding: 0; }} "
                            f"QToolButton:hover {{ border: 2px solid {theme.c('ACCENT')}; }} QToolButton:disabled {{ background: {theme.c('BORDER')}; }}")
            b.clicked.connect(lambda _=False, sl=slot: self._pick(fn, sl))
            lay.addWidget(b)
        lay.addStretch(1)

    @staticmethod
    def _pick(fn, slot):
        QApplication.closeAllPopups()
        QTimer.singleShot(0, lambda: fn(slot))


class CodeEditor(QPlainTextEdit):
    cursorStatus = Signal()                 # caret / selection / mode changed: refresh the status bar
    zoomRequested = Signal(int)             # Ctrl+wheel
    filesDropped = Signal(list)             # local files dropped or pasted: the window opens them
    imagePasted = Signal(str)               # path of the image file that was saved for a paste
    definitionRequested = Signal(str)       # Ctrl+click on a name: the window finds its definition
    openPathRequested = Signal(str)         # 'Open File' in the right-click menu
    statusMessage = Signal(str)             # short messages for the status bar
    imageActivated = Signal(str)            # a picture was double-clicked: the window shows it large

    is_large = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path = None
        self.encoding = "UTF-8"
        self.eol = "\r\n" if os.name == "nt" else "\n"
        self.lang = PLAIN
        self.line_base = 0                  # large-file windows show real line numbers: base + block number
        self.line_prefix = ""               # "~" while a large file's line numbers are still estimates
        self.tab_width = 4
        self.use_spaces = True
        self.image_folder = "images"
        self.read_only_window = False
        self.marks = []                     # [(start, length)] highlighted by the Mark tab
        self._pix_cache = {}
        self.autocomplete_on = False
        self._has_para = False
        self._in_para = False
        self._shaded = set()
        self._para_timer = QTimer(self, singleShot=True, interval=140)
        self._para_timer.timeout.connect(self._refresh_paragraphs)
        self.mini_toolbar = True            # the Word-style formatting box above the right-click menu
        self.styles_all = {}               # {slot: token}: every occurrence of the token is coloured
        self.styles_one = {}               # {slot: [QTextCursor]}: single places coloured by hand
        self._style_cache = (None, "")
        self._sel_mark = None              # where Begin/End Select started
        self.user_hidden = []              # [(cursor at the first hidden line, cursor at the end of the last)]
        self.plugin_actions_provider = None
        self.path_resolver = None          # callable(text) -> existing path or ''
        self.context_provider = None       # callable(menu, editor) -> True when it added items (the Compare window uses it)
        self.search_url = "https://www.google.com/search?q={q}"
        self.line_tint = {}                # {line: QColor}: lines painted in a colour (the comparison window)
        self.span_tint = {}                # {line: [(start, end, QColor)]}: parts of lines (the changed words)
        self._edit_link = None             # block number of a picture link being edited by hand (Enter on a selected picture)
        self.copy_styled = True            # plain-text copy of formatted text uses bold / italic look-alike characters
        self.lang_auto = False             # the language follows what the text looks like (new documents, unknown extensions)
        self._auto_rev = -1
        self.diagnostics = []              # [(line, col, end line, end col, severity, message)] from a language server
        self.hover_provider = None         # callable (line, col) -> text, set by the window when a language server is running
        self.macro_rec = None               # a list while a macro is being recorded
        self.macro_playing = False
        self.git_marks = {}                 # {line: 'added' | 'modified' | 'deleted'} against Git HEAD
        self.extra_cursors = []
        self._col_anchor = None
        self.is_hex = False
        self.config = {}
        self.folding_on = True
        self.fold_regions = {}
        self._has_flags = False
        self._hidden_any = False
        self._fold_pills = []
        self._fold_timer = QTimer(self, singleShot=True, interval=450)
        self._fold_timer.timeout.connect(self.recompute_folds)
        self.autoclose_on = False
        self.show_guides = True
        self._word_cache = (None, 0.0, None)
        self._completer = QCompleter(QStringListModel([], self), self)
        self._completer.setWidget(self)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setMaxVisibleItems(3)
        self._completer.activated[str].connect(self._insert_completion)
        self._preview_rects = []            # [(QRect, link block)] of the pictures drawn in the last paint
        self._img_sel = None                # block number of the selected picture
        self._in_zone_fix = False
        self._prev_block = 0
        self._prev_col = 0
        self.autocorrect_on = False
        self._ac = None                     # the last automatic correction, so Backspace can take it back
        self.gutter = LineNumberArea(self)
        self.highlighter = Highlighter(self.document())
        self.highlighter.view = self
        self._smart = []
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFrameShape(QPlainTextEdit.NoFrame)
        self.setCursorWidth(2)
        self.setAcceptDrops(True)
        self.setUndoRedoEnabled(True)
        self.document().setDocumentMargin(8)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self.cursorPositionChanged.connect(self._on_cursor)
        self.selectionChanged.connect(self._on_cursor)
        self.document().contentsChange.connect(self._on_edit)
        self.verticalScrollBar().valueChanged.connect(self._schedule_refresh)
        self._refresh_timer = QTimer(self, singleShot=True, interval=60)
        self._refresh_timer.timeout.connect(self.refresh_selections)
        self.apply_font(11)
        self._update_gutter_width()
        self.refresh_selections()

    # ---- appearance ------------------------------------------------------------------------------
    def apply_font(self, size):
        f = theme.mono(size)
        self.setFont(f)
        self.setTabStopDistance(QFontMetricsF(f).horizontalAdvance(" ") * self.tab_width)
        self._update_gutter_width()

    def set_tab_width(self, n):
        self.tab_width = n
        self.setTabStopDistance(QFontMetricsF(self.font()).horizontalAdvance(" ") * n)

    def set_word_wrap(self, on):
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth if on else QPlainTextEdit.NoWrap)

    def set_show_whitespace(self, on):
        opt = self.document().defaultTextOption()
        flags = opt.flags()
        if on:
            flags |= QTextOption.ShowTabsAndSpaces
        else:
            flags &= ~QTextOption.ShowTabsAndSpaces
        opt.setFlags(flags)
        self.document().setDefaultTextOption(opt)

    def restyle(self):
        self.highlighter.rebuild_formats()
        self.refresh_selections()
        self.gutter.update()

    def set_spellcheck(self, on, autocorrect):
        new_on = bool(on and spellmod.speller.available)
        changed = new_on != self.highlighter.spell_on
        self.highlighter.spell_on = new_on
        self.autocorrect_on = autocorrect and new_on
        if changed:                                        # re-colouring a whole document is not free: only when it matters
            self.highlighter.rehighlight()

    def set_language(self, lang):
        if lang is self.lang and self.highlighter.lang is lang:
            return
        self.lang = lang
        self._fold_timer.start()
        self.highlighter.set_lang(lang)

    def detect_language(self):
        self.set_language(lang_for_path(self.path))

    # ---- gutter ---------------------------------------------------------------------------------------
    def _fmt_num(self, n):
        return self.line_prefix + (f"{n:,}" if self.line_base else str(n))

    def gutter_width(self):
        last = self.blockCount() + self.line_base
        digits = len(self._fmt_num(max(last, 99)))
        return 28 + self.FOLD_W + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy):
        if dy:
            self.gutter.scroll(0, dy)
        else:
            self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))
        self._schedule_refresh()
        if self._has_para:
            self._para_timer.start()                    # centred and right-aligned lines depend on the width of the window
        panel = getattr(self, "goto_panel", None)
        if panel is not None and panel.isVisible():
            panel.move(self.width() - panel.width() - 28, 16)

    def paint_gutter(self, event):
        p = QPainter(self.gutter)
        p.fillRect(event.rect(), QColor(theme.c("GUTTER")))
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = self.textCursor().blockNumber()
        w = self.gutter.width()
        font = QFont(self.font())
        font.setPointSizeF(max(8.0, self.font().pointSizeF() - 1))
        p.setFont(font)
        h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                mark = self.git_marks.get(number + 1) if self.git_marks else None
                if mark:
                    p.fillRect(0, top, 3, h if mark != 'deleted' else 3, QColor(theme.c({'added': 'ACCENT', 'modified': 'ORANGE', 'deleted': 'RED'}[mark])))
                if number == cur and not self.read_only_window:
                    p.fillRect(0, top, w, max(h, bottom - top), QColor(theme.c("LINE_HL")))
                p.setPen(QColor(theme.c("TEXT") if number == cur else theme.c("FAINT")))
                p.drawText(0, top, w - 12 - self.FOLD_W, h, Qt.AlignRight | Qt.AlignVCenter, self._fmt_num(number + 1 + self.line_base))
                if number in self.fold_regions:
                    folded = self._is_folded(block)
                    cx, cy = w - 14, top + h // 2
                    p.setPen(QPen(QColor(theme.c("ACCENT") if folded else theme.c("FAINT")), 1.5))
                    if folded:
                        p.drawPolyline([QPoint(cx - 2, cy - 4), QPoint(cx + 2, cy), QPoint(cx - 2, cy + 4)])
                    else:
                        p.drawPolyline([QPoint(cx - 4, cy - 2), QPoint(cx, cy + 2), QPoint(cx + 4, cy - 2)])
                data = block.userData()
                if isinstance(data, BlockData) and data.bookmark:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(theme.c("BLUE")))
                    p.drawEllipse(7, top + h // 2 - 4, 8, 8)
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1

    def gutter_click(self, e):
        if e.position().x() >= self.gutter.width() - self.FOLD_W - 2 and self.fold_regions:
            blk = self.cursorForPosition(QPoint(0, int(e.position().y()))).block()
            if blk.blockNumber() in self.fold_regions:
                self.fold_block(blk, not self._is_folded(blk))
                return
        cur = self.cursorForPosition(QPoint(0, int(e.position().y())))
        self.toggle_bookmark(cur.block())

    # ---- bookmarks --------------------------------------------------------------------------------------
    def toggle_bookmark(self, block=None):
        block = block or self.textCursor().block()
        data = block.userData()
        if not isinstance(data, BlockData):
            data = BlockData()
            block.setUserData(data)
        data.bookmark = not data.bookmark
        self.gutter.update()

    def _bookmarked_blocks(self):
        b = self.document().firstBlock()
        out = []
        while b.isValid():
            d = b.userData()
            if isinstance(d, BlockData) and d.bookmark:
                out.append(b)
            b = b.next()
        return out

    def goto_bookmark(self, forward=True):
        marks = self._bookmarked_blocks()
        if not marks:
            return False
        cur = self.textCursor().blockNumber()
        nums = [b.blockNumber() for b in marks]
        if forward:
            target = next((b for b in marks if b.blockNumber() > cur), marks[0])
        else:
            target = next((b for b in reversed(marks) if b.blockNumber() < cur), marks[-1])
        self.setTextCursor(QTextCursor(target))
        self.centerCursor()
        return True

    def clear_bookmarks(self):
        for b in self._bookmarked_blocks():
            b.userData().bookmark = False
        self.gutter.update()

    # ---- highlights -------------------------------------------------------------------------------------
    def _on_cursor(self):
        self._reveal_cursor()
        self._leave_zone()
        self.cursorStatus.emit()
        self._schedule_refresh()
        self.gutter.update()

    def _on_edit(self, pos, removed, added):
        if not self._in_para:
            self._para_timer.start()
        self._fold_timer.start()
        if self.marks:
            self.marks = []
        self._schedule_refresh()

    def _schedule_refresh(self, *_):
        self._refresh_timer.start()

    def refresh_selections(self):
        sels = []
        if not self.isReadOnly() or self.read_only_window:
            line = QTextEdit.ExtraSelection()
            line.format.setBackground(QColor(theme.c("LINE_HL")))
            line.format.setProperty(QTextFormat.FullWidthSelection, True)
            line.cursor = self.textCursor()
            line.cursor.clearSelection()
            sels.append(line)
        sels += self._image_hide_selections()
        sels += self._extra_cursor_selections()
        sels += self._tint_selections()
        sels += self._style_selections()
        sels += self._diag_selections()
        sels += self._mark_selections()
        sels += self._smart_selections()
        sels += self._bracket_selections()
        self.setExtraSelections(sels)

    def _mark_selections(self):
        out = []
        for start, length in self.marks[:5000]:
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(QColor(theme.c("MARK_BG")))
            s.format.setForeground(QColor(theme.c("MARK_FG")))
            s.cursor = QTextCursor(self.document())
            s.cursor.setPosition(start)
            s.cursor.setPosition(start + length, QTextCursor.KeepAnchor)
            out.append(s)
        return out

    def _smart_word(self):
        cur = self.textCursor()
        if cur.hasSelection():
            t = cur.selectedText()
            return t if 2 <= len(t) <= 80 and " " not in t and WORD_RE.fullmatch(t) else None
        block = cur.block()
        text = block.text()
        col = cur.positionInBlock()
        for m in WORD_RE.finditer(text):
            if m.start() <= col <= m.end() and len(m.group()) >= 2:
                return m.group()
        return None

    def _smart_selections(self):
        word = self._smart_word()
        if not word:
            return []
        top = self.cursorForPosition(self.viewport().rect().topLeft())
        bottom = self.cursorForPosition(self.viewport().rect().bottomLeft())
        start_block = top.block()
        end_block = bottom.block()
        first = start_block.position()
        last = end_block.position() + end_block.length()
        doc = self.document()
        cursor = QTextCursor(doc)
        cursor.setPosition(first)
        cursor.setPosition(min(last, doc.characterCount() - 1), QTextCursor.KeepAnchor)
        text = cursor.selection().toPlainText()
        rx = re.compile(r"(?<!\w)" + re.escape(word) + r"(?!\w)")
        out = []
        for m in rx.finditer(text):
            if len(out) > 400:
                break
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(QColor(theme.c("SMART_BG")))
            s.cursor = QTextCursor(doc)
            s.cursor.setPosition(first + m.start())
            s.cursor.setPosition(first + m.end(), QTextCursor.KeepAnchor)
            out.append(s)
        return out

    def _bracket_selections(self):
        doc = self.document()
        cur = self.textCursor()
        pos = cur.position()
        for p in (pos - 1, pos):
            if p < 0 or p >= doc.characterCount() - 1:
                continue
            ch = doc.characterAt(p)
            if ch in BRACKETS or ch in CLOSERS:
                other = self._match_bracket(p, ch)
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(theme.c("SMART_BG")))
                fmt.setForeground(QColor(theme.c("ACCENT")))
                fmt.setFontWeight(QFont.Bold)
                out = []
                for q in ((p, other) if other is not None else (p,)):
                    s = QTextEdit.ExtraSelection()
                    s.format = fmt
                    s.cursor = QTextCursor(doc)
                    s.cursor.setPosition(q)
                    s.cursor.setPosition(q + 1, QTextCursor.KeepAnchor)
                    out.append(s)
                return out
        i = self._enclosing_bracket() if self.is_code() else None          # caret is inside a pair: light up both ends
        if i is not None:
            j = self._match_bracket(i, doc.characterAt(i))
            if j is not None:
                fmt = QTextCharFormat()
                fmt.setBackground(QColor(theme.c("SMART_BG")))
                out = []
                for q in (i, j):
                    s = QTextEdit.ExtraSelection()
                    s.format = fmt
                    s.cursor = QTextCursor(doc)
                    s.cursor.setPosition(q)
                    s.cursor.setPosition(q + 1, QTextCursor.KeepAnchor)
                    out.append(s)
                return out
        return []

    def _match_bracket(self, p, ch):
        doc = self.document()
        total = doc.characterCount() - 1
        if ch in BRACKETS:
            step, want, same = 1, BRACKETS[ch], ch
            limit = min(total, p + 40000)
        else:
            step, want, same = -1, CLOSERS[ch], ch
            limit = max(-1, p - 40000)
        depth = 0
        i = p
        while i != limit:
            c = doc.characterAt(i)
            if c == same:
                depth += 1
            elif c == want:
                depth -= 1
                if depth == 0:
                    return i
            i += step
        return None

    # ---- editing helpers -------------------------------------------------------------------------------------
    def _indent_unit(self):
        return " " * self.tab_width if self.use_spaces else "\t"

    def _selected_blocks(self):
        cur = self.textCursor()
        doc = self.document()
        start = doc.findBlock(cur.selectionStart())
        end_pos = cur.selectionEnd()
        end = doc.findBlock(end_pos)
        if cur.hasSelection() and end_pos == end.position() and end != start:
            end = end.previous()                    # a selection that ends at a line start does not include that line
        return start, end

    def indent_selection(self, outdent=False):
        start, end = self._selected_blocks()
        cur = self.textCursor()
        cur.beginEditBlock()
        b = start
        while b.isValid() and b.blockNumber() <= end.blockNumber():
            c = QTextCursor(b)
            if outdent:
                text = b.text()
                n = 0
                if text.startswith("\t"):
                    n = 1
                else:
                    while n < self.tab_width and n < len(text) and text[n] == " ":
                        n += 1
                if n:
                    c.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, n)
                    c.removeSelectedText()
            else:
                c.insertText(self._indent_unit())
            b = b.next()
        cur.endEditBlock()

    AC_DELIMS = " .,;:!?)\"]}"

    def _autocorrect_before(self, delim):
        """Called as a delimiter is typed: fixes the finished word when it is a confident single typo. -> True if replaced."""
        if not (self.autocorrect_on and self.lang.name in ("Plain text", "Markdown")):
            return False
        cur = self.textCursor()
        if cur.hasSelection():
            return False
        before = cur.block().text()[:cur.positionInBlock()]
        m = re.search(r"[A-Za-z']+$", before)
        if not m or (m.start() > 0 and (before[m.start() - 1].isalnum() or before[m.start() - 1] in "_/\\@.")):
            return False
        word = m.group()
        fixed = spellmod.speller.correction(word)
        if not fixed:
            return False
        start = cur.position() - len(word)
        cur.beginEditBlock()
        cur.setPosition(start)
        cur.setPosition(start + len(word), QTextCursor.KeepAnchor)
        cur.insertText(fixed)
        cur.insertText(delim)
        cur.endEditBlock()
        self.setTextCursor(cur)
        self._ac = dict(start=start, original=word, delim=delim, end=cur.position(), rev=self.document().revision())
        return True

    def _undo_autocorrect(self):
        """Backspace straight after an automatic fix puts back exactly what was typed (and stops correcting that word)."""
        ac, self._ac = self._ac, None
        cur = self.textCursor()
        if not ac or cur.hasSelection() or cur.position() != ac["end"] or self.document().revision() != ac["rev"]:
            return False
        spellmod.speller.ignore(ac["original"])
        cur.beginEditBlock()
        cur.setPosition(ac["start"])
        cur.setPosition(ac["end"], QTextCursor.KeepAnchor)
        cur.insertText(ac["original"] + ac["delim"])
        cur.endEditBlock()
        self.setTextCursor(cur)
        self.highlighter.rehighlight()
        return True

    # ---- the right-click menu -----------------------------------------------------------------------------------------------
    STYLE_COLORS = ("#f2a65a", "#5aa9ff", "#8ad95c", "#c792ea", "#ee6a50")

    def _word_or_selection(self, cur=None):
        cur = cur or self.textCursor()
        if cur.hasSelection():
            return cur.selectedText().replace("\u2029", "\n")
        c = QTextCursor(cur)
        c.select(QTextCursor.WordUnderCursor)
        return c.selectedText()

    def _style_selections(self):
        out = []
        if not self.styles_all and not self.styles_one:
            return out
        doc = self.document()
        rev = doc.revision()
        if self._style_cache[0] != rev:
            self._style_cache = (rev, self.toPlainText() if self.length() < 3_000_000 else "")
        text = self._style_cache[1]
        pm = PosMap(text) if text else None
        for slot, token in self.styles_all.items():
            col = QColor(self.STYLE_COLORS[slot])
            col.setAlpha(120)
            n, i = 0, text.find(token) if text else -1
            while i >= 0 and n < 4000:
                before = text[i - 1] if i else " "
                after = text[i + len(token)] if i + len(token) < len(text) else " "
                if not (token[:1].isalnum() or token[:1] == "_") or not (before.isalnum() or before == "_"):
                    if not (token[-1:].isalnum() or token[-1:] == "_") or not (after.isalnum() or after == "_"):
                        s = QTextEdit.ExtraSelection()
                        s.format.setBackground(col)
                        s.cursor = QTextCursor(doc)
                        s.cursor.setPosition(pm.to_q(i))
                        s.cursor.setPosition(pm.to_q(i + len(token)), QTextCursor.KeepAnchor)
                        out.append(s)
                        n += 1
                i = text.find(token, i + len(token))
        for slot, cursors in self.styles_one.items():
            col = QColor(self.STYLE_COLORS[slot])
            col.setAlpha(120)
            for c in cursors:
                if c.hasSelection():
                    s = QTextEdit.ExtraSelection()
                    s.format.setBackground(col)
                    s.cursor = c
                    out.append(s)
        return out

    def style_all(self, slot):
        token = self._word_or_selection()
        if token and "\n" not in token:
            self.styles_all[slot] = token
            self.refresh_selections()

    def style_one(self, slot):
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.WordUnderCursor)
        if cur.hasSelection():
            self.styles_one.setdefault(slot, []).append(QTextCursor(cur))
            self.refresh_selections()

    def clear_style(self, slot=None):
        if slot is None:
            self.styles_all, self.styles_one = {}, {}
        else:
            self.styles_all.pop(slot, None)
            self.styles_one.pop(slot, None)
        self.refresh_selections()

    def begin_end_select(self, column=False):
        """First use remembers the caret; the second selects everything between that place and the caret (a block of columns
        in column mode)."""
        cur = self.textCursor()
        if self._sel_mark is None:
            self._sel_mark = (cur.position(), cur.blockNumber(), cur.positionInBlock())
            self.statusMessage.emit("Selection start set: move to the end and choose Begin/End Select again")
            return
        pos, line, col = self._sel_mark
        self._sel_mark = None
        if column:
            self._column_select(line, col, cur.blockNumber(), cur.positionInBlock())
        else:
            c = QTextCursor(self.document())
            c.setPosition(pos)
            c.setPosition(cur.position(), QTextCursor.KeepAnchor)
            self.setTextCursor(c)

    def path_in_text(self):
        """The file name under the caret / in the selection, resolved to an existing path (else '')."""
        token = self.textCursor().selectedText().strip() if self.textCursor().hasSelection() else ""
        if not token:
            cur = self.textCursor()
            text, col = cur.block().text(), cur.positionInBlock()
            for m in re.finditer(r"[^\s\"'<>|*?(),;]+", text):
                if m.start() <= col <= m.end():
                    token = m.group()
                    break
        token = token.strip("\"'").rstrip(".:")
        if not token or "\u2029" in token:
            return ""
        token = re.sub(r":\d+(:\d+)?$", "", token)                # file.py:12:3
        if self.path_resolver is not None:
            return self.path_resolver(token) or ""
        base = os.path.dirname(self.path) if self.path else ""
        full = token if os.path.isabs(token) else os.path.join(base, token)
        return os.path.normpath(full) if os.path.exists(full) else ""

    def search_internet(self):
        text = self._word_or_selection().strip()
        if text:
            import urllib.parse
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(self.search_url.replace("{q}", urllib.parse.quote(text))))

    def block_comment(self, on):
        """Wraps the selection in the language's block comment marks, or takes them off. Languages that only have line comments
        get the comment mark on every selected line instead."""
        pair = self.lang.block_comment
        cur = self.textCursor()
        if pair is None:
            if self.lang.comment:
                start, end = self._selected_blocks()
                first = start
                lines = []
                b = first
                while b.isValid() and b.blockNumber() <= end.blockNumber():
                    lines.append(b.text())
                    b = b.next()
                commented = all(not t.strip() or t.lstrip().startswith(self.lang.comment) for t in lines)
                if commented == (not on):
                    self.toggle_comment()
            return
        s, e = pair
        if not cur.hasSelection():
            return
        text = cur.selectedText().replace("\u2029", "\n")
        a, b = cur.selectionStart(), cur.selectionEnd()
        if on:
            cur.insertText(s + text + e)
            c = QTextCursor(self.document())
            c.setPosition(a + len(s))
            c.setPosition(a + len(s) + len(text), QTextCursor.KeepAnchor)
            self.setTextCursor(c)
        else:
            t = text.strip()
            if t.startswith(s) and t.endswith(e):
                inner = t[len(s):len(t) - len(e)]
                cur.insertText(inner)
            else:                                                       # the marks may sit just outside the selection
                doc = self.document()
                c = QTextCursor(doc)
                c.setPosition(max(0, a - len(s)))
                c.setPosition(min(doc.characterCount() - 1, b + len(e)), QTextCursor.KeepAnchor)
                t2 = c.selectedText()
                if t2.startswith(s) and t2.endswith(e):
                    c.insertText(text)

    def hide_lines(self):
        """Hides the selected lines (or the current one) behind a small ... marker you can click to bring them back."""
        start, end = self._selected_blocks()
        if not start.previous().isValid():
            self.statusMessage.emit("The first line cannot be hidden: select lines below it")
            return
        c1, c2 = QTextCursor(start), QTextCursor(end)
        c2.movePosition(QTextCursor.EndOfBlock)
        self.user_hidden.append((c1, c2))
        line = start.blockNumber() - 1
        self.fold_regions[line] = max(self.fold_regions.get(line, 0), end.blockNumber())
        self._bd(self.document().findBlockByNumber(line)).folded = True
        self._has_flags = True
        self._apply_folds()
        self.setTextCursor(QTextCursor(self.document().findBlockByNumber(line)))
        self.gutter.update()

    def show_hidden_lines(self):
        for c1, c2 in self.user_hidden:
            blk = self.document().findBlockByNumber(c1.blockNumber() - 1)
            if blk.isValid():
                self._bd(blk).folded = False
        self.user_hidden = []
        self._apply_folds()
        self.gutter.update()

    def contextMenuEvent(self, e):
        self.build_context_menu(e.pos()).exec(e.globalPos())

    def build_context_menu(self, pos):
        click = self.cursorForPosition(pos)
        cur = self.textCursor()
        if not cur.hasSelection() or not (cur.selectionStart() <= click.position() <= cur.selectionEnd()):
            self.setTextCursor(click)
            cur = self.textCursor()
        menu = ContextMenu(self)
        ro = self.isReadOnly()
        has_sel = cur.hasSelection()
        word = self._word_or_selection()
        if self.format_supported() and not ro and self.mini_toolbar:
            from .minitoolbar import MiniToolbar                      # the formatting bar on top, one compact row
            menu.set_bar(MiniToolbar(self, menu))

        def ic(name):
            return theme.icon(name, theme.c("MUTED"), 18)

        def add(target, text, fn, enabled=True, shortcut=None, icon=None):
            a = target.addAction(text, fn)
            a.setEnabled(enabled)
            if shortcut:
                a.setShortcut(shortcut)
            if icon:
                a.setIcon(ic(icon))
            return a

        def submenu(text, icon, enabled=True):
            sub = menu.addMenu(ic(icon), text)
            theme.round_menu(sub)
            sub.setEnabled(enabled)
            return sub
        # mistakes first
        if self.highlighter.spell_on and word and not has_sel and spellmod.speller.is_wrong(word) and not ro:
            sugg = spellmod.speller.suggestions(word)
            wc = QTextCursor(click)
            wc.select(QTextCursor.WordUnderCursor)
            for sg in sugg:
                add(menu, sg, lambda _=False, sg=sg, c=QTextCursor(wc): c.insertText(sg))
            if not sugg:
                add(menu, "(no suggestions)", None, False)
            add(menu, f'Add "{word}" to dictionary', lambda: (spellmod.speller.add_word(word), self.highlighter.rehighlight()))
            add(menu, "Ignore all", lambda: (spellmod.speller.ignore(word), self.highlighter.rehighlight()))
            menu.addSeparator()
        if self.context_provider is not None:                         # extra commands from the window the editor lives in
            try:
                if self.context_provider(menu, self):
                    menu.addSeparator()
            except Exception:  # noqa: BLE001
                pass
        add(menu, "Cut", self.cut, has_sel and not ro, "Ctrl+X", "cut")
        add(menu, "Copy", self.copy, has_sel, "Ctrl+C", "copy")
        add(menu, "Paste", self.paste, not ro, "Ctrl+V", "paste")
        add(menu, "Delete", lambda: self.textCursor().removeSelectedText(), has_sel and not ro, "Del", "delete")
        menu.addSeparator()
        add(menu, "Select all", self.selectAll, True, "Ctrl+A", "selectall")
        mode = submenu("Selection mode", "selmode")
        add(mode, "Begin / end select" + (" (start is set)" if self._sel_mark else ""), lambda: self.begin_end_select(False))
        add(mode, "Begin / end select in column mode", lambda: self.begin_end_select(True))
        menu.addSeparator()
        tokens = submenu("Style tokens", "brush")
        for title, fn in (("Style all occurrences", self.style_all), ("Style one token", self.style_one)):
            row = QWidgetAction(tokens)
            row.setDefaultWidget(_SwatchRow(title, self.STYLE_COLORS, fn, bool(word)))
            tokens.addAction(row)
        tokens.addSeparator()
        clear = tokens.addMenu("Clear style")
        theme.round_menu(clear)
        clear.setEnabled(bool(self.styles_all or self.styles_one))
        for slot, col in enumerate(self.STYLE_COLORS):
            a = clear.addAction(f"Clear style {slot + 1}", lambda _=False, sl=slot: self.clear_style(sl))
            a.setEnabled(slot in self.styles_all or slot in self.styles_one)
        clear.addSeparator()
        clear.addAction("Clear all styles", lambda: self.clear_style())
        if has_sel and not ro:
            case = submenu("Change case", "case")
            add(case, "UPPERCASE", lambda: self.transform_selection(str.upper))
            add(case, "lowercase", lambda: self.transform_selection(str.lower))
        can_line = bool(self.lang.comment) and not ro
        can_block = (self.lang.block_comment is not None or bool(self.lang.comment)) and not ro
        if can_line or can_block:
            cm = submenu("Comment", "comment")
            add(cm, "Toggle single line comment", self.toggle_comment, can_line)
            add(cm, "Block comment", lambda: self.block_comment(True), can_block)
            add(cm, "Block uncomment", lambda: self.block_comment(False), can_block)
        menu.addSeparator()
        if word:
            shown = word if len(word) <= 24 else word[:23] + "\u2026"
            add(menu, f"Search \u201c{shown}\u201d on the web", self.search_internet, True, None, "web")
        target = self.path_in_text()
        if target:
            add(menu, "Open file at cursor", lambda: self.openPathRequested.emit(target), True, None, "file")
        plug = submenu("Plugin commands", "plug")
        actions = self.plugin_actions_provider() if self.plugin_actions_provider else []
        for a in actions:
            plug.addAction(a)
        plug.setEnabled(bool(actions) and not ro)
        add(menu, "Hide lines", self.hide_lines, not self.read_only_window, None, "hide")
        if self.user_hidden:
            add(menu, "Show hidden lines", self.show_hidden_lines, True, None, "hide")
        return menu

    def keyPressEvent(self, e):
        if self.macro_rec is not None and not self.macro_playing and e.key() not in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Meta):
            self.macro_rec.append(("key", int(e.key()), int(e.modifiers().value if hasattr(e.modifiers(), 'value') else e.modifiers()), e.text()))
        self._key_press(e)
        self._maybe_complete(e)

    def _key_press(self, e):
        key, mods = e.key(), e.modifiers()
        if self.isReadOnly():
            return super().keyPressEvent(e)
        if self._completer.popup().isVisible() and key in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Escape, Qt.Key_Tab, Qt.Key_Backtab):
            e.ignore()                       # the suggestion list takes these keys (Enter / Tab accept, Esc closes)
            return
        if self._img_sel is not None and self._image_key(e):
            return
        if self.extra_cursors and self._multi_key(e):
            return
        if key in (Qt.Key_Backspace, Qt.Key_Delete) and not mods and not self.textCursor().hasSelection() and self.lang.name in RICH_LANGS:
            c = self.textCursor()
            col = c.positionInBlock()
            for a, b in mark_spans(c.block().text()):          # step over an invisible mark so the visible letter is deleted
                if key == Qt.Key_Backspace and col == b:
                    c.setPosition(c.block().position() + a)
                    self.setTextCursor(c)
                    break
                if key == Qt.Key_Delete and col == a:
                    c.setPosition(c.block().position() + b)
                    self.setTextCursor(c)
                    break
        if key == Qt.Key_Backspace and self._ac is not None and not mods:
            if self._undo_autocorrect():
                return
        if key == Qt.Key_Backspace and not mods and self._try_autoclose_backspace():
            return
        if e.text() and self._try_autoclose(e):
            self._ac = None
            return
        elif key not in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt):
            ch = e.text()
            if ch and len(ch) == 1 and ch in self.AC_DELIMS and not mods & (Qt.ControlModifier | Qt.AltModifier):
                self._ac = None
                if self._autocorrect_before(ch):
                    return
            elif key in (Qt.Key_Return, Qt.Key_Enter) and not mods & Qt.ControlModifier:
                self._ac = None
                if self._autocorrect_before("\n"):
                    return
            else:
                self._ac = None
        if key == Qt.Key_Tab and not mods & (Qt.ControlModifier | Qt.AltModifier):
            cur = self.textCursor()
            if cur.hasSelection() and self.document().findBlock(cur.selectionStart()) != self.document().findBlock(cur.selectionEnd()):
                self.indent_selection()
            elif self.use_spaces:
                col = cur.positionInBlock()
                cur.insertText(" " * (self.tab_width - col % self.tab_width))
            else:
                cur.insertText("\t")
            return
        if key == Qt.Key_Backtab:
            self.indent_selection(outdent=True)
            return
        if key in (Qt.Key_Return, Qt.Key_Enter) and not mods & Qt.ControlModifier:
            cur = self.textCursor()
            text = cur.block().text()
            before = text[:cur.positionInBlock()]
            indent = re.match(r"[ \t]*", text).group()
            after = text[cur.positionInBlock():]
            if self.is_code() and before.rstrip().endswith(("{", "(", "[")) and after[:1] in ("}", ")", "]") and before.rstrip()[-1:] + after[:1] in ("{}", "()", "[]"):
                cur.insertText("\n" + indent + self._indent_unit() + "\n" + indent)       # Enter between {} opens a block
                cur.movePosition(QTextCursor.Up)
                cur.movePosition(QTextCursor.EndOfBlock)
                self.setTextCursor(cur)
                self.ensureCursorVisible()
                return
            if before.rstrip().endswith((":", "{", "(", "[")) and len(before.strip()) > 0:
                indent += self._indent_unit()
            cur.insertText("\n" + indent)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            return
        if key == Qt.Key_Home and not mods & Qt.ControlModifier:
            cur = self.textCursor()
            text = cur.block().text()
            first = len(text) - len(text.lstrip())
            target = cur.block().position() + (0 if cur.positionInBlock() == first else first)
            cur.setPosition(target, QTextCursor.KeepAnchor if mods & Qt.ShiftModifier else QTextCursor.MoveAnchor)
            self.setTextCursor(cur)
            return
        super().keyPressEvent(e)
        if key == Qt.Key_Insert:
            self.cursorStatus.emit()

    def duplicate_line(self):
        cur = self.textCursor()
        cur.beginEditBlock()
        if cur.hasSelection():
            text = cur.selectedText().replace(" ", "\n")
            cur.setPosition(cur.selectionEnd())
            cur.insertText(text)
        else:
            text = cur.block().text()
            cur.movePosition(QTextCursor.EndOfBlock)
            cur.insertText("\n" + text)
        cur.endEditBlock()
        self.setTextCursor(cur)

    def delete_line(self):
        start, end = self._selected_blocks()
        cur = QTextCursor(start)
        cur.beginEditBlock()
        cur.setPosition(start.position())
        cur.setPosition(end.position() + end.length() - 1, QTextCursor.KeepAnchor)
        cur.removeSelectedText()
        if cur.block().next().isValid():
            cur.deleteChar()
        elif cur.position() > 0:
            cur.deletePreviousChar()
        cur.endEditBlock()
        self.setTextCursor(cur)

    def move_lines(self, up):
        start, end = self._selected_blocks()
        doc = self.document()
        if up and not start.previous().isValid():
            return
        if not up and not end.next().isValid():
            return
        cur = self.textCursor()
        sel_start, sel_end = cur.selectionStart(), cur.selectionEnd()
        cur.beginEditBlock()
        first, last = start.position(), end.position() + end.length() - 1
        c = QTextCursor(doc)
        c.setPosition(first)
        c.setPosition(last, QTextCursor.KeepAnchor)
        block_text = c.selectedText().replace(" ", "\n")
        if up:
            prev = start.previous()
            shift = -(prev.length())
            c.setPosition(prev.position())
            c.setPosition(last, QTextCursor.KeepAnchor)
            c.insertText(block_text + "\n" + prev.text())
        else:
            nxt = end.next()
            shift = nxt.length()
            c.setPosition(first)
            c.setPosition(nxt.position() + nxt.length() - 1, QTextCursor.KeepAnchor)
            c.insertText(nxt.text() + "\n" + block_text)
        cur.endEditBlock()
        c = QTextCursor(doc)
        c.setPosition(sel_start + shift)
        c.setPosition(sel_end + shift, QTextCursor.KeepAnchor)
        self.setTextCursor(c)

    def transform_selection(self, fn):
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.WordUnderCursor)
        text = cur.selectedText().replace(" ", "\n")
        start = cur.selectionStart()
        masked, table = self._mask_marks(text) if self.format_supported() else (text, [])
        new = fn(masked)
        if table:                                           # a change (UPPERCASE, a plugin, ...) must never touch the formatting marks
            restored = self._unmask_marks(new, table)
            new = restored if restored is not None else fn(text)
        cur.insertText(new)
        c = QTextCursor(self.document())
        c.setPosition(start)
        c.setPosition(start + len(new), QTextCursor.KeepAnchor)
        self.setTextCursor(c)

    def _mask_marks(self, text):
        """The text with every formatting mark (**, _, <u>, <span style=...>, <p style=...>) swapped for one private character, so a
        text change cannot alter them. -> (masked text, [the marks])."""
        table, lines = [], []
        for line in text.replace(chr(0x2029), "\n").split("\n"):
            spans = mark_spans(line)
            if not spans or len(table) + len(spans) > 6000:
                lines.append(line)
                continue
            out, pos = [], 0
            for a, b in spans:
                if a < pos:
                    continue
                out.append(line[pos:a])
                out.append(chr(0xE000 + len(table)))
                table.append(line[a:b])
                pos = b
            out.append(line[pos:])
            lines.append("".join(out))
        return "\n".join(lines), table

    @staticmethod
    def _unmask_marks(text, table):
        used = [ord(ch) - 0xE000 for ch in text if 0xE000 <= ord(ch) < 0xE000 + len(table)]
        if sorted(used) != list(range(len(table))):         # the change dropped or copied a mark: give up rather than break the text
            return None
        return "".join(table[ord(ch) - 0xE000] if 0xE000 <= ord(ch) < 0xE000 + len(table) else ch for ch in text)

    def transform_all_or_selection(self, fn):
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.Document)
            self.setTextCursor(cur)
        self.transform_selection(fn)

    # ---- text formatting marks (Markdown / HTML / plain notes) --------------------------------------------------------
    def format_supported(self):
        return self.lang.name in ("Plain text", "Markdown", "HTML / XML")

    def _marks(self, kind):
        html = self.lang.name == "HTML / XML"
        return {"bold": ("<b>", "</b>") if html else ("**", "**"), "italic": ("<i>", "</i>") if html else ("_", "_"),
                "underline": ("<u>", "</u>")}[kind]

    _LEFT_TOKEN = re.compile(r'(\*\*|_|\*|<u>|<b>|<i>|<span style="(?:font-size|font-family|color|background):[^"]*">)$')
    _RIGHT_TOKEN = re.compile(r'^(\*\*|_|\*|</u>|</b>|</i>|</span>)')
    _KIND_OF = {"**": "bold", "<b>": "bold", "_": "italic", "*": "italic", "<i>": "italic", "<u>": "underline"}
    _CLOSER = {"**": "**", "<b>": "</b>", "_": "_", "*": "*", "<i>": "</i>", "<u>": "</u>"}
    _SPAN_OPEN = re.compile(r'^<span style="font-size:(\d+)px">$')

    SPAN_PROP = {"size": "font-size", "family": "font-family", "color": "color", "bg": "background"}

    def _kind_of_token(self, tok):
        if tok.startswith("<span"):
            m = re.match(r'<span style="([a-z-]+):', tok)
            return next((k for k, v in self.SPAN_PROP.items() if m and v == m.group(1)), None)
        return self._KIND_OF.get(tok)

    def _closer_of(self, tok):
        return "</span>" if tok.startswith("<span") else self._CLOSER.get(tok)

    def _find_layer(self, kind, s, e):
        """Looks outward from the text s..e through the layers of marks around it (bold, italic, underline and size can all
        be stacked) for the layer of `kind`. -> (position of its opening mark, its length, position of its closing mark,
        its length, opening mark text) or None."""
        doc = self.document()
        block = doc.findBlock(s)
        if block != doc.findBlock(e) or e > block.position() + block.length() - 1:
            return None
        text = block.text()
        ls, le = s - block.position(), e - block.position()
        left, right = [], []                                   # innermost layer first
        i, j = ls, le
        while True:
            m = self._LEFT_TOKEN.search(text[:i])
            n = self._RIGHT_TOKEN.match(text[j:])
            if not m or not n:
                break
            left.append((m.start(), m.group()))
            right.append((j, n.group()))
            i, j = m.start(), j + len(n.group())
        for (lp, ltok), (rp, rtok) in zip(left, right):
            if self._kind_of_token(ltok) == kind and self._closer_of(ltok) == rtok:
                if ltok == "*" and ((lp > 0 and text[lp - 1] == "*") or text[rp + 1:rp + 2] == "*"):
                    continue                                   # half of a **
                return block.position() + lp, len(ltok), block.position() + rp, len(rtok), ltok
        return None

    def _normalize(self, s, e):
        """Makes the range s..e safe to wrap: it may not cut a pair of marks in two (which would cross them, like
        **a <u>b** c</u>). A range that does is widened to take the whole pair in. A range that is exactly a whole pair
        becomes the text inside it."""
        doc = self.document()
        block = doc.findBlock(s)
        base = block.position()
        text = block.text()
        ls, le = s - base, e - base
        pairs = [(m.start(), m.end(), a2, b2) for _k, m, a2, b2 in rich_matches(text)]
        for ms, me, a2, b2 in pairs:
            if (ls, le) == (ms, me):
                ls, le = a2, b2
                break
        changed = True
        while changed:
            changed = False
            for ms, me, a2, b2 in pairs:
                intersects = ls < me and ms < le
                inside = ls >= a2 and le <= b2
                contains = ls <= ms and me <= le
                if intersects and not inside and not contains:
                    ls, le = min(ls, ms), max(le, me)
                    changed = True
        return base + ls, base + le

    def _segments(self, s, e):
        """The part of every non-blank line that the selection covers: [(line number, start col, end col)]."""
        doc = self.document()
        first, last = doc.findBlock(s), doc.findBlock(e)
        out = []
        blk = first
        while blk.isValid() and blk.blockNumber() <= last.blockNumber():
            a = max(s, blk.position()) - blk.position()
            b = min(e, blk.position() + len(blk.text())) - blk.position()
            if b > a and blk.text()[a:b].strip():
                out.append((blk.blockNumber(), a, b))
            blk = blk.next()
        return out

    def _toggle_one(self, kind, s, e, remove):
        """Adds or removes one kind of mark around s..e (inside one line). -> (new start, new end) of the text."""
        doc = self.document()
        opening, closing = self._marks(kind)
        s, e = self._normalize(s, e)
        layer = self._find_layer(kind, s, e)
        cur = QTextCursor(doc)
        cur.setPosition(s)
        cur.setPosition(e, QTextCursor.KeepAnchor)
        text = cur.selectedText()
        if layer is not None and remove:                            # take that one layer off, keep the rest
            lp, ll, rp, rl, _t = layer
            c = QTextCursor(doc)
            c.setPosition(rp)
            c.setPosition(rp + rl, QTextCursor.KeepAnchor)
            c.removeSelectedText()
            c.setPosition(lp)
            c.setPosition(lp + ll, QTextCursor.KeepAnchor)
            c.removeSelectedText()
            return s - ll, e - ll
        if remove and len(text) >= len(opening) + len(closing) and text.startswith(opening) and text.endswith(closing):
            cur.insertText(text[len(opening):len(text) - len(closing)])
            return s, e - len(opening) - len(closing)
        if layer is None or not remove:
            if layer is not None:
                return s, e                                         # already has it
            cur.insertText(opening + text + closing)
            return s + len(opening), e + len(opening)
        return s, e

    def toggle_format(self, kind):
        """Bold / italic / underline on the selection (every selected line gets its own marks) or the word at the caret.
        The three can be combined on the same text, in any order; pressing again takes that one off."""
        if not self.format_supported() or self.isReadOnly():
            return False
        opening, closing = self._marks(kind)
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.WordUnderCursor)
            if not cur.hasSelection():
                cur.insertText(opening + closing)
                cur.movePosition(QTextCursor.Left, QTextCursor.MoveAnchor, len(closing))
                self.setTextCursor(cur)
                return True
        s, e = cur.selectionStart(), cur.selectionEnd()
        segs = self._segments(s, e)
        if not segs:
            return True
        doc = self.document()
        # already formatted on every line -> take it off, otherwise put it on the lines that lack it (as in a word processor)
        def covered(seg):
            blk = doc.findBlockByNumber(seg[0])
            ns, ne = self._normalize(blk.position() + seg[1], blk.position() + seg[2])
            lay = self._find_layer(kind, ns, ne)
            own = False
            if lay is None:
                c = QTextCursor(doc)
                c.setPosition(ns)
                c.setPosition(ne, QTextCursor.KeepAnchor)
                t = c.selectedText()
                own = len(t) >= len(opening) + len(closing) and t.startswith(opening) and t.endswith(closing)
            return lay is not None or own
        remove = all(covered(sg) for sg in segs)
        cur.beginEditBlock()
        last_range = None
        for ln, a, b in reversed(segs):                             # bottom up, so earlier positions stay valid
            blk = doc.findBlockByNumber(ln)
            last_range = (ln, self._toggle_one(kind, blk.position() + a, blk.position() + b, remove or False) if (remove or not covered((ln, a, b))) else None)
        cur.endEditBlock()
        sel = QTextCursor(doc)
        if len(segs) == 1 and last_range and last_range[1]:
            sel.setPosition(last_range[1][0])
            sel.setPosition(last_range[1][1], QTextCursor.KeepAnchor)
        else:                                                       # several lines: keep them selected
            sel.setPosition(doc.findBlockByNumber(segs[0][0]).position())
            end_blk = doc.findBlockByNumber(segs[-1][0])
            sel.setPosition(end_blk.position() + len(end_blk.text()), QTextCursor.KeepAnchor)
        self.setTextCursor(sel)
        return True

    def clear_format(self):
        """Removes every bold / italic / underline / size mark from the selection (or the current line)."""
        if not self.format_supported() or self.isReadOnly():
            return False
        cur = self.textCursor()
        doc = self.document()
        s, e = (cur.selectionStart(), cur.selectionEnd()) if cur.hasSelection() else (cur.block().position(), cur.block().position() + len(cur.block().text()))
        cur.beginEditBlock()
        blk = doc.findBlock(e)
        while blk.isValid() and blk.position() + len(blk.text()) >= s:
            text = blk.text()
            lo, hi = max(s, blk.position()) - blk.position(), min(e, blk.position() + len(text)) - blk.position()
            spans = []
            for _k, m, a2, b2 in rich_matches(text):
                if m.start() < hi and m.end() > lo:                  # a pair that touches the selection goes completely
                    spans += [(m.start(), a2), (b2, m.end())]
            for m in re.finditer(r'</?(?:u|b|i)>|</?span[^>]*>|\*\*', text):
                if lo <= m.start() < hi:
                    spans.append((m.start(), m.end()))
            done = set()
            for a2, b2 in sorted(spans, reverse=True):
                if (a2, b2) in done:
                    continue
                done.add((a2, b2))
                c = QTextCursor(doc)
                c.setPosition(blk.position() + a2)
                c.setPosition(blk.position() + b2, QTextCursor.KeepAnchor)
                c.removeSelectedText()
            blk = blk.previous()
        cur.endEditBlock()
        return True

    def _current_size_px(self, s=None, e=None):
        """The size of the text at the caret / selection (the size mark around it, else the editor's own size), in px."""
        if s is not None:
            lay = self._find_layer("size", s, e)
            if lay:
                m = self._SPAN_OPEN.match(lay[4])
                if m:
                    return int(m.group(1))
        f = self.font()
        return round(f.pixelSize() if f.pixelSize() > 0 else f.pointSizeF() * 96 / 72)

    def _size_one(self, s, e, px, delta):
        doc = self.document()
        s, e = self._normalize(s, e)
        base = self._current_size_px(s, e)
        new = px if px is not None else max(6, min(80, base + delta))
        lay = self._find_layer("size", s, e)
        c = QTextCursor(doc)
        if lay is not None:
            lp, ll, rp, rl, _tok = lay
            if new == 0:
                c.setPosition(rp)
                c.setPosition(rp + rl, QTextCursor.KeepAnchor)
                c.removeSelectedText()
                c.setPosition(lp)
                c.setPosition(lp + ll, QTextCursor.KeepAnchor)
                c.removeSelectedText()
                return s - ll, e - ll
            tag = f'<span style="font-size:{new}px">'
            c.setPosition(lp)
            c.setPosition(lp + ll, QTextCursor.KeepAnchor)
            c.insertText(tag)
            return s + len(tag) - ll, e + len(tag) - ll
        if new == 0:
            return s, e
        c.setPosition(s)
        c.setPosition(e, QTextCursor.KeepAnchor)
        tag = f'<span style="font-size:{new}px">'
        c.insertText(tag + c.selectedText() + "</span>")
        return s + len(tag), e + len(tag)

    def set_text_size(self, px=None, delta=0):
        """Sets the size (px) of the selected text, or changes it by `delta` px. px=0 removes the size. Every selected line is
        sized on its own; with nothing selected the word at the caret is used."""
        if not self.format_supported() or self.isReadOnly():
            return False
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.WordUnderCursor)
            if not cur.hasSelection():
                return False
        s, e = cur.selectionStart(), cur.selectionEnd()
        segs = self._segments(s, e)
        if not segs:
            return False
        doc = self.document()
        cur.beginEditBlock()
        result = None
        for ln, a, b in reversed(segs):
            blk = doc.findBlockByNumber(ln)
            result = self._size_one(blk.position() + a, blk.position() + b, px, delta)
        cur.endEditBlock()
        sel = QTextCursor(doc)
        if len(segs) == 1:
            sel.setPosition(result[0])
            sel.setPosition(result[1], QTextCursor.KeepAnchor)
        else:
            sel.setPosition(doc.findBlockByNumber(segs[0][0]).position())
            end_blk = doc.findBlockByNumber(segs[-1][0])
            sel.setPosition(end_blk.position() + len(end_blk.text()), QTextCursor.KeepAnchor)
        self.setTextCursor(sel)
        return True

    # ---- the Word-style mini toolbar: font, colours, lists, styles, comments ----------------------------------------------------
    def _span_one(self, kind, s, e, value):
        """Puts <span style="prop:value"> around s..e (or changes / removes the one that is already there). value None removes."""
        doc = self.document()
        s, e = self._normalize(s, e)
        lay = self._find_layer(kind, s, e)
        prop = self.SPAN_PROP[kind]
        c = QTextCursor(doc)
        if lay is not None:
            lp, ll, rp, rl, _tok = lay
            if value is None:
                c.setPosition(rp)
                c.setPosition(rp + rl, QTextCursor.KeepAnchor)
                c.removeSelectedText()
                c.setPosition(lp)
                c.setPosition(lp + ll, QTextCursor.KeepAnchor)
                c.removeSelectedText()
                return s - ll, e - ll
            tag = f'<span style="{prop}:{value}">'
            c.setPosition(lp)
            c.setPosition(lp + ll, QTextCursor.KeepAnchor)
            c.insertText(tag)
            return s + len(tag) - ll, e + len(tag) - ll
        if value is None:
            return s, e
        tag = f'<span style="{prop}:{value}">'
        c.setPosition(s)
        c.setPosition(e, QTextCursor.KeepAnchor)
        c.insertText(tag + c.selectedText() + "</span>")
        return s + len(tag), e + len(tag)

    def set_span(self, kind, value):
        """Applies a font family / text colour / highlight to the selection (or the word at the caret). value None removes it."""
        if not self.format_supported() or self.isReadOnly():
            return False
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.WordUnderCursor)
            if not cur.hasSelection():
                return False
        segs = self._segments(cur.selectionStart(), cur.selectionEnd())
        if not segs:
            return False
        doc = self.document()
        cur.beginEditBlock()
        result = None
        for ln, a, b in reversed(segs):
            blk = doc.findBlockByNumber(ln)
            result = self._span_one(kind, blk.position() + a, blk.position() + b, value)
        cur.endEditBlock()
        sel = QTextCursor(doc)
        if len(segs) == 1:
            sel.setPosition(result[0])
            sel.setPosition(result[1], QTextCursor.KeepAnchor)
        else:
            sel.setPosition(doc.findBlockByNumber(segs[0][0]).position())
            end_blk = doc.findBlockByNumber(segs[-1][0])
            sel.setPosition(end_blk.position() + len(end_blk.text()), QTextCursor.KeepAnchor)
        self.setTextCursor(sel)
        return True

    def set_font_family(self, name):
        return self.set_span("family", name or None)

    def set_text_color(self, color):
        return self.set_span("color", color or None)

    def set_highlight(self, color):
        return self.set_span("bg", color or None)

    LIST_RX = re.compile(r"^(\s*)((?:\d+|[a-zA-Z]|[ivxlcdmIVXLCDM]+)[.)]|[-*+\u2022\u25e6\u25aa])\s+")
    BULLETS = ("-", "*", "+", "\u2022", "\u25e6", "\u25aa")
    NUMBERINGS = ("1.", "1)", "a.", "A.", "i.", "I.")

    @staticmethod
    def _roman(n):
        out = ""
        for v, s in ((1000, "m"), (900, "cm"), (500, "d"), (400, "cd"), (100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
            while n >= v:
                out += s
                n -= v
        return out

    def _marker(self, style, n):
        """The text of list item number n in a style: '1.' '1)' 'a.' 'A.' 'i.' 'I.' or a bullet character."""
        if style in self.BULLETS:
            return style
        body, end = style[:-1], style[-1]
        if body == "1":
            return f"{n}{end}"
        if body in ("a", "A"):
            letter = chr(ord(body) + (n - 1) % 26)
            return letter * ((n - 1) // 26 + 1) + end
        r = self._roman(n)
        return (r.upper() if body == "I" else r) + end

    def toggle_list(self, numbered=False, style=None):
        """Makes the selected lines a bulleted (or numbered) list in the chosen style, switches an existing list to it, or takes
        the list marks off when every line already has exactly that kind."""
        if self.isReadOnly():
            return False
        style = style or ("1." if numbered else "-")
        start, end = self._selected_blocks()
        blocks = []
        b = start
        while b.isValid() and b.blockNumber() <= end.blockNumber():
            if b.text().strip():
                blocks.append(b)
            b = b.next()
        if not blocks:
            return False

        def kind(text):
            m = self.LIST_RX.match(text)
            if not m:
                return None
            return "bullet" if m.group(2) in self.BULLETS else "number"
        want = "bullet" if style in self.BULLETS else "number"
        remove = all(kind(blk.text()) == want and self.LIST_RX.match(blk.text()).group(2) == self._marker(style, i)
                     for i, blk in enumerate(blocks, 1))
        cur = self.textCursor()
        cur.beginEditBlock()
        n = 1
        for blk in blocks:
            text = blk.text()
            m = self.LIST_RX.match(text)
            c = QTextCursor(blk)
            indent = len(text) - len(text.lstrip())
            if remove:
                c.setPosition(blk.position() + len(m.group(1)))
                c.setPosition(blk.position() + m.end(), QTextCursor.KeepAnchor)
                c.removeSelectedText()
                continue
            c.setPosition(blk.position() + (len(m.group(1)) if m else indent))
            if m:
                c.setPosition(blk.position() + m.end(), QTextCursor.KeepAnchor)
            c.insertText(self._marker(style, n) + " ")
            n += 1
        cur.endEditBlock()
        return True

    def multilevel_list(self):
        """Numbers the selected lines as an outline: the indent of a line decides its level (1. then a. then i. ...)."""
        if self.isReadOnly():
            return False
        start, end = self._selected_blocks()
        blocks = []
        b = start
        while b.isValid() and b.blockNumber() <= end.blockNumber():
            if b.text().strip():
                blocks.append(b)
            b = b.next()
        if not blocks:
            return False
        unit = max(1, self.tab_width) if self.use_spaces else 1
        styles = ("1.", "a.", "i.", "1)", "a)", "i)")
        counters = []
        cur = self.textCursor()
        cur.beginEditBlock()
        for blk in blocks:
            text = blk.text().expandtabs(self.tab_width)
            m = self.LIST_RX.match(text)
            lead = len(m.group(1)) if m else len(text) - len(text.lstrip())
            level = min(len(styles) - 1, lead // unit)
            del counters[level + 1:]
            while len(counters) <= level:
                counters.append(0)
            counters[level] += 1
            body = text[m.end():] if m else text.lstrip()
            c = QTextCursor(blk)
            c.select(QTextCursor.LineUnderCursor)
            c.insertText(" " * (level * unit) + self._marker(styles[level], counters[level]) + " " + body)
        cur.endEditBlock()
        return True

    def change_indent(self, delta):
        """Moves the selected lines one step right (+1) or left (-1): by a tab width of spaces (or a tab)."""
        if self.isReadOnly():
            return False
        start, end = self._selected_blocks()
        unit = self._indent_unit()
        cur = self.textCursor()
        cur.beginEditBlock()
        b = start
        while b.isValid() and b.blockNumber() <= end.blockNumber():
            text = b.text()
            if text.strip():
                c = QTextCursor(b)
                inner = len(re.match(r'<p style="[^"]*">', text).group()) if para_style(text) else 0
                c.setPosition(b.position() + inner)
                if delta > 0:
                    c.insertText(unit)
                else:
                    seg = text[inner:]
                    n = 1 if seg.startswith("\t") else min(len(unit), len(seg) - len(seg.lstrip(" ")))
                    if n:
                        c.setPosition(b.position() + inner + n, QTextCursor.KeepAnchor)
                        c.removeSelectedText()
            b = b.next()
        cur.endEditBlock()
        return True

    def sort_lines(self, descending=False):
        """Sorts the selected lines (every line when nothing is selected) A to Z or Z to A, ignoring case."""
        if self.isReadOnly():
            return False
        self.transform_all_or_selection(lambda t: "\n".join(sorted(t.split("\n"), key=lambda s: s.lower(), reverse=descending)))
        return True

    # ---- paragraph marks: alignment, spacing, shading, borders ---------------------------------------------------------------------
    PARA_RX = re.compile(r'^<p style="([^"]*)">(.*)</p>$', re.S)

    def paragraph_state(self):
        """The paragraph properties of the line under the caret: {'text-align': 'center', ...}."""
        return para_style(self.textCursor().block().text())

    def set_paragraph(self, prop, value):
        """Sets (or with value None removes) one paragraph property on every selected line: text-align, line-height, background,
        border or margin-left. The line is wrapped in <p style="...">...</p>; with no property left the wrapper goes."""
        if not self.format_supported() or self.isReadOnly():
            return False
        start, end = self._selected_blocks()
        cur = self.textCursor()
        cur.beginEditBlock()
        b = start
        while b.isValid() and b.blockNumber() <= end.blockNumber():
            text = b.text()
            if text.strip() or b == start:
                m = self.PARA_RX.match(text)
                style = para_style(text) if m else {}
                inner = m.group(2) if m else text
                if value is None:
                    style.pop(prop, None)
                else:
                    style[prop] = value
                new = (f'<p style="{";".join(f"{k}:{v}" for k, v in style.items())}">{inner}</p>' if style else inner)
                if new != text:
                    c = QTextCursor(b)
                    c.select(QTextCursor.LineUnderCursor)
                    c.insertText(new)
            b = b.next()
        cur.endEditBlock()
        self._para_timer.start()
        return True

    def add_space_before(self):
        """Puts an empty line before every selected paragraph that does not already have one."""
        if self.isReadOnly():
            return False
        start, end = self._selected_blocks()
        cur = self.textCursor()
        cur.beginEditBlock()
        blocks = []
        b = start
        while b.isValid() and b.blockNumber() <= end.blockNumber():
            if b.text().strip() and (not b.previous().isValid() or b.previous().text().strip()):
                blocks.append(b.position())
            b = b.next()
        for pos in reversed(blocks):
            c = QTextCursor(self.document())
            c.setPosition(pos)
            c.insertText("\n")
        cur.endEditBlock()
        return True

    def insert_table(self, cols, rows):
        """Inserts a table with a header row and `rows` empty rows: Markdown (or plain text) pipes, HTML tags in an HTML document."""
        if self.isReadOnly():
            return False
        names = [f"Column {i + 1}" for i in range(cols)]
        if self.lang.name == "HTML / XML":
            body = "".join("  <tr>" + "<td></td>" * cols + "</tr>\n" for _ in range(rows))
            text = "<table>\n  <tr>" + "".join(f"<th>{n}</th>" for n in names) + "</tr>\n" + body + "</table>\n"
        else:
            text = "| " + " | ".join(names) + " |\n| " + " | ".join("---" for _ in names) + " |\n" + ("|" + "  |" * cols + "\n") * rows
        cur = self.textCursor()
        if cur.positionInBlock() > 0:
            text = "\n" + text
        cur.insertText(text)
        self.setTextCursor(cur)
        return True

    def set_alignment(self, align):
        return self.set_paragraph("text-align", None if align == "left" else align)

    def set_line_spacing(self, factor):
        return self.set_paragraph("line-height", None if not factor or float(factor) == 1.0 else f"{float(factor):g}")

    def set_shading(self, color):
        return self.set_paragraph("background", color or None)

    def set_border(self, spec):
        return self.set_paragraph("border", spec or None)

    def _refresh_paragraphs(self):
        """Shading is a real block background; alignment and spacing are drawn by sizing the hidden marks; borders are painted."""
        if self.read_only_window:
            return
        doc = self.document()
        text = self.toPlainText() if self.length() < 2_000_000 else ""
        self._has_para = '<p style="' in text
        if not self._has_para and not self._shaded:
            return
        want = {}
        if self._has_para:
            for i, line in enumerate(text.split("\n")):
                if line.startswith('<p style="'):
                    st = para_style(line)
                    if "background" in st:
                        want[i] = QColor(st["background"])
        for i in sorted(set(self._shaded) | set(want)):
            blk = doc.findBlockByNumber(i)
            if not blk.isValid():
                continue
            fmt = blk.blockFormat()
            col = want.get(i)
            if (col is None and fmt.background().style() == Qt.NoBrush) or (col is not None and fmt.background().color() == col and fmt.background().style() != Qt.NoBrush):
                continue
            fmt.setBackground(col) if col is not None else fmt.clearBackground()
            self._in_para = True
            QTextCursor(blk).setBlockFormat(fmt)
            self._in_para = False
        self._shaded = set(want)
        if self._has_para:                                       # alignment and spacing depend on the width: size the marks again
            b = doc.firstBlock()
            while b.isValid():
                if b.text().startswith('<p style="'):
                    self.highlighter.rehighlightBlock(b)
                b = b.next()

    def _paint_borders(self):
        if not self._has_para:
            return
        p = QPainter(self.viewport())
        block = self.firstVisibleBlock()
        bottom = self.viewport().height()
        group = None
        x0 = int(self.contentOffset().x() + self.document().documentMargin() - 3)
        x1 = self.viewport().width() - 5

        def flush():
            if group is not None:
                top, bot, spec = group
                m = re.match(r"(\d+)px\s+(?:\w+\s+)?(#[0-9a-fA-F]{3,8}|\w+)?", spec)
                w = int(m.group(1)) if m else 1
                col = QColor(m.group(2)) if m and m.group(2) and QColor(m.group(2)).isValid() else QColor(theme.c("MUTED"))
                p.setPen(QPen(col, w))
                p.setBrush(Qt.NoBrush)
                p.drawRect(x0, int(top) + 1, x1 - x0, int(bot - top) - 2)
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if geo.top() > bottom:
                break
            spec = para_style(block.text()).get("border") if block.isVisible() and block.text().startswith('<p style="') else None
            if spec and group is not None and group[2] == spec and abs(group[1] - geo.top()) < 2:
                group = (group[0], geo.bottom(), spec)
            else:
                flush()
                group = (geo.top(), geo.bottom(), spec) if spec else None
            block = block.next()
        flush()
        p.end()

    STYLES = {"Normal": None, "Title": (True, False, 32), "Heading 1": (True, False, 28), "Heading 2": (True, False, 22),
              "Heading 3": (True, False, 18), "Emphasis": (False, True, 0), "Strong": (True, False, 0), "Quote": (False, True, 0),
              "Code": (False, False, 0)}

    def apply_style(self, name):
        """A paragraph style, built from the same marks as everything else (Heading 1 = bold, 28 px ...)."""
        if not self.format_supported() or self.isReadOnly() or name not in self.STYLES:
            return False
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.BlockUnderCursor if False else QTextCursor.LineUnderCursor)
            self.setTextCursor(cur)
        self.clear_format()
        spec = self.STYLES[name]
        if spec is None:
            return True
        bold, ital, size = spec
        if name == "Code":
            self.set_span("family", "Consolas")
            self.set_span("bg", "#e8e8e8")
        elif name == "Quote":
            self.toggle_format("italic")
            self.set_span("color", "#6b7482")
        else:
            if ital:
                self.toggle_format("italic")
            if size:
                self.set_text_size(size)
            if bold:
                self.toggle_format("bold")
        return True

    def comment_selection(self):
        """New Comment: a comment in the document's own syntax around the selection (or on the line)."""
        if self.isReadOnly():
            return False
        if self.lang.comment:
            self.toggle_comment()
            return True
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.LineUnderCursor)
        text = cur.selectedText().replace("\u2029", "\n")
        cur.insertText(f"<!-- {text} -->" if text.strip() else "<!--  -->")
        return True

    # ---- the area under a picture is not editable -----------------------------------------------------------------
    def _preview_at(self, block):
        """(link start, link end, pixmap, blank lines below) when `block` is a link whose picture is shown inline."""
        text = block.text()
        if len(text) >= 400 or not block.isValid() or not text.strip():
            return None
        low = text.lower()
        if not any(x in low for x in util.IMAGE_EXTS):
            return None
        refs = util.find_image_refs(text)
        if not refs:
            return None
        s, e, ref = refs[0]
        full = util.resolve_image(ref, os.path.dirname(self.path) if self.path else None)
        pm = self._image_pixmap(full) if full else None
        if pm is None or pm.isNull():
            return None
        blanks, nb = 0, block.next()
        while nb.isValid() and not nb.text().strip() and blanks < 60:
            blanks += 1
            nb = nb.next()
        return (s, e, pm, blanks) if blanks >= 2 else None

    def _preview_size(self, pm, blanks):
        ls = self.fontMetrics().lineSpacing()
        x = int(self.contentOffset().x() + self.document().documentMargin() + 2)
        scale = min(1.0, self.PREVIEW_MAX_W / max(1, pm.width()), (blanks * ls - 6) / max(1, pm.height()),
                    max(40, self.viewport().width() - x - 20) / max(1, pm.width()))
        return max(1, int(pm.width() * scale)), max(1, int(pm.height() * scale))

    def _zone_blanks(self, info):
        """How many blank lines under the link are covered by its picture (the caret may not enter them)."""
        s, e, pm, blanks = info
        ls = max(1, self.fontMetrics().lineSpacing())
        return min(blanks, -(-(self._preview_size(pm, blanks)[1] + 6) // ls))

    def _zone_owner(self, block):
        """(link block, covered blank lines) when `block` is a blank line hidden behind a picture, else None."""
        if self.read_only_window or not block.isValid() or block.text().strip():
            return None
        prev, k = block.previous(), 1
        while prev.isValid() and not prev.text().strip() and k < 62:
            prev = prev.previous()
            k += 1
        if not prev.isValid():
            return None
        info = self._preview_at(prev)
        if info is None:
            return None
        zb = self._zone_blanks(info)
        return (prev, zb) if k <= zb else None

    def _skip_hidden_marks(self):
        """The formatting marks are invisible, so the caret may not stop inside one: it jumps to the nearer visible edge."""
        cur = self.textCursor()
        if cur.hasSelection() or self._in_zone_fix or self.lang.name not in RICH_LANGS:
            return
        block = cur.block()
        col = cur.positionInBlock()
        for a, b in mark_spans(block.text()):
            if a < col < b:
                forward = block.blockNumber() > self._prev_block or (block.blockNumber() == self._prev_block and col >= self._prev_col)
                self._in_zone_fix = True
                cur.setPosition(block.position() + (b if forward else a))
                self.setTextCursor(cur)
                self._in_zone_fix = False
                return

    def _leave_zone(self):
        self._skip_hidden_marks()
        self._prev_col = self.textCursor().positionInBlock()
        cur = self.textCursor()
        if cur.hasSelection() or self._in_zone_fix:
            return
        if self._edit_link is not None and cur.blockNumber() != self._edit_link:
            self._edit_link = None                          # the caret left the link: it is hidden behind its picture again
        owner = self._zone_owner(cur.block())
        if owner is None and cur.blockNumber() != self._edit_link:
            info = self._preview_at(cur.block())            # the link line itself belongs to the picture too
            if info is not None:
                owner = (cur.block(), self._zone_blanks(info))
        if owner is None:
            self._prev_block = cur.blockNumber()
            return
        link, zb = owner
        if self._prev_block <= link.blockNumber():
            target = link.next()
            for _ in range(zb):
                target = target.next()
            if not target.isValid():                        # nothing after the picture yet: make a line to type on
                self._in_zone_fix = True
                c = QTextCursor(self.document())
                c.movePosition(QTextCursor.End)
                c.insertText("\n")
                self._in_zone_fix = False
                target = self.document().lastBlock()
        else:
            target = link.previous() if link.previous().isValid() else link          # moving up: stop above the picture
        self._in_zone_fix = True
        c = QTextCursor(target)
        if target is not link:
            c.movePosition(QTextCursor.EndOfBlock)
        self.setTextCursor(c)
        self._in_zone_fix = False
        self._prev_block = c.blockNumber()

    def _image_at(self, pos):
        for rect, block in self._preview_rects:
            if rect.contains(pos):
                return block
        return None

    def word_at_cursor(self):
        cur = self.textCursor()
        if cur.hasSelection():
            t = cur.selectedText().strip()
            return t if re.fullmatch(r"[A-Za-z_][\w]*", t) else ""
        text, col = cur.block().text(), cur.positionInBlock()
        for m in re.finditer(r"[A-Za-z_]\w*", text):
            if m.start() <= col <= m.end():
                return m.group()
        return ""

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.read_only_window:
            mods = e.modifiers()
            pos = self.cursorForPosition(e.position().toPoint())
            if mods & Qt.AltModifier and mods & Qt.ShiftModifier:               # column selection starts here
                self._col_anchor = (pos.blockNumber(), pos.positionInBlock())
                self.setTextCursor(pos)
                self.extra_cursors = []
                e.accept()
                return
            if mods & Qt.AltModifier:                                          # Alt+click adds a cursor
                if not self.extra_cursors:
                    pass
                self.add_cursor_at(pos.position())
                e.accept()
                return
            self._col_anchor = None
            if self.extra_cursors:
                self.clear_extra_cursors()
        if e.button() == Qt.LeftButton and e.modifiers() & Qt.ControlModifier and not self.read_only_window and self.is_code():
            cur = self.cursorForPosition(e.position().toPoint())
            text, col = cur.block().text(), cur.positionInBlock()
            word = next((m.group() for m in re.finditer(r"[A-Za-z_]\w*", text) if m.start() <= col <= m.end()), "")
            if word:
                self.setTextCursor(cur)
                self.definitionRequested.emit(word)
                e.accept()
                return
        if e.button() == Qt.LeftButton and self._has_flags:
            for rect, blk in self._fold_pills:
                if rect.contains(e.position().toPoint()):
                    self.fold_block(blk, False)
                    e.accept()
                    return
        if e.button() == Qt.LeftButton and not self.read_only_window:
            block = self._image_at(e.position().toPoint())
            if block is not None:                           # a click on a picture selects it instead of editing behind it
                self._img_sel = block.blockNumber()
                info = self._preview_at(block)
                target = block.next()
                for _ in range(self._zone_blanks(info) if info else 0):
                    target = target.next()
                if target.isValid():
                    self._in_zone_fix = True
                    self.setTextCursor(QTextCursor(target))
                    self._in_zone_fix = False
                self.viewport().update()
                e.accept()
                return
        if self._img_sel is not None:
            self._img_sel = None
            self.viewport().update()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._col_anchor is not None and e.buttons() & Qt.LeftButton and e.modifiers() & Qt.AltModifier:
            pos = self.cursorForPosition(e.position().toPoint())
            self._column_select(self._col_anchor[0], self._col_anchor[1], pos.blockNumber(), pos.positionInBlock())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._col_anchor is not None:
            self._col_anchor = None
            self.cursorStatus.emit()
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        block = self._image_at(e.position().toPoint()) if not self.read_only_window else None
        if block is not None:
            info = self._preview_at(block)
            if info:
                full = util.resolve_image(util.find_image_refs(block.text())[0][2], os.path.dirname(self.path) if self.path else None)
                if full:
                    self.imageActivated.emit(full)
            e.accept()
            return
        super().mouseDoubleClickEvent(e)

    def _delete_selected_image(self):
        block = self.document().findBlockByNumber(self._img_sel)
        info = self._preview_at(block) if block.isValid() else None
        self._img_sel = None
        if info is None:
            return
        last = block
        for _ in range(info[3]):                                  # the link and all the blank lines made for it
            last = last.next() if last.next().isValid() else last
        c = QTextCursor(block)
        c.setPosition(block.position())
        end = last.position() + last.length() - 1
        c.setPosition(min(end, self.document().characterCount() - 1), QTextCursor.KeepAnchor)
        c.beginEditBlock()
        c.removeSelectedText()
        if c.block().next().isValid():
            c.deleteChar()
        c.endEditBlock()
        self.setTextCursor(c)
        self.viewport().update()

    def _image_key(self, e):
        """Keys while a picture is selected. -> True when the key was used up."""
        k = e.key()
        if k in (Qt.Key_Delete, Qt.Key_Backspace):
            self._delete_selected_image()
            return True
        if k in (Qt.Key_Return, Qt.Key_Enter):                  # edit the link text
            c = QTextCursor(self.document().findBlockByNumber(self._img_sel))
            c.movePosition(QTextCursor.EndOfBlock)
            self._edit_link = self._img_sel
            self._img_sel = None
            self._in_zone_fix = True
            self.setTextCursor(c)
            self._in_zone_fix = False
            self.viewport().update()
            return True
        if k not in (Qt.Key_Shift, Qt.Key_Control, Qt.Key_Alt, Qt.Key_Copy) and not (e.modifiers() & Qt.ControlModifier and k in (Qt.Key_C, Qt.Key_X)):
            self._img_sel = None
            self.viewport().update()
        return False

    # ---- word autocomplete ----------------------------------------------------------------------------------------
    WORD_TAIL = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")

    def _doc_words(self):
        """{word: count} of the words in this document (refreshed at most twice a second while typing)."""
        now = time.monotonic()
        rev = self.document().revision()
        cached = self._word_cache
        if cached[0] == rev or (cached[2] is not None and now - cached[1] < 0.5):
            return cached[2] or {}
        words = {}
        if self.length() < 2_000_000:
            for w in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", self.toPlainText()):
                words[w] = words.get(w, 0) + 1
        self._word_cache = (rev, now, words)
        return words

    def completion_candidates(self, prefix, limit=3):
        low = prefix.lower()
        out, seen = [], {prefix}
        docw = self._doc_words()
        for w, _n in sorted(((w, n) for w, n in docw.items() if w.lower().startswith(low) and w != prefix),
                            key=lambda t: (-t[1], len(t[0]), t[0].lower())):
            out.append(w)
            seen.add(w)
        for w in sorted(self.lang.completions()):
            if w.lower().startswith(low) and w not in seen:
                out.append(w)
                seen.add(w)
        if len(prefix) >= 3 and len(out) < limit and self.lang.name in ("Plain text", "Markdown"):
            for w in spellmod.speller.words_with_prefix(low, limit):
                shown = w.capitalize() if prefix[:1].isupper() else w
                if shown not in seen:
                    out.append(shown)
                    seen.add(shown)
        return out[:limit]

    def _insert_completion(self, text):
        prefix_len = len(self._completer.completionPrefix())
        cur = self.textCursor()
        cur.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, prefix_len)
        cur.insertText(text)
        self.setTextCursor(cur)

    def _maybe_complete(self, e):
        popup = self._completer.popup()
        if not self.autocomplete_on or self.isReadOnly() or self.textCursor().hasSelection():
            popup.hide()
            return
        ch = e.text()
        typing = bool(ch) and (ch.isalnum() or ch == "_")
        if not typing and e.key() != Qt.Key_Backspace:
            popup.hide()
            return
        cur = self.textCursor()
        m = self.WORD_TAIL.search(cur.block().text()[:cur.positionInBlock()])
        if not m or len(m.group()) < 2:
            popup.hide()
            return
        prefix = m.group()
        cands = self.completion_candidates(prefix)
        if not cands:
            popup.hide()
            return
        self._completer.model().setStringList(cands)
        self._completer.setCompletionPrefix(prefix)
        popup.setCurrentIndex(self._completer.completionModel().index(0, 0))
        rect = self.cursorRect()
        rect.setWidth(max(160, popup.sizeHintForColumn(0) + popup.verticalScrollBar().sizeHint().width() + 24))
        self._completer.complete(rect)

    # ---- IDE helpers: enclosing brackets, auto-close, indent guides ---------------------------------------------------
    CODE_NO = ("Plain text", "Markdown", "Log", "Diff / Patch")
    PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "`": "`"}

    def is_code(self):
        return self.lang.name not in self.CODE_NO

    def _enclosing_bracket(self, pos=None):
        """Index of the nearest unclosed opening bracket before the caret (None when there is none)."""
        doc = self.document()
        pos = self.textCursor().position() if pos is None else pos
        need = {")": 0, "]": 0, "}": 0}
        i = pos - 1
        stop = max(-1, pos - 60000)
        while i > stop:
            ch = doc.characterAt(i)
            if ch in need:
                need[ch] += 1
            elif ch in BRACKETS:
                closer = BRACKETS[ch]
                if need[closer] > 0:
                    need[closer] -= 1
                else:
                    return i
            i -= 1
        return None

    def select_enclosing(self):
        """Selects what is inside the nearest pair of brackets; again, and it grows to the next pair out."""
        cur = self.textCursor()
        start, end = cur.selectionStart(), cur.selectionEnd()
        pos = start
        while True:
            i = self._enclosing_bracket(pos)
            if i is None:
                return False
            j = self._match_bracket(i, self.document().characterAt(i))
            if j is None:
                pos = i
                continue
            if i + 1 < start or j > end or (i + 1 == start and j == end and cur.hasSelection()):
                if i + 1 == start and j == end:
                    pos = i
                    continue
                self.select_range(i + 1, j - i - 1)
                return True
            pos = i

    def _try_autoclose(self, e):
        """Typing ( [ { quotes inserts the closing one too, typing a closer steps over it. -> True when handled."""
        ch = e.text()
        if len(ch) != 1 or e.modifiers() & (Qt.ControlModifier | Qt.AltModifier) or not self.autoclose_on or not self.is_code():
            return False
        cur = self.textCursor()
        text = cur.block().text()
        col = cur.positionInBlock()
        nxt = text[col:col + 1]
        prev = text[col - 1:col] if col else ""
        if cur.hasSelection():
            if ch in self.PAIRS and ch not in "'`" or ch in "\"'`":
                sel = cur.selectedText().replace("\u2029", "\n")
                s = cur.selectionStart()
                cur.insertText(ch + sel + self.PAIRS[ch])
                c = QTextCursor(self.document())
                c.setPosition(s + 1)
                c.setPosition(s + 1 + len(sel), QTextCursor.KeepAnchor)
                self.setTextCursor(c)
                return True
            return False
        if ch in ")]}" and nxt == ch:
            cur.movePosition(QTextCursor.Right)
            self.setTextCursor(cur)
            return True
        if ch in "\"'`":
            if nxt == ch:
                cur.movePosition(QTextCursor.Right)
                self.setTextCursor(cur)
                return True
            if prev.isalnum() or prev in "_\\" or nxt.isalnum() or (ch == "'" and self.lang.name in ("Rust", "Lua")):
                return False
        elif ch not in "([{":
            return False
        elif nxt and not (nxt.isspace() or nxt in ")]}>,;:."):
            return False
        cur.beginEditBlock()
        cur.insertText(ch + self.PAIRS[ch])
        cur.movePosition(QTextCursor.Left)
        cur.endEditBlock()
        self.setTextCursor(cur)
        return True

    def _try_autoclose_backspace(self):
        if not self.autoclose_on or not self.is_code():
            return False
        cur = self.textCursor()
        if cur.hasSelection():
            return False
        text, col = cur.block().text(), cur.positionInBlock()
        if 0 < col < len(text) and text[col - 1] in self.PAIRS and text[col] == self.PAIRS[text[col - 1]]:
            cur.beginEditBlock()
            cur.deletePreviousChar()
            cur.deleteChar()
            cur.endEditBlock()
            self.setTextCursor(cur)
            return True
        return False

    def _paint_indent_guides(self):
        if not self.show_guides or not self.is_code() or self.read_only_window:
            return
        p = QPainter(self.viewport())
        col = QColor(theme.c("BORDER2"))
        col.setAlpha(110)
        p.setPen(QPen(col, 1))
        cw = QFontMetricsF(self.font()).horizontalAdvance(" ")
        x0 = self.contentOffset().x() + self.document().documentMargin()
        block = self.firstVisibleBlock()
        bottom = self.viewport().height()
        tw = max(1, self.tab_width)
        last_levels = 0
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if geo.top() > bottom:
                break
            text = block.text()
            if text.strip():
                width = len(text.expandtabs(tw)) - len(text.expandtabs(tw).lstrip())
                last_levels = width // tw
            levels = last_levels if not text.strip() else width // tw       # blank lines carry the guides on
            for j in range(levels):
                x = int(x0 + j * tw * cw)
                p.drawLine(x, int(geo.top()), x, int(geo.bottom()))
            block = block.next()
        p.end()

    def replace_document_text(self, new):
        """Replaces the whole text as one undo step, keeping the caret near its line."""
        cur = self.textCursor()
        line, col = cur.blockNumber(), cur.positionInBlock()
        bar = self.verticalScrollBar().value()
        cur.beginEditBlock()
        cur.select(QTextCursor.Document)
        cur.insertText(new)
        cur.endEditBlock()
        self.goto_line(line + 1, col)
        self.verticalScrollBar().setValue(bar)

    # ---- code folding ----------------------------------------------------------------------------------------------
    FOLD_W = 16

    def _bd(self, block):
        d = block.userData()
        if not isinstance(d, BlockData):
            d = BlockData()
            block.setUserData(d)
        return d

    def _is_folded(self, block):
        d = block.userData()
        return isinstance(d, BlockData) and d.folded

    def recompute_folds(self):
        """Finds the foldable regions again (called a moment after edits) and re-applies the folds that still exist."""
        if self.read_only_window or not self.folding_on:
            self.fold_regions = {}
        else:
            self.fold_regions = folding.compute_regions(self.lang.name, self.toPlainText())
            for c1, c2 in self.user_hidden:                     # lines hidden by hand stay hidden (and openable) as the text changes
                line = c1.blockNumber() - 1
                if line >= 0:
                    self.fold_regions[line] = max(self.fold_regions.get(line, 0), c2.blockNumber())
        self._apply_folds()
        self.gutter.update()

    def _apply_folds(self):
        doc = self.document()
        hidden = [False] * doc.blockCount()
        any_flag = False
        block = doc.firstBlock()
        while block.isValid() and self._has_flags:
            if self._is_folded(block):
                start = block.blockNumber()
                end = self.fold_regions.get(start)
                if end is None:
                    self._bd(block).folded = False                # its region is gone (the text was edited)
                else:
                    any_flag = True
                    for k in range(start + 1, min(end, len(hidden) - 1) + 1):
                        hidden[k] = True
            block = block.next()
        self._has_flags = any_flag
        if not any_flag and not self._hidden_any:
            return
        self._hidden_any = any(hidden)
        changed = False
        block, i = doc.firstBlock(), 0
        while block.isValid():
            if block.isVisible() == hidden[i]:
                block.setVisible(not hidden[i])
                block.setLineCount(0 if hidden[i] else 1)
                changed = True
            block, i = block.next(), i + 1
        if changed:
            doc.markContentsDirty(0, max(1, doc.characterCount() - 1))
            self.viewport().update()
            self.updateGeometry()

    def fold_block(self, block, fold=True):
        if block.blockNumber() not in self.fold_regions:
            return False
        self._bd(block).folded = fold
        self._has_flags = self._has_flags or fold
        cur = self.textCursor()
        self._apply_folds()
        if fold and cur.blockNumber() > block.blockNumber() and cur.blockNumber() <= self.fold_regions[block.blockNumber()]:
            self.setTextCursor(QTextCursor(block))
        self.gutter.update()
        return True

    def _region_containing(self, line):
        best = None
        for s, e in self.fold_regions.items():
            if s <= line <= e and (best is None or s > best):
                best = s
        return best

    def fold_current(self):
        """Folds the innermost open block around the caret."""
        line = self.textCursor().blockNumber()
        starts = sorted((s for s, e in self.fold_regions.items() if s <= line <= e and not self._is_folded(self.document().findBlockByNumber(s))),
                        reverse=True)
        return bool(starts) and self.fold_block(self.document().findBlockByNumber(starts[0]), True)

    def unfold_current(self):
        line = self.textCursor().blockNumber()
        folded = sorted((s for s, e in self.fold_regions.items() if s <= line <= e and self._is_folded(self.document().findBlockByNumber(s))),
                        reverse=True)
        return bool(folded) and self.fold_block(self.document().findBlockByNumber(folded[-1] if len(folded) > 1 else folded[0]), False)

    def fold_all(self, functions_only=False):
        doc = self.document()
        funcs = self.lang.funcs
        starts = [s for s in self.fold_regions
                  if not functions_only or (funcs and funcs.search(doc.findBlockByNumber(s).text()))]
        if functions_only:                                      # fold the functions themselves, not the class around them
            starts = [s for s in starts if not any(s < t <= self.fold_regions[s] for t in starts)]
        flagged = []
        for s in starts:
            self._bd(doc.findBlockByNumber(s)).folded = True
            self._has_flags = True
            flagged.append(s)
        line = self.textCursor().blockNumber()                  # the caret must not stay inside what is about to be hidden
        outer = [s for s in flagged if s < line <= self.fold_regions[s]]
        if outer:
            self.setTextCursor(QTextCursor(doc.findBlockByNumber(min(outer))))
        self._apply_folds()
        self.gutter.update()

    def unfold_all(self):
        b = self.document().firstBlock()
        while b.isValid():
            d = b.userData()
            if isinstance(d, BlockData) and d.folded:
                d.folded = False
            b = b.next()
        self._has_flags = False
        self._apply_folds()
        self.gutter.update()

    def _reveal_cursor(self):
        """The caret (search hit, Go To, bookmark ...) landed on a hidden line: open the blocks that hide it."""
        block = self.textCursor().block()
        if block.isVisible() or not self._has_flags:
            return
        line = block.blockNumber()
        for s, e in sorted(self.fold_regions.items()):
            sb = self.document().findBlockByNumber(s)
            if s < line <= e and self._is_folded(sb):
                self._bd(sb).folded = False
        self._apply_folds()
        self.gutter.update()

    def _paint_fold_pills(self):
        if not self._has_flags:
            return
        p = QPainter(self.viewport())
        fm = self.fontMetrics()
        self._fold_pills = []
        block = self.firstVisibleBlock()
        bottom = self.viewport().height()
        while block.isValid():
            geo = self.blockBoundingGeometry(block).translated(self.contentOffset())
            if geo.top() > bottom:
                break
            if block.isVisible() and self._is_folded(block):
                c = QTextCursor(block)
                c.movePosition(QTextCursor.EndOfBlock)
                x = self.cursorRect(c).x() + 8
                rect = QRect(x, int(geo.top()) + 3, 26, int(geo.height()) - 6)
                p.setPen(QPen(QColor(theme.c("BORDER2")), 1))
                p.setBrush(QColor(theme.c("PANEL2")))
                p.drawRoundedRect(rect, 4, 4)
                p.setPen(QColor(theme.c("MUTED")))
                p.drawText(rect, Qt.AlignCenter, "\u2026")
                self._fold_pills.append((rect, block))
            block = block.next()
        p.end()

    # ---- multiple cursors and column selection ------------------------------------------------------------------------
    def _all_cursors(self):
        return [self.textCursor()] + self.extra_cursors

    def clear_extra_cursors(self):
        if self.extra_cursors:
            self.extra_cursors = []
            self.refresh_selections()
            self.viewport().update()
            self.cursorStatus.emit()

    def _dedupe_cursors(self):
        main = self.textCursor()
        seen = {(main.anchor(), main.position())}
        keep = []
        for c in self.extra_cursors:
            key = (c.anchor(), c.position())
            if key not in seen:
                seen.add(key)
                keep.append(c)
        self.extra_cursors = keep

    def add_cursor_at(self, pos, anchor=None):
        c = QTextCursor(self.document())
        c.setPosition(pos)
        if anchor is not None:
            c.setPosition(anchor)
            c.setPosition(pos, QTextCursor.KeepAnchor)
        self.extra_cursors.append(c)
        self._dedupe_cursors()
        self.refresh_selections()
        self.viewport().update()
        self.cursorStatus.emit()

    def add_next_occurrence(self):
        """Ctrl+Alt+D: selects the word (first time), then adds the next match of the selected text as another cursor."""
        main = self.textCursor()
        if not main.hasSelection():
            main.select(QTextCursor.WordUnderCursor)
            if not main.hasSelection():
                return False
            self.setTextCursor(main)
            return True
        needle = main.selectedText()
        if "\u2029" in needle:
            return False
        text = self.toPlainText()
        pm = PosMap(text)
        last_end = max(c.selectionEnd() for c in self._all_cursors())
        i = text.find(needle, pm.to_py(last_end))
        if i < 0:
            i = text.find(needle)
        if i < 0:
            return False
        a, b = pm.to_q(i), pm.to_q(i + len(needle))
        if any(c.selectionStart() == a and c.selectionEnd() == b for c in self._all_cursors()):
            return False
        self.add_cursor_at(b, a)
        self.ensureCursorVisible()
        return True

    def select_all_occurrences(self):
        main = self.textCursor()
        if not main.hasSelection():
            main.select(QTextCursor.WordUnderCursor)
        needle = main.selectedText()
        if not needle or "\u2029" in needle:
            return False
        text = self.toPlainText()
        pm = PosMap(text)
        self.extra_cursors = []
        found = [m.start() for m in re.finditer(re.escape(needle), text)][:5000]
        for i in found:
            a, b = pm.to_q(i), pm.to_q(i + len(needle))
            if a == main.selectionStart():
                continue
            self.add_cursor_at(b, a)
        self.setTextCursor(main)
        self.refresh_selections()
        return True

    def add_cursor_vertical(self, up):
        cursors = self._all_cursors()
        base = min(cursors, key=lambda c: c.position()) if up else max(cursors, key=lambda c: c.position())
        block = base.block().previous() if up else base.block().next()
        if not block.isValid():
            return False
        col = min(base.positionInBlock(), len(block.text()))
        self.add_cursor_at(block.position() + col)
        return True

    def _column_select(self, anchor_line, anchor_col, line, col):
        """Alt+Shift+drag: one cursor per line, each selecting the columns between the two corners."""
        doc = self.document()
        lo, hi = sorted((anchor_col, col))
        lines = range(min(anchor_line, line), max(anchor_line, line) + 1)
        cursors = []
        for ln in lines:
            b = doc.findBlockByNumber(ln)
            if not b.isValid():
                continue
            n = len(b.text())
            c = QTextCursor(doc)
            c.setPosition(b.position() + min(lo, n))
            c.setPosition(b.position() + min(hi, n), QTextCursor.KeepAnchor)
            cursors.append(c)
        if not cursors:
            return
        main = next((c for c in cursors if c.block().blockNumber() == line), cursors[-1])
        self.setTextCursor(main)
        self.extra_cursors = [c for c in cursors if c is not main]
        self.refresh_selections()
        self.viewport().update()

    def _multi_key(self, e):
        """Keys while several cursors are active. -> True when handled here."""
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & Qt.ControlModifier)
        shift = bool(mods & Qt.ShiftModifier)
        if key == Qt.Key_Escape:
            self.clear_extra_cursors()
            return True
        move = {Qt.Key_Left: QTextCursor.Left, Qt.Key_Right: QTextCursor.Right, Qt.Key_Up: QTextCursor.Up,
                Qt.Key_Down: QTextCursor.Down, Qt.Key_Home: QTextCursor.StartOfBlock, Qt.Key_End: QTextCursor.EndOfBlock}
        if key in move and not (mods & Qt.AltModifier):
            op = move[key]
            if ctrl and key == Qt.Key_Left:
                op = QTextCursor.WordLeft
            elif ctrl and key == Qt.Key_Right:
                op = QTextCursor.WordRight
            mode = QTextCursor.KeepAnchor if shift else QTextCursor.MoveAnchor
            cursors = self._all_cursors()
            for c in cursors:
                if not shift and c.hasSelection() and key in (Qt.Key_Left, Qt.Key_Right):
                    c.setPosition(c.selectionStart() if key == Qt.Key_Left else c.selectionEnd())
                else:
                    c.movePosition(op, mode)
            self.setTextCursor(cursors[0])
            self._dedupe_cursors()
            self._after_multi()
            return True
        if ctrl and key in (Qt.Key_C, Qt.Key_X):
            cursors = sorted(self._all_cursors(), key=lambda c: c.selectionStart())
            texts = [c.selectedText().replace("\u2029", "\n") for c in cursors if c.hasSelection()]
            if texts:
                QGuiApplication.clipboard().setText("\n".join(texts))
            if key == Qt.Key_X:
                self._multi_edit(lambda c: c.removeSelectedText() if c.hasSelection() else None)
            return True
        if ctrl and key == Qt.Key_V:
            clip = QGuiApplication.clipboard().text().replace("\r\n", "\n")
            cursors = sorted(self._all_cursors(), key=lambda c: c.selectionStart())
            parts = clip.split("\n")
            if len(parts) == len(cursors):
                mapping = {id(c): parts[i] for i, c in enumerate(cursors)}
                self._multi_edit(lambda c: c.insertText(mapping[id(c)]))
            else:
                self._multi_edit(lambda c: c.insertText(clip))
            return True
        if ctrl or (mods & Qt.AltModifier):
            self.clear_extra_cursors()
            return False
        if key in (Qt.Key_Backspace, Qt.Key_Delete):
            def erase(c):
                if c.hasSelection():
                    c.removeSelectedText()
                elif key == Qt.Key_Backspace:
                    c.deletePreviousChar()
                else:
                    c.deleteChar()
            self._multi_edit(erase)
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter):
            def newline(c):
                indent = re.match(r"[ \t]*", c.block().text()).group()
                c.insertText("\n" + indent)
            self._multi_edit(newline)
            return True
        if key == Qt.Key_Tab:
            unit = self._indent_unit()
            self._multi_edit(lambda c: c.insertText(unit))
            return True
        ch = e.text()
        if ch and ch >= " " and ch != "\x7f":
            self._multi_edit(lambda c: c.insertText(ch))
            return True
        return False

    def _multi_edit(self, fn):
        """Applies one edit at every cursor as a single undo step (the cursors follow the text as it changes)."""
        cursors = self._all_cursors()
        order = sorted(cursors, key=lambda c: c.position(), reverse=True)       # later text first, so earlier cursors stay valid
        main = cursors[0]
        main.beginEditBlock()
        for c in order:
            fn(c)
        main.endEditBlock()
        self.setTextCursor(main)
        self.extra_cursors = cursors[1:]
        self._dedupe_cursors()
        self._after_multi()

    def _after_multi(self):
        self.ensureCursorVisible()
        self.refresh_selections()
        self.viewport().update()
        self.cursorStatus.emit()

    def _extra_cursor_selections(self):
        out = []
        for c in self.extra_cursors:
            if c.hasSelection():
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(QColor(theme.c("SEL_BG")))
                s.cursor = c
                out.append(s)
        return out

    def _paint_extra_carets(self):
        if not self.extra_cursors:
            return
        p = QPainter(self.viewport())
        for c in self.extra_cursors:
            r = self.cursorRect(c)
            p.fillRect(r.x(), r.y(), 2, r.height(), QColor(theme.c("ACCENT")))
        p.end()

    def share_document_from(self, other):
        """Makes this editor another view of `other`'s document (split view): same text, undo history and folds."""
        self.setDocument(other.document())
        self.highlighter = other.highlighter
        self.document().contentsChange.connect(self._on_edit)
        self.document().contentsChanged.connect(self._fold_timer.start)
        self.path, self.lang, self.encoding, self.eol = other.path, other.lang, other.encoding, other.eol
        self.tab_width, self.use_spaces = other.tab_width, other.use_spaces
        self.set_tab_width(other.tab_width)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)              # a shared layout can only wrap for one view
        self.fold_regions = dict(other.fold_regions)
        self._has_flags = other._has_flags
        self.git_marks = other.git_marks
        self._update_gutter_width()
        self.refresh_selections()

    def _tint_selections(self):
        out = []
        doc = self.document()
        for line, color in list(self.line_tint.items())[:4000]:
            b = doc.findBlockByNumber(line)
            if not b.isValid():
                continue
            s = QTextEdit.ExtraSelection()
            s.format.setBackground(color)
            s.format.setProperty(QTextFormat.FullWidthSelection, True)
            s.cursor = QTextCursor(b)
            out.append(s)
        for line, spans in list(self.span_tint.items())[:2000]:
            b = doc.findBlockByNumber(line)
            if not b.isValid():
                continue
            for st, en, color in spans[:40]:
                s = QTextEdit.ExtraSelection()
                s.format.setBackground(color)
                s.cursor = QTextCursor(doc)
                s.cursor.setPosition(b.position() + min(st, max(0, b.length() - 1)))
                s.cursor.setPosition(b.position() + min(max(en, st), max(0, b.length() - 1)), QTextCursor.KeepAnchor)
                out.append(s)
        return out

    def _diag_selections(self):
        out = []
        doc = self.document()
        for sl, sc, el, ec, sev, msg in self.diagnostics[:500]:
            b1, b2 = doc.findBlockByNumber(sl), doc.findBlockByNumber(el)
            if not b1.isValid() or not b2.isValid():
                continue
            s = QTextEdit.ExtraSelection()
            s.format.setUnderlineStyle(QTextCharFormat.WaveUnderline)
            s.format.setUnderlineColor(QColor(theme.c("RED") if sev == 1 else theme.c("ORANGE") if sev == 2 else theme.c("BLUE")))
            s.cursor = QTextCursor(doc)
            s.cursor.setPosition(b1.position() + min(sc, max(0, b1.length() - 1)))
            end = b2.position() + min(ec, max(0, b2.length() - 1))
            s.cursor.setPosition(max(end, s.cursor.position() + 1), QTextCursor.KeepAnchor)
            out.append(s)
        return out

    def _diagnostic_at(self, line, col):
        for sl, sc, el, ec, sev, msg in self.diagnostics:
            if (sl, sc) <= (line, col) <= (el, max(ec, sc + 1)):
                return msg
        return ""

    def toggle_comment(self):
        prefix = self.lang.comment
        if not prefix:
            return
        start, end = self._selected_blocks()
        blocks = []
        b = start
        while b.isValid() and b.blockNumber() <= end.blockNumber():
            blocks.append(b)
            b = b.next()
        all_commented = all(not b.text().strip() or b.text().lstrip().startswith(prefix) for b in blocks)
        cur = self.textCursor()
        cur.beginEditBlock()
        for b in blocks:
            text = b.text()
            if not text.strip():
                continue
            c = QTextCursor(b)
            indent = len(text) - len(text.lstrip())
            c.setPosition(b.position() + indent)
            if all_commented:
                n = len(prefix) + (1 if text[indent + len(prefix):indent + len(prefix) + 1] == " " else 0)
                c.setPosition(b.position() + indent + n, QTextCursor.KeepAnchor)
                c.removeSelectedText()
            else:
                c.insertText(prefix + " ")
        cur.endEditBlock()

    # ---- navigation -------------------------------------------------------------------------------------------
    def goto_line(self, line, col=0):
        block = self.document().findBlockByNumber(max(0, line - 1))
        if not block.isValid():
            block = self.document().lastBlock()
        cur = QTextCursor(block)
        cur.setPosition(block.position() + min(col, block.length() - 1))
        self.setTextCursor(cur)
        self.centerCursor()

    def goto_offset(self, offset):
        offset = max(0, min(offset, self.document().characterCount() - 1))
        cur = QTextCursor(self.document())
        cur.setPosition(offset)
        self.setTextCursor(cur)
        self.centerCursor()

    def select_range(self, start, length):
        cur = QTextCursor(self.document())
        cur.setPosition(start)
        cur.setPosition(start + length, QTextCursor.KeepAnchor)
        self.setTextCursor(cur)
        self.centerCursor()

    # ---- wheel / zoom -----------------------------------------------------------------------------------------
    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            # Ctrl + wheel zooms the text, one step per notch (a touchpad's small deltas add up to a notch)
            self._wheel_acc = getattr(self, "_wheel_acc", 0) + e.angleDelta().y()
            while abs(self._wheel_acc) >= 120:
                self.zoomRequested.emit(1 if self._wheel_acc > 0 else -1)
                self._wheel_acc -= 120 if self._wheel_acc > 0 else -120
            e.accept()
            return
        super().wheelEvent(e)

    # ---- pictures: paste, drop, hover preview ------------------------------------------------------------------
    MARKS_MIME = "application/x-lavatinoter-text"

    def createMimeDataFromSelection(self):
        """What Copy / Cut / drag put on the clipboard. For formatted text the marks never leak into other programs: they get the
        visible text (plain) and real bold / italic / underline / size (HTML). LavatiNoter itself also gets the original text
        with its marks, so pasting back here keeps the formatting."""
        md = super().createMimeDataFromSelection()
        if self.read_only_window or not self.format_supported():
            return md
        raw = self.textCursor().selectedText().replace("\u2029", "\n")
        if raw and richtext.has_marks(raw):
            from PySide6.QtCore import QMimeData
            md = QMimeData()                                  # Qt's own object answers from the selection and ignores what is set on it
            md.setText(richtext.to_unicode(raw) if self.copy_styled else richtext.strip_marks(raw))
            md.setHtml(richtext.marks_to_html(raw))
            md.setData(self.MARKS_MIME, raw.encode("utf-8"))
        return md

    def copy_plain(self):
        """Copies the visible text only: no marks and no styled characters."""
        from PySide6.QtCore import QMimeData
        raw = self.textCursor().selectedText().replace("\u2029", "\n")
        if raw:
            md = QMimeData()
            md.setText(richtext.strip_marks(raw))
            QGuiApplication.clipboard().setMimeData(md)

    def copy_with_marks(self):
        """Copies the text exactly as written, marks included (for pasting into Markdown, GitHub, a chat ...)."""
        from PySide6.QtCore import QMimeData
        raw = self.textCursor().selectedText().replace("\u2029", "\n")
        if raw:
            md = QMimeData()
            md.setText(raw)
            QGuiApplication.clipboard().setMimeData(md)

    def canInsertFromMimeData(self, src):
        return src.hasImage() or src.hasUrls() or src.hasText()

    def insertFromMimeData(self, src):
        if src.hasFormat(self.MARKS_MIME) and not self.isReadOnly():
            raw = bytes(src.data(self.MARKS_MIME)).decode("utf-8")
            # formatted text pasted back into a text / Markdown / HTML tab keeps its formatting; into code it is the plain text
            self.textCursor().insertText(raw if self.format_supported() else richtext.strip_marks(raw))
            self.ensureCursorVisible()
            return
        has_text = src.hasText() and bool(src.text().strip())
        if src.hasImage() and not has_text:
            img = src.imageData()
            if isinstance(img, QImage) and not img.isNull():
                self.paste_image(img)
                return
            from PySide6.QtGui import QPixmap
            if isinstance(img, QPixmap) and not img.isNull():
                self.paste_image(img.toImage())
                return
        if src.hasUrls():
            paths = [u.toLocalFile() for u in src.urls() if u.isLocalFile()]
            if paths and (not has_text or all(os.path.exists(p) for p in paths)):
                images = [p for p in paths if p.lower().endswith(util.IMAGE_EXTS)]
                others = [p for p in paths if p not in images]
                for p in images:
                    self.insert_image_ref(p)
                if others:
                    self.filesDropped.emit(others)
                if paths:
                    return
        super().insertFromMimeData(src)

    def has_clipboard_image(self):
        from PySide6.QtGui import QGuiApplication
        return QGuiApplication.clipboard().mimeData().hasImage()

    def paste_image_from_clipboard(self):
        from PySide6.QtGui import QGuiApplication
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            return None
        return self.paste_image(img)

    def image_target_dir(self):
        if self.path:
            return os.path.join(os.path.dirname(self.path), self.image_folder or "images")
        return util.sub_dir("pasted-images")

    def paste_image(self, img):
        folder = self.image_target_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        name, n = f"image-{stamp}.png", 1
        while os.path.exists(os.path.join(folder, name)):
            n += 1
            name = f"image-{stamp}-{n}.png"
        path = os.path.join(folder, name)
        if not img.save(path, "PNG"):
            return None
        self.insert_image_ref(path, img.width(), img.height())
        self.ensureCursorVisible()
        self.imagePasted.emit(path)
        return path

    # The picture is painted over blank lines that follow its link, and the link text is hidden while the caret is
    # elsewhere, so a pasted picture shows as a picture. The blank lines are ordinary newlines in the file.
    PREVIEW_MAX_W = 520
    PREVIEW_MAX_H = 320

    def _preview_lines(self, w, h):
        x = int(self.contentOffset().x() + self.document().documentMargin() + 2)
        room = max(40, self.viewport().width() - x - 20)           # a narrow window shows the picture smaller, so it needs fewer lines
        scale = min(1.0, self.PREVIEW_MAX_W / max(1, w), self.PREVIEW_MAX_H / max(1, h), room / max(1, w))
        return int((h * scale) // max(1, self.fontMetrics().lineSpacing())) + 2

    def insert_image_ref(self, abs_path, w=None, h=None):
        if w is None:
            im = QImage(abs_path)
            w, h = im.width(), im.height()
        cur = self.textCursor()
        cur.beginEditBlock()
        if cur.positionInBlock() > 0 and cur.block().text().strip():
            cur.insertText("\n")
        if not cur.block().previous().isValid():            # the very first line: leave an empty line above the picture
            cur.insertText("\n")
        cur.insertText(self.image_reference(abs_path) + "\n" * (self._preview_lines(w, h) + 1))
        cur.endEditBlock()
        self.setTextCursor(cur)

    def _image_pixmap(self, full):
        try:
            m = os.path.getmtime(full)
        except OSError:
            return None
        hit = self._pix_cache.get(full)
        if hit and hit[0] == m:
            return hit[1]
        pm = QPixmap(full)
        if len(self._pix_cache) > 40:
            self._pix_cache.clear()
        self._pix_cache[full] = (m, pm)
        return pm

    def _visible_previews(self):
        """[(block, link start, link end, pixmap, blank lines below)] for pictures that can be shown inline."""
        out = []
        if self.read_only_window:
            return out
        base = os.path.dirname(self.path) if self.path else None
        block = self.firstVisibleBlock()
        for _ in range(65):                 # a picture can still be in view after its link line scrolled off the top
            if not block.previous().isValid():
                break
            block = block.previous()
        bottom = self.viewport().height()
        while block.isValid():
            top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
            if top > bottom:
                break
            text = block.text()
            low = text.lower()
            if len(text) < 400 and any(x in low for x in util.IMAGE_EXTS):
                refs = util.find_image_refs(text)
                if refs:
                    s, e, ref = refs[0]
                    full = util.resolve_image(ref, base)
                    pm = self._image_pixmap(full) if full else None
                    if pm is not None and not pm.isNull():
                        blanks, nb = 0, block.next()
                        while nb.isValid() and not nb.text().strip() and blanks < 60:
                            blanks += 1
                            nb = nb.next()
                        if blanks >= 2:
                            out.append((block, s, e, pm, blanks))
            block = block.next()
        return out

    def _image_hide_selections(self):
        out = []
        for block, s, e, pm, blanks in self._visible_previews():
            if block.blockNumber() == self._edit_link:
                continue
            sel = QTextEdit.ExtraSelection()
            sel.format.setForeground(QColor(0, 0, 0, 0))
            sel.cursor = QTextCursor(block)
            sel.cursor.setPosition(block.position() + s)
            sel.cursor.setPosition(block.position() + e, QTextCursor.KeepAnchor)
            out.append(sel)
        return out

    def paintEvent(self, e):
        super().paintEvent(e)
        self._paint_indent_guides()
        self._paint_fold_pills()
        self._paint_borders()
        self._cover_selected_marks()
        self._paint_extra_carets()
        previews = self._visible_previews()
        self._preview_rects = []
        if not previews:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        ls = self.fontMetrics().lineSpacing()
        cur_block = self.textCursor().block()
        sel_a, sel_b = self.textCursor().selectionStart(), self.textCursor().selectionEnd()
        for block, s, e2, pm, blanks in previews:
            geo = self.blockBoundingGeometry(block).translated(self.contentOffset())
            x = int(self.contentOffset().x() + self.document().documentMargin() + 2)
            y = int(geo.top()) if block.blockNumber() != self._edit_link else int(geo.bottom()) + 2     # while the link is edited the picture sits below it
            w, h = self._preview_size(pm, blanks)
            if sel_a < sel_b and block.blockNumber() != self._edit_link:
                self._cover_selected_path(p, block, s, e2, sel_a, sel_b)
            p.drawPixmap(x, y + 2, pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            selected = block.blockNumber() == self._img_sel
            p.setPen(QPen(QColor(theme.c("ACCENT")), 2) if selected else QColor(theme.c("BORDER2")))
            p.setBrush(Qt.NoBrush)
            p.drawRect(x - 1, y + 1, w + 1, h + 1)
            self._preview_rects.append((QRect(x, y + 2, w, h), block))
        p.end()

    def _cover_selected_marks(self):
        """Selected text is painted in the selection's text colour, which would show the hidden <p style=...> and </p> marks
        (large ones when a line is aligned or spaced out): paint the selection colour over them."""
        cur = self.textCursor()
        if not self._has_para or not cur.hasSelection():
            return
        sel_a, sel_b = cur.selectionStart(), cur.selectionEnd()
        p = QPainter(self.viewport())
        col = QColor(theme.c("SEL_BG"))
        block = self.firstVisibleBlock()
        bottom = self.viewport().height()
        while block.isValid():
            top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
            if top > bottom:
                break
            text = block.text()
            if text.startswith('<p style="') and text.endswith("</p>") and block.position() <= sel_b and block.position() + len(text) >= sel_a:
                start = block.position()
                for a, b in ((0, text.index(">") + 1), (len(text) - 4, len(text))):
                    if start + b <= sel_a or start + a >= sel_b:
                        continue
                    c1 = QTextCursor(self.document())
                    c1.setPosition(start + max(a, sel_a - start))
                    c2 = QTextCursor(self.document())
                    c2.setPosition(start + min(b, sel_b - start))
                    r1, r2 = self.cursorRect(c1), self.cursorRect(c2)
                    if r1.top() == r2.top():
                        p.fillRect(QRect(r1.left(), r1.top(), r2.left() - r1.left() + 1, max(r1.height(), r2.height())), col)
            block = block.next()
        p.end()

    def _cover_selected_path(self, p, block, s, e, sel_a, sel_b):
        """A selected picture path is painted in the selection's text colour, which a transparent extra selection cannot hide:
        paint the selection colour over the path's text so only the picture shows."""
        start, end = block.position() + s, block.position() + e
        if sel_b <= start or sel_a >= end:
            return
        c = QTextCursor(self.document())
        c.setPosition(start)
        r1 = self.cursorRect(c)
        c.setPosition(end)
        r2 = self.cursorRect(c)
        if r1.top() != r2.top():                              # a wrapped path: cover the whole width of the lines it takes
            r2.setLeft(self.viewport().width())
            r2.setTop(r1.top())
        p.fillRect(QRect(r1.left(), r1.top(), max(0, r2.left() - r1.left()) + 2, r2.bottom() - r1.top() + 1),
                   QColor(theme.c("SEL_BG")))

    def image_reference(self, abs_path):
        """The text inserted for a pasted picture, in the syntax of the document's language."""
        if self.path:
            try:
                ref = os.path.relpath(abs_path, os.path.dirname(self.path))
            except ValueError:                      # another drive: keep the absolute path
                ref = abs_path
        else:
            ref = abs_path
        ref = ref.replace("\\", "/")
        quoted = ref.replace(" ", "%20")
        name = self.lang.name
        if name == "Markdown":
            return f"![image]({quoted})"
        if name == "HTML / XML":
            return f'<img src="{quoted}" alt="">'
        if name == "CSS":
            return f'url("{quoted}")'
        return ref

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            pos = e.pos() - self.viewport().pos()
            cur = self.cursorForPosition(pos)
            line = cur.block().text()
            col = cur.positionInBlock()
            for s, t, ref in util.find_image_refs(line):
                if s <= col <= t:
                    base = os.path.dirname(self.path) if self.path else None
                    full = util.resolve_image(ref, base)
                    uri = util.image_data_uri(full) if full else None
                    if uri:
                        QToolTip.showText(e.globalPos(), f'<img src="{uri}"><br>{os.path.basename(full)}', self)
                    else:
                        QToolTip.showText(e.globalPos(), f"Image not found: {ref}", self)
                    return True
            msg = self._diagnostic_at(cur.blockNumber(), col) if self.diagnostics else ""
            if not msg and self.hover_provider is not None and not self.read_only_window:
                try:
                    msg = self.hover_provider(cur.blockNumber(), col) or ""
                except Exception:  # noqa: BLE001 - a language server problem must never break the editor
                    msg = ""
            if msg:
                QToolTip.showText(e.globalPos(), msg[:1200], self)
                return True
            QToolTip.hideText()
        return super().event(e)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasImage():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        md = e.mimeData()
        if md.hasUrls() and any(u.isLocalFile() for u in md.urls()):
            paths = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
            images = [p for p in paths if p.lower().endswith(util.IMAGE_EXTS)]
            if images and len(images) == len(paths):
                self.setTextCursor(self.cursorForPosition(e.position().toPoint()))
                for p in images:
                    self.insert_image_ref(p)
                e.acceptProposedAction()
                return
            self.filesDropped.emit([p for p in paths if p not in images] or paths)
            e.acceptProposedAction()
            return
        super().dropEvent(e)

    # ---- document info ------------------------------------------------------------------------------------------
    def length(self):
        return self.document().characterCount() - 1

    def selection_info(self):
        cur = self.textCursor()
        if not cur.hasSelection():
            return 0, 0
        text = cur.selectedText()
        return len(text), text.count(" ") + 1
