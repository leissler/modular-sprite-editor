# -*- mode: python ; coding: utf-8 -*-

import os
import re

block_cipher = None

# The version from app.py, also for the app's Info.plist (Finder ▸ Get Info).
with open(os.path.join(SPECPATH, 'app.py'), encoding='utf-8') as source:
    APP_VERSION = re.search(r'^APP_VERSION = "(.*)"', source.read(), re.M).group(1)

a = Analysis(
    ['app.py'],
    pathex=['tools', 'examples/megadrive/tools', 'examples/snes/tools'],  # gui_smoke: the --smoke-test self-test; the Mega Drive and SNES exporters
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('assets', 'assets'),
    ],
    hiddenimports=['PIL._tkinter_finder', 'app', 'gui_smoke', 'export_megadrive', 'export_snes'],
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
    [],
    exclude_binaries=True,
    name='ModularSpriteEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ModularSpriteEditor',
)

app = BUNDLE(
    coll,
    name='ModularSpriteEditor.app',
    icon='assets/icon.icns',
    bundle_identifier='com.martinth.modularspriteeditor',
    version=APP_VERSION,
)
