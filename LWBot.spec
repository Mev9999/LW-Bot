# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['bagger_detector.py'],
    pathex=[],
    binaries=[],
    datas=[('Module\\data', 'Module\\data'), ('bagger_icon.png', '.'), ('bn_close_x.png', '.'), ('bn_blue_btn.png', '.'), ('golden_egg.png', '.'), ('Module\\i18n.py', 'Module'), ('Module\\config.py', 'Module'), ('Module\\log.py', 'Module'), ('Module\\telebot.py', 'Module'), ('Module\\ui_recipients.py', 'Module'), ('Module\\version.py', 'Module')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='LWBot',
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
)
