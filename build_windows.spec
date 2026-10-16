# -*- mode: python ; coding: utf-8 -*-

import sys

block_cipher = None

# The editor runs every console's exporter itself (File ▸ Export): console_exports lists them.
sys.path.insert(0, SPECPATH)
import console_exports  # noqa: E402

a = Analysis(
    ['app.py'],
    pathex=['tools'] + console_exports.tools_folders(),  # gui_smoke: the --smoke-test self-test; every console's exporter
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('assets', 'assets'),
    ],
    hiddenimports=['wx.lib.agw.flatnotebook', 'app', 'gui_smoke'] + console_exports.modules(),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy'],  # unused; wxPython and Pillow pull it in (35 MB)
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ModularSpriteEditor',
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
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)
