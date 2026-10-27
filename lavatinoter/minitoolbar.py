"""The small formatting box that sits on top of the right-click menu, like Word's mini toolbar: font, size, bigger / smaller,
clear formatting, bold / italic / underline, highlight and text colour, bullets, numbering, styles and a new comment."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QMenu, QToolButton

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


def _arrow_png():
    """A small chevron saved once to a temp file so the stylesheet can use it as the combo arrow."""
    import os
    import tempfile
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainter, QPen, QPixmap, QColor
    col = theme.c("MUTED")
    path = os.path.join(tempfile.gettempdir(), "lavatinoter_arrow_%s.png" % col.lstrip("#"))
    if not os.path.exists(path):
        pm = QPixmap(20, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(col), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPointF(4, 7), QPointF(10, 13), QPointF(16, 7)])
        p.end()
        pm.save(path)
    return path.replace("\\", "/")


class MiniToolbar(QFrame):
    def __init__(self, editor, menu):
        super().__init__(menu)
        self.ed = editor
        self.menu = menu
        self.setObjectName("miniToolbar")
        self.setStyleSheet(f"QFrame#miniToolbar {{ background: transparent; border: none; }}"
                           f"QToolButton {{ padding: 3px; border-radius: 6px; }} QToolButton:hover {{ background: {theme.c('HOVER')}; }}"
                           f"QToolButton:checked {{ background: {theme.c('SELECTED')}; }} QToolButton::menu-indicator {{ image: none; width: 0; }}"
                           f"QToolButton::menu-button {{ width: 10px; border: none; }}"
                           f"QComboBox {{ padding: 3px 8px; border: 1px solid {theme.c('BORDER')}; border-radius: 8px; min-height: 22px; background: {theme.c('PANEL')}; }}"
                           f"QComboBox::drop-down {{ border: none; width: 22px; }}"
                           f"QComboBox::down-arrow {{ image: url({_arrow_png()}); width: 10px; height: 10px; }}")
        self.hl, self.fc = HIGHLIGHTS[0][1], TEXT_COLORS[0][1]
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(4)
        # one row: font, size | B I U, highlight, colour | bullets, numbering | styles, comment
        self.font_box = QComboBox()
        self.font_box.setFixedWidth(116)
        have = set(QFontDatabase.families())
        self.font_box.addItem("Font", "")
        for f in FONTS:
            if f in have:
                self.font_box.addItem(f, f)
        self.font_box.addItem("(none: normal)", "-")
        self.font_box.activated.connect(self._font)
        lay.addWidget(self.font_box)
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.setFixedWidth(64)
        self.size_box.addItems([str(s) for s in SIZES_PT])
        cur_pt = round(editor._current_size_px() * 72 / 96) if hasattr(editor, "_current_size_px") else 11
        self.size_box.setCurrentText(str(cur_pt))
        self.size_box.activated.connect(lambda _i: self._size())
        self.size_box.lineEdit().returnPressed.connect(self._size)
        lay.addWidget(self.size_box)
        lay.addWidget(self._sep())
        for name, tip, kind in (("bold", "Bold (Ctrl+B)", "bold"), ("italic", "Italic (Ctrl+I)", "italic"), ("underline", "Underline (Ctrl+U)", "underline")):
            lay.addWidget(self._btn(name, tip, lambda k=kind: editor.toggle_format(k)))
        self.hl_btn = self._color_button("highlight", "Highlight colour", HIGHLIGHTS, "hl", editor.set_highlight)
        self.fc_btn = self._color_button("fontcolor", "Text colour", TEXT_COLORS, "fc", editor.set_text_color)
        lay.addWidget(self.hl_btn)
        lay.addWidget(self.fc_btn)
        lay.addWidget(self._sep())
        lay.addWidget(self._btn("bullets", "Bulleted list", lambda: editor.toggle_list(False)))
        lay.addWidget(self._btn("numbering", "Numbered list", lambda: editor.toggle_list(True)))
        lay.addWidget(self._sep())
        styles = QToolButton()
        styles.setIcon(theme.icon("styles", theme.c("TEXT"), 18))
        styles.setToolTip("Styles")
        styles.setPopupMode(QToolButton.InstantPopup)
        sm = QMenu(styles)
        theme.round_menu(sm)
        for name in editor.STYLES:
            sm.addAction(name, lambda _=False, n=name: self._do(lambda: editor.apply_style(n)))
        styles.setMenu(sm)
        lay.addWidget(styles)
        cm = QToolButton()
        cm.setIcon(theme.icon("comment", theme.c("TEXT"), 18))
        cm.setToolTip("Comment out the selection (or put it in a comment)")
        cm.clicked.connect(lambda: self._do(editor.comment_selection))
        lay.addWidget(cm)

    def _sep(self):
        line = QFrame()
        line.setFixedSize(1, 16)
        line.setStyleSheet(f"background: {theme.c('BORDER')}; border: none;")
        return line

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
        b.setToolTip(tip + " (click to use the colour shown, right-click or hold for more)")
        b.setPopupMode(QToolButton.DelayedPopup)
        b.setContextMenuPolicy(Qt.CustomContextMenu)
        m = QMenu(b)
        theme.round_menu(m)
        for name, col in colors:
            m.addAction(_swatch_icon(col), name, lambda _=False, c=col: self._pick(attr, icon, b, apply, c))
        m.addSeparator()
        m.addAction("No colour", lambda: self._do(lambda: apply(None)))
        b.setMenu(m)
        b.customContextMenuRequested.connect(lambda pos, b=b, m=m: m.popup(b.mapToGlobal(pos)))
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
