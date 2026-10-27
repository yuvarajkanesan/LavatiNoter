"""Gives a window the custom title bar: frameless, draggable, resizable from its edges, with the caption buttons."""
import ctypes
import ctypes.wintypes
import sys

from PySide6.QtCore import QEvent, QPoint, Qt

from .titlebar import TitleBar

BORDER = 6
# (column, row) -> HTTOPLEFT 13, HTTOP 12, HTTOPRIGHT 14, HTLEFT 10, HTRIGHT 11, HTBOTTOMLEFT 16, HTBOTTOM 15, HTBOTTOMRIGHT 17
_HIT = {(0, 0): 13, (1, 0): 12, (2, 0): 14, (0, 1): 10, (2, 1): 11, (0, 2): 16, (1, 2): 15, (2, 2): 17}


class FramelessMixin:
    """Put first in the bases (before QMainWindow / QDialog) and call setup_frameless(name) once."""

    def setup_frameless(self, name):
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowMinMaxButtonsHint, True)
        tb = TitleBar(self)
        tb.set_name(name)
        tb.set_title(self.windowTitle())
        tb.minimize.connect(self.showMinimized)
        tb.toggleMaximize.connect(lambda: self.showNormal() if self.isMaximized() else self.showMaximized())
        tb.closeWindow.connect(self.close)
        tb.startMove.connect(self._start_move)
        self.windowTitleChanged.connect(tb.set_title)
        self.title_bar = tb
        return tb

    def _start_move(self):
        h = self.windowHandle()
        if h is not None:
            h.startSystemMove()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.set_maximized(self.isMaximized())

    def nativeEvent(self, event_type, message):
        if (sys.platform == "win32" and hasattr(self, "title_bar") and event_type == b"windows_generic_MSG"
                and not self.isMaximized() and not self.isFullScreen()):
            try:
                msg = ctypes.wintypes.MSG.from_address(int(message))
            except (TypeError, ValueError):
                return super().nativeEvent(event_type, message)
            if msg.message == 0x0084:                                  # WM_NCHITTEST
                x = ctypes.c_short(msg.lParam & 0xFFFF).value
                y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                dpr = self.devicePixelRatioF() or 1.0
                pos = self.mapFromGlobal(QPoint(int(x / dpr), int(y / dpr)))
                col = 0 if pos.x() < BORDER else 2 if pos.x() >= self.width() - BORDER else 1
                row = 0 if pos.y() < BORDER else 2 if pos.y() >= self.height() - BORDER else 1
                if (col, row) != (1, 1):
                    return True, _HIT[(col, row)]
        return super().nativeEvent(event_type, message)
