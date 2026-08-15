from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)
hidden_imports = collect_submodules("uvicorn") + collect_submodules("keyring.backends")

a = Analysis(
    [str(ROOT / "backend" / "launcher.py")],
    pathex=[str(ROOT / "backend")],
    binaries=[],
    datas=[(str(ROOT / "frontend" / "dist"), "frontend/dist")],
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Savox76Giveaway",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)
