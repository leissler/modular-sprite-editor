# -*- mode: python ; coding: utf-8 -*-
# The SNES exporter as one console executable (export_snes / export_snes.exe), for the release and the Windows kit.
# It finds examples/ next to itself (see REPO_ROOT in export_snes.py).

a = Analysis(
    ['examples/snes/tools/export_snes.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['wx', 'tkinter', 'numpy'],
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
    name='export_snes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
