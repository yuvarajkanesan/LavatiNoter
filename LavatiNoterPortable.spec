# PyInstaller spec for the portable edition: ONE file, dist\\LavatiNoter-Portable.exe (no installer, no extra files).
# Run through make_portable.bat. Same program as LavatiNoter.exe; it keeps its data beside the exe (see lavatinoter/util.py).
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

sys.path.insert(0, os.path.abspath("tools"))
import trim  # noqa: E402

datas = [("fonts", "fonts"), ("assets", "assets"), ("sample_plugins", "sample_plugins"), ("builtin_plugins", "builtin_plugins")] + collect_data_files("spellchecker")

a = Analysis(
    ["main.py"],
    pathex=["."],
    datas=datas,
    excludes=["PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtPdf",
              "PySide6.QtOpenGL", "PySide6.QtDBus", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtMultimedia",
              "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtSensors",
              "PySide6.QtSvg", "tkinter", "PIL", "numpy", "pytest"],
)
a.binaries = trim.keep(a.binaries)
a.datas = trim.keep(a.datas)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="LavatiNoter-Portable", icon="assets/lavatinoter.ico", console=False,
          version="installer/generated/version_LavatiNoter.txt", upx=False)
