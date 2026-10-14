"""Keep native desktop input methods without the unused QML keyboard."""
from pathlib import Path
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
binaries = [(source, target) for source, target in binaries
            if 'virtualkeyboard' not in Path(source).name.lower()
            and Path(source).name.lower() not in ('qpdf.dll', 'libqpdf.so', 'libqpdf.dylib')]
