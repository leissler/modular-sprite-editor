# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['tools'],  # gui_smoke: the --smoke-test self-test
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('assets', 'assets'),
    ],
    hiddenimports=['PIL._tkinter_finder', 'app', 'gui_smoke'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
)
