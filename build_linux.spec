# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['tools', 'examples/megadrive/tools', 'examples/snes/tools'],  # gui_smoke: the --smoke-test self-test; the Mega Drive and SNES exporters
    binaries=[],
    datas=[
        ('ui', 'ui'),
        ('assets', 'assets'),
    ],
    hiddenimports=['wx.lib.agw.flatnotebook', 'PIL._tkinter_finder', 'app', 'gui_smoke', 'export_megadrive', 'export_snes'],
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
    strip=True,  # wxPython's Linux wheel has debug symbols (wx/_core alone 179 MB)
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
