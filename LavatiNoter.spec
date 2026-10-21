# PyInstaller spec: LavatiNoter.exe (windowed app). Run through build.bat.
from PyInstaller.utils.hooks import collect_data_files

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
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="LavatiNoter", icon="assets/lavatinoter.ico", console=False,
          version="installer/generated/version_LavatiNoter.txt")
coll = COLLECT(exe, a.binaries, a.datas, name="LavatiNoter")
