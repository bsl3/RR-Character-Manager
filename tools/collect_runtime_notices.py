"""Collect license texts of the installed runtime used for a local EXE build."""
from pathlib import Path
import importlib.metadata as metadata
from urllib.request import urlopen
import shutil

root=Path(__file__).resolve().parents[1]/'THIRD_PARTY_NOTICES';root.mkdir(exist_ok=True)
for name in ('numpy','Pillow','PySide6','PySide6_Essentials','PySide6_Addons','shiboken6','certifi'):
    dist=metadata.distribution(name)
    dest=root/name;dest.mkdir(exist_ok=True)
    for file in dist.files or []:
        if '.dist-info/' in str(file) and 'license' in str(file).lower() and file.locate().is_file():
            shutil.copy2(file.locate(),dest/file.name)
    (dest/'package.txt').write_text(f'{name} {dist.version}\nLicense metadata: {dist.metadata.get("License","")}\n',encoding='utf-8')
for label,url in (
    ('LGPL-3.0-only.txt','https://raw.githubusercontent.com/spdx/license-list-data/main/text/LGPL-3.0-only.txt'),
    ('GPL-3.0-only.txt','https://raw.githubusercontent.com/spdx/license-list-data/main/text/GPL-3.0-only.txt')):
    if not (root/label).is_file():
        (root/label).write_bytes(urlopen(url,timeout=20).read())
