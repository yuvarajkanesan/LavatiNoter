"""The code editor widget: line numbers, bookmarks, smart highlight, bracket matching, indentation helpers
and picture paste (clipboard images are saved next to the document and linked in)."""
import datetime
import os
import re

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QColor, QPen, QFont, QFontMetricsF, QImage, QPainter, QPixmap, QTextCharFormat, QTextCursor, QTextFormat,
                           QTextOption, QTextBlockUserData)
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QToolTip, QWidget

from . import spell as spellmod
from . import theme, util
from .highlighter import PLAIN, Highlighter, lang_for_path

BRACKETS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = {v: k for k, v in BRACKETS.items()}
WORD_RE = re.compile(r"\w+")


class BlockData(QTextBlockUserData):
    def __init__(self):
        super().__init__()
        self.bookmark = False


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


class CodeEditor(QPlainTextEdit):
    cursorStatus = Signal()                 # caret / selection / mode changed: refresh the status bar
    zoomRequested = Signal(int)             # Ctrl+wheel
    filesDropped = Signal(list)             # local files dropped or pasted: the window opens them
    imagePasted = Signal(str)               # path of the image file that was saved for a paste
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
        self._preview_rects = []            # [(QRect, link block)] of the pictures drawn in the last paint
        self._img_sel = None                # block number of the selected picture
        self._in_zone_fix = False
        self._prev_block = 0
        self.autocorrect_on = False
        self._ac = None                     # the last automatic correction, so Backspace can take it back
        self.gutter = LineNumberArea(self)
        self.highlighter = Highlighter(self.document())
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
        self.highlighter.spell_on = on and spellmod.speller.available
        self.autocorrect_on = autocorrect and self.highlighter.spell_on
        self.highlighter.rehighlight()

    def set_language(self, lang):
        self.lang = lang
        self.highlighter.set_lang(lang)

    def detect_language(self):
        self.set_language(lang_for_path(self.path))

    # ---- gutter ---------------------------------------------------------------------------------------
    def _fmt_num(self, n):
        return self.line_prefix + (f"{n:,}" if self.line_base else str(n))

    def gutter_width(self):
        last = self.blockCount() + self.line_base
        digits = len(self._fmt_num(max(last, 99)))
        return 28 + self.fontMetrics().horizontalAdvance("9") * digits

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
        panel = getattr(self, "goto_panel", None)
        if panel is not None and panel.isVisible():
            panel.move(self.width() - panel.width() - 28, 16)

    def paint_gutter(self, event):
        p = QPainter(self.gutter)
        p.fillRect(event.rect(), QColor(theme.c("EDITOR")))
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
                p.setPen(QColor(theme.c("TEXT") if number == cur else theme.c("FAINT")))
                p.drawText(0, top, w - 12, h, Qt.AlignRight | Qt.AlignVCenter, self._fmt_num(number + 1 + self.line_base))
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
        self._leave_zone()
        self.cursorStatus.emit()
        self._schedule_refresh()
        self.gutter.update()

    def _on_edit(self, pos, removed, added):
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

    def contextMenuEvent(self, e):
        menu = self.createStandardContextMenu()
        cur = self.cursorForPosition(e.pos())
        cur.select(QTextCursor.WordUnderCursor)
        word = cur.selectedText()
        if self.highlighter.spell_on and word and spellmod.speller.is_wrong(word) and not self.isReadOnly():
            first = menu.actions()[0] if menu.actions() else None
            sugg = spellmod.speller.suggestions(word)
            for s in sugg:
                a = QAction(s, menu)
                a.triggered.connect(lambda _=False, s=s, c=QTextCursor(cur): c.insertText(s))
                menu.insertAction(first, a)
            if not sugg:
                na = QAction("(no suggestions)", menu)
                na.setEnabled(False)
                menu.insertAction(first, na)
            add = QAction(f'Add "{word}" to dictionary', menu)
            add.triggered.connect(lambda: (spellmod.speller.add_word(word), self.highlighter.rehighlight()))
            ign = QAction("Ignore all", menu)
            ign.triggered.connect(lambda: (spellmod.speller.ignore(word), self.highlighter.rehighlight()))
            menu.insertAction(first, add)
            menu.insertAction(first, ign)
            menu.insertSeparator(first)
        menu.exec(e.globalPos())

    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        if self.isReadOnly():
            return super().keyPressEvent(e)
        if self._img_sel is not None and self._image_key(e):
            return
        if key == Qt.Key_Backspace and self._ac is not None and not mods:
            if self._undo_autocorrect():
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
        new = fn(text)
        cur.insertText(new)
        c = QTextCursor(self.document())
        c.setPosition(start)
        c.setPosition(start + len(new), QTextCursor.KeepAnchor)
        self.setTextCursor(c)

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
        return {"bold": ("<b>", "</b>") if html else ("**", "**"), "italic": ("<i>", "</i>") if html else ("*", "*"),
                "underline": ("<u>", "</u>")}[kind]

    def toggle_format(self, kind):
        """Bold / italic / underline: wraps the selection (or the word at the caret) in the marks, or removes them."""
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
        text = cur.selectedText().replace("\u2029", "\n")
        s, e = cur.selectionStart(), cur.selectionEnd()
        doc = self.document()
        outer = QTextCursor(doc)
        outer.setPosition(max(0, s - len(opening)))
        outer.setPosition(min(doc.characterCount() - 1, e + len(closing)), QTextCursor.KeepAnchor)
        around = outer.selectedText()
        cur.beginEditBlock()
        if len(text) >= len(opening) + len(closing) and text.startswith(opening) and text.endswith(closing):
            inner = text[len(opening):len(text) - len(closing)]
            cur.insertText(inner)
            start = s
        elif around.startswith(opening) and around.endswith(closing) and s >= len(opening):
            inner = text
            outer.insertText(inner)
            start = s - len(opening)
        else:
            inner = text
            cur.insertText(opening + inner + closing)
            start = s + len(opening)
        cur.endEditBlock()
        sel = QTextCursor(doc)
        sel.setPosition(start)
        sel.setPosition(start + len(inner), QTextCursor.KeepAnchor)
        self.setTextCursor(sel)
        return True

    SIZE_RX = re.compile(r'^<span style="font-size:\s*(\d+)px">(.*)</span>$', re.S)

    def _current_size_px(self):
        cur = self.textCursor()
        line = cur.block().text()
        col = cur.positionInBlock()
        for m in re.finditer(r'<span style="font-size:\s*(\d+)px">(.+?)</span>', line):
            if m.start() <= col <= m.end():
                return int(m.group(1))
        return round(self.font().pointSizeF() * 4 / 3)

    def set_text_size(self, px=None, delta=0):
        """Sets the size of the selected text (px) or changes it by `delta` px. px=0 removes the size mark."""
        if not self.format_supported() or self.isReadOnly():
            return False
        cur = self.textCursor()
        if not cur.hasSelection():
            cur.select(QTextCursor.WordUnderCursor)
            if not cur.hasSelection():
                return False
        base = self._current_size_px()
        text = cur.selectedText().replace("\u2029", "\n")
        s = cur.selectionStart()
        m = self.SIZE_RX.match(text)
        doc = self.document()
        if m is None:                       # the caret may sit inside a span without having selected its tags
            block = cur.block()
            for sm in re.finditer(r'<span style="font-size:\s*(\d+)px">(.+?)</span>', block.text()):
                a, b = block.position() + sm.start(), block.position() + sm.end()
                if a <= cur.selectionStart() and cur.selectionEnd() <= b:
                    cur.setPosition(a)
                    cur.setPosition(b, QTextCursor.KeepAnchor)
                    text = cur.selectedText()
                    m = self.SIZE_RX.match(text)
                    s = a
                    break
        inner = m.group(2) if m else text
        new = px if px is not None else max(6, min(80, base + delta))
        out = inner if new == 0 else f'<span style="font-size:{new}px">{inner}</span>'
        cur.beginEditBlock()
        cur.insertText(out)
        cur.endEditBlock()
        sel = QTextCursor(doc)
        sel.setPosition(s)
        sel.setPosition(s + len(out), QTextCursor.KeepAnchor)
        self.setTextCursor(sel)
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

    def _leave_zone(self):
        cur = self.textCursor()
        if cur.hasSelection() or self._in_zone_fix:
            return
        owner = self._zone_owner(cur.block())
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
            target = link
        self._in_zone_fix = True
        c = QTextCursor(target)
        if target is link:
            c.movePosition(QTextCursor.EndOfBlock)
        self.setTextCursor(c)
        self._in_zone_fix = False
        self._prev_block = c.blockNumber()

    def _image_at(self, pos):
        for rect, block in self._preview_rects:
            if rect.contains(pos):
                return block
        return None

    def mousePressEvent(self, e):
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
            self.zoomRequested.emit(1 if e.angleDelta().y() > 0 else -1)
            e.accept()
            return
        super().wheelEvent(e)

    # ---- pictures: paste, drop, hover preview ------------------------------------------------------------------
    def canInsertFromMimeData(self, src):
        return src.hasImage() or src.hasUrls() or src.hasText()

    def insertFromMimeData(self, src):
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
        scale = min(1.0, self.PREVIEW_MAX_W / max(1, w), self.PREVIEW_MAX_H / max(1, h))
        return int((h * scale) // max(1, self.fontMetrics().lineSpacing())) + 2

    def insert_image_ref(self, abs_path, w=None, h=None):
        if w is None:
            im = QImage(abs_path)
            w, h = im.width(), im.height()
        cur = self.textCursor()
        cur.beginEditBlock()
        if cur.positionInBlock() > 0 and cur.block().text().strip():
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
        cur_block = self.textCursor().block()
        for block, s, e, pm, blanks in self._visible_previews():
            if block == cur_block:
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
        previews = self._visible_previews()
        self._preview_rects = []
        if not previews:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        ls = self.fontMetrics().lineSpacing()
        cur_block = self.textCursor().block()
        for block, s, e2, pm, blanks in previews:
            geo = self.blockBoundingGeometry(block).translated(self.contentOffset())
            x = int(self.contentOffset().x() + self.document().documentMargin() + 2)
            y = int(geo.top()) if block != cur_block else int(geo.bottom()) + 2     # while the link is edited the picture sits below it
            w, h = self._preview_size(pm, blanks)
            p.drawPixmap(x, y + 2, pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            selected = block.blockNumber() == self._img_sel
            p.setPen(QPen(QColor(theme.c("ACCENT")), 2) if selected else QColor(theme.c("BORDER2")))
            p.setBrush(Qt.NoBrush)
            p.drawRect(x - 1, y + 1, w + 1, h + 1)
            self._preview_rects.append((QRect(x, y + 2, w, h), block))
        p.end()

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
