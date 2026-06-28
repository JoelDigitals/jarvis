# PyInstaller-Spec für Jarvis.exe — Build mit: pyinstaller jarvis.spec
import sys
from pathlib import Path

BASE = Path(SPECPATH)

datas = [
    (str(BASE / "core" / "prompt.txt"), "core"),
    (str(BASE / "server" / "templates"), "server/templates"),
    (str(BASE / "server" / "static"), "server/static"),
]
if (BASE / "face.png").exists():
    datas.append((str(BASE / "face.png"), "."))
if (BASE / "version.txt").exists():
    datas.append((str(BASE / "version.txt"), "."))

a = Analysis(
    ["main.py"],
    pathex=[str(BASE)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "google.genai", "google.generativeai",
        "PyQt6", "PyQt6.QtCore", "PyQt6.QtGui", "PyQt6.QtWidgets",
        "win10toast", "pycaw", "comtypes", "pywinauto",
        "discord", "speech_recognition",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Jarvis",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # auf False setzen, sobald der Build stabil läuft (versteckt das Konsolenfenster)
    icon=str(BASE / "icon.ico") if (BASE / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Jarvis",
)
