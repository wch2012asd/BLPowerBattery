# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path

project_root = Path(SPECPATH)


a = Analysis(
    [str(project_root / 'src' / 'blpower' / 'app.py')],
    pathex=[str(project_root / 'src')],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Qt 6.11 uses the Windows system ICU. Some development environments also put
# Poppler's incompatible ICU 78 on PATH; PyInstaller can accidentally collect
# that copy and make QtCore fail with ERROR_PROC_NOT_FOUND. Never bundle it.
a.binaries = [entry for entry in a.binaries
              if entry[0].casefold() not in {"icuuc.dll", "icudt78.dll"}]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BLPowerBattery',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    version=str(project_root / 'scripts' / 'windows_version_info.txt'),
    codesign_identity=None,
    entitlements_file=None,
    icon=[str(project_root / 'assets' / 'app.ico')],
)
