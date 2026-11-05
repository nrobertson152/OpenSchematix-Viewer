# -*- mode: python ; coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
# PyInstaller spec: one folder with openschematix-viewer(.exe). Build: pyinstaller packaging/osviewer.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

here = os.path.abspath(SPECPATH)
datas = collect_data_files("openschematix") + collect_data_files("osviewer")
hidden = collect_submodules("openschematix") + collect_submodules("osviewer")
a = Analysis([os.path.join(here, "entry", "viewer.py")], pathex=[os.path.dirname(here)], datas=datas,
             hiddenimports=hidden, excludes=["PySide6", "PyQt5", "PyQt6"])
pyz = PYZ(a.pure, a.zipped_data)
icon = None
for d in datas:
    if d[0].endswith("openschematix.ico"):
        icon = d[0]
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="openschematix-viewer", console=False, upx=False,
          icon=icon)
COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="OpenSchematix-Viewer")
