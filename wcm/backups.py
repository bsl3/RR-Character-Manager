"""External, complete Patches snapshots and transactional restores."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

FORMAT='rrcm-patches-backup/1'


def default_root():
    return Path(os.environ.get('RRCM_BACKUP_ROOT',Path.home()/'RR Character Manager Backups')).expanduser().resolve()


def validate_root(root,installation,patches,assets=None):
    root=Path(root).expanduser().resolve()
    protected=[Path(installation).resolve(),Path(patches).resolve()]
    if assets:protected.append(Path(assets).resolve())
    if any(root==p or root.is_relative_to(p) for p in protected):
        raise ValueError('Choose a backup location outside the RR installation.')
    return root


def files(root):
    root=Path(root)
    if not root.exists():return []
    result=[]
    pending=[root]
    while pending:
        path=pending.pop()
        info=path.lstat()
        if path.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('Patches snapshots cannot contain links: '+str(path))
        if path.is_file():result.append(path)
        elif path.is_dir():pending.extend(path.iterdir())
    return result


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def snapshot(patches,root,description='Patches backup'):
    patches=Path(patches).resolve();root=validate_root(root,patches.parent,patches);root.mkdir(parents=True,exist_ok=True)
    paths=files(patches)
    token=datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S_%f')+'-'+uuid.uuid4().hex[:8]
    dest=root/(patches.parent.name+'-Patches-'+token)
    dest.mkdir()
    try:
        folder=dest/'Patches';folder.mkdir()
        hashes={}
        if patches.exists():
            for directory in patches.rglob('*'):
                if directory.is_dir():(folder/directory.relative_to(patches)).mkdir(parents=True,exist_ok=True)
        for path in paths:
            relative=path.relative_to(patches);target=folder/relative;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,target);hashes[relative.as_posix()]=digest(target)
            if hashes[relative.as_posix()]!=digest(path):raise ValueError('Patches changed while creating the backup. Try again.')
        if set(paths)!=set(files(patches)):raise ValueError('Patches changed while creating the backup. Try again.')
        (dest/'manifest.json').write_text(json.dumps({'format':FORMAT,'description':description,
            'created':datetime.datetime.now().isoformat(),'source':str(patches),
            'existed':patches.exists(),'files':hashes},indent=2),encoding='utf8')
    except Exception:
        shutil.rmtree(dest);raise
    return dest


def inspect(folder):
    folder=Path(folder).resolve()
    data=json.loads((folder/'manifest.json').read_text(encoding='utf8'))
    if data.get('format')!=FORMAT or not isinstance(data.get('files'),dict):raise ValueError('Not a Patches backup')
    actual={p.relative_to(folder/'Patches').as_posix():digest(p)
            for p in files(folder/'Patches')}
    if actual!=data['files']:raise ValueError('Backup files are missing or changed; nothing was restored.')
    return data


def history(root):
    result=[]
    if Path(root).is_dir():
        for path in Path(root).iterdir():
            try:
                data=json.loads((path/'manifest.json').read_text(encoding='utf8'))
                if data.get('format')==FORMAT:result.append((path,data))
            except (OSError,ValueError):pass
    return sorted(result,key=lambda row:row[1].get('created',''),reverse=True)


def restore(folder,patches,root):
    folder=Path(folder).resolve();patches=Path(patches).resolve();inspect(folder)
    patches.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rrcm-restore-',dir=patches.parent) as temporary:
        stage=Path(temporary);incoming=stage/'incoming';previous=stage/'previous'
        shutil.copytree(folder/'Patches',incoming)
        had=patches.exists()
        try:
            if had:patches.rename(previous)
            incoming.rename(patches)
        except Exception:
            if previous.exists() and not patches.exists():previous.rename(patches)
            raise
    return None
