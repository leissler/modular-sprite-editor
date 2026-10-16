# -*- mode: python ; coding: utf-8 -*-
# The SGDK exporter as one console executable (export_megadrive / export_megadrive.exe), for the release and the Windows kit.
# It finds examples/ next to itself (see REPO_ROOT in export_megadrive.py).

a = Analysis(
    ['examples/megadrive/tools/export_megadrive.py'],
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
    name='export_megadrive',
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
