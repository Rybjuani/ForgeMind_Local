# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec para ForgeMind Local.

Entry point: ../run.py (NO app/__main__.py ni app/main.py directamente:
el bootloader PyInstaller ejecuta el entry como script top-level, lo que
romperia los imports relativos dentro de `app.*`. El shim en run.py hace
import absoluto desde project root, lo que setea __package__="app").

Build:
    pyinstaller forgemind.spec --noconfirm

Output:
    dist/ForgeMind.exe         (single file, ~70-90 MB)
    dist/ForgeMind/            (alternativa onedir, descomentar EXE abajo)
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve()

# Hidden imports: PyQt6 entero + submodulos que PyInstaller a veces no detecta.
# psutil y urllib ya son stdlib-friendly, pero por las dudas los listamos.
# app.chat_history se importa lazy (from . import chat_history dentro de
# metodos de MainWindow) → PyInstaller no lo detecta via analisis estatico,
# hay que listarlo explicitamente.
hidden = (
    collect_submodules("PyQt6")
    + [
        "psutil",
        "urllib.request",
        "urllib.error",
        "app.chat_history",
        # NO incluimos llama_cpp ni cryptography: son opcionales y agregan MBs.
    ]
)

# Binarios / data
datas = []
# Bundled fonts (Newsreader variable TTF) — without this the .exe
# falls back to generic sans and the mockup's serif identity is lost.
# The destination "app/assets/fonts" mirrors the source layout so
# _load_bundled_fonts() resolves the same Path at runtime.
_fonts_dir = ROOT / "app" / "assets" / "fonts"
if _fonts_dir.is_dir():
    datas.append((str(_fonts_dir), "app/assets/fonts"))

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Excluir modulos pesados que no usamos. Reduce 30-60 MB.
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PyQt6.QtNetwork",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtMultimedia",
        "PyQt6.Qt3DCore",
        "PyQt6.Qt3DRender",
        "PyQt6.QtBluetooth",
        "PyQt6.QtNfc",
        "PyQt6.QtPositioning",
        "PyQt6.QtSensors",
        "PyQt6.QtSerialPort",
        "PyQt6.QtSql",
        "PyQt6.QtTest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ForgeMind",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # GUI: NO mostrar ventana de consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=str(ROOT / "assets" / "forgemind.ico") if (ROOT / "assets" / "forgemind.ico").exists() else None,
)

# Si queres --onedir en vez de --onefile, comentá el EXE de arriba y
# descomenta el COLLECT de abajo. Borrá el EXE() para evitar duplicar.
# coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=True, upx_exclude=[], name="ForgeMind")