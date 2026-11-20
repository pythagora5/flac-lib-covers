# PyInstaller spec – builds "dist/FLAC Cover Fixer.app".  Run via scripts/build_app.sh.
# -*- mode: python ; coding: utf-8 -*-
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

APP = "FLAC Cover Fixer"
ICON = "assets/AppIcon.icns"

a = Analysis(
    ["scripts/launch.py"],
    pathex=["."],
    hiddenimports=collect_submodules("keyring.backends"),
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP, console=False,
          target_arch="arm64" if sys.platform == "darwin" else None)
coll = COLLECT(exe, a.binaries, a.datas, name=APP)
app = BUNDLE(
    coll,
    name=f"{APP}.app",
    icon=ICON if os.path.exists(ICON) else None,
    bundle_identifier="local.flaccovers.app",
    info_plist={
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "13.0",
        "NSRemovableVolumesUsageDescription":
            "FLAC Cover Fixer reads your music drive to check and write album artwork.",
    },
)
