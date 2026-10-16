"""Collections of complete mkchara packages, validated without extracting ZIP paths."""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import io
import json
import os
import tempfile
import zipfile
from .mkchara import build_package, read_package, zip_members, safe_path, MAX_TOTAL, MAX_MANIFEST

FORMAT = 'mkpack'
VERSION = 1
MAX_CHARACTERS = 500


@dataclass
class CharacterPackPackage:
    name: str
    characters: list  # (member path, mkchara bytes, character metadata)

    def stage(self, directory):
        directory = Path(directory)
        paths = []
        for number, (_, payload, _) in enumerate(self.characters, 1):
            target = directory / f'{number:04d}.mkchara'
            target.write_bytes(payload)
            paths.append(target)
        return paths


def nested_size(payload):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = zip_members(archive)
        return sum(info.file_size for info in members.values())


def read_pack(source):
    try:
        with zipfile.ZipFile(source) as archive:
            members = zip_members(archive, max_file=MAX_TOTAL)
            manifest_info = members.get('manifest.json')
            if manifest_info is None or manifest_info.file_size > MAX_MANIFEST:
                raise ValueError('Missing or oversized mkpack manifest')
            manifest = json.loads(archive.read(manifest_info))
            if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or type(manifest.get('version')) is not int or manifest.get('version') != VERSION:
                raise ValueError('Unsupported mkpack format or version')
            name = manifest.get('name')
            records = manifest.get('characters')
            if not isinstance(name, str) or not name.strip() or len(name) > 200:
                raise ValueError('Invalid character pack name')
            if not isinstance(records, list) or not 1 <= len(records) <= MAX_CHARACTERS:
                raise ValueError('A character pack must contain 1–500 characters')
            seen = {'manifest.json'}
            characters = []
            total = 0
            for record in records:
                if not isinstance(record, dict):raise ValueError('Invalid character pack entry')
                path = safe_path(record.get('path'))
                if not path.startswith('characters/') or not path.endswith('.mkchara') or path in seen:
                    raise ValueError('Invalid or duplicate mkchara member: ' + path)
                seen.add(path)
                if path not in members:raise ValueError('Missing character package: ' + path)
                payload = archive.read(members[path])
                if hashlib.sha256(payload).hexdigest() != record.get('sha256'):
                    raise ValueError('Character package checksum mismatch: ' + path)
                total += nested_size(payload)
                if total > MAX_TOTAL:raise ValueError('Character pack exceeds 1 GiB unpacked')
                package = read_package(io.BytesIO(payload))
                characters.append((path, payload, package.character))
            if set(members) != seen:raise ValueError('Unlisted files in character pack')
            return CharacterPackPackage(name.strip(), characters)
    except (zipfile.BadZipFile, UnicodeError, KeyError, TypeError, RuntimeError, NotImplementedError) as error:
        raise ValueError('Invalid character pack: ' + str(error)) from error


def write_pack(target, pack, keys, name):
    keys = list(keys)
    if len(keys) != len(set(keys)) or not 2 <= len(keys) <= MAX_CHARACTERS:
        raise ValueError('Select 2–500 different characters to export as a pack')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 200:
        raise ValueError('Enter a pack name of at most 200 characters')
    target = Path(target).absolute()
    if target.suffix.lower() != '.mkpack' or target.is_symlink():
        raise ValueError('Choose a regular .mkpack output file')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.mkpack-', delete=False) as stage:
            temporary = Path(stage.name)
        manifest = {'format': FORMAT, 'version': VERSION, 'name': name.strip(), 'characters': []}
        total = 0
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_STORED) as archive:
            for number, (code, slot) in enumerate(keys, 1):
                payload = build_package(pack, code, slot)
                total += nested_size(payload)
                if total > MAX_TOTAL:raise ValueError('Character pack exceeds 1 GiB unpacked')
                path = f'characters/{number:04d}-{code}-{slot}.mkchara'
                archive.writestr(path, payload)
                manifest['characters'].append({'path': path, 'sha256': hashlib.sha256(payload).hexdigest()})
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False).encode('utf-8'))
        if temporary.stat().st_size > MAX_TOTAL:raise ValueError('Character pack exceeds 1 GiB')
        read_pack(temporary)
        os.replace(temporary, target)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
