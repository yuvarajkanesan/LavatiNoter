"""The main window: menus, toolbar, tabs, docks, status bar, file handling and session restore."""
import json
import os
import sys
import time

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QDesktopServices, QGuiApplication, QKeySequence,
                           QTextCursor)
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QSpinBox,
                               QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget, QComboBox, QLineEdit)

from . import APP_NAME, VERSION, session, theme, util
from .editor import CodeEditor
from .finddialog import FindDialog
from .highlighter import LANGS, PLAIN, lang_by_name, lang_for_path
from .largefile import GoToPanel, LargeFileView
from .panels import FunctionsPanel, ImagePreview, ImagesPanel, MinimapWidget, ResultsPanel, WorkspacePanel, reveal_in_explorer

MB = 1024 * 1024


class PreferencesDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        form.setContentsMargins(20, 20, 20, 16)
        form.setVerticalSpacing(12)
        self.theme = QComboBox()
        self.theme.addItems(theme.THEME_CHOICES)
        self.theme.setCurrentText(settings["theme"])
        self.size = QSpinBox()
        self.size.setRange(6, 40)
        self.size.setValue(settings["font_size"])
        self.tab = QSpinBox()
        self.tab.setRange(1, 16)
        self.tab.setValue(settings["tab_width"])
        self.spaces = QCheckBox("Insert spaces when I press Tab")
        self.spaces.setChecked(settings["use_spaces"])
        self.large = QSpinBox()
        self.large.setRange(1, 4096)
        self.large.setSuffix(" MB")
        self.large.setValue(settings["large_file_mb"])
        self.images = QLineEdit(settings["image_folder"])
        self.images.setToolTip("Pasted pictures are saved in this folder next to the document")
        self.restore = QCheckBox("Reopen my files and keep unsaved text when I quit")
        self.restore.setChecked(settings["restore_session"])
        form.addRow("Theme", self.theme)
        form.addRow("Editor font size", self.size)
        form.addRow("Tab width", self.tab)
        form.addRow("", self.spaces)
        form.addRow("Open files larger than", self.large)
        form.addRow("Folder for pasted pictures", self.images)
        form.addRow("", self.restore)
        note = QLabel("Files above the size limit open in large file mode: read-only, instant, and limited to a small window of memory.")
        note.setWordWrap(True)
        note.setProperty("muted", True)
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setProperty("primary", True)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def apply_to(self, s):
        s["theme"] = self.theme.currentText()
        s["font_size"] = self.size.value()
        s["tab_width"] = self.tab.value()
        s["use_spaces"] = self.spaces.isChecked()
        s["large_file_mb"] = self.large.value()
        name = self.images.text().strip().strip("\\/")
        s["image_folder"] = name or "images"
        s["restore_session"] = self.restore.isChecked()


class MainWindow(QMainWindow):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._icon_actions = []              # (action, icon name) pairs, rebuilt when the theme changes
        self._untitled = 0
        self._flash_timer = QTimer(self, singleShot=True, interval=4000)
        self._flash_timer.timeout.connect(self._unflash)
        self.setWindowIcon(theme.app_icon())
        self.setAcceptDrops(True)
        self.resize(1280, 800)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(False)
        self.tabs.setElideMode(Qt.ElideRight)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.tabs.tabBar().tabMoved.connect(lambda *_: self.refresh_documents())
        self.tabs.tabBar().setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.tabBar().customContextMenuRequested.connect(self._tab_menu)
        self.tabs.tabBar().tabBarDoubleClicked.connect(lambda i: self.new_file() if i < 0 else None)
        plus = QToolButton()
        plus.setIcon(theme.icon("plus", theme.c("MUTED"), 18))
        plus.setToolTip("New document (Ctrl+N)")
        plus.clicked.connect(lambda _=False: self.new_file())
        self.plus = plus
        self.tabs.setCornerWidget(plus, Qt.TopRightCorner)
        self.setCentralWidget(self.tabs)

        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_status()
        self.find_dialog = FindDialog(self)
        self._autosave = QTimer(self, singleShot=True, interval=2500)      # like Notepad++: unsaved work is backed up as you type
        self._autosave.timeout.connect(self._backup_session)
        self._content_timer = QTimer(self, singleShot=True, interval=350)
        self._content_timer.timeout.connect(self._content_settled)
        self._apply_theme(settings["theme"], first=True)
        if settings["geometry"]:
            try:
                self.restoreGeometry(QByteArray.fromBase64(settings["geometry"].encode("ascii")))
            except (ValueError, TypeError):
                pass
        self.show_workspace.setChecked(settings["show_workspace"])
        self.workspace_dock.setVisible(settings["show_workspace"])
        self.map_dock.setVisible(settings["show_minimap"])
        if settings["workspace"] and os.path.isdir(settings["workspace"]):
            self.workspace.set_root(settings["workspace"])
        QApplication.instance().applicationStateChanged.connect(self._app_state)

    # ---- construction ---------------------------------------------------------------------------------------------
    def _dock(self, title, widget, area, name):
        d = QDockWidget(title, self)
        d.setObjectName(name)
        d.setWidget(widget)
        d.setTitleBarWidget(QWidget())               # panels draw their own header
        d.setFeatures(QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(area, d)
        return d

    def _build_docks(self):
        self.workspace = WorkspacePanel()
        self.workspace.openFile.connect(self.open_path)
        self.workspace.findInFolder.connect(lambda d: self.find_dialog.show_tab(2, directory=d))
        self.workspace.folderChanged.connect(self._workspace_changed)
        self.workspace_dock = self._dock("Workspace", self.workspace, Qt.LeftDockWidgetArea, "workspace")
        self.workspace_dock.setMinimumWidth(180)
        self.resizeDocks([self.workspace_dock], [270], Qt.Horizontal)

        self.minimap = MinimapWidget()
        self.functions = FunctionsPanel()
        self.functions.jump.connect(lambda ln: self._jump_line(ln))
        self.images = ImagesPanel()
        self.images.jump.connect(lambda ln: self._jump_line(ln))
        self.images.pasteRequested.connect(self.paste_image)
        self.side = QTabWidget()
        self.side.setObjectName("side")
        self.side.setDocumentMode(True)
        self.side.addTab(self.minimap, "Map")
        self.side.addTab(self.functions, "Functions")
        self.side.addTab(self.images, "Images")
        self.map_dock = self._dock("Panels", self.side, Qt.RightDockWidgetArea, "side")
        self.map_dock.setMinimumWidth(170)
        self.resizeDocks([self.map_dock], [230], Qt.Horizontal)

        self.results = ResultsPanel()
        self.results.openHit.connect(self.open_hit)
        self.results.closeRequested.connect(lambda: self.bottom_dock.hide())
        self.results.docs.itemActivated.connect(lambda it, *_: self.tabs.setCurrentIndex(it.data(0, Qt.UserRole)))
        self.bottom_dock = self._dock("Results", self.results, Qt.BottomDockWidgetArea, "results")
        self.bottom_dock.setMinimumHeight(120)
        self.resizeDocks([self.bottom_dock], [230], Qt.Vertical)
        self.bottom_dock.hide()
        self.bottom_dock.visibilityChanged.connect(lambda v: self.view_results.setChecked(v))

    def show_results_dock(self):
        self.bottom_dock.show()
        self.view_results.setChecked(True)

    def act(self, text, slot=None, shortcut=None, icon=None, checkable=False, checked=False, tip=None):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut) if isinstance(shortcut, str) else QKeySequence(shortcut))
            a.setShortcutContext(Qt.WindowShortcut)
        a.setCheckable(checkable)
        if checkable:
            a.setChecked(checked)
        if slot:
            if checkable:
                a.toggled.connect(slot)
            else:
                a.triggered.connect(lambda _=False, fn=slot: fn())      # never pass the 'checked' flag on
        if tip:
            a.setToolTip(tip)
        if icon:
            self._icon_actions.append((a, icon))
        return a

    def _build_actions(self):
        A = self.act
        S = QKeySequence
        self.a_new = A("New", self.new_file, S.New, "new", tip="New (Ctrl+N)")
        self.a_open = A("Open...", self.open_dialog, S.Open, "open", tip="Open (Ctrl+O)")
        self.a_open_folder = A("Open Folder as Workspace...", lambda: self.workspace.choose_folder(), "Ctrl+Shift+O")
        self.a_save = A("Save", lambda: self.save(), S.Save, "save", tip="Save (Ctrl+S)")
        self.a_save_as = A("Save As...", lambda: self.save_as(), "Ctrl+Alt+S")
        self.a_save_all = A("Save All", self.save_all, "Ctrl+Shift+S", "saveall", tip="Save all (Ctrl+Shift+S)")
        self.a_close = A("Close", lambda: self.close_tab(self.current()), "Ctrl+W", "close", tip="Close (Ctrl+W)")
        self.a_close_all = A("Close All", self.close_all, "Ctrl+Shift+W")
        self.a_reload = A("Reload from Disk", self.reload_current, "Ctrl+Shift+R")
        self.a_reveal = A("Show in Explorer", self.reveal_current)
        self.a_copy_path = A("Copy Full Path", self.copy_path)
        self.a_exit = A("Exit", self.close, "Alt+F4")

        self.a_undo = A("Undo", lambda: self._ed_call("undo"), S.Undo, "undo")
        self.a_redo = A("Redo", lambda: self._ed_call("redo"), S.Redo, "redo")
        self.a_cut = A("Cut", lambda: self._ed_call("cut"), S.Cut, "cut")
        self.a_copy = A("Copy", lambda: self._ed_call("copy"), S.Copy, "copy")
        self.a_paste = A("Paste", lambda: self._ed_call("paste"), S.Paste, "paste")
        self.a_paste_image = A("Paste Image from Clipboard", self.paste_image, "Ctrl+Shift+V", "pasteimage",
                               tip="Paste a picture: it is saved next to the document and linked in (Ctrl+Shift+V)")
        self.a_select_all = A("Select All", lambda: self._ed_call("selectAll"), S.SelectAll)
        self.a_dup = A("Duplicate Line", lambda: self._ed_call("duplicate_line"), "Ctrl+D")
        self.a_del_line = A("Delete Line", lambda: self._ed_call("delete_line"), "Ctrl+L")
        self.a_up = A("Move Line Up", lambda: self._ed_call("move_lines", True), "Ctrl+Shift+Up")
        self.a_down = A("Move Line Down", lambda: self._ed_call("move_lines", False), "Ctrl+Shift+Down")
        self.a_comment = A("Toggle Comment", lambda: self._ed_call("toggle_comment"), "Ctrl+/")
        self.a_indent = A("Indent", lambda: self._ed_call("indent_selection"), "Ctrl+]")
        self.a_outdent = A("Outdent", lambda: self._ed_call("indent_selection", True), "Ctrl+[")
        self.a_upper = A("UPPERCASE", lambda: self._transform(str.upper), "Ctrl+Alt+U")
        self.a_lower = A("lowercase", lambda: self._transform(str.lower), "Ctrl+Alt+L")
        self.a_sort_asc = A("Sort Lines Ascending", lambda: self._transform_lines(lambda ls: sorted(ls, key=str.lower)))
        self.a_sort_desc = A("Sort Lines Descending", lambda: self._transform_lines(lambda ls: sorted(ls, key=str.lower, reverse=True)))
        self.a_unique = A("Remove Duplicate Lines", lambda: self._transform_lines(lambda ls: list(dict.fromkeys(ls))))
        self.a_blank = A("Remove Empty Lines", lambda: self._transform_lines(lambda ls: [l for l in ls if l.strip()]))
        self.a_trim = A("Trim Trailing Whitespace", lambda: self._transform_lines(lambda ls: [l.rstrip() for l in ls]))
        self.a_bm_toggle = A("Toggle Bookmark", lambda: self._ed_call("toggle_bookmark"), "Ctrl+F2")
        self.a_bm_next = A("Next Bookmark", lambda: self._bookmark(True), "F2")
        self.a_bm_prev = A("Previous Bookmark", lambda: self._bookmark(False), "Shift+F2")
        self.a_bm_clear = A("Clear All Bookmarks", lambda: self._ed_call("clear_bookmarks"))

        self.a_bold = A("Bold", lambda: self._format("bold"), "Ctrl+B", "bold", tip="Bold (Ctrl+B)")
        self.a_italic = A("Italic", lambda: self._format("italic"), "Ctrl+I", "italic", tip="Italic (Ctrl+I)")
        self.a_underline = A("Underline", lambda: self._format("underline"), "Ctrl+U", "underline", tip="Underline (Ctrl+U)")
        self.a_size_up = A("Increase Text Size", lambda: self._size(delta=2), "Ctrl+Alt+Up", "textup", tip="Larger text (Ctrl+Alt+Up)")
        self.a_size_down = A("Decrease Text Size", lambda: self._size(delta=-2), "Ctrl+Alt+Down", "textdown", tip="Smaller text (Ctrl+Alt+Down)")
        self.a_find = A("Find...", lambda: self.find_dialog.show_tab(0, self._selected_text()), S.Find, "find", tip="Find (Ctrl+F)")
        self.a_replace = A("Replace...", lambda: self.find_dialog.show_tab(1, self._selected_text()), "Ctrl+H", "replace", tip="Replace (Ctrl+H)")
        self.a_find_files = A("Find in Files...", lambda: self.find_dialog.show_tab(2, self._selected_text()), "Ctrl+Shift+F")
        self.a_mark = A("Mark...", lambda: self.find_dialog.show_tab(3, self._selected_text()), "Ctrl+M")
        self.a_find_next = A("Find Next", lambda: self._find_step(False), "F3")
        self.a_find_prev = A("Find Previous", lambda: self._find_step(True), "Shift+F3")
        self.a_goto = A("Go to...", self.goto, "Ctrl+G")
        self.a_bracket = A("Go to Matching Bracket", self.goto_bracket, "Ctrl+Shift+B")

        self.view_wrap = A("Word Wrap", self.set_wrap, None, "wrap", True, self.settings["word_wrap"], "Word wrap")
        self.view_marks = A("Show Formatting Marks (** _ <u> ...)", self.set_show_marks, None, None, True, False,
                            "Normally the marks behind bold, italic, underline and size are hidden")
        self.view_ws = A("Show Whitespace and Tabs", self.set_whitespace, None, "pilcrow", True, self.settings["show_whitespace"],
                         "Show whitespace and tabs")
        self.view_map = A("Panels on the Right (Map, Functions, Images)", self.toggle_map, None, "map", True, self.settings["show_minimap"],
                          "Map, functions and images")
        self.show_workspace = A("Workspace Folder", self.toggle_workspace, None, "folder", True, self.settings["show_workspace"])
        self.view_results = A("Results Panel", self.toggle_results, "Ctrl+Shift+J", None, True, False)
        self.a_zoom_in = A("Zoom In", lambda: self.zoom(1), "Ctrl+=", "zoomin", tip="Zoom in (Ctrl+wheel)")
        self.a_zoom_in2 = A("Zoom In", lambda: self.zoom(1), "Ctrl++")
        self.a_zoom_out = A("Zoom Out", lambda: self.zoom(-1), "Ctrl+-", "zoomout", tip="Zoom out (Ctrl+wheel)")
        self.a_zoom_reset = A("Restore Default Zoom", lambda: self.set_font_size(11), "Ctrl+0")
        self.a_full = A("Full Screen", self.toggle_full, "F11", None, True)
        self.a_spell = A("Spell Check", self.set_spell, None, None, True, self.settings["spellcheck"])
        self.a_autocorrect = A("Auto-correct Misspelled Words", self.set_spell, None, None, True, self.settings["autocorrect"],
                               "Fixes obvious typos in text and Markdown when you finish a word. Backspace right after takes it back.")
        self.a_complete = A("Word Autocomplete", self.set_complete, None, None, True, self.settings["autocomplete"],
                            "Suggests words from this document, the language's keywords and common English words while you type")
        self.a_prefs = A("Preferences...", self.preferences, "Ctrl+,")
        self.a_next_tab = A("Next Tab", lambda: self.step_tab(1), "Ctrl+PgDown")
        self.a_prev_tab = A("Previous Tab", lambda: self.step_tab(-1), "Ctrl+PgUp")
        self.a_next_tab2 = A("Next Tab", lambda: self.step_tab(1), "Ctrl+Tab")
        self.a_prev_tab2 = A("Previous Tab", lambda: self.step_tab(-1), "Ctrl+Shift+Tab")
        self.a_about = A("About LavatiNoter", self.about)
        self.a_data = A("Open Settings Folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(util.data_dir())))
        self.a_diag = A("Copy Diagnostic Info", self.copy_diagnostics)
        for a in (self.a_zoom_in2, self.a_next_tab2, self.a_prev_tab2, self.a_next_tab, self.a_prev_tab):
            self.addAction(a)

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu("File")
        for a in (self.a_new, self.a_open, self.a_open_folder):
            m.addAction(a)
        self.recent_menu = m.addMenu("Open Recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        for a in (self.a_save, self.a_save_as, self.a_save_all, self.a_reload):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_reveal)
        m.addAction(self.a_copy_path)
        m.addSeparator()
        m.addAction(self.a_close)
        m.addAction(self.a_close_all)
        m.addSeparator()
        m.addAction(self.a_exit)

        m = mb.addMenu("Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_cut, self.a_copy, self.a_paste, self.a_paste_image,
                  self.a_select_all, None, self.a_dup, self.a_del_line, self.a_up, self.a_down, None, self.a_comment,
                  self.a_indent, self.a_outdent):
            m.addSeparator() if a is None else m.addAction(a)
        c = m.addMenu("Convert Case")
        c.addAction(self.a_upper)
        c.addAction(self.a_lower)
        ln = m.addMenu("Line Operations")
        for a in (self.a_sort_asc, self.a_sort_desc, self.a_unique, self.a_blank, self.a_trim):
            ln.addAction(a)
        bm = m.addMenu("Bookmarks")
        for a in (self.a_bm_toggle, self.a_bm_next, self.a_bm_prev, self.a_bm_clear):
            bm.addAction(a)
        eol = m.addMenu("EOL Conversion")
        self.eol_group = QActionGroup(self)
        self.eol_actions = {}
        for label, val in util.EOLS.items():
            a = QAction(label, self, checkable=True)
            a.triggered.connect(lambda _=False, v=val: self.set_eol(v))
            self.eol_group.addAction(a)
            eol.addAction(a)
            self.eol_actions[val] = a

        m = mb.addMenu("Format")
        for a in (self.a_bold, self.a_italic, self.a_underline, None, self.a_size_up, self.a_size_down):
            m.addSeparator() if a is None else m.addAction(a)
        sz = m.addMenu("Text Size")
        for px in (10, 12, 14, 18, 24, 32, 48):
            sz.addAction(f"{px} px", lambda _=False, v=px: self._size(px=v))
        sz.addSeparator()
        sz.addAction("Normal (remove size)", lambda: self._size(px=0))
        m.addSeparator()
        m.addAction("About formatting marks", self._format_help)

        m = mb.addMenu("Search")
        for a in (self.a_find, self.a_find_next, self.a_find_prev, self.a_replace, self.a_find_files, self.a_mark, None,
                  self.a_goto, self.a_bracket):
            m.addSeparator() if a is None else m.addAction(a)

        m = mb.addMenu("View")
        for a in (self.view_wrap, self.view_ws, self.view_marks, None, self.show_workspace, self.view_map, self.view_results, None,
                  self.a_zoom_in, self.a_zoom_out, self.a_zoom_reset, None, self.a_full):
            m.addSeparator() if a is None else m.addAction(a)

        m = mb.addMenu("Encoding")
        self.enc_group = QActionGroup(self)
        self.enc_actions = {}
        sub = m.addMenu("Reopen with Encoding")
        for label in util.ENCODINGS:
            sub.addAction(label, lambda l=label: self.reopen_with(l))
        m.addSeparator()
        for label in util.ENCODINGS:
            a = QAction(label, self, checkable=True)
            a.triggered.connect(lambda _=False, l=label: self.set_encoding(l))
            self.enc_group.addAction(a)
            m.addAction(a)
            self.enc_actions[label] = a

        m = mb.addMenu("Language")
        self.lang_group = QActionGroup(self)
        self.lang_actions = {}
        for l in LANGS:
            a = QAction(l.name, self, checkable=True)
            a.triggered.connect(lambda _=False, name=l.name: self.set_language(name))
            self.lang_group.addAction(a)
            m.addAction(a)
            self.lang_actions[l.name] = a

        m = mb.addMenu("Settings")
        m.addAction(self.a_prefs)
        m.addAction(self.a_spell)
        m.addAction(self.a_autocorrect)
        m.addAction(self.a_complete)
        th = m.addMenu("Theme")
        self.theme_group = QActionGroup(self)
        for name in theme.THEME_CHOICES:
            a = QAction(name, self, checkable=True)
            a.setChecked(name == self.settings["theme"])
            a.triggered.connect(lambda _=False, n=name: self.switch_theme(n))
            self.theme_group.addAction(a)
            th.addAction(a)
        m.addAction(self.a_data)

        m = mb.addMenu("Tools")
        m.addAction(self.a_paste_image)
        m.addAction(self.a_find_files)
        m.addAction(self.a_reveal)

        self.window_menu = mb.addMenu("Window")
        self.window_menu.aboutToShow.connect(self._fill_window_menu)

        m = mb.addMenu("?")
        m.addAction(self.a_about)
        m.addAction(self.a_diag)

    def _build_toolbar(self):
        tb = self.addToolBar("Main")
        tb.setObjectName("main-toolbar")
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        for a in (self.a_new, self.a_open, self.a_save, self.a_save_all, self.a_close, None, self.a_cut, self.a_copy,
                  self.a_paste, self.a_paste_image, None, self.a_undo, self.a_redo, None, self.a_bold, self.a_italic,
                  self.a_underline, self.a_size_up, self.a_size_down, None, self.a_find, self.a_replace, None,
                  self.a_zoom_in, self.a_zoom_out, None, self.view_wrap, self.view_ws, self.view_map):
            tb.addSeparator() if a is None else tb.addAction(a)
        self.toolbar = tb

    def _build_status(self):
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.lbl_lang = QLabel("Plain text")
        sb.addWidget(self.lbl_lang, 1)

        def lab(text=""):
            l = QLabel(text)
            l.setProperty("sep", True)
            sb.addPermanentWidget(l)
            return l
        self.lbl_len = lab()
        self.lbl_pos = lab()
        self.lbl_eol = lab()
        self.lbl_enc = lab()
        self.lbl_mode = lab("INS")
        self.lbl_ram = lab()
        self.lbl_ram.hide()
        self.lbl_eol.setCursor(Qt.PointingHandCursor)
        self.lbl_eol.mousePressEvent = lambda e: self._eol_popup()
        self.lbl_enc.setCursor(Qt.PointingHandCursor)
        self.lbl_enc.mousePressEvent = lambda e: self._enc_popup()
        self.lbl_lang.setCursor(Qt.PointingHandCursor)
        self.lbl_lang.mousePressEvent = lambda e: self._lang_popup()
        self._ram_timer = QTimer(self, interval=3000)
        self._ram_timer.timeout.connect(self._update_ram)

    # ---- theme -------------------------------------------------------------------------------------------------------
    def _apply_theme(self, name, first=False):
        theme.apply(name)
        self.settings["theme"] = theme.THEME_NAME
        QApplication.instance().setStyleSheet(theme.qss())
        k = theme.c
        self.side.setStyleSheet(
            f"QTabWidget#side QTabBar::tab {{ border-top: 2px solid transparent; border-bottom: 2px solid transparent; "
            f"border-right: none; padding: 9px 14px; min-width: 40px; background: transparent; }} "
            f"QTabWidget#side QTabBar::tab:selected {{ border-bottom: 2px solid {k('ACCENT')}; background: transparent; color: {k('TEXT')}; }}")
        for a, icon in self._icon_actions:
            a.setIcon(theme.icon(icon, k("MUTED")))
        self.plus.setIcon(theme.icon("plus", k("MUTED"), 18))
        self.results.close_btn.setIcon(theme.icon("close", k("MUTED"), 16))
        theme.set_titlebar(self)
        for page in self.all_tabs():
            if hasattr(page, "restyle"):
                page.restyle()
            elif hasattr(page, "editor"):
                page.editor.restyle()
        self.workspace.restyle()
        self.minimap.update()
        for i in range(self.tabs.count()):
            self._decorate_tab(self.tabs.widget(i))

    def switch_theme(self, name):
        self._apply_theme(name)
        self.settings.save()

    # ---- tabs ---------------------------------------------------------------------------------------------------------
    def current(self):
        return self.tabs.currentWidget()

    def all_tabs(self):
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def editor_of(self, page):
        """The CodeEditor behind a tab (the inner window editor for large files)."""
        if page is None:
            return None
        return page.editor if getattr(page, "is_large", False) else page

    def tab_title(self, page):
        return os.path.basename(page.path) if page.path else page.title

    def tab_key(self, page):
        return page.path or page.title

    def _modified(self, page):
        return (not page.is_large) and page.document().isModified()

    def modified_paths(self):
        return {os.path.normcase(p.path) for p in self.all_tabs() if p.path and self._modified(p)}

    def _decorate_tab(self, page):
        i = self.tabs.indexOf(page)
        if i < 0:
            return
        mod = self._modified(page)
        self.tabs.setTabIcon(i, theme.dot_icon(theme.c("RED") if mod else theme.c("FAINT"), 10))
        self.tabs.setTabText(i, self.tab_title(page))
        self.tabs.setTabToolTip(i, page.path or page.title)
        box = QWidget()
        hl = QHBoxLayout(box)
        hl.setContentsMargins(4, 0, 0, 0)
        hl.setSpacing(6)
        if page.is_large:
            badge = QLabel(util.human_size(page.size).replace(" ", ""))
            badge.setStyleSheet(f"background: {theme.c('ACCENT_BG')}; color: {theme.c('ACCENT')}; border-radius: 8px; "
                                f"padding: 1px 7px; font-size: 11px; font-weight: 600;")
            hl.addWidget(badge)
        close = QToolButton()
        close.setIcon(theme.icon("close", theme.c("MUTED"), 14))
        close.setIconSize(QSize(12, 12))
        close.setAutoRaise(True)
        close.setToolTip("Close (Ctrl+W)")
        close.clicked.connect(lambda _=False, p=page: self.close_tab(p))
        close.setStyleSheet("QToolButton { padding: 3px; border-radius: 4px; }")
        hl.addWidget(close)
        self.tabs.tabBar().setTabButton(i, QTabBar.RightSide, box)

    def _add_page(self, page, activate=True):
        i = self.tabs.addTab(page, "")
        self._decorate_tab(page)
        if activate:
            self.tabs.setCurrentIndex(i)
        self.refresh_documents()
        return page

    def _make_editor(self):
        ed = CodeEditor()
        ed.title = ""
        ed.mtime = None
        ed.apply_font(self.settings["font_size"])
        ed.set_tab_width(self.settings["tab_width"])
        ed.use_spaces = self.settings["use_spaces"]
        ed.image_folder = self.settings["image_folder"]
        ed.set_word_wrap(self.settings["word_wrap"])
        ed.set_show_whitespace(self.settings["show_whitespace"])
        ed.set_spellcheck(self.settings["spellcheck"], self.settings["autocorrect"])
        ed.autocomplete_on = self.settings["autocomplete"]
        ed.zoomRequested.connect(self.zoom)
        ed.filesDropped.connect(self.open_paths)
        ed.cursorStatus.connect(self._update_status)
        ed.document().modificationChanged.connect(lambda _=False, p=ed: self._modification_changed(p))
        ed.document().contentsChanged.connect(self._content_timer.start)
        ed.imagePasted.connect(self._image_pasted)
        ed.imageActivated.connect(lambda path: ImagePreview(path, self).exec())
        return ed

    def _modification_changed(self, page):
        self._autosave.start()
        self._decorate_tab(page)
        if page is self.current():
            self._update_title()

    def new_file(self, text="", title=None, language=None):
        self._untitled += 1
        ed = self._make_editor()
        ed.title = title or f"new {self._untitled}"
        ed.setPlainText(text)
        ed.document().setModified(bool(text) and title is not None)
        if language:
            ed.set_language(language)
        self._add_page(ed)
        ed.setFocus()
        return ed

    def close_tab(self, page, force=False):
        if page is None:
            return True
        if not force and self._modified(page) and not self.settings["restore_session"]:
            r = QMessageBox.question(self, "Unsaved changes", f'Save changes to "{self.tab_title(page)}"?',
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save and not self.save(page):
                return False
        elif not force and self._modified(page):
            r = QMessageBox.question(self, "Unsaved changes", f'"{self.tab_title(page)}" has unsaved changes.\n\nClose it and discard them?',
                                     QMessageBox.Discard | QMessageBox.Save | QMessageBox.Cancel, QMessageBox.Save)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.Save and not self.save(page):
                return False
        i = self.tabs.indexOf(page)
        self.tabs.removeTab(i)
        if page.is_large:
            page.close_file()
        page.deleteLater()
        if self.tabs.count() == 0:
            self.new_file()
        self.refresh_documents()
        return True

    def close_all(self):
        for page in list(self.all_tabs()):
            if not self.close_tab(page):
                return False
        return True

    def step_tab(self, d):
        n = self.tabs.count()
        if n:
            self.tabs.setCurrentIndex((self.tabs.currentIndex() + d) % n)

    def _tab_menu(self, pos):
        i = self.tabs.tabBar().tabAt(pos)
        if i < 0:
            return
        page = self.tabs.widget(i)
        m = QMenu(self)
        m.addAction("Close", lambda: self.close_tab(page))
        m.addAction("Close Others", lambda: [self.close_tab(p) for p in self.all_tabs() if p is not page])
        m.addAction("Close All", self.close_all)
        m.addSeparator()
        if not page.is_large:
            m.addAction("Save", lambda: self.save(page))
        if page.path:
            m.addAction("Show in Explorer", lambda: reveal_in_explorer(page.path))
            m.addAction("Copy Full Path", lambda: QGuiApplication.clipboard().setText(os.path.normpath(page.path)))
        m.exec(self.tabs.tabBar().mapToGlobal(pos))

    def refresh_documents(self):
        self._autosave.start()
        rows = []
        for p in self.all_tabs():
            size = util.human_size(p.size) if p.is_large else util.human_size(p.length())
            lang = p.lang.name if not p.is_large else "Large file"
            rows.append((self.tab_title(p) + (" *" if self._modified(p) else ""), os.path.normpath(p.path) if p.path else "", lang, size))
        self.results.set_documents(rows, self.tabs.currentIndex())

    # ---- opening ---------------------------------------------------------------------------------------------------------
    def open_dialog(self):
        start = os.path.dirname(self.current().path) if self.current() is not None and self.current().path else self.default_directory()
        paths, _ = QFileDialog.getOpenFileNames(self, "Open", start, "All files (*.*)")
        self.open_paths(paths)

    def open_paths(self, paths):
        for p in paths:
            if p and os.path.isdir(p):
                self.workspace.set_root(p)
            elif p:
                self.open_path(p)

    def find_open(self, path):
        norm = os.path.normcase(os.path.abspath(path))
        return next((p for p in self.all_tabs() if p.path and os.path.normcase(os.path.abspath(p.path)) == norm), None)

    def open_path(self, path, line=None):
        path = os.path.abspath(path)
        existing = self.find_open(path)
        if existing is not None:
            self.tabs.setCurrentWidget(existing)
            if line:
                self._jump_line(line)
            self.raise_window()
            return existing
        if not os.path.isfile(path):
            QMessageBox.warning(self, APP_NAME, f"The file was not found:\n{path}")
            return None
        blank = self._blank_tab()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            size = os.path.getsize(path)
            if size > self.settings["large_file_mb"] * MB:
                page = self._open_large(path)
            else:
                page = self._open_text(path)
        except OSError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, APP_NAME, f"Could not open the file:\n{path}\n\n{e}")
            return None
        finally:
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        if page is None:
            return None
        if blank is not None and blank is not page:
            self.close_tab(blank, force=True)               # the empty "new 1" tab makes way for the first file
        self.settings.add_recent(path)
        if line:
            self._jump_line(line)
        self.raise_window()
        self.results.log(f"Opened {path}" + (" (large file mode)" if page.is_large else ""))
        return page

    def _blank_tab(self):
        if self.tabs.count() != 1:
            return None
        p = self.tabs.widget(0)
        return p if (not p.is_large and not p.path and not self._modified(p) and p.length() == 0) else None

    def _open_text(self, path):
        text, enc, eol, binary = util.read_text_file(path)
        if binary:
            QApplication.restoreOverrideCursor()
            r = QMessageBox.question(self, APP_NAME, f'"{os.path.basename(path)}" looks like a binary file. Open it as text anyway?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            QApplication.setOverrideCursor(Qt.WaitCursor)
            if r != QMessageBox.Yes:
                return None
        ed = self._make_editor()
        ed.path = path
        ed.encoding, ed.eol = enc, eol
        ed.mtime = os.path.getmtime(path)
        ed.setPlainText(text)
        ed.document().setModified(False)
        ed.document().clearUndoRedo() if hasattr(ed.document(), "clearUndoRedo") else None
        ed.detect_language()
        ed.moveCursor(QTextCursor.Start)
        return self._add_page(ed)

    def _open_large(self, path):
        view = LargeFileView(path, self.settings["large_file_mb"])
        view.title = os.path.basename(path)
        view.mtime = os.path.getmtime(path)
        view.editor.apply_font(self.settings["font_size"])
        view.editor.zoomRequested.connect(self.zoom)
        view.cursorStatus.connect(self._update_status)
        view.copyRequested.connect(lambda text, title: self.new_file(text, title))
        return self._add_page(view)

    def open_text_as_new(self, text, title):
        return self.new_file(text, title)

    def open_hit(self, path, line, col, length):
        page = self.find_open(path) if os.path.isabs(path) else next((p for p in self.all_tabs() if p.title == path and not p.path), None)
        if page is None and os.path.isabs(path):
            page = self.open_path(path)
        if page is None:
            return
        self.tabs.setCurrentWidget(page)
        if page.is_large:
            return
        block = page.document().findBlockByNumber(line - 1)
        if block.isValid():
            page.select_range(block.position() + col, max(length, 0))
        page.setFocus()

    def raise_window(self):
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def _workspace_changed(self, path):
        self.settings["workspace"] = path
        self.find_dialog.directory.setText(path)

    def default_directory(self):
        if self.workspace.root:
            return self.workspace.root
        cur = self.current()
        if cur is not None and cur.path:
            return os.path.dirname(cur.path)
        return os.path.expanduser("~")

    def _fill_recent(self):
        self.recent_menu.clear()
        recent = [p for p in self.settings["recent_files"] if os.path.isfile(p)]
        for p in recent:
            self.recent_menu.addAction(p, lambda path=p: self.open_path(path))
        if not recent:
            self.recent_menu.addAction("(none)").setEnabled(False)
        else:
            self.recent_menu.addSeparator()
            self.recent_menu.addAction("Clear list", lambda: self.settings.__setitem__("recent_files", []))

    def _fill_window_menu(self):
        m = self.window_menu
        m.clear()
        m.addAction(self.a_next_tab)
        m.addAction(self.a_prev_tab)
        m.addSeparator()
        for i, p in enumerate(self.all_tabs()):
            a = m.addAction(f"{i + 1}  {self.tab_title(p)}" + (" *" if self._modified(p) else ""))
            a.setCheckable(True)
            a.setChecked(p is self.current())
            a.triggered.connect(lambda _=False, page=p: self.tabs.setCurrentWidget(page))

    # ---- saving ---------------------------------------------------------------------------------------------------------------
    def save(self, page=None):
        page = page or self.current()
        if page is not None and page.is_large:
            self.flash("Large files are read-only. Use Make editable copy... to edit a piece of it.")
            return False
        if page is None:
            return False
        if not page.path:
            return self.save_as(page)
        return self._write(page, page.path)

    def save_as(self, page=None):
        page = page or self.current()
        if page is None or page.is_large:
            self.flash("Large files are read-only. Use Make editable copy... first.")
            return False
        start = page.path or os.path.join(self.default_directory(), page.title + (".txt" if "." not in page.title else ""))
        path, _ = QFileDialog.getSaveFileName(self, "Save As", start, "All files (*.*)")
        if not path:
            return False
        ok = self._write(page, path)
        if ok:
            page.path = path
            page.detect_language()
            self._decorate_tab(page)
            self._update_all()
        return ok

    def _write(self, page, path):
        text = page.toPlainText()
        try:
            try:
                util.write_text_file(path, text, page.encoding, page.eol, "strict")
            except UnicodeEncodeError:
                r = QMessageBox.question(self, APP_NAME, f"Some characters cannot be stored in {page.encoding}.\n\nSave as UTF-8 instead?",
                                         QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes)
                if r != QMessageBox.Yes:
                    return False
                page.encoding = "UTF-8"
                util.write_text_file(path, text, page.encoding, page.eol)
        except OSError as e:
            QMessageBox.critical(self, APP_NAME, f"Could not save the file:\n{path}\n\n{e}")
            return False
        page.document().setModified(False)
        page.mtime = os.path.getmtime(path)
        self.settings.add_recent(path)
        self.flash(f"Saved {os.path.basename(path)}")
        self.results.log(f"Saved {path}")
        self._decorate_tab(page)
        self._update_status()
        return True

    def save_all(self):
        for p in self.all_tabs():
            if self._modified(p) and not self.save(p):
                return False
        return True

    def reload_current(self):
        page = self.current()
        if page is not None and page.path and not page.is_large:
            if self._modified(page):
                r = QMessageBox.question(self, APP_NAME, "Discard your changes and reload the file from disk?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if r != QMessageBox.Yes:
                    return
            self._reload(page)

    def _reload(self, page, encoding=None):
        try:
            text, enc, eol, _ = util.read_text_file(page.path, encoding)
        except OSError as e:
            self.flash(f"Could not reload: {e}")
            return
        cur = page.textCursor()
        line, col = cur.blockNumber(), cur.positionInBlock()
        bar = page.verticalScrollBar().value()
        page.encoding, page.eol = enc, eol
        page.setPlainText(text)
        page.document().setModified(False)
        page.goto_line(line + 1, col)
        page.verticalScrollBar().setValue(bar)
        page.mtime = os.path.getmtime(page.path)
        self._update_all()

    def reload_unmodified(self, paths):
        wanted = {os.path.normcase(os.path.abspath(p)) for p in paths}
        for p in self.all_tabs():
            if p.path and not p.is_large and not self._modified(p) and os.path.normcase(os.path.abspath(p.path)) in wanted:
                self._reload(p)

    def _app_state(self, state):
        if state == Qt.ApplicationActive:
            QTimer.singleShot(50, self.check_external_changes)

    def check_external_changes(self):
        for p in self.all_tabs():
            if not p.path or p.is_large:
                continue
            try:
                m = os.path.getmtime(p.path)
            except OSError:
                continue
            if p.mtime is not None and abs(m - p.mtime) > 0.5:
                p.mtime = m
                if self._modified(p):
                    r = QMessageBox.question(self, APP_NAME, f'"{self.tab_title(p)}" was changed by another program, and you have unsaved changes.\n\nReload it and lose your changes?',
                                             QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                    if r == QMessageBox.Yes:
                        self._reload(p)
                else:
                    self._reload(p)
                    self.flash(f"{self.tab_title(p)} was updated from disk")

    def reveal_current(self):
        p = self.current()
        if p is not None and p.path:
            reveal_in_explorer(p.path)

    def copy_path(self):
        p = self.current()
        if p is not None and p.path:
            QGuiApplication.clipboard().setText(os.path.normpath(p.path))
            self.flash("Path copied")

    # ---- editing commands ------------------------------------------------------------------------------------------------------
    def _ed_call(self, name, *args):
        ed = self.editor_of(self.current())
        if ed is None:
            return
        if ed.isReadOnly() and name in ("cut", "paste", "undo", "redo", "duplicate_line", "delete_line", "move_lines",
                                        "toggle_comment", "indent_selection"):
            self.flash("This document is read-only.")
            return
        getattr(ed, name)(*args)

    def _writable(self):
        ed = self.editor_of(self.current())
        return ed if ed is not None and not ed.isReadOnly() else None

    def _transform(self, fn):
        ed = self._writable()
        if ed:
            ed.transform_selection(fn)

    def _transform_lines(self, fn):
        ed = self._writable()
        if ed:
            ed.transform_all_or_selection(lambda text: "\n".join(fn(text.split("\n"))))

    def _bookmark(self, forward):
        ed = self.editor_of(self.current())
        if ed is not None and not ed.goto_bookmark(forward):
            self.flash("No bookmarks")

    def paste_image(self):
        ed = self._writable()
        if ed is None:
            self.flash("Open or create a document first.")
            return
        if not ed.has_clipboard_image():
            self.flash("The clipboard does not hold a picture.")
            return
        ed.paste_image_from_clipboard()

    def _image_pasted(self, path):
        self.flash(f"Picture saved to {path}")
        self.results.log(f"Pasted picture saved: {path}")
        self.images.refresh(self.editor_of(self.current()))

    def set_eol(self, eol):
        page = self.current()
        if page is not None and not page.is_large and page.eol != eol:
            page.eol = eol
            page.document().setModified(True)
            self._update_status()

    def set_encoding(self, label):
        page = self.current()
        if page is not None and not page.is_large and page.encoding != label:
            page.encoding = label
            page.document().setModified(True)
            self._update_status()

    def reopen_with(self, label):
        page = self.current()
        if page is None or page.is_large or not page.path:
            self.flash("Only saved documents can be reopened with another encoding.")
            return
        if self._modified(page):
            r = QMessageBox.question(self, APP_NAME, "Reopening discards unsaved changes. Continue?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        self._reload(page, label)

    def set_language(self, name):
        ed = self.editor_of(self.current())
        if ed is not None:
            ed.set_language(lang_by_name(name))
            self._update_status()
            self.functions.refresh(ed)

    def _eol_popup(self):
        m = QMenu(self)
        for label, val in util.EOLS.items():
            m.addAction(label, lambda v=val: self.set_eol(v))
        m.exec(self.lbl_eol.mapToGlobal(self.lbl_eol.rect().topLeft()))

    def _enc_popup(self):
        m = QMenu(self)
        for label in util.ENCODINGS:
            m.addAction(label, lambda l=label: self.set_encoding(l))
        m.exec(self.lbl_enc.mapToGlobal(self.lbl_enc.rect().topLeft()))

    def _lang_popup(self):
        m = QMenu(self)
        for l in LANGS:
            m.addAction(l.name, lambda n=l.name: self.set_language(n))
        m.exec(self.lbl_lang.mapToGlobal(self.lbl_lang.rect().topLeft()))

    # ---- search helpers --------------------------------------------------------------------------------------------------------------
    def _selected_text(self):
        ed = self.editor_of(self.current())
        if ed is None:
            return None
        t = ed.textCursor().selectedText()
        return t if t and " " not in t and len(t) < 200 else None

    def _find_step(self, backward):
        if not self.find_dialog.find_box.currentText():
            self.find_dialog.show_tab(0, self._selected_text())
            return
        self.find_dialog.find_next(backward)

    def goto(self):
        page = self.current()
        if page is None:
            return
        if page.is_large:
            page.show_goto("Line")
            return
        panel = getattr(page, "goto_panel", None)
        if panel is None:
            panel = GoToPanel(page, ("Line", "Offset"))
            panel.requested.connect(lambda kind, v, p=page: self._goto_requested(p, kind, v))
            page.goto_panel = panel
        cur = page.textCursor()
        panel.open("Line", str(cur.blockNumber() + 1), f"This document has {page.blockCount():,} lines and {page.length():,} characters.")
        panel.adjustSize()
        panel.move(page.width() - panel.width() - 28, 16)

    def _goto_requested(self, page, kind, value):
        if kind == "Line":
            page.goto_line(int(value))
        else:
            page.goto_offset(int(value))
        page.goto_panel.hide()
        page.setFocus()

    def goto_bracket(self):
        ed = self.editor_of(self.current())
        if ed is None:
            return
        doc = ed.document()
        pos = ed.textCursor().position()
        for p in (pos, pos - 1):
            if 0 <= p < doc.characterCount() - 1:
                ch = doc.characterAt(p)
                if ch in "()[]{}":
                    other = ed._match_bracket(p, ch)
                    if other is not None:
                        c = ed.textCursor()
                        c.setPosition(other + (0 if ch in "([{" else 0))
                        ed.setTextCursor(c)
                        ed.centerCursor()
                        return
        self.flash("No matching bracket")

    def _jump_line(self, line):
        ed = self.editor_of(self.current())
        if ed is None:
            return
        if self.current().is_large:
            off = self.current().offset_of_line(line)
            if off is not None:
                self.current().scroll_to_offset(off)
            return
        ed.goto_line(line)
        ed.setFocus()

    # ---- view ---------------------------------------------------------------------------------------------------------------------------
    def _format(self, kind):
        ed = self.editor_of(self.current())
        if ed is None:
            return
        if not ed.toggle_format(kind):
            self.flash("Bold, italic and underline work in text, Markdown and HTML documents.")

    def _size(self, px=None, delta=0):
        ed = self.editor_of(self.current())
        if ed is None:
            return
        if not ed.set_text_size(px, delta):
            self.flash("Select some text in a text, Markdown or HTML document to change its size.")

    def _format_help(self):
        QMessageBox.information(self, "Formatting marks", "Bold, italic, underline and text size are stored as marks in the text, "
                                "so the file stays plain text. The editor hides the marks and just shows the formatting (View > Show Formatting Marks reveals them):\n\n  **bold**   *italic*   <u>underline</u>\n  <span style=\"font-size:24px\">size</span>"
                                "\n\nThe editor shows them formatted and dims the marks; Markdown viewers and browsers render the same.\n"
                                "In HTML documents <b>, <i> and <u> are used. Code files are left alone.")

    def set_complete(self, on=None):
        self.settings["autocomplete"] = self.a_complete.isChecked()
        for p in self.all_tabs():
            self.editor_of(p).autocomplete_on = self.settings["autocomplete"] and not p.is_large
        self.settings.save()

    def set_spell(self, _=None):
        self.settings["spellcheck"] = self.a_spell.isChecked()
        self.settings["autocorrect"] = self.a_autocorrect.isChecked()
        for p in self.all_tabs():
            self.editor_of(p).set_spellcheck(self.settings["spellcheck"], self.settings["autocorrect"] and not p.is_large)
        self.settings.save()

    def set_wrap(self, on):
        self.settings["word_wrap"] = on
        for p in self.all_tabs():
            self.editor_of(p).set_word_wrap(on)

    def set_show_marks(self, on):
        from . import highlighter
        highlighter.SHOW_MARKS = on
        for p in self.all_tabs():
            self.editor_of(p).highlighter.rehighlight()

    def set_whitespace(self, on):
        self.settings["show_whitespace"] = on
        for p in self.all_tabs():
            self.editor_of(p).set_show_whitespace(on)

    def toggle_map(self, on):
        self.settings["show_minimap"] = on
        self.map_dock.setVisible(on)

    def toggle_workspace(self, on):
        self.settings["show_workspace"] = on
        self.workspace_dock.setVisible(on)

    def toggle_results(self, on):
        self.bottom_dock.setVisible(on)

    def toggle_full(self, on):
        self.showFullScreen() if on else self.showNormal()

    def zoom(self, delta):
        self.set_font_size(self.settings["font_size"] + delta)

    def set_font_size(self, size):
        size = max(6, min(40, size))
        self.settings["font_size"] = size
        for p in self.all_tabs():
            self.editor_of(p).apply_font(size)
            if p.is_large:
                p.show_window()
        self.flash(f"Font size {size}")

    def preferences(self):
        d = PreferencesDialog(self.settings, self)
        if d.exec() != QDialog.Accepted:
            return
        d.apply_to(self.settings)
        self.settings.save()
        if self.settings["theme"] != theme.THEME_NAME:
            self._apply_theme(self.settings["theme"])
        for p in self.all_tabs():
            ed = self.editor_of(p)
            ed.set_tab_width(self.settings["tab_width"])
            ed.use_spaces = self.settings["use_spaces"]
            ed.image_folder = self.settings["image_folder"]
        self.set_font_size(self.settings["font_size"])

    def about(self):
        d = QDialog(self)
        d.setWindowTitle(f"About {APP_NAME}")
        lay = QVBoxLayout(d)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(72))
        logo.setAlignment(Qt.AlignCenter)
        lay.addWidget(logo)
        t = QLabel(f"<h2 style='margin:0'>{APP_NAME}</h2>")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        from PySide6 import __version__ as pyside_version
        for text in (f"Version {VERSION}", "A fast, local-first text and code editor.\nOpens multi-gigabyte files instantly.",
                     f"Qt for Python {pyside_version}  -  Python {sys.version.split()[0]}", "Copyright (c) 2026 Lavati Softwares (MIT License)"):
            l = QLabel(text)
            l.setAlignment(Qt.AlignCenter)
            l.setProperty("muted", True)
            lay.addWidget(l)
        b = QPushButton("OK")
        b.setProperty("primary", True)
        b.clicked.connect(d.accept)
        lay.addWidget(b)
        d.exec()

    def copy_diagnostics(self):
        from PySide6 import __version__ as pv
        text = f"{APP_NAME} {VERSION}\nPython {sys.version.split()[0]}\nPySide6 {pv}\nWindows: {sys.platform}\nData folder: {util.data_dir()}"
        QGuiApplication.clipboard().setText(text)
        self.flash("Diagnostic info copied")

    # ---- status bar ---------------------------------------------------------------------------------------------------------------------
    def flash(self, text):
        self.lbl_lang.setText(text)
        self._flash_timer.start()

    def _unflash(self):
        self._update_status()

    def _update_ram(self):
        mem = util.rss_mb()
        if mem:
            self.lbl_ram.setText(f"RAM {mem} MB")

    def _tab_changed(self, i):
        page = self.current()
        self._update_all()
        if page is not None and not page.is_large:
            page.setFocus()

    def _backup_session(self):
        if self.settings["restore_session"]:
            self.save_session()

    def _content_settled(self):
        self._autosave.start()
        ed = self.editor_of(self.current())
        self.functions.refresh(ed)
        self.images.refresh(ed)
        self._update_status()

    def _update_all(self):
        page = self.current()
        ed = self.editor_of(page)
        self.minimap.set_editor(ed if page is not None and not page.is_large else None)
        self.functions.refresh(ed)
        self.images.refresh(ed)
        self._update_status()
        self._update_title()
        self.refresh_documents()
        if page is not None and page.is_large:
            self._ram_timer.start()
            self._update_ram()
        else:
            self._ram_timer.stop()

    def _update_title(self):
        page = self.current()
        if page is None:
            self.setWindowTitle(APP_NAME)
            return
        loc = os.path.dirname(page.path) if page.path else ""
        star = "*" if self._modified(page) else ""
        self.setWindowTitle(f"{star}{self.tab_title(page)}" + (f" — {os.path.normpath(loc)}" if loc else "") + f" — {APP_NAME}")

    def _update_status(self):
        page = self.current()
        if page is None:
            return
        if page.is_large:
            line, col, off = page.caret_info()
            total = page.total_lines()
            self.lbl_lang.setText("Large file, read-only")
            self.lbl_len.setText(f"size : {util.human_size(page.size)}   lines : " + (f"{total:,}" if page.indexing_done else f"about {util.short_count(total)}"))
            self.lbl_pos.setText(f"Ln : {line:,}   Col : {col}   Offset : {off:,}")
            self.lbl_eol.setText({"\r\n": "Windows (CR LF)", "\n": "Unix (LF)", "\r": "Old Mac (CR)"}[page.eol])
            self.lbl_enc.setText(page.encoding.replace("UTF-8 with BOM", "UTF-8 BOM"))
            self.lbl_mode.setText("READ")
            self.lbl_ram.show()
            return
        self.lbl_ram.hide()
        cur = page.textCursor()
        sel_chars, sel_lines = page.selection_info()
        self.lbl_lang.setText(f"{page.lang.name} file" if page.lang is not PLAIN else "Normal text file")
        self.lbl_len.setText(f"length : {page.length():,}   lines : {page.blockCount():,}")
        self.lbl_pos.setText(f"Ln : {cur.blockNumber() + 1:,}   Col : {cur.positionInBlock() + 1}   Sel : {sel_chars} | {sel_lines}")
        self.lbl_eol.setText({"\r\n": "Windows (CR LF)", "\n": "Unix (LF)", "\r": "Old Mac (CR)"}[page.eol])
        self.lbl_enc.setText(page.encoding.replace("UTF-8 with BOM", "UTF-8 BOM"))
        self.lbl_mode.setText("OVR" if page.overwriteMode() else "INS")
        a = self.lang_actions.get(page.lang.name)
        if a:
            a.setChecked(True)
        e = self.enc_actions.get(page.encoding)
        if e:
            e.setChecked(True)
        ea = self.eol_actions.get(page.eol)
        if ea:
            ea.setChecked(True)

    # ---- drag and drop ---------------------------------------------------------------------------------------------------------------------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.open_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    # ---- session --------------------------------------------------------------------------------------------------------------------------------
    def save_session(self):
        """Writes every open tab, and the text of every unsaved one, into one compressed, checksummed, atomically replaced file."""
        items, budget = [], session.MAX_BACKUP_BYTES
        for p in self.all_tabs():
            if p.is_large:
                items.append({"path": p.path, "large": True})
                continue
            cur = p.textCursor()
            entry = {"path": p.path, "title": p.title, "encoding": p.encoding, "eol": p.eol, "lang": p.lang.name,
                     "line": cur.blockNumber() + 1, "col": cur.positionInBlock(), "scroll": p.verticalScrollBar().value(),
                     "bookmarks": [b.blockNumber() + 1 for b in p._bookmarked_blocks()]}
            if self._modified(p) or (not p.path and p.length()):
                text = p.toPlainText()
                if len(text) <= budget:
                    budget -= len(text)
                    entry["text"] = text
                    entry["modified"] = self._modified(p)
            items.append(entry)
        data = {"version": VERSION, "items": items, "current": self.tabs.currentIndex(), "untitled": self._untitled,
                "workspace": self.workspace.root}
        return session.save(data)

    def restore_session(self):
        data = session.load()
        if not data:
            return False
        self._untitled = int(data.get("untitled", 0))
        opened = 0
        for entry in data.get("items", []):
            p = entry.get("path")
            try:
                page = None
                if "text" in entry:
                    ed = self._make_editor()
                    ed.title = entry.get("title") or f"new {self._untitled + 1}"
                    ed.path = p if p and os.path.isfile(p) else None
                    ed.encoding = entry.get("encoding", "UTF-8")
                    ed.eol = entry.get("eol", "\r\n")
                    ed.setPlainText(entry["text"])
                    ed.detect_language() if ed.path else ed.set_language(lang_by_name(entry.get("lang", "Plain text")))
                    # unsaved "new N" text shows as modified, like Notepad++
                    ed.document().setModified(bool(entry.get("modified", True)) or not ed.path)
                    if ed.path:
                        ed.mtime = os.path.getmtime(ed.path)
                    page = self._add_page(ed, activate=False)
                elif not p and entry.get("title"):                          # an empty "new N" tab
                    ed = self._make_editor()
                    ed.title = entry["title"]
                    ed.encoding = entry.get("encoding", "UTF-8")
                    ed.eol = entry.get("eol", "\r\n")
                    ed.set_language(lang_by_name(entry.get("lang", "Plain text")))
                    page = self._add_page(ed, activate=False)
                    ed.document().setModified(False)
                elif p and os.path.isfile(p):
                    page = self.open_path(p)
                if page is not None:
                    opened += 1
                    if not page.is_large:
                        page.goto_line(entry.get("line", 1), entry.get("col", 0))
                        page.verticalScrollBar().setValue(entry.get("scroll", 0))
                        for ln in entry.get("bookmarks", []):
                            page.toggle_bookmark(page.document().findBlockByNumber(ln - 1))
            except (OSError, ValueError, KeyError):
                continue
        if opened:
            self.tabs.setCurrentIndex(max(0, min(int(data.get("current", 0)), self.tabs.count() - 1)))
            self._update_all()
        return opened > 0

    def closeEvent(self, e: QCloseEvent):
        self.find_dialog.stop()
        if self.settings["restore_session"]:
            self.save_session()
        else:
            for p in self.all_tabs():
                self.tabs.setCurrentWidget(p)
                if self._modified(p) and not self.close_tab(p, force=False):
                    e.ignore()
                    return
        self.settings["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.settings.save()
        for p in self.all_tabs():
            if p.is_large:
                p.close_file()
        e.accept()
