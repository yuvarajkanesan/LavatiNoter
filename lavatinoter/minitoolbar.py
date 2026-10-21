"""The small formatting box that sits on top of the right-click menu, like Word's mini toolbar: font, size, bigger / smaller,
clear formatting, bold / italic / underline, highlight and text colour, bullets, numbering, styles and a new comment."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QMenu, QToolButton, QVBoxLayout

from . import theme

HIGHLIGHTS = (("Yellow", "#fff176"), ("Bright green", "#a5f3a0"), ("Turquoise", "#8defe6"), ("Pink", "#f8a8d0"), ("Orange", "#ffcc80"),
              ("Light grey", "#d9dde3"), ("Light blue", "#a8d4ff"))
TEXT_COLORS = (("Red", "#d32f2f"), ("Orange", "#ef6c00"), ("Green", "#2e7d32"), ("Blue", "#1565c0"), ("Purple", "#6a1b9a"),
               ("Grey", "#6b7482"), ("Black", "#000000"))
FONTS = ("Segoe UI", "Calibri", "Aptos", "Arial", "Verdana", "Tahoma", "Times New Roman", "Georgia", "Consolas", "Courier New",
         "Cascadia Mono", "JetBrains Mono", "IBM Plex Sans")
SIZES_PT = (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 72)


def _swatch_icon(color, size=14):
    pm = QPixmap(size, size)
    pm.fill(QColor(color))
    return QIcon(pm)


def _icon_with_bar(name, color):
    """A toolbar icon with a bar of the chosen colour under it (Word shows the current highlight / text colour that way)."""
    base = theme.icon(name, theme.c("TEXT"), 18).pixmap(18, 18)
    pm = QPixmap(base.width(), base.height() + 4)
    pm.setDevicePixelRatio(base.devicePixelRatio())
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.drawPixmap(0, 0, base)
    p.fillRect(2, int(base.height() / base.devicePixelRatio()) + 1, 14, 3, QColor(color))
    p.end()
    return QIcon(pm)


class MiniToolbar(QFrame):
    def __init__(self, editor, menu):
        super().__init__(menu)
        self.ed = editor
        self.menu = menu
        self.setObjectName("miniToolbar")
        self.setStyleSheet(f"QFrame#miniToolbar {{ background: {theme.c('PANEL2')}; border: 1px solid {theme.c('BORDER2')}; border-radius: 8px; }}"
                           f"QToolButton {{ padding: 4px; border-radius: 5px; }} QToolButton:hover {{ background: {theme.c('HOVER')}; }}"
                           f"QToolButton:checked {{ background: {theme.c('SELECTED')}; }}")
        self.hl, self.fc = HIGHLIGHTS[0][1], TEXT_COLORS[0][1]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)
        r1, r2 = QHBoxLayout(), QHBoxLayout()
        r1.setSpacing(4)
        r2.setSpacing(2)
        # row 1: font, size, bigger, smaller, clear, styles, comment
        self.font_box = QComboBox()
        self.font_box.setMinimumWidth(130)
        have = set(QFontDatabase.families())
        self.font_box.addItem("Font", "")
        for f in FONTS:
            if f in have:
                self.font_box.addItem(f, f)
        self.font_box.addItem("(none: normal)", "-")
        self.font_box.activated.connect(self._font)
        r1.addWidget(self.font_box)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.setFixedWidth(62)
        self.size_box.addItems([str(s) for s in SIZES_PT])
        cur_pt = round(editor._current_size_px() * 72 / 96) if hasattr(editor, "_current_size_px") else 11
        self.size_box.setCurrentText(str(cur_pt))
        self.size_box.activated.connect(lambda _i: self._size())
        self.size_box.lineEdit().returnPressed.connect(self._size)
        r1.addWidget(self.size_box)
        r1.addWidget(self._btn("textup", "Bigger text", lambda: editor.set_text_size(delta=2)))
        r1.addWidget(self._btn("textdown", "Smaller text", lambda: editor.set_text_size(delta=-2)))
        r1.addWidget(self._btn("clearfmt", "Clear all formatting (Ctrl+Space)", editor.clear_format))
        r1.addStretch(1)
        styles = QToolButton()
        styles.setIcon(theme.icon("styles", theme.c("TEXT"), 20))
        styles.setText("Styles")
        styles.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        styles.setPopupMode(QToolButton.InstantPopup)
        sm = QMenu(styles)
        for name in editor.STYLES:
            sm.addAction(name, lambda _=False, n=name: self._do(lambda: editor.apply_style(n)))
        styles.setMenu(sm)
        r1.addWidget(styles)
        cm = QToolButton()
        cm.setIcon(theme.icon("comment", theme.c("TEXT"), 20))
        cm.setText("Comment")
        cm.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        cm.setToolTip("Comment out the selection (or put it in a comment)")
        cm.clicked.connect(lambda: self._do(editor.comment_selection))
        r1.addWidget(cm)
        # row 2: B I U, highlight, colour, lists
        for name, tip, kind in (("bold", "Bold (Ctrl+B)", "bold"), ("italic", "Italic (Ctrl+I)", "italic"), ("underline", "Underline (Ctrl+U)", "underline")):
            r2.addWidget(self._btn(name, tip, lambda k=kind: editor.toggle_format(k)))
        self.hl_btn = self._color_button("highlight", "Highlight colour", HIGHLIGHTS, "hl", editor.set_highlight)
        self.fc_btn = self._color_button("fontcolor", "Text colour", TEXT_COLORS, "fc", editor.set_text_color)
        r2.addWidget(self.hl_btn)
        r2.addWidget(self.fc_btn)
        r2.addWidget(self._btn("bullets", "Bulleted list", lambda: editor.toggle_list(False)))
        r2.addWidget(self._btn("numbering", "Numbered list", lambda: editor.toggle_list(True)))
        r2.addStretch(1)
        lay.addLayout(r1)
        lay.addLayout(r2)

    def _do(self, fn):
        fn()
        self.menu.close()

    def _btn(self, icon, tip, fn):
        b = QToolButton()
        b.setIcon(theme.icon(icon, theme.c("TEXT"), 18))
        b.setToolTip(tip)
        b.clicked.connect(lambda _=False: self._do(fn))
        return b

    def _color_button(self, icon, tip, colors, attr, apply):
        b = QToolButton()
        b.setIcon(_icon_with_bar(icon, getattr(self, attr)))
        b.setToolTip(tip + " (click to use the colour shown, the arrow lists more)")
        b.setPopupMode(QToolButton.MenuButtonPopup)
        m = QMenu(b)
        for name, col in colors:
            m.addAction(_swatch_icon(col), name, lambda _=False, c=col: self._pick(attr, icon, b, apply, c))
        m.addSeparator()
        m.addAction("No colour", lambda: self._do(lambda: apply(None)))
        b.setMenu(m)
        b.clicked.connect(lambda _=False: self._do(lambda: apply(getattr(self, attr))))
        return b

    def _pick(self, attr, icon, button, apply, color):
        setattr(self, attr, color)
        button.setIcon(_icon_with_bar(icon, color))
        self._do(lambda: apply(color))

    def _font(self, index):
        v = self.font_box.itemData(index)
        if v == "-":
            self._do(lambda: self.ed.set_font_family(None))
        elif v:
            self._do(lambda: self.ed.set_font_family(v))

    def _size(self):
        text = self.size_box.currentText().strip()
        if text.isdigit() and 4 <= int(text) <= 200:
            px = round(int(text) * 96 / 72)
            self._do(lambda: self.ed.set_text_size(px))
