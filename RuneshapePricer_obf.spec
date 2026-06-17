# -*- mode: python ; coding: utf-8 -*-
"""Obfuscated build: PyInstaller over PyArmor-obfuscated sources in _obf/.

Because PyArmor obfuscation replaces every module body with an encrypted blob,
PyInstaller's import analysis sees nothing -- so every module our code imports
(ours, stdlib, third-party) must be declared explicitly here.
"""
import os
import sys

OBF = os.path.abspath("_obf")
sys.path.insert(0, OBF)

from PyInstaller.utils.hooks import collect_all

datas = [("exalt.png", "."), ("divine.png", ".")]  # currency orb icons
binaries = []
hiddenimports = ["PIL.ImageTk"]

for pkg in ("winrt", "winocr", "mss", "pystray", "keyboard", "PIL",
            "pyarmor_runtime_000000"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:
        print(f"[spec] collect_all({pkg!r}): {exc!r}")

# winrt projection submodules winocr touches
hiddenimports += [
    "winrt.runtime", "winrt.windows.media.ocr", "winrt.windows.globalization",
    "winrt.windows.graphics.imaging", "winrt.windows.storage.streams",
    "winrt.windows.foundation", "winrt.windows.foundation.collections",
    "winrt._winrt",
]

# Our (obfuscated) modules -- invisible to analysis, so list them.
hiddenimports += [
    "runeshape_pricer", "runeshape_pricer.app", "runeshape_pricer.config",
    "runeshape_pricer.prices", "runeshape_pricer.parsing",
    "runeshape_pricer.capture", "runeshape_pricer.ocr",
    "runeshape_pricer.overlay", "runeshape_pricer.licensing",
    "runeshape_pricer.tray", "runeshape_pricer.settings_ui",
    "runeshape_pricer.icons", "runeshape_pricer.i18n",
    "pyarmor_runtime_000000",
]

# Stdlib modules our obfuscated code imports (also hidden from analysis).
hiddenimports += [
    "json", "dataclasses", "difflib", "threading", "time", "queue", "io",
    "re", "unicodedata", "ctypes", "hashlib", "uuid", "winreg", "asyncio",
    "urllib", "urllib.parse", "urllib.request", "urllib.error",
    "tkinter", "tkinter.simpledialog", "tkinter.messagebox", "tkinter.ttk",
    "tkinter.font",
]

a = Analysis(
    [os.path.join(OBF, "main.py")],
    pathex=[OBF],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["cv2", "fastapi", "uvicorn", "numpy.testing"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="RuneshapePricer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
