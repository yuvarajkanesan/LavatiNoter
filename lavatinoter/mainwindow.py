"""The main window: menus, toolbar, tabs, docks, status bar, file handling and session restore."""
import json
import os
import sys
import time

from PySide6.QtCore import QByteArray, QProcess, QProcessEnvironment, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent, QDesktopServices, QGuiApplication, QKeySequence,
                           QTextCursor)
from PySide6.QtWidgets import (QSplitter, QApplication, QCheckBox, QDialog, QDialogButtonBox, QDockWidget, QFileDialog, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu, QMessageBox, QPushButton, QSpinBox,
                               QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget, QComboBox, QLineEdit)

from . import detect, export, filetypes, lsp, runner, updates
from . import APP_NAME, VERSION, diffview, editorconfig, formatter, gitinfo, hexview, plugins, session, symbols, theme, util
from .editor import CodeEditor
from .finddialog import FindDialog
from .highlighter import LANGS, PLAIN, lang_by_name, lang_for_path
from .largefile import GoToPanel, LargeFileView
from . import search
from .palette import Picker, fuzzy
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
        from PySide6.QtGui import QFontDatabase
        self.family = QComboBox()
        self.family.addItem("Default (JetBrains Mono)", "")
        for fam in sorted(f for f in QFontDatabase.families() if QFontDatabase.isFixedPitch(f) and not f.startswith("@")):
            self.family.addItem(fam, fam)
        self.family.setCurrentIndex(max(0, self.family.findData(settings["font_family"])))
        self.size = QSpinBox()
        self.size.setRange(6, 72)
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
        self.copystyle = QComboBox()
        self.copystyle.addItem("Keep bold / italic / underline as styled characters", "styled")
        self.copystyle.addItem("Plain text only (formatting stays in rich-text programs)", "clean")
        self.copystyle.setCurrentIndex(max(0, self.copystyle.findData(settings["copy_style"])))
        self.autoupdate = QCheckBox("Check for a new version once a day (contacts github.com only)")
        self.autoupdate.setChecked(settings["auto_update_check"])
        self.restore = QCheckBox("Reopen my files and keep unsaved text when I quit")
        self.restore.setChecked(settings["restore_session"])
        form.addRow("Theme", self.theme)
        form.addRow("Editor font size", self.size)
        form.addRow("Editor font", self.family)
        form.addRow("Tab width", self.tab)
        form.addRow("", self.spaces)
        form.addRow("Open files larger than", self.large)
        form.addRow("Folder for pasted pictures", self.images)
        form.addRow("When I copy formatted text into a plain-text program", self.copystyle)
        form.addRow("", self.restore)
        form.addRow("", self.autoupdate)
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
        s["font_family"] = self.family.currentData() or ""
        s["tab_width"] = self.tab.value()
        s["use_spaces"] = self.spaces.isChecked()
        s["large_file_mb"] = self.large.value()
        name = self.images.text().strip().strip("\\/")
        s["image_folder"] = name or "images"
        s["restore_session"] = self.restore.isChecked()
        s["copy_style"] = self.copystyle.currentData()
        s["auto_update_check"] = self.autoupdate.isChecked()


class MainWindow(QMainWindow):
    gitReady = Signal(object, object, str, str)        # root, status, branch, HEAD id: from the Git worker thread to the window
    gitMarks = Signal(str, int, object)                # path, document revision, (HEAD text, marks)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self._proc = None
        self.lsp_clients = {}
        self._macro = None                   # steps being recorded
        self._last_macro = []
        self._actions_by_text = {}
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
        self.main_split = QSplitter(Qt.Horizontal)
        self.main_split.setChildrenCollapsible(False)
        self.main_split.setHandleWidth(1)
        self.main_split.addWidget(self.tabs)
        self.split_pane = None
        self.setCentralWidget(self.main_split)

        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_status()
        self.find_dialog = FindDialog(self)
        self.plugins = plugins.PluginManager(self)
        self._git_root = None
        self._git_busy = False
        self._git_sha = None
        self._git_marks_busy = False
        self._git_marks_again = False
        self._restoring = False
        self.gitReady.connect(self._git_done)
        self.gitMarks.connect(self._git_marks_done)
        self._git_head = {}                  # path -> HEAD text (cleared when the status is refreshed)
        self._git_timer = QTimer(self, interval=20000)
        self._git_timer.timeout.connect(self.refresh_git)
        self._git_marks_timer = QTimer(self, singleShot=True, interval=700)
        self._git_marks_timer.timeout.connect(self._update_git_marks)
        self._plugin_actions = []
        self._nav = []                       # (tab key, line) places to go Back to
        self._docs_timer = QTimer(self, singleShot=True, interval=150)        # many tabs opening at once refresh the list once
        self._docs_timer.timeout.connect(self._refresh_documents_now)
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
        if settings["plugins_enabled"]:
            QTimer.singleShot(0, self.reload_plugins)
        if settings["auto_update_check"] and time.time() - float(settings["last_update_check"] or 0) > 86400:
            QTimer.singleShot(8000, lambda: self.check_updates(False))

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
                a.triggered.connect(lambda _=False, fn=slot, act=a: (self._macro_note(act), fn()))      # never pass the 'checked' flag on
        self._actions_by_text[text] = a
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
        self.a_hex = A("View as Hex", self.hex_current)
        self.a_copy_path = A("Copy Full Path", self.copy_path)
        self.a_exit = A("Exit", self.close, "Alt+F4")

        self.a_undo = A("Undo", lambda: self._ed_call("undo"), S.Undo, "undo")
        self.a_redo = A("Redo", lambda: self._ed_call("redo"), S.Redo, "redo")
        self.a_cut = A("Cut", lambda: self._ed_call("cut"), S.Cut, "cut")
        self.a_copy = A("Copy", lambda: self._ed_call("copy"), S.Copy, "copy")
        self.a_paste = A("Paste", lambda: self._ed_call("paste"), S.Paste, "paste")
        self.a_copy_marks = A("Copy with Formatting Marks", lambda: self._ed_call("copy_with_marks"), "Ctrl+Alt+C", None,
                              tip="Copies the text as written, with the ** _ <u> marks, for Markdown or GitHub")
        self.a_copy_plain = A("Copy as Plain Text", lambda: self._ed_call("copy_plain"), None, None, tip="Copies the visible text only: no marks and no styled characters")
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
        self.a_clear_fmt = A("Clear Formatting", lambda: self._clear_format(), "Ctrl+Space", None, tip="Removes bold, italic, underline and size from the selection or line (Ctrl+Space)")
        self.a_size_up = A("Increase Text Size", lambda: self._size(delta=2), "Ctrl+Alt+Up", "textup", tip="Larger text (Ctrl+Alt+Up)")
        self.a_size_down = A("Decrease Text Size", lambda: self._size(delta=-2), "Ctrl+Alt+Down", "textdown", tip="Smaller text (Ctrl+Alt+Down)")
        self.a_format_doc = A("Format Document", self.format_document, "Shift+Alt+F", None,
                              tip="Pretty-prints JSON, XML, HTML, CSS and SQL; re-indents JavaScript, TypeScript, Java, C#, C/C++, Go, Rust, PHP and more")
        self.a_minify = A("Minify JSON", self.minify_json)
        self.a_validate = A("Check Syntax", self.validate_document, "F7", None,
                            tip="Finds the first error in JSON, XML, Python or unbalanced brackets in other code")
        self.a_select_in = A("Select Inside Brackets", lambda: self._ed_call("select_enclosing"), "Ctrl+Alt+B")
        self.a_autoclose = A("Auto-close Brackets and Quotes", self.set_autoclose, None, None, True, self.settings["autoclose"])
        self.view_guides = A("Indent Guides", self.set_guides, None, None, True, self.settings["indent_guides"])
        self.a_fold = A("Fold", lambda: self._ed_call("fold_current"), "Ctrl+Shift+[")
        self.a_unfold = A("Unfold", lambda: self._ed_call("unfold_current"), "Ctrl+Shift+]")
        self.a_fold_all = A("Fold All", lambda: self._ed_call("fold_all"), "Alt+0")
        self.a_fold_funcs = A("Fold All Functions / Methods", lambda: self._ed_call("fold_all", True), "Alt+9")
        self.a_unfold_all = A("Unfold All", lambda: self._ed_call("unfold_all"), "Alt+Shift+0")
        self.a_goto_def = A("Go to Definition", self.go_to_definition, "F12", None, tip="Finds where the name under the caret is defined (Ctrl+click)")
        self.a_refs = A("Find All References", self.find_references, "Shift+F12")
        self.a_symbol = A("Go to Symbol in File...", self.go_to_symbol, "Ctrl+R")
        self.a_back = A("Navigate Back", self.nav_back, "Alt+Left")
        self.a_palette = A("Command Palette...", self.command_palette, "Ctrl+Shift+P", None,
                           tip="Type to run any command. In Quick Open, start with > for commands, : for a line, @ for a symbol")
        self.a_quick = A("Quick Open File...", self.quick_open, "Ctrl+P")
        self.a_next_occ = A("Add Next Occurrence", lambda: self._ed_call("add_next_occurrence"), "Ctrl+Alt+D")
        self.a_all_occ = A("Select All Occurrences", lambda: self._ed_call("select_all_occurrences"), "Ctrl+Shift+L")
        self.a_cursor_up = A("Add Cursor Above", lambda: self._ed_call("add_cursor_vertical", True), "Alt+Shift+Up")
        self.a_cursor_down = A("Add Cursor Below", lambda: self._ed_call("add_cursor_vertical", False), "Alt+Shift+Down")
        self.a_cmp_tab = A("Compare with Another Open Tab...", self.compare_with_tab)
        self.a_cmp_file = A("Compare with File on Disk...", self.compare_with_file)
        self.a_cmp_saved = A("Compare with Saved Version", self.compare_with_saved)
        self.a_cmp_git = A("Compare with Git HEAD (show changes)", self.compare_with_head)
        self.a_run = A("Run Current File", self.run_file, "F5", None, tip="Runs the file with the interpreter for its language; output goes to the Console")
        self.a_run_sel = A("Run Selection", lambda: self.run_file(selection=True), "Shift+F5")
        self.a_stop = A("Stop", self.stop_run, "Ctrl+F5")
        self.a_run_cfg = A("Edit Run Commands...", self.edit_run_commands)
        self.a_rec = A("Start Recording", self.macro_toggle, "Ctrl+Alt+R", None, tip="Records your typing and editing commands so they can be played back")
        self.a_play = A("Play Macro", self.macro_play, "Ctrl+Alt+P")
        self.a_play_n = A("Run Macro Multiple Times...", self.macro_play_many)
        self.a_save_macro = A("Save Current Macro...", self.macro_save)
        self.a_print = A("Print...", self.print_doc, None, None, tip="Print with syntax colours on a white page")
        self.a_preview = A("Print Preview...", lambda: self.print_doc(preview=True))
        self.a_pdf = A("Export as PDF...", self.export_pdf)
        self.a_html = A("Export as HTML...", self.export_html)
        self.a_split = A("Clone Tab to Split View", self.open_split, "Ctrl+\\", None, tip="Shows the same document in a second pane beside it")
        self.a_split_flip = A("Switch Split Direction", self.flip_split)
        self.a_split_close = A("Close Split View", self.close_split)
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
        self.view_map = A("Panels on the Right (Map, Functions, Images)", self.toggle_map, None, "minimap", True, self.settings["show_minimap"],
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
        self.a_lsp = A("Language Servers (LSP)...", self.edit_lsp, None, None, tip="Use an installed language server for go to definition, hover and error underlines")
        self.a_prefs = A("Preferences...", self.preferences, "Ctrl+,")
        self.a_next_tab = A("Next Tab", lambda: self.step_tab(1), "Ctrl+PgDown")
        self.a_prev_tab = A("Previous Tab", lambda: self.step_tab(-1), "Ctrl+PgUp")
        self.a_next_tab2 = A("Next Tab", lambda: self.step_tab(1), "Ctrl+Tab")
        self.a_prev_tab2 = A("Previous Tab", lambda: self.step_tab(-1), "Ctrl+Shift+Tab")
        self.a_about = A("About LavatiNoter", self.about)
        self.a_update = A("Check for Updates...", lambda: self.check_updates(True))
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
        m.addAction(self.a_hex)
        m.addSeparator()
        for a in (self.a_print, self.a_preview, self.a_pdf, self.a_html):
            m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_close)
        m.addAction(self.a_close_all)
        m.addSeparator()
        m.addAction(self.a_exit)

        m = mb.addMenu("Edit")
        for a in (self.a_undo, self.a_redo, None, self.a_cut, self.a_copy, self.a_copy_marks, self.a_copy_plain, self.a_paste, self.a_paste_image,
                  self.a_select_all, None, self.a_dup, self.a_del_line, self.a_up, self.a_down, None, self.a_comment,
                  self.a_indent, self.a_outdent):
            m.addSeparator() if a is None else m.addAction(a)
        c = m.addMenu("Convert Case")
        c.addAction(self.a_upper)
        c.addAction(self.a_lower)
        ln = m.addMenu("Line Operations")
        for a in (self.a_sort_asc, self.a_sort_desc, self.a_unique, self.a_blank, self.a_trim):
            ln.addAction(a)
        mc = m.addMenu("Multiple Cursors")
        for a in (self.a_next_occ, self.a_all_occ, self.a_cursor_up, self.a_cursor_down):
            mc.addAction(a)
        mc.addAction("Alt+click adds a cursor, Alt+Shift+drag selects a column, Esc leaves").setEnabled(False)
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
        for a in (self.a_bold, self.a_italic, self.a_underline, self.a_clear_fmt, None, self.a_size_up, self.a_size_down):
            m.addSeparator() if a is None else m.addAction(a)
        m.addSeparator()
        m.addAction(self.a_format_doc)
        m.addAction(self.a_minify)
        m.addAction(self.a_validate)
        sz = m.addMenu("Text Size")
        for px in (10, 12, 14, 18, 24, 32, 48):
            sz.addAction(f"{px} px", lambda _=False, v=px: self._size(px=v))
        sz.addSeparator()
        sz.addAction("Normal (remove size)", lambda: self._size(px=0))
        m.addSeparator()
        m.addAction("About formatting marks", self._format_help)

        m = mb.addMenu("Search")
        m.addAction(self.a_palette)
        m.addAction(self.a_quick)
        m.addSeparator()
        for a in (self.a_find, self.a_find_next, self.a_find_prev, self.a_replace, self.a_find_files, self.a_mark, None,
                  self.a_goto, self.a_goto_def, self.a_refs, self.a_symbol, self.a_back, self.a_bracket, self.a_select_in):
            m.addSeparator() if a is None else m.addAction(a)

        m = mb.addMenu("View")
        sm = m.addMenu("Split View")
        for a in (self.a_split, self.a_split_flip, self.a_split_close):
            sm.addAction(a)
        fm = m.addMenu("Code Folding")
        for a in (self.a_fold, self.a_unfold, self.a_fold_all, self.a_fold_funcs, self.a_unfold_all):
            fm.addAction(a)
        for a in (self.view_wrap, self.view_ws, self.view_guides, self.view_marks, None, self.show_workspace, self.view_map, self.view_results, None,
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
        self.a_auto_lang = QAction("Detect Language Automatically", self, checkable=True)
        self.a_auto_lang.triggered.connect(self.toggle_auto_language)
        m.addAction(self.a_auto_lang)
        m.addSeparator()
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
        m.addAction(self.a_lsp)
        m.addAction(self.a_autoclose)
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
        cm = m.addMenu("Compare")
        for a in (self.a_cmp_tab, self.a_cmp_file, self.a_cmp_saved, self.a_cmp_git):
            cm.addAction(a)
        m.addSeparator()
        m.addAction(self.a_paste_image)
        m.addAction(self.a_find_files)
        m.addAction(self.a_reveal)

        rm = mb.addMenu("Run")
        for a in (self.a_run, self.a_run_sel, self.a_stop, None, self.a_run_cfg):
            rm.addSeparator() if a is None else rm.addAction(a)
        self.macro_menu = mb.addMenu("Macro")
        self.macro_menu.aboutToShow.connect(self._fill_macro_menu)
        self.plugins_menu = mb.addMenu("Plugins")
        self.plugins_menu.aboutToShow.connect(self._fill_plugins_menu)

        self.window_menu = mb.addMenu("Window")
        self.window_menu.aboutToShow.connect(self._fill_window_menu)

        m = mb.addMenu("?")
        m.addAction(self.a_update)
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
        self.lbl_git = lab()
        self.lbl_git.hide()
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
        if self.split_pane is not None:
            self.split_editor.restyle()
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
        ed.copy_styled = self.settings["copy_style"] == "styled"
        ed.autoclose_on = self.settings["autoclose"]
        ed.show_guides = self.settings["indent_guides"]
        ed.zoomRequested.connect(self.zoom)
        ed.filesDropped.connect(self.open_paths)
        ed.cursorStatus.connect(self._update_status)
        ed.document().modificationChanged.connect(lambda _=False, p=ed: self._modification_changed(p))
        ed.document().contentsChanged.connect(self._content_timer.start)
        ed.imagePasted.connect(self._image_pasted)
        ed.imageActivated.connect(lambda path: ImagePreview(path, self).exec())
        ed.definitionRequested.connect(lambda w: self.go_to_definition(w))
        ed.hover_provider = lambda line, col, e=ed: self._lsp_hover(e, line, col)
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
        ed.lang_auto = language is None
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
        if self.split_pane is not None and self.split_page is page:
            self.close_split()
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
        st = getattr(page, "_lsp_state", None)
        if st is not None and page.path:
            st[0].close_doc(lsp.path_to_uri(page.path))
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
        if not self._restoring:
            self._docs_timer.start()

    def _refresh_documents_now(self):
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
            if size > self.settings["large_file_mb"] * MB or (size > MB and self._has_very_long_line(path)):
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
        self.plugins.emit("open", path)
        self.results.log(f"Opened {path}" + (" (large file mode)" if page.is_large else ""))
        return page

    @staticmethod
    def _has_very_long_line(path, limit=200_000):
        """A file whose lines are hundreds of thousands of characters long (minified JSON, a one-line export) would freeze the
        normal editor while it lays the text out. Such files open in large file mode, which shows them instantly."""
        try:
            with open(path, "rb") as f:
                run = 0
                for _ in range(8):                                  # the first 8 MB are enough to tell
                    chunk = f.read(1 << 20)
                    if not chunk:
                        break
                    parts = chunk.split(b"\n")
                    if len(parts) == 1:
                        run += len(chunk)
                    else:
                        if run + len(parts[0]) > limit or max(map(len, parts[1:-1]), default=0) > limit:
                            return True
                        run = len(parts[-1])
                    if run > limit:
                        return True
        except OSError:
            return False
        return False

    def _blank_tab(self):
        if self.tabs.count() != 1:
            return None
        p = self.tabs.widget(0)
        return p if (not p.is_large and not p.path and not self._modified(p) and p.length() == 0) else None

    def _open_text(self, path):
        text, enc, eol, binary = util.read_text_file(path)
        if binary:
            QApplication.restoreOverrideCursor()
            box = QMessageBox(QMessageBox.Question, APP_NAME, f'"{os.path.basename(path)}" looks like a binary file.')
            hexb = box.addButton("Open as hex", QMessageBox.AcceptRole)
            txtb = box.addButton("Open as text", QMessageBox.ActionRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(hexb)
            box.exec()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            if box.clickedButton() is hexb:
                return self.open_hex(path)
            if box.clickedButton() is not txtb:
                return None
        ed = self._make_editor()
        ed.path = path
        ed.encoding, ed.eol = enc, eol
        ed.mtime = os.path.getmtime(path)
        ed.setPlainText(text)
        ed.document().setModified(False)
        ed.document().clearUndoRedo() if hasattr(ed.document(), "clearUndoRedo") else None
        ed.detect_language()
        if ed.lang is PLAIN and os.path.splitext(path)[1].lower() not in (".txt", ".text", ".nfo", ".csv", ".tsv"):
            ed.lang_auto = True                               # no known extension: look at the text
            self._auto_detect(ed)
        self._apply_file_settings(ed)
        ed.moveCursor(QTextCursor.Start)
        return self._add_page(ed)

    def _apply_file_settings(self, ed):
        """Per-file choices: .editorconfig first, then what you set for this file last time (word wrap)."""
        ed.config = editorconfig.properties_for(ed.path) if ed.path else {}
        c = ed.config
        if c.get("indent_style") in ("space", "tab"):
            ed.use_spaces = c["indent_style"] == "space"
        size = c.get("indent_size") if c.get("indent_size", "").isdigit() else c.get("tab_width")
        if size and size.isdigit() and 1 <= int(size) <= 16:
            ed.set_tab_width(int(size))
        prefs = self.settings["file_prefs"].get(os.path.normcase(ed.path or ""), {})
        if "wrap" in prefs:
            ed.set_word_wrap(prefs["wrap"])

    def open_hex(self, path):
        text, shown, size = hexview.read_hex(path)
        ed = self._make_editor()
        ed.title = os.path.basename(path) + " (hex)"
        ed.setPlainText(text)
        ed.setReadOnly(True)
        ed.is_hex = True
        ed.set_language(PLAIN)
        ed.document().setModified(False)
        page = self._add_page(ed)
        if shown < size:
            self.flash(f"Showing the first {util.human_size(shown)} of {util.human_size(size)}")
        return page

    def hex_current(self):
        page = self.current()
        if page is not None and page.path and os.path.isfile(page.path):
            self.open_hex(page.path)

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
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized)       # back to how it was (maximized stays maximized)
            self.show()
        self.raise_()
        self.activateWindow()

    def _workspace_changed(self, path):
        self.settings["workspace"] = path
        QTimer.singleShot(0, self.refresh_git)
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
        if getattr(page, "is_hex", False):
            self.flash("A hex view is read-only.")
            return False
        if not page.path:
            return self.save_as(page)
        return self._write(page, page.path)

    def save_as(self, page=None):
        page = page or self.current()
        if page is None or page.is_large:
            self.flash("Large files are read-only. Use Make editable copy... first.")
            return False
        if page.path:                                     # a file keeps its own type unless you pick another one
            start, current = page.path, filetypes.filter_for_path(page.path)
        else:                                             # a new document starts as a text file
            start = os.path.join(self.default_directory(), page.title)
            current = filetypes.filter_for_lang(page.lang.name)
        path = self._ask_save_path(start, current)
        if not path:
            return False
        ok = self._write(page, path)
        if ok:
            page.path = path
            page.lang_auto = False
            page.detect_language()
            page.config = editorconfig.properties_for(path)
            page.title = os.path.basename(path)
            self._decorate_tab(page)
            self._update_all()
        return ok

    def _ask_save_path(self, start, current_filter):
        """The Save As dialog with a 'Save as type' list. A name typed without an extension gets the extension of the chosen
        type (text files: .txt); a name typed with one is saved exactly as typed. -> the chosen path or ''."""
        dlg = QFileDialog(self, "Save As", os.path.dirname(start) or self.default_directory())
        dlg.setAcceptMode(QFileDialog.AcceptSave)
        dlg.setFileMode(QFileDialog.AnyFile)
        dlg.setNameFilters(filetypes.filter_list())
        dlg.selectNameFilter(current_filter if current_filter in filetypes.filter_list() else filetypes.filter_list()[0])
        dlg.setLabelText(QFileDialog.FileType, "Save as type:")
        name = os.path.basename(start)
        base, ext = os.path.splitext(name)
        dlg.selectFile(name if ext else base)
        if dlg.exec() != QDialog.Accepted or not dlg.selectedFiles():
            return ""
        path = filetypes.with_extension(os.path.normpath(dlg.selectedFiles()[0]), dlg.selectedNameFilter())
        # the dialog only asked about overwriting the name as typed: ask again if adding the extension hit another file
        if os.path.exists(path) and os.path.normcase(path) != os.path.normcase(os.path.normpath(dlg.selectedFiles()[0])):
            r = QMessageBox.question(self, "Save As", f"{os.path.basename(path)} already exists.\nDo you want to replace it?",
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return ""
        return path

    def _write(self, page, path):
        text = page.toPlainText()
        cfg = getattr(page, "config", None) or {}
        fixed = editorconfig.apply_on_save(cfg, text) if cfg else text
        if fixed != text:
            page.replace_document_text(fixed)
            text = fixed
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
        self.plugins.emit("save", path)
        QTimer.singleShot(0, self.refresh_git)
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
            ed.lang_auto = False                               # an explicit choice always wins
            ed.set_language(lang_by_name(name))
            self._update_status()
            self.functions.refresh(ed)

    def _auto_detect(self, page):
        """While a document is in auto mode, its language follows the text: paste Python into a new tab and it is Python."""
        if page is None or page.is_large or not getattr(page, "lang_auto", False):
            return
        rev = page.document().revision()
        if rev == page._auto_rev or page.length() > 1_500_000:
            return
        page._auto_rev = rev
        text = page.toPlainText()
        name = detect.guess_language(text)
        if name is None:
            if len(text.strip()) < 12 and page.lang is not PLAIN:
                page.set_language(PLAIN)                       # emptied: back to plain text
                self._update_status()
            return
        lang = lang_by_name(name)
        if lang is not page.lang and lang is not PLAIN:
            page.set_language(lang)
            self._update_status()
            self.flash(f"Detected {lang.name}")

    def toggle_auto_language(self, on=None):
        ed = self.editor_of(self.current())
        if ed is None:
            return
        ed.lang_auto = self.a_auto_lang.isChecked()
        ed._auto_rev = -1
        if ed.lang_auto:
            self._auto_detect(ed)
        self._update_status()

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

    def _clear_format(self):
        ed = self.editor_of(self.current())
        if ed is not None and not ed.clear_format():
            self.flash("Clear Formatting works in text, Markdown and HTML documents.")

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

    # ---- navigation: definitions, references, symbols ---------------------------------------------------------------
    def _nav_push(self):
        page = self.current()
        ed = self.editor_of(page)
        if page is not None and not page.is_large and (not self._nav or self._nav[-1][0] != self.tab_key(page) or
                                                         self._nav[-1][1] != ed.textCursor().blockNumber() + 1):
            self._nav.append((self.tab_key(page), ed.textCursor().blockNumber() + 1))
            del self._nav[:-50]

    def _show_location(self, path, line, name=None):
        self.open_hit(path, line, 0, 0)
        ed = self.editor_of(self.current())
        if ed is not None and name:
            b = ed.document().findBlockByNumber(line - 1)
            i = b.text().find(name)
            if i >= 0:
                ed.select_range(b.position() + i, len(name))
        if ed is not None:
            ed.setFocus()

    def nav_back(self):
        if not self._nav:
            self.flash("Nothing to go back to")
            return
        key, line = self._nav.pop()
        self.open_hit(key, line, 0, 0)

    # ---- command palette and quick open ---------------------------------------------------------------------------
    def _all_commands(self):
        """[(label, shortcut, QAction)] for every enabled menu command, plus plugin commands."""
        out, seen = [], set()

        def walk(menu, trail):
            for a in menu.actions():
                if a.isSeparator():
                    continue
                text = a.text().replace("&", "")
                if a.menu() is not None:
                    walk(a.menu(), trail + [text])
                elif a.isEnabled() and text and id(a) not in seen:
                    seen.add(id(a))
                    out.append((" > ".join(trail + [text]), a.shortcut().toString(), a))
        for top in self.menuBar().actions():
            if top.menu() is not None and top.text().replace("&", "") not in ("Window",):
                walk(top.menu(), [top.text().replace("&", "")])
        for a in self._plugin_actions:
            if id(a) not in seen:
                out.append(("Plugins > " + a.text(), a.shortcut().toString(), a))
        return out

    def command_palette(self, start=""):
        cmds = self._all_commands()

        def items(q):
            return [(label, sc, act) for label, sc, act in cmds]
        d = Picker(self, "Command Palette", "Type a command...", items)
        d.chosen.connect(lambda act: act.trigger())
        d.box.setText(start)
        d.show()

    def _workspace_files(self):
        import time as _t
        root = self.workspace.root or (os.path.dirname(self.current().path) if self.current() is not None and self.current().path else "")
        cache = getattr(self, "_file_cache", None)
        if cache and cache[0] == root and _t.time() - cache[1] < 30:
            return cache[2]
        files = []
        if root and os.path.isdir(root):
            for i, p in enumerate(search.iter_files(root, "*", True, True)):
                if i >= 30000:
                    break
                files.append(os.path.relpath(p, root))
        self._file_cache = (root, _t.time(), files, root)
        return files

    def quick_open(self):
        root = getattr(self, "_file_cache", (None, 0, [], ""))[3] if getattr(self, "_file_cache", None) else ""

        def items(q):
            if q.startswith(">"):
                return None
            if q.startswith(":"):
                return []
            if q.startswith("@"):
                page = self.current()
                ed = self.editor_of(page)
                if ed is None or page.is_large:
                    return []
                name = q[1:].strip()
                syms = symbols.symbols_in_text(ed.lang, ed.toPlainText())
                return [(n, f"line {ln}", ("line", ln), True) for n, ln, _t in syms if fuzzy(name, n) is not None]
            rows = [(("\u25cf " if False else "") + self.tab_title(p), os.path.dirname(p.path) if p.path else "(unsaved)", ("tab", p)) for p in self.all_tabs()]
            base = self._file_cache[3] if getattr(self, "_file_cache", None) else ""
            rows += [(os.path.basename(f), os.path.dirname(f), ("file", os.path.join(base, f))) for f in self._workspace_files()]
            return rows
        self._workspace_files()
        d = Picker(self, "Quick Open", "Go to file...   (: line   @ symbol   > command)", items)

        def on_text(q):
            if q.startswith(">"):
                d.reject()
                QTimer.singleShot(0, lambda: self.command_palette(q[1:]))
        d.box.textChanged.connect(on_text)

        def chosen(payload):
            kind, val = payload
            if kind == "tab":
                self.tabs.setCurrentWidget(val)
            elif kind == "file":
                self.open_path(val)
            elif kind == "line":
                self._nav_push()
                self._jump_line(val)
        d.chosen.connect(chosen)
        orig = d.accept_current

        def accept_current():
            q = d.box.text()
            if q.startswith(":") and q[1:].strip().isdigit():          # ":120" jumps to line 120
                d.accept()
                self._nav_push()
                self._jump_line(int(q[1:]))
                return
            orig()
        d.box.returnPressed.disconnect()
        d.box.returnPressed.connect(accept_current)
        d.show()

    # ---- compare and Git ----------------------------------------------------------------------------------------------
    def _text_of(self, page):
        return page.toPlainText()

    def _show_diff(self, lt, rt, old, new, left_apply=None, right_apply=None, lang=None, left_label="Apply", right_label="Apply"):
        try:
            d = diffview.DiffWindow(self, lt, rt, old, new, left_apply, right_apply, lang, self.settings["font_size"], left_label, right_label)
        except ValueError as e:
            self.flash(str(e))
            return
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.show()

    def _tab_apply(self, page):
        """A callable that puts text back into a tab (undoable there; save the tab to keep it)."""
        def apply(text):
            if page in self.all_tabs() and not page.is_large and not page.isReadOnly():
                page.replace_document_text(text)
                self.flash(f"Changes applied to {self.tab_title(page)} (not saved yet)")
        return apply

    def _file_apply(self, path, encoding, eol):
        def apply(text):
            util.write_text_file(path, text, encoding, eol)
            page = self.find_open(path)
            if page is not None and not page.is_large and not self._modified(page):
                self._reload(page)
            self.flash(f"Saved {os.path.basename(path)}")
        return apply

    def compare_with_tab(self):
        page = self.current()
        others = [p for p in self.all_tabs() if p is not page and not p.is_large]
        if page is None or page.is_large or not others:
            self.flash("Open a second document to compare with.")
            return

        def go(other):
            self._show_diff(self.tab_title(other), self.tab_title(page), other.toPlainText(), page.toPlainText(),
                            self._tab_apply(other), self._tab_apply(page), page.lang,
                            f"Apply to {self.tab_title(other)}", f"Apply to {self.tab_title(page)}")
        d = Picker(self, "Compare with", "Choose the document to compare with...",
                   lambda q: [(self.tab_title(p), p.path or "(unsaved)", p) for p in others])
        d.chosen.connect(go)
        d.show()

    def compare_with_file(self):
        page = self.current()
        if page is None or page.is_large:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Compare with", self.default_directory(), "All files (*.*)")
        if path:
            try:
                text, enc, eol, _b = util.read_text_file(path)
            except OSError as e:
                self.flash(str(e))
                return
            self._show_diff(os.path.basename(path), self.tab_title(page), text, page.toPlainText(), self._file_apply(path, enc, eol),
                            self._tab_apply(page), page.lang, f"Save {os.path.basename(path)}", f"Apply to {self.tab_title(page)}")

    def compare_with_saved(self):
        page = self.current()
        if page is None or page.is_large or not page.path:
            self.flash("Only a saved document can be compared with its saved version.")
            return
        try:
            text, enc, eol, _b = util.read_text_file(page.path)
        except OSError as e:
            self.flash(str(e))
            return
        self._show_diff("Saved on disk", "Current (editor)", text, page.toPlainText(), self._file_apply(page.path, enc, eol),
                        self._tab_apply(page), page.lang, "Save to disk", f"Apply to {self.tab_title(page)}")

    def compare_with_head(self):
        page = self.current()
        if page is None or page.is_large or not page.path or not self._git_root:
            self.flash("This file is not in a Git repository (or git is not installed).")
            return
        old = gitinfo.head_text(self._git_root, page.path)
        if old is None:
            self.flash("This file is not tracked by Git yet.")
            return
        self._show_diff("Git HEAD", "Current (editor)", old, page.toPlainText(), None, self._tab_apply(page), page.lang, "",
                        f"Apply to {self.tab_title(page)}")

    def refresh_git(self, force=False):
        """Branch name and workspace colours. Git runs in a short-lived thread so the window never waits for it, and it is only
        asked while the window is in use."""
        if not gitinfo.git_exe() or self._restoring:
            return
        if not force and QApplication.applicationState() != Qt.ApplicationActive:
            return
        folder = self.workspace.root or (os.path.dirname(self.current().path) if self.current() is not None and self.current().path else "")
        if not folder or self._git_busy:
            return
        self._git_busy = True
        import threading

        def work():
            root = gitinfo.repo_root(folder)
            if root:
                out = gitinfo.run(["rev-parse", "HEAD"], root)
                self.gitReady.emit(root, gitinfo.status(root), gitinfo.branch(root), out.decode().strip() if out else "")
            else:
                self.gitReady.emit(None, {}, "", "")
        threading.Thread(target=work, daemon=True).start()

    def _git_done(self, root, status, branch, sha):
        self._git_busy = False
        self._git_root = root
        if sha != self._git_sha:                                # the commit changed: the old HEAD texts are stale
            self._git_head = {}
            self._git_sha = sha
        self.workspace.model.set_status(status)
        if root:
            self.lbl_git.setText(f"\u2387 {branch}" + (f"  \u00b1{len(status)}" if status else ""))
            self.lbl_git.show()
            if not self._git_timer.isActive():
                self._git_timer.start()
        else:
            self.lbl_git.hide()
            self._git_timer.stop()
        self._git_marks_timer.start()

    def _update_git_marks(self):
        """Change bars for the document you are looking at. The comparison runs in a thread, and only for files of a sane size."""
        page = self.current()
        if page is None or page.is_large or not self._git_root or not page.path or self._restoring:
            return
        if not os.path.normcase(page.path).startswith(os.path.normcase(self._git_root)):
            return
        if page.length() > 300_000 or page.blockCount() > 8000:
            if page.git_marks:
                page.git_marks = {}
                page.gutter.update()
            return
        if self._git_marks_busy:
            self._git_marks_again = True
            return
        self._git_marks_busy = True
        path, rev, text, root = page.path, page.document().revision(), page.toPlainText(), self._git_root
        cached = self._git_head.get(path, "\0missing")
        import threading

        def work():
            old = gitinfo.head_text(root, path) if cached == "\0missing" else cached
            marks = gitinfo.line_changes(old, text) if old is not None else {}
            self.gitMarks.emit(path, rev, (old, marks))
        threading.Thread(target=work, daemon=True).start()

    def _git_marks_done(self, path, rev, payload):
        old, marks = payload
        self._git_marks_busy = False
        self._git_head[path] = old
        page = self.find_open(path)
        if page is not None and not page.is_large and page.document().revision() == rev and marks != page.git_marks:
            page.git_marks = marks
            page.gutter.update()
        if self._git_marks_again:
            self._git_marks_again = False
            self._git_marks_timer.start()

    # ---- run ------------------------------------------------------------------------------------------------------------
    def run_file(self, selection=False):
        page = self.current()
        ed = self.editor_of(page)
        if ed is None or page.is_large:
            return
        if self._proc is not None:
            self.flash("Something is already running. Stop it first (Ctrl+F5).")
            return
        lang = ed.lang
        if selection:
            text = ed.textCursor().selectedText().replace("\u2029", "\n")
            if not text.strip():
                self.flash("Select the code to run first.")
                return
            ext = lang.exts[0] if lang.exts else ".txt"
            path = os.path.join(util.sub_dir("run"), "selection" + ext)
            util.write_text_file(path, text, "UTF-8", "\n")
        elif page.path:
            if self._modified(page) and not self.save(page):
                return
            path = page.path
        else:
            ext = lang.exts[0] if lang.exts else ".txt"
            path = os.path.join(util.sub_dir("run"), "untitled" + ext)
            util.write_text_file(path, ed.toPlainText(), "UTF-8", "\n")
        cmd = runner.command_for(lang.name, path, self.settings["run_commands"])
        if not cmd:
            self.flash(f"No way to run {lang.name} files yet. Run > Edit Run Commands... adds one.")
            return
        import time as _t
        self.results.show_console()
        self.show_results_dock()
        self.results.write(f"\n> {cmd}\n")
        prog, args, native = runner.shell_args(cmd)
        proc = QProcess(self)
        proc.setWorkingDirectory(os.path.dirname(path))
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONIOENCODING", "utf-8")
        env.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(env)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(lambda: self.results.write(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")))
        t0 = _t.time()

        def finished(code, status):
            self.results.write(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace"))
            self.results.write(f"\n[exit code {code} in {_t.time() - t0:.2f} s]\n")
            self._proc = None
            proc.deleteLater()
            self.flash(f"Finished with exit code {code}")
        proc.finished.connect(finished)
        proc.errorOccurred.connect(lambda err: (self.results.write(f"\n[could not start: {proc.errorString()}]\n"), setattr(self, "_proc", None)) if err == QProcess.FailedToStart else None)
        self._proc = proc
        proc.setProgram(prog)
        if native:
            proc.setNativeArguments(native)
        else:
            proc.setArguments(args)
        proc.start()
        self.flash(f"Running {os.path.basename(path)}...")

    def stop_run(self):
        if self._proc is None:
            return
        import subprocess
        pid = self._proc.processId()
        if sys.platform == "win32" and pid:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self._proc.kill()
        self.results.write("\n[stopped]\n")

    def edit_run_commands(self):
        d = QDialog(self)
        d.setWindowTitle("Run commands")
        d.setMinimumSize(560, 360)
        lay = QVBoxLayout(d)
        info = QLabel('One per line: <b>Language = command</b>. Use {file} for the script path, e.g.  <code>Python = py -3 "{file}"</code>.<br>'
                      "Built in: " + ", ".join(sorted(k for k, v in runner.DEFAULTS.items() if v)))
        info.setWordWrap(True)
        info.setProperty("muted", True)
        lay.addWidget(info)
        from PySide6.QtWidgets import QPlainTextEdit
        box = QPlainTextEdit()
        box.setFont(theme.mono(10))
        box.setPlainText("\n".join(f"{k} = {v}" for k, v in self.settings["run_commands"].items()))
        lay.addWidget(box, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec() == QDialog.Accepted:
            self.settings["run_commands"] = runner.parse_overrides(box.toPlainText())
            self.settings.save()

    # ---- macros ------------------------------------------------------------------------------------------------------------------
    def _macro_note(self, action):
        if self._macro is not None and action not in (self.a_rec, self.a_play, self.a_play_n, self.a_save_macro):
            self._macro.append(("action", action.text()))

    def macro_toggle(self):
        ed = self.editor_of(self.current())
        if self._macro is None:
            self._macro = []
            for p in self.all_tabs():
                self.editor_of(p).macro_rec = self._macro
            self.a_rec.setText("Stop Recording")
            self.flash("Recording macro... (Ctrl+Alt+R to stop)")
        else:
            steps, self._macro = self._macro, None
            for p in self.all_tabs():
                self.editor_of(p).macro_rec = None
            self._last_macro = steps
            self.a_rec.setText("Start Recording")
            self.flash(f"Macro recorded: {len(steps)} step{'s' if len(steps) != 1 else ''}")

    def _macro_run(self, steps, until_end=False, times=1):
        from PySide6.QtCore import QEvent
        from PySide6.QtGui import QKeyEvent
        ed = self.editor_of(self.current())
        if ed is None or ed.isReadOnly() or not steps:
            return 0
        ed.macro_playing = True
        done = 0
        try:
            limit = 200000 if until_end else times
            while done < limit:
                before = ed.textCursor().blockNumber()
                for step in steps:
                    if step[0] == "key":
                        mods = Qt.KeyboardModifier(step[2])
                        for kind in (QEvent.KeyPress, QEvent.KeyRelease):
                            QApplication.sendEvent(ed, QKeyEvent(kind, step[1], mods, step[3] if kind == QEvent.KeyPress else ""))
                    else:
                        act = self._actions_by_text.get(step[1])
                        if act is not None and act.isEnabled():
                            act.trigger()
                done += 1
                if until_end and (ed.textCursor().blockNumber() >= ed.blockCount() - 1 and ed.textCursor().atBlockEnd()):
                    break
                if until_end and ed.textCursor().blockNumber() == before and done > 1 and ed.textCursor().atEnd():
                    break
                if done % 50 == 0:
                    QApplication.processEvents()
        finally:
            ed.macro_playing = False
        return done

    def macro_play(self):
        if self._macro is not None:
            self.macro_toggle()
        if not self._last_macro:
            self.flash("Nothing recorded yet. Ctrl+Alt+R starts recording.")
            return
        self._macro_run(self._last_macro)

    def macro_play_many(self):
        if not self._last_macro and self._macro is None:
            self.flash("Nothing recorded yet. Ctrl+Alt+R starts recording.")
            return
        if self._macro is not None:
            self.macro_toggle()
        from PySide6.QtWidgets import QInputDialog
        n, ok = QInputDialog.getInt(self, "Run macro", "Times to run it (0 = until the end of the file):", 10, 0, 100000)
        if ok:
            ran = self._macro_run(self._last_macro, until_end=(n == 0), times=n)
            self.flash(f"Macro ran {ran} time{'s' if ran != 1 else ''}")

    def macro_save(self):
        if not self._last_macro:
            self.flash("Record a macro first.")
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Save macro", "Name:")
        if ok and name.strip():
            macros = [m for m in self.settings["macros"] if m["name"] != name.strip()]
            macros.append({"name": name.strip(), "steps": [list(s) for s in self._last_macro]})
            self.settings["macros"] = macros
            self.settings.save()

    def _fill_macro_menu(self):
        m = self.macro_menu
        m.clear()
        for a in (self.a_rec, self.a_play, self.a_play_n, self.a_save_macro):
            m.addAction(a)
        saved = self.settings["macros"]
        if saved:
            m.addSeparator()
        for mac in saved:
            sub = m.addMenu(mac["name"])
            sub.addAction("Play", lambda _=False, s=mac["steps"]: self._macro_run([tuple(x) for x in s]))
            sub.addAction("Play multiple times...", lambda _=False, s=mac["steps"]: self._play_saved_many(s))
            sub.addAction("Delete", lambda _=False, n=mac["name"]: self._delete_macro(n))

    def _play_saved_many(self, steps):
        self._last_macro = [tuple(x) for x in steps]
        self.macro_play_many()

    def _delete_macro(self, name):
        self.settings["macros"] = [x for x in self.settings["macros"] if x["name"] != name]
        self.settings.save()

    # ---- print and export ------------------------------------------------------------------------------------------------
    def _export_source(self):
        page = self.current()
        ed = self.editor_of(page)
        if ed is None or page.is_large:
            self.flash("Printing and export work on normal (editable) documents.")
            return None
        sel = ed.textCursor().selectedText().replace("\u2029", "\n") if ed.textCursor().hasSelection() else ""
        return (sel or ed.toPlainText()), ed.lang, self.tab_title(page)

    def print_doc(self, preview=False):
        src = self._export_source()
        if src is None:
            return
        text, lang, title = src
        from PySide6.QtPrintSupport import QPrintDialog, QPrintPreviewDialog
        doc = export.styled_document(text, lang, self.settings["font_size"] - 1)
        pr = export.make_printer()
        pr.setDocName(title)
        if preview:
            dlg = QPrintPreviewDialog(pr, self)
            dlg.paintRequested.connect(lambda printer: doc.print_(printer))
            dlg.resize(900, 700)
            dlg.exec()
        else:
            dlg = QPrintDialog(pr, self)
            if dlg.exec() == QDialog.Accepted:
                doc.print_(pr)

    def export_pdf(self):
        src = self._export_source()
        if src is None:
            return
        text, lang, title = src
        start = os.path.splitext(self.current().path or os.path.join(self.default_directory(), title))[0] + ".pdf"
        path, _ = QFileDialog.getSaveFileName(self, "Export as PDF", start, "PDF (*.pdf)")
        if path:
            export.export_pdf(path, text, lang, title, self.settings["font_size"] - 1)
            self.flash(f"Exported {os.path.basename(path)}")

    def export_html(self):
        src = self._export_source()
        if src is None:
            return
        text, lang, title = src
        start = os.path.splitext(self.current().path or os.path.join(self.default_directory(), title))[0] + ".html"
        path, _ = QFileDialog.getSaveFileName(self, "Export as HTML", start, "HTML (*.html)")
        if path:
            export.export_html(path, text, lang, title)
            self.flash(f"Exported {os.path.basename(path)}")

    # ---- split view ----------------------------------------------------------------------------------------------------
    def open_split(self):
        page = self.current()
        if page is None or page.is_large or getattr(page, "is_hex", False):
            self.flash("Split view needs a normal (editable) document.")
            return
        self.close_split()
        clone = CodeEditor()
        clone.apply_font(self.settings["font_size"])
        clone.share_document_from(page)
        clone.zoomRequested.connect(self.zoom)
        clone.set_show_whitespace(self.settings["show_whitespace"])
        clone.autoclose_on = self.settings["autoclose"]
        pane = QFrame()
        pane.setStyleSheet(f"QFrame#splitPane {{ border-left: 1px solid {theme.c('BORDER')}; border-top: 1px solid {theme.c('BORDER')}; }}")
        pane.setObjectName("splitPane")
        lay = QVBoxLayout(pane)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(12, 4, 6, 4)
        title = QLabel(f"SPLIT VIEW  \u2014  {self.tab_title(page)}")
        title.setProperty("heading", True)
        head.addWidget(title, 1)
        for icon_name, tip, fn in (("replace", "Switch direction", self.flip_split), ("close", "Close split view", self.close_split)):
            b = QToolButton()
            b.setIcon(theme.icon(icon_name, theme.c("MUTED"), 16))
            b.setAutoRaise(True)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, f=fn: f())
            head.addWidget(b)
        lay.addLayout(head)
        lay.addWidget(clone, 1)
        self.split_pane = pane
        self.split_editor = clone
        self.split_page = page
        self.main_split.addWidget(pane)
        self.main_split.setSizes([700, 500])
        clone.setFocus()

    def flip_split(self):
        if self.split_pane is not None:
            self.main_split.setOrientation(Qt.Vertical if self.main_split.orientation() == Qt.Horizontal else Qt.Horizontal)

    def close_split(self):
        if self.split_pane is not None:
            self.split_pane.setParent(None)
            self.split_pane.deleteLater()
            self.split_pane = self.split_editor = self.split_page = None

    # ---- updates -----------------------------------------------------------------------------------------------------
    def check_updates(self, manual):
        if getattr(self, "_update_thread", None) is not None and self._update_thread.isRunning():
            return
        t = updates.UpdateCheck(self)
        self._update_thread = t
        t.finished_check.connect(lambda res, err: self._update_done(res, err, manual))
        self.flash("Checking for updates...") if manual else None
        t.start()

    def _update_done(self, res, err, manual):
        self.settings["last_update_check"] = time.time()
        self.settings.save()
        if res is None:
            if manual:
                QMessageBox.information(self, "Check for updates", f"Could not reach GitHub ({err}).\nCheck your connection and try again.")
            return
        if res["newer"]:
            box = QMessageBox(QMessageBox.Information, "Update available", f"{APP_NAME} {res['tag']} is available (you have {VERSION}).")
            if res["notes"]:
                box.setDetailedText(res["notes"])
            go = box.addButton("Open download page", QMessageBox.AcceptRole)
            box.addButton("Later", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is go:
                QDesktopServices.openUrl(QUrl(res["url"]))
        elif manual:
            QMessageBox.information(self, "Check for updates",
                                    f"You have the newest version ({VERSION})." if not res.get("none") else
                                    f"No releases are published yet. You have version {VERSION}.")

    # ---- language servers ----------------------------------------------------------------------------------------------------
    def lsp_client_for(self, page):
        if not self.settings["lsp_enabled"] or page is None or page.is_large or not page.path:
            return None
        name = page.lang.name
        cmd = lsp.detect_server(name, self.settings["lsp_servers"])
        if not cmd:
            return None
        root = self._project_root() or os.path.dirname(page.path)
        key = (name, root)
        client = self.lsp_clients.get(key)
        if client is None or client.proc.state() == 0:
            if client is not None and client.error:
                return None                                              # the server could not start: do not retry on every keystroke
            client = lsp.LspClient(cmd, root, lsp.LANGUAGE_ID.get(name, name.lower()), self)
            client.diagnostics.connect(self._lsp_diagnostics)
            self.lsp_clients[key] = client
            client.start()
        return client

    def _lsp_sync(self, page):
        if page is None or page.is_large or not page.path:
            return
        client = self.lsp_client_for(page)
        if client is None:
            return
        uri = lsp.path_to_uri(page.path)
        st = getattr(page, "_lsp_state", None)
        rev = page.document().revision()
        if st is None or st[0] is not client:
            client.open_doc(uri, page.toPlainText(), 1)
            page._lsp_state = (client, 1, rev)
        elif st[2] != rev:
            client.change_doc(uri, page.toPlainText(), st[1] + 1)
            page._lsp_state = (client, st[1] + 1, rev)

    def _lsp_diagnostics(self, uri, items):
        page = self.find_open(lsp.uri_to_path(uri))
        if page is None or page.is_large:
            return
        page.diagnostics = [(d["range"]["start"]["line"], d["range"]["start"]["character"], d["range"]["end"]["line"],
                             d["range"]["end"]["character"], d.get("severity", 1), d.get("message", "")) for d in items if "range" in d]
        page.refresh_selections()
        if page is self.current() and items:
            self.flash(f"{len(items)} problem{'s' if len(items) != 1 else ''} reported by the language server")

    def _lsp_hover(self, ed, line, col):
        st = getattr(ed, "_lsp_state", None)
        if st is None or not ed.path:
            return ""
        return st[0].hover(lsp.path_to_uri(ed.path), line, col)

    def edit_lsp(self):
        d = QDialog(self)
        d.setWindowTitle("Language servers")
        d.setMinimumSize(600, 420)
        lay = QVBoxLayout(d)
        on = QCheckBox("Use language servers (starts the programs below when you open a file of that language)")
        on.setChecked(self.settings["lsp_enabled"])
        lay.addWidget(on)
        found = [f"{name}: {' '.join(cmd)}" for name in sorted(lsp.DEFAULT_SERVERS) for cmd in [lsp.detect_server(name)] if cmd]
        info = QLabel("Installed servers found on this computer:<br>" + ("<br>".join(found) if found else "none (install one, e.g. <code>npm i -g pyright</code>)")
                      + '<br><br>To use another program, add a line: <code>Python = pylsp</code> or <code>Go = "C:\\tools\\gopls.exe"</code>')
        info.setWordWrap(True)
        info.setProperty("muted", True)
        lay.addWidget(info)
        from PySide6.QtWidgets import QPlainTextEdit
        box = QPlainTextEdit()
        box.setFont(theme.mono(10))
        box.setPlainText("\n".join(f"{k} = {v}" for k, v in self.settings["lsp_servers"].items()))
        lay.addWidget(box, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec() == QDialog.Accepted:
            self.settings["lsp_enabled"] = on.isChecked()
            self.settings["lsp_servers"] = runner.parse_overrides(box.toPlainText())
            self.settings.save()
            for c in self.lsp_clients.values():
                c.stop()
            self.lsp_clients = {}
            for p in self.all_tabs():
                p._lsp_state = None
                if not p.is_large:
                    p.diagnostics = []
            self._lsp_sync(self.current())

    def _project_root(self):
        page = self.current()
        return self.workspace.root or (os.path.dirname(page.path) if page is not None and page.path else "")

    def go_to_definition(self, name=None):
        page = self.current()
        ed = self.editor_of(page)
        if ed is None or page.is_large:
            return
        name = name if isinstance(name, str) and name else ed.word_at_cursor()
        if not name:
            self.flash("Put the caret on a name first")
            return
        client = self.lsp_client_for(page)
        if client is not None and page.path:
            self._lsp_sync(page)
            cur = ed.textCursor()
            line0, col0 = cur.blockNumber(), cur.positionInBlock()
            if name and not ed.textCursor().hasSelection():                        # a Ctrl+click already moved the caret onto the name
                pass
            locs = client.definition(lsp.path_to_uri(page.path), line0, col0)
            if locs:
                self._nav_push()
                self._show_location(locs[0][0], locs[0][1] + 1, name)
                return
        found = []
        for ln, text in symbols.definitions_in_text(ed.lang, ed.toPlainText(), name):
            found.append((self.tab_key(page), ln, text))
        if not found and self._project_root():
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                found = symbols.find_definitions(name, self._project_root(), page.path)
            finally:
                QApplication.restoreOverrideCursor()
        if not found:
            self.flash(f'No definition of "{name}" found' + ("" if self._project_root() else " (open a folder as workspace to search other files)"))
            return
        if len(found) == 1 or all(f[0] == found[0][0] for f in found[:1]) and len({f[0] for f in found}) == 1 and len(found) == 1:
            self._nav_push()
            self._show_location(found[0][0], found[0][1], name)
            return
        by_file = {}
        for path, ln, text in found:
            i = text.find(name)
            by_file.setdefault(path, search.FileResult(path)).hits.append(search.Hit(ln, max(0, i), len(name), text, 0))
        self._nav_push()
        self.results.show_results(f'Definitions of "{name}"', list(by_file.values()))
        self.show_results_dock()

    def find_references(self):
        ed = self.editor_of(self.current())
        name = ed.word_at_cursor() if ed is not None else ""
        root = self._project_root()
        if not name or not root:
            self.flash("Put the caret on a name, and open a folder as workspace, to find its references")
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            res = symbols.find_references(name, root)
        finally:
            QApplication.restoreOverrideCursor()
        self.results.show_results(f'References to "{name}"', res)
        self.show_results_dock()

    def go_to_symbol(self):
        page = self.current()
        ed = self.editor_of(page)
        if ed is None or page.is_large:
            return
        syms = symbols.symbols_in_text(ed.lang, ed.toPlainText())
        if not syms:
            self.flash("No functions or classes found in this document")
            return
        d = QDialog(self)
        d.setWindowTitle("Go to Symbol")
        d.setMinimumSize(460, 380)
        lay = QVBoxLayout(d)
        box = QLineEdit()
        box.setPlaceholderText("Type to filter functions and classes...")
        from PySide6.QtWidgets import QListWidget, QListWidgetItem
        lst = QListWidget()
        lay.addWidget(box)
        lay.addWidget(lst, 1)

        def fill():
            lst.clear()
            q = box.text().lower()
            for name, ln, text in syms:
                if q in name.lower():
                    it = QListWidgetItem(f"{name}    \u2014 line {ln}")
                    it.setData(Qt.UserRole, ln)
                    lst.addItem(it)
            if lst.count():
                lst.setCurrentRow(0)

        def go(*_):
            it = lst.currentItem()
            if it:
                d.accept()
                self._nav_push()
                ed.goto_line(it.data(Qt.UserRole))
                ed.setFocus()
        box.textChanged.connect(fill)
        box.returnPressed.connect(go)
        lst.itemActivated.connect(go)
        fill()
        d.exec()

    # ---- plugins ---------------------------------------------------------------------------------------------------------
    def set_plugins_enabled(self, on):
        if on and not self.settings["plugins_enabled"]:
            r = QMessageBox.warning(self, "Enable plugins",
                                    "Plugins are Python files from your plugins folder. They run with the same rights as "
                                    f"{APP_NAME} and can read and change your files.\n\nOnly enable plugins you wrote or trust.\n\n"
                                    f"Folder: {plugins.plugins_dir()}", QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
            if r != QMessageBox.Ok:
                return
        self.settings["plugins_enabled"] = on
        self.settings.save()
        self.reload_plugins()

    def reload_plugins(self):
        for a in self._plugin_actions:
            self.removeAction(a)
            a.deleteLater()
        self._plugin_actions = []
        if not self.settings["plugins_enabled"]:
            self.plugins.plugins, self.plugins.handlers = [], {}
            return
        for p in self.plugins.load_all():
            p["actions"] = []
            for title, fn, shortcut in p["commands"]:
                a = QAction(title, self)
                if shortcut:
                    a.setShortcut(QKeySequence(shortcut))
                a.triggered.connect(lambda _=False, pn=p["name"], t=title, f=fn: self.plugins.run(pn, t, f))
                self.addAction(a)
                p["actions"].append(a)
                self._plugin_actions.append(a)
        loaded = [p for p in self.plugins.plugins if not p["error"]]
        self.flash(f"{len(loaded)} plugin{'s' if len(loaded) != 1 else ''} loaded" + (f", {len(self.plugins.plugins) - len(loaded)} failed" if len(loaded) != len(self.plugins.plugins) else ""))

    def install_sample_plugins(self):
        copied = plugins.install_samples()
        self.flash(f"Installed {len(copied)} sample plugin{'s' if len(copied) != 1 else ''}" if copied else "The sample plugins are already installed")
        if self.settings["plugins_enabled"]:
            self.reload_plugins()

    def _fill_plugins_menu(self):
        m = self.plugins_menu
        m.clear()
        en = m.addAction("Enable Plugins")
        en.setCheckable(True)
        en.setChecked(self.settings["plugins_enabled"])
        en.triggered.connect(lambda checked: self.set_plugins_enabled(checked))
        m.addAction("Reload Plugins", self.reload_plugins).setEnabled(self.settings["plugins_enabled"])
        m.addAction("Install Sample Plugins", self.install_sample_plugins)
        m.addAction("Open Plugins Folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(plugins.plugins_dir())))
        m.addSeparator()
        if not self.settings["plugins_enabled"]:
            m.addAction("(plugins are off)").setEnabled(False)
            return
        if not self.plugins.plugins:
            m.addAction("(no plugins installed)").setEnabled(False)
        for p in self.plugins.plugins:
            if p["error"]:
                m.addAction(f"{p['file']}  (failed - see Console)").setEnabled(False)
                continue
            sub = m.addMenu(p["name"] + (f"  {p['version']}" if p["version"] else ""))
            if p["description"]:
                sub.setToolTipsVisible(True)
                sub.setToolTip(p["description"])
            for a in p.get("actions", []):
                sub.addAction(a)
            if not p.get("actions"):
                sub.addAction("(no commands)").setEnabled(False)

    def set_autoclose(self, on=None):
        self.settings["autoclose"] = self.a_autoclose.isChecked()
        for p in self.all_tabs():
            self.editor_of(p).autoclose_on = self.settings["autoclose"] and not p.is_large
        self.settings.save()

    def set_guides(self, on=None):
        self.settings["indent_guides"] = self.view_guides.isChecked()
        for p in self.all_tabs():
            self.editor_of(p).show_guides = self.settings["indent_guides"]
            self.editor_of(p).viewport().update()
        self.settings.save()

    def _problem(self, ed, err, what):
        msg = f"{err}" + (f" (line {err.line}, column {err.col})" if err.line else "")
        self.flash(msg)
        self.results.log(f"{what}: {msg}")
        if err.line:
            ed.goto_line(err.line, max(0, (err.col or 1) - 1))
            ed.setFocus()

    def format_document(self):
        page = self.current()
        ed = self.editor_of(page)
        if ed is None or page.is_large or ed.isReadOnly():
            self.flash("Open a normal (editable) document to format it.")
            return
        name = ed.lang.name
        if not formatter.can_format(name):
            self.flash(f"No formatter for {name} documents yet.")
            return
        try:
            new = formatter.format_text(name, ed.toPlainText(), self.settings["tab_width"], not self.settings["use_spaces"])
        except formatter.FormatError as e:
            self._problem(ed, e, "Format")
            return
        if new == ed.toPlainText():
            self.flash("Already formatted")
            return
        ed.replace_document_text(new)
        self.flash(f"Formatted as {name}")

    def minify_json(self):
        ed = self.editor_of(self.current())
        if ed is None or ed.isReadOnly() or ed.lang.name != "JSON":
            self.flash("Minify works on JSON documents.")
            return
        try:
            ed.replace_document_text(formatter.minify_json(ed.toPlainText()))
        except formatter.FormatError as e:
            self._problem(ed, e, "Minify")

    def validate_document(self):
        ed = self.editor_of(self.current())
        if ed is None or self.current().is_large:
            return
        try:
            formatter.validate_text(ed.lang.name, ed.toPlainText())
        except formatter.FormatError as e:
            self._problem(ed, e, "Check")
            return
        self.flash(f"No problems found in this {ed.lang.name} document")

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
        page = self.current()
        if page is not None and page.path:                      # remembered for this file next time
            self.settings["file_prefs"].setdefault(os.path.normcase(page.path), {})["wrap"] = on
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
        size = max(6, min(72, size))
        self.settings["font_size"] = size
        for p in self.all_tabs():
            self.editor_of(p).apply_font(size)
            if p.is_large:
                p.show_window()
        if self.split_pane is not None:
            self.split_editor.apply_font(size)
        self.flash(f"Zoom {round(size / 11 * 100)}%  ({size} pt)   -   Ctrl+wheel or Ctrl +/- to change, Ctrl+0 for 100%")

    def preferences(self):
        d = PreferencesDialog(self.settings, self)
        if d.exec() != QDialog.Accepted:
            return
        d.apply_to(self.settings)
        self.settings.save()
        theme.set_mono_family(self.settings["font_family"])
        if self.settings["theme"] != theme.THEME_NAME:
            self._apply_theme(self.settings["theme"])
        for p in self.all_tabs():
            ed = self.editor_of(p)
            ed.set_tab_width(self.settings["tab_width"])
            ed.use_spaces = self.settings["use_spaces"]
            ed.image_folder = self.settings["image_folder"]
            ed.copy_styled = self.settings["copy_style"] == "styled"
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
        if self._restoring:
            return
        self._update_all()
        if page is not None and not page.is_large:
            page.setFocus()

    def _backup_session(self):
        if self.settings["restore_session"]:
            self.save_session()

    def _content_settled(self):
        self._autosave.start()
        self._auto_detect(self.current())
        self._lsp_sync(self.current())
        self._git_marks_timer.start()
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
        self._lsp_sync(page)
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
        self.lbl_pos.setText(f"Ln : {cur.blockNumber() + 1:,}   Col : {cur.positionInBlock() + 1}   Sel : {sel_chars} | {sel_lines}"
                             + (f"   {len(page.extra_cursors) + 1} cursors" if page.extra_cursors else ""))
        self.lbl_eol.setText({"\r\n": "Windows (CR LF)", "\n": "Unix (LF)", "\r": "Old Mac (CR)"}[page.eol])
        self.lbl_enc.setText(page.encoding.replace("UTF-8 with BOM", "UTF-8 BOM"))
        self.lbl_mode.setText("OVR" if page.overwriteMode() else "INS")
        a = self.lang_actions.get(page.lang.name)
        if a:
            a.setChecked(True)
        self.a_auto_lang.setChecked(bool(getattr(page, "lang_auto", False)))
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
                     "line": cur.blockNumber() + 1, "col": cur.positionInBlock(), "scroll": p.verticalScrollBar().value(), "auto": p.lang_auto,
                     "bookmarks": [b.blockNumber() + 1 for b in p._bookmarked_blocks()]}
            if self._modified(p) or (not p.path and p.length()):
                text = p.toPlainText()
                if len(text) <= budget and len(text) <= session.MAX_BACKUP_DOC:
                    budget -= len(text)
                    entry["text"] = text
                    entry["modified"] = self._modified(p)
            items.append(entry)
        data = {"version": VERSION, "items": items, "current": self.tabs.currentIndex(), "untitled": self._untitled,
                "workspace": self.workspace.root}
        return session.save(data)

    def _restore_entry(self, entry):
        """Brings one saved tab back. -> the page, or None."""
        p = entry.get("path")
        page = None
        try:
            if "text" in entry:
                ed = self._make_editor()
                ed.title = entry.get("title") or f"new {self._untitled + 1}"
                ed.path = p if p and os.path.isfile(p) else None
                ed.encoding = entry.get("encoding", "UTF-8")
                ed.eol = entry.get("eol", "\r\n")
                ed.lang_auto = bool(entry.get("auto", not p))
                if ed.path:                                       # language first, text second: the text is coloured once
                    ed.detect_language()
                else:
                    ed.set_language(lang_by_name(entry.get("lang", "Plain text")))
                ed.setPlainText(entry["text"])
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
            if page is not None and not page.is_large:
                page.goto_line(entry.get("line", 1), entry.get("col", 0))
                page.verticalScrollBar().setValue(entry.get("scroll", 0))
                for ln in entry.get("bookmarks", []):
                    page.toggle_bookmark(page.document().findBlockByNumber(ln - 1))
        except (OSError, ValueError, KeyError):
            return None
        return page

    def _restore_finish(self, data, opened):
        self._restoring = False
        if opened:
            self.tabs.setCurrentIndex(max(0, min(int(data.get("current", 0)), self.tabs.count() - 1)))
        self._update_all()
        self._refresh_documents_now()
        self.refresh_git()
        util.startup_log(f"session restored: {opened} tabs")

    def restore_session(self):
        """Restores every saved tab in one go (used by tests; the app itself uses restore_session_async)."""
        data = session.load()
        if not data:
            return False
        self._untitled = int(data.get("untitled", 0))
        self._restoring = True
        opened = sum(1 for entry in data.get("items", []) if self._restore_entry(entry) is not None)
        self._restore_finish(data, opened)
        return opened > 0

    def restore_session_async(self, done=None):
        """Restores the saved tabs one at a time with the window already on screen, so it stays responsive however many (or how
        big) the tabs are. `done()` is called when they are all back."""
        data = session.load()
        if not data or not data.get("items"):
            if done:
                done()
            return False
        self._untitled = int(data.get("untitled", 0))
        self._restoring = True
        queue = list(data["items"])
        total = len(queue)
        state = {"opened": 0}

        def step():
            if not queue:
                self._restore_finish(data, state["opened"])
                if done:
                    done()
                return
            entry = queue.pop(0)
            self.flash(f"Restoring your tabs...  {total - len(queue)} of {total}")
            t0 = time.perf_counter()
            page = self._restore_entry(entry)
            state["opened"] += page is not None
            util.startup_log(f"  tab {total - len(queue)}/{total} {entry.get('title') or os.path.basename(entry.get('path') or '?')}: "
                             f"{(time.perf_counter() - t0) * 1000:.0f} ms")
            QTimer.singleShot(0, step)
        QTimer.singleShot(0, step)
        return True

    def closeEvent(self, e: QCloseEvent):
        self.find_dialog.stop()
        for c in self.lsp_clients.values():
            c.stop()
        if self.settings["restore_session"]:
            self.save_session()
        else:
            for p in self.all_tabs():
                self.tabs.setCurrentWidget(p)
                if self._modified(p) and not self.close_tab(p, force=False):
                    e.ignore()
                    return
        self.settings["geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.settings["maximized"] = self.isMaximized() or self.isFullScreen()
        self.settings.save()
        for p in self.all_tabs():
            if p.is_large:
                p.close_file()
        e.accept()
