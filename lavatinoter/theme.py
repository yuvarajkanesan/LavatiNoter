"""Colours, fonts, painted icons and the application stylesheet."""
import os
import sys

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap)

from .util import resource, sub_dir

_DARK = dict(
    IS_DARK=True, BG="#0c1015", PANEL="#10151c", EDITOR="#11161d", PANEL2="#171d26", FIELD="#0b0f14",
    BORDER="#1d2430", BORDER2="#2a3342", TEXT="#d9dfeb", MUTED="#8d97aa", FAINT="#566073",
    ACCENT="#8ad95c", ACCENT_HOVER="#a2e67b", ON_ACCENT="#0d1a08", ACCENT_BG="#1d2c1a", RED="#ee6a50",
    BLUE="#5aa9ff", ORANGE="#f2a65a", HOVER="#18202b", SELECTED="#1e2733", LINE_HL="#151c26",
    SEL_BG="#2c4a6e", SMART_BG="#27421f", MARK_BG="#7a4a12", MARK_FG="#ffe7c4",
    SYN_KEYWORD="#f2a65a", SYN_STRING="#8fd18b", SYN_NUMBER="#67b0f5", SYN_COMMENT="#5d6b82",
    SYN_FUNC="#ead58e", SYN_DECOR="#b794f6", SYN_BUILTIN="#7fc7e8", SYN_TYPE="#e5c07b", SYN_TAG="#f2a65a",
    SYN_ATTR="#e9d58a", SYN_KEY="#7fc7e8", SYN_LITERAL="#c792ea", SYN_OP="#a9b4c7", SYN_ERROR="#ff7b72",
    SYN_WARN="#f2a65a", SYN_INFO="#7fc7e8")
_LIGHT = dict(
    IS_DARK=False, BG="#eceff3", PANEL="#f6f7f9", EDITOR="#ffffff", PANEL2="#e8ebf0", FIELD="#ffffff",
    BORDER="#d9dee6", BORDER2="#c3cad6", TEXT="#1c2330", MUTED="#5a6579", FAINT="#99a2b2",
    ACCENT="#3f9e1c", ACCENT_HOVER="#348516", ON_ACCENT="#ffffff", ACCENT_BG="#e3f3dc", RED="#d9482e",
    BLUE="#1f66d1", ORANGE="#b85d0c", HOVER="#e4e8ef", SELECTED="#dbe3f1", LINE_HL="#f1f4f8",
    SEL_BG="#b8d4f7", SMART_BG="#d6efc8", MARK_BG="#ffd9a1", MARK_FG="#3a2300",
    SYN_KEYWORD="#b85d0c", SYN_STRING="#2e7d32", SYN_NUMBER="#1560c2", SYN_COMMENT="#7b879b",
    SYN_FUNC="#8a6d00", SYN_DECOR="#7a4fd1", SYN_BUILTIN="#0b7a94", SYN_TYPE="#946000", SYN_TAG="#b85d0c",
    SYN_ATTR="#8a6d00", SYN_KEY="#0b7a94", SYN_LITERAL="#8a3fc4", SYN_OP="#485468", SYN_ERROR="#c62828",
    SYN_WARN="#b85d0c", SYN_INFO="#0b7a94")

def _variant(base, **kw):
    d = dict(base)
    d.update(kw)
    return d


_MONOKAI = _variant(
    _DARK, BG="#1b1c18", PANEL="#23241f", EDITOR="#272822", PANEL2="#2f302a", FIELD="#1f201b", BORDER="#38392f", BORDER2="#4a4b3f",
    TEXT="#f8f8f2", MUTED="#a6a68f", FAINT="#75715e", ACCENT="#a6e22e", ACCENT_HOVER="#bef25a", ON_ACCENT="#1b1c18",
    ACCENT_BG="#34401d", RED="#f92672", BLUE="#66d9ef", ORANGE="#fd971f", HOVER="#34352d", SELECTED="#3e3d32", LINE_HL="#2f302a",
    SEL_BG="#49483e", SMART_BG="#46512a", MARK_BG="#7a4a12", SYN_KEYWORD="#f92672", SYN_STRING="#e6db74", SYN_NUMBER="#ae81ff",
    SYN_COMMENT="#75715e", SYN_FUNC="#a6e22e", SYN_DECOR="#66d9ef", SYN_BUILTIN="#66d9ef", SYN_TYPE="#66d9ef", SYN_TAG="#f92672",
    SYN_ATTR="#a6e22e", SYN_KEY="#66d9ef", SYN_LITERAL="#ae81ff", SYN_OP="#f8f8f2")
_SOLAR_DARK = _variant(
    _DARK, BG="#00212b", PANEL="#002b36", EDITOR="#002b36", PANEL2="#073642", FIELD="#00252f", BORDER="#0a4250", BORDER2="#1b5766",
    TEXT="#93a1a1", MUTED="#839496", FAINT="#586e75", ACCENT="#2aa198", ACCENT_HOVER="#3dbab0", ON_ACCENT="#002b36",
    ACCENT_BG="#07424a", RED="#dc322f", BLUE="#268bd2", ORANGE="#cb4b16", HOVER="#0a3a46", SELECTED="#0d4654", LINE_HL="#06323e",
    SEL_BG="#164f5d", SMART_BG="#1a5a5e", MARK_BG="#7a4a12", SYN_KEYWORD="#859900", SYN_STRING="#2aa198", SYN_NUMBER="#d33682",
    SYN_COMMENT="#586e75", SYN_FUNC="#268bd2", SYN_DECOR="#6c71c4", SYN_BUILTIN="#b58900", SYN_TYPE="#b58900", SYN_TAG="#268bd2",
    SYN_ATTR="#93a1a1", SYN_KEY="#268bd2", SYN_LITERAL="#cb4b16", SYN_OP="#839496")
_SOLAR_LIGHT = _variant(
    _LIGHT, BG="#eee8d5", PANEL="#f5efdc", EDITOR="#fdf6e3", PANEL2="#e9e2cc", FIELD="#fdf6e3", BORDER="#ddd6c1", BORDER2="#c9c1a9",
    TEXT="#586e75", MUTED="#657b83", FAINT="#93a1a1", ACCENT="#2aa198", ACCENT_HOVER="#1f8a82", ON_ACCENT="#fdf6e3", ACCENT_BG="#d9ece6",
    RED="#dc322f", BLUE="#268bd2", ORANGE="#cb4b16", HOVER="#e6dfc8", SELECTED="#dcd5bd", LINE_HL="#f2ebd4", SEL_BG="#d5e6dd",
    SMART_BG="#dbe8cf", MARK_BG="#ffd9a1", SYN_KEYWORD="#859900", SYN_STRING="#2aa198", SYN_NUMBER="#d33682", SYN_COMMENT="#93a1a1",
    SYN_FUNC="#268bd2", SYN_DECOR="#6c71c4", SYN_BUILTIN="#b58900", SYN_TYPE="#b58900", SYN_TAG="#268bd2", SYN_ATTR="#657b83",
    SYN_KEY="#268bd2", SYN_LITERAL="#cb4b16", SYN_OP="#657b83")
_CONTRAST = _variant(
    _DARK, BG="#000000", PANEL="#000000", EDITOR="#000000", PANEL2="#0d0d0d", FIELD="#000000", BORDER="#6b6b6b", BORDER2="#9a9a9a",
    TEXT="#ffffff", MUTED="#e0e0e0", FAINT="#b0b0b0", ACCENT="#ffd400", ACCENT_HOVER="#ffe45c", ON_ACCENT="#000000", ACCENT_BG="#3a3000",
    RED="#ff6b6b", BLUE="#6cb6ff", ORANGE="#ffb347", HOVER="#1f1f1f", SELECTED="#2e2e2e", LINE_HL="#141414", SEL_BG="#0b4f8a",
    SMART_BG="#4d4400", MARK_BG="#8a5a00", MARK_FG="#ffffff", SYN_KEYWORD="#ffb347", SYN_STRING="#7dff9b", SYN_NUMBER="#6cb6ff",
    SYN_COMMENT="#b0b0b0", SYN_FUNC="#ffe45c", SYN_DECOR="#d8b4ff", SYN_BUILTIN="#8be9fd", SYN_TYPE="#ffe45c", SYN_TAG="#ffb347",
    SYN_ATTR="#ffe45c", SYN_KEY="#8be9fd", SYN_LITERAL="#d8b4ff", SYN_OP="#ffffff")
PALETTES = {"Dark": _DARK, "Light": _LIGHT, "Monokai": _MONOKAI, "Solarized Dark": _SOLAR_DARK, "Solarized Light": _SOLAR_LIGHT,
            "High Contrast": _CONTRAST}
THEME_CHOICES = list(PALETTES)
THEME_NAME = "Dark"

LOGO_PURPLE_1, LOGO_PURPLE_2, LOGO_DARK, LOGO_ORANGE = "#6D28D9", "#4C1D95", "#2A1160", "#FF7A59"


def c(key):
    """The colour called `key` in the active palette."""
    return PALETTES[THEME_NAME][key]


def is_dark():
    return PALETTES[THEME_NAME]["IS_DARK"]


def _mix(a, b, t):
    ca, cb = QColor(a), QColor(b)
    return QColor.fromRgbF(ca.redF() * t + cb.redF() * (1 - t), ca.greenF() * t + cb.greenF() * (1 - t),
                           ca.blueF() * t + cb.blueF() * (1 - t)).name()


# ---- fonts ------------------------------------------------------------------------------------------
_families = {}


def load_fonts():
    """Registers the bundled fonts (read by Python and handed to Qt as bytes, so non-ASCII install paths work)."""
    folder = resource("fonts")
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            if name.lower().endswith(".ttf"):
                try:
                    with open(os.path.join(folder, name), "rb") as f:
                        QFontDatabase.addApplicationFontFromData(QByteArray(f.read()))
                except OSError:
                    pass
    have = set(QFontDatabase.families())
    _families["ui"] = next((f for f in ("IBM Plex Sans", "Segoe UI", "Arial") if f in have), "Sans Serif")
    _families["mono"] = next((f for f in ("JetBrains Mono", "Cascadia Mono", "Consolas", "Courier New") if f in have),
                             "Monospace")


def ui_family():
    return _families.get("ui", "Segoe UI")


def set_mono_family(name):
    """A font chosen in Preferences (empty = the bundled JetBrains Mono)."""
    _families["mono_choice"] = name if name and name in set(QFontDatabase.families()) else ""


def mono_family():
    return _families.get("mono_choice") or _families.get("mono", "Consolas")


def mono(size=11):
    f = QFont(mono_family(), size)
    f.setStyleHint(QFont.Monospace)
    return f


# ---- painted icons -------------------------------------------------------------------------------------
def _pen(p, color, w=1.7):
    pen = QPen(QColor(color), w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)


def _poly(p, pts, close=False):
    path = QPainterPath()
    path.moveTo(*pts[0])
    for pt in pts[1:]:
        path.lineTo(*pt)
    if close:
        path.closeSubpath()
    p.drawPath(path)


def _page(p, folded=True):
    _poly(p, [(6, 3), (14, 3), (19, 8), (19, 21), (6, 21)], True)
    if folded:
        _poly(p, [(14, 3), (14, 8), (19, 8)])


def _ic_new(p):
    _page(p)
    p.drawLine(12, 12, 12, 17)
    p.drawLine(9.5, 14.5, 14.5, 14.5)


def _ic_open(p):
    _poly(p, [(3, 7), (3, 19), (18, 19), (21, 11), (8, 11), (6, 19)])
    _poly(p, [(3, 7), (3, 5), (9, 5), (11, 7), (17, 7), (17, 11)])


def _ic_save(p):
    _poly(p, [(4, 4), (17, 4), (20, 7), (20, 20), (4, 20)], True)
    _poly(p, [(8, 4), (8, 9), (15, 9), (15, 4)])
    _poly(p, [(7, 20), (7, 14), (17, 14), (17, 20)])


def _ic_saveall(p):
    _poly(p, [(3, 6), (13, 6), (16, 9), (16, 19), (3, 19)], True)
    _poly(p, [(6, 6), (6, 10), (11, 10), (11, 6)])
    _poly(p, [(16, 3), (21, 3), (21, 14), (18, 17)])


def _ic_close(p):
    p.drawLine(6, 6, 18, 18)
    p.drawLine(18, 6, 6, 18)


def _ic_cut(p):
    p.drawEllipse(QRectF(4, 14, 5, 5))
    p.drawEllipse(QRectF(15, 14, 5, 5))
    p.drawLine(7, 14, 15, 4)
    p.drawLine(17, 14, 9, 4)


def _ic_copy(p):
    p.drawRoundedRect(QRectF(9, 9, 11, 11), 2, 2)
    _poly(p, [(5, 15), (5, 5), (15, 5)])


def _ic_paste(p):
    p.drawRoundedRect(QRectF(5, 5, 14, 16), 2, 2)
    p.drawRoundedRect(QRectF(9, 3, 6, 4), 1, 1)
    p.drawLine(9, 12, 15, 12)
    p.drawLine(9, 16, 13, 16)


def _ic_pasteimage(p):
    """A clipboard with a small picture on it: pasting a picture, not importing one."""
    p.drawRoundedRect(QRectF(4, 5, 16, 17), 2.5, 2.5)
    p.drawRoundedRect(QRectF(8.5, 2.5, 7, 4), 1.2, 1.2)
    p.drawRoundedRect(QRectF(7, 10, 10, 8), 1.2, 1.2)
    p.drawEllipse(QRectF(9, 11.6, 2, 2))
    _poly(p, [(7.4, 17.6), (10.6, 14.6), (12.6, 16.4), (14, 15.2), (16.6, 17.6)])


def _ic_undo(p):
    _poly(p, [(9, 6), (4, 11), (9, 16)])
    path = QPainterPath()
    path.moveTo(4, 11)
    path.lineTo(14, 11)
    path.cubicTo(18, 11, 20, 13, 20, 16)
    path.cubicTo(20, 19, 18, 20, 15, 20)
    p.drawPath(path)


def _ic_redo(p):
    _poly(p, [(15, 6), (20, 11), (15, 16)])
    path = QPainterPath()
    path.moveTo(20, 11)
    path.lineTo(10, 11)
    path.cubicTo(6, 11, 4, 13, 4, 16)
    path.cubicTo(4, 19, 6, 20, 9, 20)
    p.drawPath(path)


def _ic_find(p):
    p.drawEllipse(QRectF(4, 4, 11, 11))
    p.drawLine(13, 13, 20, 20)


def _ic_replace(p):
    _poly(p, [(5, 9), (19, 9), (15, 5)])
    _poly(p, [(19, 15), (5, 15), (9, 19)])


def _ic_zoomin(p):
    _ic_find(p)
    p.drawLine(9.5, 7.5, 9.5, 11.5)
    p.drawLine(7.5, 9.5, 11.5, 9.5)


def _ic_zoomout(p):
    _ic_find(p)
    p.drawLine(7.5, 9.5, 11.5, 9.5)


def _ic_wrap(p):
    p.drawLine(4, 6, 20, 6)
    path = QPainterPath()
    path.moveTo(4, 12)
    path.lineTo(16, 12)
    path.cubicTo(20, 12, 20, 18, 16, 18)
    path.lineTo(12, 18)
    p.drawPath(path)
    _poly(p, [(14.5, 15.5), (11.5, 18), (14.5, 20.5)])


def _ic_pilcrow(p):
    path = QPainterPath()
    path.moveTo(15, 4)
    path.lineTo(11, 4)
    path.cubicTo(7, 4, 7, 12, 11, 12)
    path.lineTo(15, 12)
    p.drawPath(path)
    p.drawLine(15, 4, 15, 20)
    p.drawLine(11, 4, 11, 20)


def _ic_bars(p):
    for x, y in ((5, 8), (10, 4), (15, 11), (20, 6)):
        p.drawLine(x, y, x, 20)


def _ic_folder(p):
    _poly(p, [(3, 6), (3, 19), (21, 19), (21, 8), (11, 8), (9, 6)], True)


def _ic_folder_open(p):
    _poly(p, [(3, 19), (3, 6), (9, 6), (11, 8), (19, 8), (19, 11)])
    _poly(p, [(3, 19), (6, 11), (22, 11), (19, 19)], True)


def _ic_file(p):
    _page(p)


def _ic_image(p):
    p.drawRoundedRect(QRectF(3.5, 5, 17, 14), 2, 2)
    p.drawEllipse(QRectF(7, 8, 3, 3))
    _poly(p, [(4, 18), (10, 13), (14, 16), (17, 13), (20, 16)])


def _ic_chev_r(p):
    _poly(p, [(9, 6), (15, 12), (9, 18)])


def _ic_chev_d(p):
    _poly(p, [(6, 9), (12, 15), (18, 9)])


def _ic_plus(p):
    p.drawLine(12, 5, 12, 19)
    p.drawLine(5, 12, 19, 12)


def _ic_bookmark(p):
    _poly(p, [(7, 4), (17, 4), (17, 20), (12, 16), (7, 20)], True)


def _ic_gear(p):
    p.drawEllipse(QRectF(8.5, 8.5, 7, 7))
    for i in range(8):
        p.save()
        p.translate(12, 12)
        p.rotate(i * 45)
        p.drawLine(0, -7, 0, -10)
        p.restore()


def _glyph(p, text, size=18, bold=False, italic=False, underline=False, dx=0.0):
    f = QFont(ui_family())
    f.setPixelSize(size)
    f.setBold(bold)
    f.setItalic(italic)
    f.setUnderline(underline)
    p.setFont(f)
    p.drawText(QRectF(dx, 0, 24, 24), Qt.AlignCenter, text)


def _ic_bold(p):
    _glyph(p, "B", 19, bold=True)


def _ic_italic(p):
    _glyph(p, "I", 19, bold=True, italic=True)


def _ic_underline(p):
    _glyph(p, "U", 17, bold=True)
    p.drawLine(6, 21.5, 18, 21.5)


def _size_icon(p, up):
    f = QFont(ui_family())
    f.setPixelSize(19)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(1, 2, 16, 20), Qt.AlignCenter, "A")
    p.save()
    p.setBrush(p.pen().color())
    p.setPen(Qt.NoPen)
    tri = QPainterPath()
    if up:
        tri.moveTo(15.5, 14.5)
        tri.lineTo(23, 14.5)
        tri.lineTo(19.25, 8)
    else:
        tri.moveTo(15.5, 9.5)
        tri.lineTo(23, 9.5)
        tri.lineTo(19.25, 16)
    tri.closeSubpath()
    p.drawPath(tri)
    p.restore()


def _ic_textup(p):
    _size_icon(p, True)


def _ic_textdown(p):
    _size_icon(p, False)


def _ic_highlight(p):
    """A marker pen."""
    _poly(p, [(5, 15), (13, 4), (19, 10), (11, 20), (7, 20)], True)
    p.drawLine(5, 15, 11, 20)
    p.drawLine(10.5, 8, 16, 13.5)


def _ic_fontcolor(p):
    _glyph(p, "A", 17, bold=True, dx=0)


def _ic_bullets(p):
    pen = p.pen()
    p.setPen(Qt.NoPen)
    p.setBrush(pen.color())
    for y in (6, 12, 18):
        p.drawEllipse(QRectF(2.8, y - 1.9, 3.8, 3.8))
    p.setPen(pen)
    for y in (6, 12, 18):
        p.drawLine(10, y, 21, y)


def _ic_numbering(p):
    for y in (6, 12, 18):
        p.drawLine(11, y, 21, y)
    p.save()
    pen = QPen(p.pen().color(), 1.5)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    _poly(p, [(3.2, 4.6), (5.2, 3.2), (5.2, 8.6)])
    y = 12
    _poly(p, [(3.2, y - 1.8), (4.2, y - 3), (6.2, y - 3), (7.0, y - 1.8), (7.0, y - 0.6), (3.2, y + 3), (7.2, y + 3)])
    y = 18
    _poly(p, [(3.2, y - 3), (7.0, y - 3), (5.2, y - 0.4), (6.6, y + 0.4), (7.0, y + 1.6), (6.2, y + 3), (4.2, y + 3), (3.2, y + 2)])
    p.restore()


def _ic_clearfmt(p):
    _glyph(p, "A", 16, dx=-2)
    _poly(p, [(14, 17), (17, 11), (22, 14), (19, 20), (15, 20)], True)


def _ic_comment(p):
    p.drawRoundedRect(QRectF(3.5, 4, 17, 12.5), 2.5, 2.5)
    _poly(p, [(8, 16.5), (8, 21), (13, 16.5)])
    p.drawLine(12, 7.5, 12, 13)
    p.drawLine(9.3, 10.2, 14.7, 10.2)


def _ic_styles(p):
    _glyph(p, "A", 20, dx=-1)
    _poly(p, [(16.5, 8), (19, 11), (21.5, 8)])


def _ic_multilevel(p):
    pen = p.pen()
    p.setPen(Qt.NoPen)
    p.setBrush(pen.color())
    for x, y in ((3, 5), (7, 12), (11, 19)):
        p.drawEllipse(QRectF(x - 1.6, y - 1.6, 3.2, 3.2))
    p.setPen(pen)
    for x, y in ((8, 5), (12, 12), (16, 19)):
        p.drawLine(x, y, 21, y)


def _ic_indentinc(p):
    for y in (5, 19):
        p.drawLine(4, y, 20, y)
    for y in (10, 14):
        p.drawLine(11, y, 20, y)
    _poly(p, [(4, 9), (8, 12), (4, 15)])


def _ic_indentdec(p):
    for y in (5, 19):
        p.drawLine(4, y, 20, y)
    for y in (10, 14):
        p.drawLine(11, y, 20, y)
    _poly(p, [(8, 9), (4, 12), (8, 15)])


def _ic_sort(p):
    p.save()
    f = QFont(ui_family())
    f.setPixelSize(11)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QRectF(2, 2.5, 11, 10), Qt.AlignCenter, "A")
    p.drawText(QRectF(2, 12, 11, 10), Qt.AlignCenter, "Z")
    p.restore()
    p.drawLine(18, 4.5, 18, 19)
    _poly(p, [(15, 15.5), (18, 19.5), (21, 15.5)])


def _ic_align(p, mode):
    widths = (16, 11, 16, 8) if mode != "justify" else (16, 16, 16, 16)
    for k, y in enumerate((6, 10.5, 15, 19.5)):
        w = widths[k]
        x = 4 if mode in ("left", "justify") else 20 - w if mode == "right" else 12 - w / 2
        p.drawLine(x, y, x + w, y)


def _ic_alignleft(p):
    _ic_align(p, "left")


def _ic_aligncenter(p):
    _ic_align(p, "center")


def _ic_alignright(p):
    _ic_align(p, "right")


def _ic_alignjustify(p):
    _ic_align(p, "justify")


def _ic_linespacing(p):
    for y in (6, 12, 18):
        p.drawLine(11, y, 20, y)
    p.drawLine(5, 5, 5, 19)
    _poly(p, [(2.5, 8), (5, 5), (7.5, 8)])
    _poly(p, [(2.5, 16), (5, 19), (7.5, 16)])


def _ic_shading(p):
    _poly(p, [(5, 13), (12, 4), (19, 11), (12, 20), (8, 20)], True)
    p.drawLine(5, 13, 10, 18)
    p.setBrush(p.pen().color())
    p.drawRect(QRectF(4, 21, 16, 2.4))


def _ic_borders(p):
    p.drawRect(QRectF(4.5, 4.5, 15, 15))
    p.drawLine(12, 4.5, 12, 19.5)
    p.drawLine(4.5, 12, 19.5, 12)


def _ic_minimap(p):
    """A document outline with a bar down the side: the Map / functions / images panel."""
    p.drawRoundedRect(QRectF(3.5, 4, 17, 16), 2.5, 2.5)
    p.drawLine(15, 4.5, 15, 19.5)
    p.drawLine(6.5, 8.5, 12, 8.5)
    p.drawLine(6.5, 12, 11, 12)
    p.drawLine(6.5, 15.5, 12, 15.5)
    p.setBrush(p.pen().color())
    p.drawRect(QRectF(16.8, 7, 2.4, 5))


def _ic_list(p):
    for y in (6, 12, 18):
        p.drawLine(9, y, 20, y)
        p.drawPoint(4.5, y)


def _ic_map(p):
    for y, x2 in ((5, 20), (9, 14), (13, 18), (17, 12)):
        p.drawLine(5, y, x2, y)


_ICONS = {n[4:]: f for n, f in globals().items() if n.startswith("_ic_")}


def icon(name, color=None, size=20, dropdown=False):
    """A painted icon; dropdown=True shrinks it and adds a small arrow in the corner (for buttons that open a menu)."""
    color = color or c("MUTED")
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 24.0, size / 24.0)
    _pen(p, color)
    if dropdown:
        p.save()
        p.translate(0.3, 0.3)
        p.scale(0.76, 0.76)
        _ICONS.get(name, _ic_file)(p)
        p.restore()
        p.drawPolyline([QPointF(19.4, 18.6), QPointF(21.6, 20.8), QPointF(23.8, 18.6)])
    else:
        _ICONS.get(name, _ic_file)(p)
    p.end()
    return QIcon(pm)


def dot_icon(color, size=10):
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(1.5, 1.5, size - 3, size - 3))
    p.end()
    return QIcon(pm)


# ---- application icon + Lavati branding ------------------------------------------------------------------
def logo_pixmap(size):
    """The LavatiNoter icon: a dark rounded tile, lines of text in green and white, and a text cursor."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#1b2430"))
    g.setColorAt(1, QColor("#0b0f14"))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    r = size * 0.22
    p.drawRoundedRect(QRectF(0, 0, size, size), r, r)
    p.setBrush(Qt.NoBrush)
    edge = QPen(QColor("#2f3b4d"), max(1.0, size * 0.012))
    p.setPen(edge)
    p.drawRoundedRect(QRectF(size * 0.006, size * 0.006, size * 0.988, size * 0.988), r, r)
    bar = size * 0.085
    p.setPen(Qt.NoPen)
    rows = ((0.21, 0.30, "#8ad95c"), (0.36, 0.52, "#e8edf5"), (0.51, 0.40, "#e8edf5"), (0.66, 0.30, "#6f7d93"))
    x0 = size * 0.20
    for y, w, col in rows:
        p.setBrush(QColor(col))
        p.drawRoundedRect(QRectF(x0, size * y, size * w, bar), bar / 2, bar / 2)
    p.setBrush(QColor("#8ad95c"))
    p.drawRoundedRect(QRectF(x0 + size * 0.34, size * 0.645, size * 0.055, size * 0.125), size * 0.02, size * 0.02)
    p.end()
    return pm


def app_icon():
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(logo_pixmap(s))
    return ic


def save_ico(path):
    """Writes a multi-size .ico (PNG-compressed entries, which Windows reads fine) without needing Pillow."""
    import struct
    from PySide6.QtCore import QBuffer, QIODevice
    sizes = (16, 24, 32, 48, 64, 128, 256)
    blobs = []
    for s in sizes:
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        logo_pixmap(s).save(buf, "PNG")
        blobs.append(bytes(buf.data()))
    head = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, blob in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", 0 if s >= 256 else s, 0 if s >= 256 else s, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(head + entries + b"".join(blobs))


def _chevron_path(x, y, w, h):
    path = QPainterPath()
    path.moveTo(x, y)
    path.lineTo(x + w / 2, y + h)
    path.lineTo(x + w, y)
    return path


def lavati_mark_pixmap(size):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor(LOGO_PURPLE_1))
    g.setColorAt(1, QColor(LOGO_PURPLE_2))
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    r = size * 0.27
    p.drawRoundedRect(QRectF(0, 0, size, size), r, r)
    pen = QPen(QColor("#ffffff"), size * 0.095)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawPath(_chevron_path(size * 0.255, size * 0.27, size * 0.49, size * 0.30))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(LOGO_ORANGE))
    bar = size * 0.075
    p.drawRoundedRect(QRectF(size * 0.31, size * 0.69, size * 0.38, bar), bar / 2, bar / 2)
    p.end()
    return pm


def lavati_wordmark_pixmap(width, tagline=True, dark_text=LOGO_DARK):
    """'lavati' with the chevron as its v, plus the SOFTWARES line."""
    from PySide6.QtGui import QFontMetricsF
    h = int(width * (0.42 if tagline else 0.30))
    pm = QPixmap(width, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    f = QFont(ui_family(), 10)
    f.setWeight(QFont.Bold)
    f.setPixelSize(int(width * 0.26))
    fm = QFontMetricsF(f)
    vw = fm.horizontalAdvance("v") * 0.92
    total = fm.horizontalAdvance("la") + vw + fm.horizontalAdvance("ati")
    x = (width - total) / 2
    base = width * 0.22
    p.setFont(f)
    p.setPen(QColor(dark_text))
    p.drawText(QPointF(x, base), "la")
    x += fm.horizontalAdvance("la")
    cap = fm.xHeight()
    pen = QPen(QColor(LOGO_PURPLE_1), width * 0.04)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.drawPath(_chevron_path(x + vw * 0.1, base - cap * 0.95, vw * 0.8, cap * 0.78))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(LOGO_ORANGE))
    bh = width * 0.028
    p.drawRoundedRect(QRectF(x + vw * 0.22, base + width * 0.012, vw * 0.56, bh), bh / 2, bh / 2)
    x += vw
    p.setPen(QColor(dark_text))
    p.drawText(QPointF(x, base), "ati")
    if tagline:
        f2 = QFont(ui_family(), 10)
        f2.setWeight(QFont.Medium)
        f2.setPixelSize(int(width * 0.055))
        f2.setLetterSpacing(QFont.AbsoluteSpacing, width * 0.022)
        p.setFont(f2)
        p.setPen(QColor("#5B4A8A"))
        p.drawText(QRectF(0, base + width * 0.07, width, width * 0.1), Qt.AlignHCenter | Qt.AlignTop, "SOFTWARES")
    p.end()
    return pm


# ---- stylesheet -------------------------------------------------------------------------------------------
def _png(name, painter_fn, size=14):
    """Renders a small indicator image into the cache folder and returns its path for use in url()."""
    path = os.path.join(sub_dir("cache"), f"{name}.png").replace("\\", "/")
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    painter_fn(p, size)
    p.end()
    pm.save(path, "PNG")
    return path


def _box(fill, border, tick=None, radio=False):
    def draw(p, s):
        rect = QRectF(0.75, 0.75, s - 1.5, s - 1.5)
        p.setPen(QPen(QColor(border), 1.3))
        p.setBrush(QColor(fill))
        if radio:
            p.drawEllipse(rect)
        else:
            p.drawRoundedRect(rect, 3, 3)
        if tick:
            if radio:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(tick))
                p.drawEllipse(QRectF(s * 0.3, s * 0.3, s * 0.4, s * 0.4))
            else:
                _pen(p, tick, 1.8)
                _poly(p, [(s * 0.25, s * 0.52), (s * 0.43, s * 0.7), (s * 0.76, s * 0.3)])
    return draw


def apply(name="Dark"):
    global THEME_NAME
    THEME_NAME = name if name in PALETTES else "Dark"


def qss():
    k = PALETTES[THEME_NAME]
    tag = THEME_NAME.lower()
    box = _png(f"box-{tag}", _box(k["FIELD"], k["BORDER2"]))
    box_on = _png(f"box-on-{tag}", _box(k["ACCENT"], k["ACCENT"], k["ON_ACCENT"]))
    radio = _png(f"radio-{tag}", _box(k["FIELD"], k["BORDER2"], radio=True), 14)
    radio_on = _png(f"radio-on-{tag}", _box(k["FIELD"], k["ACCENT"], k["ACCENT"], radio=True), 14)
    chev = _png(f"chev-{tag}", lambda p, s: (_pen(p, k["MUTED"], 1.6), _poly(p, [(3.5, 5), (7, 9), (10.5, 5)])))
    return f"""
QMainWindow, QDialog {{ background: {k['BG']}; color: {k['TEXT']}; }}
QWidget {{ color: {k['TEXT']}; }}
QToolTip {{ background: {k['PANEL2']}; color: {k['TEXT']}; border: 1px solid {k['BORDER2']}; padding: 4px 6px; }}
QMenuBar {{ background: {k['BG']}; color: {k['TEXT']}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 9px; background: transparent; border-radius: 4px; }}
QMenuBar::item:selected {{ background: {k['HOVER']}; }}
QMenu {{ background: {k['PANEL2']}; color: {k['TEXT']}; border: 1px solid {k['BORDER2']}; padding: 5px; border-radius: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {k['SELECTED']}; }}
QMenu::item:disabled {{ color: {k['FAINT']}; }}
QMenu::separator {{ height: 1px; background: {k['BORDER']}; margin: 4px 6px; }}
QToolBar {{ background: {k['BG']}; border: none; border-bottom: 1px solid {k['BORDER']}; padding: 4px 8px; spacing: 2px; }}
QToolBar::separator {{ width: 1px; background: {k['BORDER']}; margin: 4px 7px; }}
QToolButton {{ background: transparent; border: none; border-radius: 6px; padding: 6px; }}
QToolButton:hover {{ background: {k['HOVER']}; }}
QToolButton:pressed, QToolButton:checked {{ background: {k['SELECTED']}; }}
QToolButton:disabled {{ opacity: 0.4; }}
QStatusBar {{ background: {k['BG']}; color: {k['MUTED']}; border-top: 1px solid {k['BORDER']}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ padding: 3px 12px; color: {k['MUTED']}; }}
QStatusBar QLabel[sep="true"] {{ border-left: 1px solid {k['BORDER']}; }}
QTabWidget::pane {{ border: none; border-top: 1px solid {k['BORDER']}; background: {k['EDITOR']}; }}
QTabBar {{ background: {k['BG']}; qproperty-drawBase: 0; }}
QTabBar::tab {{ background: transparent; color: {k['MUTED']}; padding: 9px 12px 9px 12px; border-top: 2px solid transparent;
    border-right: 1px solid {k['BORDER']}; min-width: 60px; }}
QTabBar::tab:hover {{ background: {k['HOVER']}; color: {k['TEXT']}; }}
QTabBar::tab:selected {{ background: {k['PANEL']}; color: {k['TEXT']}; border-top: 2px solid {k['ACCENT']}; }}
QTabBar QToolButton {{ background: {k['BG']}; border: none; }}
QPlainTextEdit, QTextEdit {{ background: {k['EDITOR']}; color: {k['TEXT']}; border: none; selection-background-color: {k['SEL_BG']};
    selection-color: {k['TEXT']}; }}
QLineEdit, QComboBox, QSpinBox {{ background: {k['FIELD']}; color: {k['TEXT']}; border: 1px solid {k['BORDER2']}; border-radius: 6px;
    padding: 5px 8px; selection-background-color: {k['SEL_BG']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {k['ACCENT']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({chev}); width: 14px; height: 14px; }}
QComboBox QAbstractItemView {{ background: {k['PANEL2']}; color: {k['TEXT']}; border: 1px solid {k['BORDER2']};
    selection-background-color: {k['SELECTED']}; outline: 0; }}
QPushButton {{ background: {k['PANEL2']}; color: {k['TEXT']}; border: 1px solid {k['BORDER2']}; border-radius: 6px; padding: 6px 14px; }}
QPushButton:hover {{ background: {k['HOVER']}; border-color: {k['FAINT']}; }}
QPushButton:pressed {{ background: {k['SELECTED']}; }}
QPushButton:disabled {{ color: {k['FAINT']}; }}
QPushButton[primary="true"] {{ background: {k['ACCENT']}; color: {k['ON_ACCENT']}; border: 1px solid {k['ACCENT']}; font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: {k['ACCENT_HOVER']}; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 14px; height: 14px; }}
QCheckBox::indicator:unchecked {{ image: url({box}); }}
QCheckBox::indicator:checked {{ image: url({box_on}); }}
QRadioButton::indicator:unchecked {{ image: url({radio}); }}
QRadioButton::indicator:checked {{ image: url({radio_on}); }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {k['BORDER2']}; border-radius: 4px; min-height: 32px; margin: 2px 2px; }}
QScrollBar::handle:vertical:hover {{ background: {k['FAINT']}; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {k['BORDER2']}; border-radius: 4px; min-width: 32px; margin: 2px 2px; }}
QScrollBar::handle:horizontal:hover {{ background: {k['FAINT']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QDockWidget {{ color: {k['TEXT']}; }}
QDockWidget > QWidget {{ background: {k['PANEL']}; }}
QMainWindow::separator {{ background: {k['BORDER']}; width: 1px; height: 1px; }}
QTreeView, QListWidget, QListView, QTreeWidget {{ background: {k['PANEL']}; color: {k['TEXT']}; border: none; outline: 0; }}
QTreeView::item, QListView::item {{ padding: 4px 4px; border-radius: 4px; }}
QTreeView::item:hover, QListView::item:hover {{ background: {k['HOVER']}; }}
QTreeView::item:selected, QListView::item:selected {{ background: {k['SELECTED']}; color: {k['TEXT']}; }}
QHeaderView::section {{ background: {k['PANEL']}; color: {k['MUTED']}; border: none; padding: 4px; }}
QLabel[muted="true"] {{ color: {k['MUTED']}; }}
QLabel[heading="true"] {{ color: {k['MUTED']}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QFrame[card="true"] {{ background: {k['PANEL2']}; border: 1px solid {k['BORDER2']}; border-radius: 10px; }}
QFrame[card="true"] QLabel {{ background: transparent; }}
QFrame[banner="true"] {{ background: {k['ACCENT_BG']}; border: none; border-bottom: 1px solid {k['BORDER']}; }}
QFrame[banner="true"] QLabel {{ background: transparent; }}
QProgressBar {{ background: {k['BORDER']}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {k['ACCENT']}; border-radius: 3px; }}
QSlider::groove:horizontal {{ background: {k['BORDER2']}; height: 4px; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {k['ACCENT']}; width: 14px; margin: -5px 0; border-radius: 7px; }}
QPushButton[seg] {{ border-radius: 0; border: 1px solid {k['BORDER2']}; margin-left: -1px; padding: 6px 10px; }}
QPushButton[seg]:checked {{ background: {k['ACCENT']}; color: {k['ON_ACCENT']}; border-color: {k['ACCENT']}; font-weight: 600; }}
QPushButton[seg="first"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
QPushButton[seg="last"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; }}
QMessageBox {{ background: {k['PANEL']}; }}
"""


def menu_qss():
    k = PALETTES[THEME_NAME]
    return (f"QMenu {{ background: {k['PANEL2']}; color: {k['TEXT']}; border: 1px solid {k['BORDER2']}; padding: 5px; border-radius: 6px; }} "
            f"QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 4px; background: transparent; }} "
            f"QMenu::item:selected {{ background: {k['SELECTED']}; }} QMenu::item:disabled {{ color: {k['FAINT']}; }} "
            f"QMenu::separator {{ height: 1px; background: {k['BORDER']}; margin: 4px 6px; }}")


def set_titlebar(widget):
    """Dark / light caption and a caption colour that matches the header on Windows 11. A no-op elsewhere."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi

        def attr(code, value):
            v = ctypes.c_int(value)
            dwm.DwmSetWindowAttribute(hwnd, code, ctypes.byref(v), ctypes.sizeof(v))

        def colorref(hex_color):
            col = QColor(hex_color)
            return col.red() | (col.green() << 8) | (col.blue() << 16)
        attr(20, 1 if is_dark() else 0)             # DWMWA_USE_IMMERSIVE_DARK_MODE
        attr(35, colorref(c("BG")))                  # DWMWA_CAPTION_COLOR (Windows 11)
        attr(36, colorref(c("TEXT")))                # DWMWA_TEXT_COLOR
        attr(34, colorref(c("BORDER")))              # DWMWA_BORDER_COLOR
    except (OSError, AttributeError, ValueError):
        pass


def install_titlebar_filter(app):
    """Styles every top-level window and popup menu as it is shown."""
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QMenu, QWidget

    class Filter(QObject):
        def eventFilter(self, obj, event):
            if event.type() == QEvent.Show:
                if isinstance(obj, QMenu) and not obj.property("_styled"):
                    obj.setProperty("_styled", True)
                    obj.setStyleSheet(menu_qss())
                elif isinstance(obj, QWidget) and obj.isWindow() and not isinstance(obj, QMenu):
                    set_titlebar(obj)
            return False
    f = Filter(app)
    app.installEventFilter(f)
    app._titlebar_filter = f
