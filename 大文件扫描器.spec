# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path
import subprocess

project = Path(SPECPATH)
helper = project / 'build' / 'trash-helper'
helper.parent.mkdir(exist_ok=True)
subprocess.run(['/usr/bin/xcrun', 'swiftc', '-O', '-target', 'arm64-apple-macos13.0',
                '-module-cache-path', str(project / 'build' / 'swift-cache'),
                str(project / 'trash_helper.swift'), '-o', str(helper)], check=True)

a = Analysis(
    ['大文件扫描器.py'],
    pathex=[],
    binaries=[(str(helper), '.')],
    datas=[],
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
    [],
    exclude_binaries=True,
    name='大文件扫描器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='大文件扫描器',
)
app = BUNDLE(
    coll,
    name='大文件扫描器.app',
    icon=None,
    bundle_identifier='local.safediskscanner.app',
    info_plist={'CFBundleShortVersionString': '1.6.0', 'CFBundleVersion': '1.6.0'},
)
