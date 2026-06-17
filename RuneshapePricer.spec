# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for RuneshapePricer.

Collecting the pywinrt (winrt-*) projection packages reliably is the tricky
part -- winocr imports winrt.windows.media.ocr etc. from several separate
distributions that all share the `winrt` namespace. We collect_all the whole
namespace plus the runtime, and add the exact submodules as hidden imports.
"""

from PyInstaller.utils.hooks import collect_all

datas = [("exalt.png", "."), ("divine.png", ".")]  # currency orb icons
binaries = []
hiddenimports = ["PIL.ImageTk"]

for pkg in ("winrt", "winocr", "mss", "pystray", "keyboard", "PIL"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # keep building even if one package has no data
        print(f"[spec] collect_all({pkg!r}) note: {exc!r}")

# Exact winrt submodules winocr touches (belt-and-suspenders for the namespace).
hiddenimports += [
    "winrt.runtime",
    "winrt.windows.media.ocr",
    "winrt.windows.globalization",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage.streams",
    "winrt.windows.foundation",
    "winrt.windows.foundation.collections",
    "winrt._winrt",
]

a = Analysis(
    ["main.py"],
    pathex=[],
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
    console=False,          # no console window; logs go to runeshape_pricer.log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
