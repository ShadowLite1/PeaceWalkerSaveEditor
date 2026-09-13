# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


project_dir = Path(SPECPATH)
datas = [
    (str(project_dir / "portrait_assets"), "portrait_assets"),
    (str(project_dir / "staff_tag_assets"), "staff_tag_assets"),
    (str(project_dir / "quote_assets"), "quote_assets"),
]

voice_previews = project_dir / "voice_previews"
if voice_previews.exists():
    datas.append((str(voice_previews), "voice_previews"))

quote_plugin = project_dir / "quote_plugin" / "dist" / "PeaceWalkerCustomQuotes.asi"
if quote_plugin.exists():
    datas.append((str(quote_plugin), "quote_plugin"))

icon_path = project_dir / "app_icon.ico"
if icon_path.exists():
    datas.append((str(icon_path), "."))

a = Analysis(
    ["soldier_editor.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
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
    name="PeaceWalkerSoldierEditor_PTB",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="PeaceWalkerSoldierEditor_PTB",
)
