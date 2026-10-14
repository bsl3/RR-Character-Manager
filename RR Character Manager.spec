# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path
from wcm import __version__

root = Path(SPECPATH)
windows = sys.platform == 'win32'
macos = sys.platform == 'darwin'
name = 'RR character manager ' + __version__

# The app uses Widgets, OpenGL and audio, but not QML, video widgets or PDF.
excludes = [
    'PySide6.QtMultimediaWidgets', 'PySide6.QtQuick', 'PySide6.QtQml',
    'PySide6.QtQuickWidgets', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
    'PySide6.QtDesigner', 'PySide6.QtTest', 'PyQt5', 'PyQt6', 'PySide2',
    'tkinter', 'PIL.AvifImagePlugin', 'PIL._avif', 'PIL.ImageTk',
]
a = Analysis(
    [str(root / 'main.py')], pathex=[str(root)], binaries=[],
    datas=[(str(root / 'assets/base_icons'), 'assets/base_icons'),
           (str(root / 'full-motorcycle-helmet.png'), '.')],
    hiddenimports=[], hookspath=[str(root / 'tools/pyinstaller-hooks')], hooksconfig={}, runtime_hooks=[],
    excludes=excludes, noarchive=False, optimize=1,
)
# QtGui's image-plugin hook also collects PDF support, which no screen uses.
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in ('qpdf.dll', 'libqpdf.so', 'libqpdf.dylib',
                                                    'qt6pdf.dll', 'libqt6pdf.so.6')]
pyz = PYZ(a.pure)
options = dict(name=name, debug=False, bootloader_ignore_signals=False,
               strip=False, upx=False, console=False, disable_windowed_traceback=False)
if windows:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              icon=str(root / 'full-motorcycle-helmet.ico'),
              version=str(root / 'tools/windows_version.txt'), **options)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **options)
    collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=name)
    if macos:
        bundle = BUNDLE(collection, name='RR Character Manager.app',
                        icon=str(root / 'build/release-icon.icns'),
                        bundle_identifier='org.rrcharactermanager.desktop',
                        info_plist={'CFBundleShortVersionString': __version__,
                                    'CFBundleVersion': __version__,
                                    'NSHighResolutionCapable': True})
