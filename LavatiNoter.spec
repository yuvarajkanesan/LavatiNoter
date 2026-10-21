# PyInstaller spec: LavatiNoter.exe (windowed app). Run through build.bat.
from PyInstaller.utils.hooks import collect_data_files

datas = [("fonts", "fonts"), ("assets", "assets"), ("sample_plugins", "sample_plugins"), ("builtin_plugins", "builtin_plugins")] + collect_data_files("spellchecker")

# Plugins are loaded from files at run time, so PyInstaller cannot see what they import: ship the standard modules they commonly use.
PLUGIN_MODULES = ["base64", "binascii", "calendar", "collections", "csv", "datetime", "decimal", "difflib", "fnmatch", "fractions", "gzip",
                  "hashlib", "hmac", "html", "html.parser", "io", "itertools", "json", "math", "random", "re", "secrets", "statistics",
                  "string", "textwrap", "unicodedata", "urllib.parse", "uuid", "xml.etree.ElementTree", "zlib"]
a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=datas,
    hiddenimports=PLUGIN_MODULES,
    excludes=["PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf",
              "PySide6.QtOpenGL", "PySide6.QtDBus", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtMultimedia",
              "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSensors",
              "PySide6.QtSvg", "tkinter", "PIL", "numpy", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LavatiNoter", icon="assets/lavatinoter.ico", console=False,
          version="installer/generated/version_LavatiNoter.txt")
coll = COLLECT(exe, a.binaries, a.datas, name="LavatiNoter")
