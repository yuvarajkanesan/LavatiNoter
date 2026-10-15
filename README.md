# LavatiNoter

A fast, local-first text and code editor for Windows (Notepad++ style), built with Python and PySide6.

- Tabs, syntax colours (Python, JS/TS, JSON, HTML/XML, CSS, YAML, INI, Markdown, SQL, C-family, shell, logs), bookmarks,
  smart highlight, bracket matching, function list, minimap, folder workspace.
- Find / Replace / Find in Files / Mark with Normal, Extended and Regex modes; results panel with highlighted hits.
- **Large file mode**: files above the limit (default 64 MB) open instantly read-only in a small memory window, with a
  background line index, Go To by line / offset / percent, streaming Find and "Make editable copy...".
- **Picture paste**: Ctrl+V (or Ctrl+Shift+V) with an image on the clipboard saves a PNG next to the document
  (`images/`) and shows it inline; the link is written as Markdown / HTML / CSS / plain path by language. Hover a link for a
  preview, see all pictures in the Images panel. Dropping image files does the same.
- Session restore with unsaved-text backup, external-change detection, single instance, encodings and EOL conversion.

## Run / build
```
pip install -r requirements.txt
python main.py [files...]
python main.py --selftest
python -m unittest discover tests
build.bat            # PyInstaller build + self-test of the packaged exe + dist\LavatiNoter-Setup.exe (Inno Setup 6)
```
Settings and session backups live in `%APPDATA%\LavatiNoter`. Code signing: set `LAVATI_SIGNTOOL` (see `build.bat`).
