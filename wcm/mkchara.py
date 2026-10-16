"""Slot-independent character packages. ZIP contents are read, never extracted."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from .library import CODE_IDS, CATEGORY_DIR, parse_asset

FORMAT = 'mkchara'
VERSION = 1
MAX_FILE = 128 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
MAX_FILES = 10000


def safe_path(name):
    if not isinstance(name, str) or not name or len(name) > 512 or '\\' in name:
        raise ValueError('Unsafe package path')
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name:
        raise ValueError(f'Unsafe package path: {name}')
    for part in path.parts:
        if (part in ('.', '..') or part.strip(' .') != part or
                any(ord(c) < 32 or c in ':<>"|?*' for c in part) or
                re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])', part.split('.')[0], re.I)):
            raise ValueError(f'Unsafe package path: {name}')
    return name


def zip_members(archive, *, max_file=None):
    if max_file is None:max_file=MAX_FILE
    infos = archive.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_TOTAL:
        raise ValueError('Package exceeds 10,000 members or 1 GiB unpacked')
    members = {}
    seen = set()
    for info in infos:
        name = safe_path(info.filename.rstrip('/') if info.is_dir() else info.filename)
        if name.casefold() in seen:
            raise ValueError(f'Duplicate package path: {name}')
        seen.add(name.casefold())
        mode = (info.external_attr >> 16) & 0o170000
        if mode not in (0, 0o100000, 0o040000) or info.flag_bits & 1:
            raise ValueError('Links, special files and encrypted ZIP members are unsupported')
        if info.file_size > max_file:
            raise ValueError(f'A package member exceeds {max_file // (1024 * 1024)} MiB')
        if not info.is_dir():
            members[name] = info
    return members


def logical_name(asset, code=None):
    """Remove only the parser's slot span; retain vehicle/team/sound identity."""
    filename = PurePosixPath(asset.relpath).name
    if asset.slot_bounds:
        start, end = asset.slot_bounds
        filename = filename[:start-1] + filename[end:]
    unnumbered = parse_asset(filename, source_import=True)
    if unnumbered is None or unnumbered.slot is not None:
        raise ValueError('Cannot normalize resource identity')
    if code is not None:
        end = unnumbered.insert_at
        begin = end - len(unnumbered.code)
        replacement = code.upper() if filename[begin:end].isupper() else code
        filename = filename[:begin] + replacement + filename[end:]
    folder = CATEGORY_DIR[asset.category]
    return f'{folder}/{filename}' if folder else filename


@dataclass
class CharacterPackage:
    character: dict
    assets: list[tuple[str, bytes]]
    sources: list[tuple[str, bytes]]

    def entries(self, code=None):
        if code is None:
            return list(self.assets)
        if code not in CODE_IDS:
            raise ValueError('Unknown base character')
        return [(logical_name(parse_asset(name, source_import=True), code), data)
                for name, data in self.assets]

    def preview_entries(self):
        return list(self.assets) + [('SourceOnly/'+name, data) for name,data in self.sources]


def read_package(source):
    try:
        with zipfile.ZipFile(source) as archive:
            members = zip_members(archive)
            if 'manifest.json' not in members or members['manifest.json'].file_size > MAX_MANIFEST:
                raise ValueError('Missing or oversized mkchara manifest')
            def unique_object(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError(f'Duplicate manifest key: {key}')
                    result[key] = value
                return result
            def invalid_constant(value):
                raise ValueError('Non-finite JSON value: '+value)
            manifest = json.loads(archive.read('manifest.json').decode('utf-8'),
                                  object_pairs_hook=unique_object,
                                  parse_constant=invalid_constant)
            if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or type(manifest.get('version')) is not int or manifest['version'] != VERSION:
                raise ValueError('Unsupported mkchara format/version')
            character = manifest.get('character')
            if not isinstance(character, dict) or character.get('base_character') not in CODE_IDS:
                raise ValueError('Invalid character base')
            for field in ('name', 'author'):
                if not isinstance(character.get(field), str) or len(character[field]) > 4096 or '\x00' in character[field]:
                    raise ValueError(f'Invalid character {field}')
            if not character['name'].strip() or 'slot' in character:
                raise ValueError('Character must have a name and no installed slot')
            metadata = character.get('metadata', {})
            if not isinstance(metadata, dict):
                raise ValueError('Invalid character metadata')
            resources = manifest.get('resources')
            if not isinstance(resources, list) or not resources:
                raise ValueError('Empty package resources')
            assets, sources, referenced, logical = [], [], {'manifest.json'}, set()
            for resource in resources:
                if not isinstance(resource, dict):
                    raise ValueError('Invalid resource record')
                payload_path = safe_path(resource.get('path'))
                name = safe_path(resource.get('name'))
                role = resource.get('role')
                key = (role, name.casefold())
                if role not in ('asset', 'source') or key in logical or payload_path in referenced or payload_path not in members:
                    raise ValueError('Duplicate, missing or invalid resource')
                logical.add(key); referenced.add(payload_path)
                info = members[payload_path]
                if type(resource.get('size')) is not int or resource['size'] != info.file_size:
                    raise ValueError(f'Resource size mismatch: {name}')
                data = archive.read(info)
                if hashlib.sha256(data).hexdigest() != resource.get('sha256'):
                    raise ValueError(f'Resource SHA-256 mismatch: {name}')
                if role == 'asset':
                    asset = parse_asset(name, source_import=True)
                    if (asset is None or asset.slot is not None or asset.code != character['base_character'] or
                            resource.get('category') != asset.category or name != logical_name(asset)):
                        raise ValueError(f'Invalid slot-independent resource: {name}')
                    assets.append((name, data))
                else:
                    sources.append((name, data))
            if referenced != set(members):
                raise ValueError('Package contains undeclared files')
            if sum(parse_asset(n, source_import=True).category == 'Driver' for n, _ in assets) != 1:
                raise ValueError('Package must contain exactly one standalone Driver')
            return CharacterPackage(character, assets, sources)
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, KeyError, TypeError, NotImplementedError) as exc:
        raise ValueError(f'Invalid mkchara package: {exc}') from exc


def build_package(pack, code, slot):
    skin = pack.inventory.skins.get((code, slot))
    if skin is None:
        raise ValueError('Select an installed character')
    if not skin.name.strip():
        raise ValueError('Save a character name before exporting')
    # Reject stale text/editor state rather than exporting mismatched identity.
    relevant = {pack.archive_path, *pack.text_archives,
                *(pack.asset_path(a.relpath) for a in skin.files)}
    folder = pack.patch_directories.get((code, slot))
    if folder is not None:
        relevant.add(folder / pack.PATCH_META_FILENAME)
    for path in relevant:
        if path in pack._snapshot:
            current = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if current != pack._snapshot[path]:
                raise ValueError('Character files changed. Refresh before exporting.')
    assets = []
    for asset in skin.files:
        path = pack.asset_path(asset.relpath)
        if (not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_FILE or
                not (path.resolve().is_relative_to(pack.character) or path.resolve().is_relative_to(pack.patches_path))):
            raise ValueError(f'Missing, linked or oversized resource: {path.name}')
        assets.append((logical_name(asset), path.read_bytes()))
    sources = {}
    folder = pack.patch_directories.get((code, slot))
    bundles = []
    if folder is not None:
        owners = [key for key, parent in pack.patch_directories.items() if parent == folder]
        if len(owners) != 1:
            raise ValueError('Shared character folder has ambiguous auxiliary resource ownership')
        mapped = {pack.asset_path(a.relpath).resolve() for a in skin.files}
        for path in folder.rglob('*'):
            if path.is_symlink() or not path.resolve().is_relative_to(pack.patches_path):
                raise ValueError('Linked character resources cannot be exported')
            if (not path.is_file() or path.resolve() in mapped or path.name == pack.PATCH_META_FILENAME or
                    path.name.lower().endswith('.mkchara') or '.mkchara.bak-' in path.name.lower()):
                continue
            if path.suffix == '.rrcm-source':
                bundles.append(path)
            else:
                name = safe_path(path.relative_to(folder).as_posix())
                if path.stat().st_size > MAX_FILE:
                    raise ValueError('Auxiliary file exceeds 128 MiB')
                sources[name] = path.read_bytes()
    else:
        bundle = pack.character / 'SourceResources' / f'{code}-{slot}-source.rrcm-source'
        if bundle.is_file():
            bundles.append(bundle)
    for bundle in bundles:
        if (bundle.is_symlink() or not (bundle.resolve().is_relative_to(pack.character) or
                                       bundle.resolve().is_relative_to(pack.patches_path))):
            raise ValueError('Linked source bundles cannot be exported')
        with zipfile.ZipFile(bundle) as archive:
            for name, info in zip_members(archive).items():
                if name.casefold() in {n.casefold() for n in sources}:
                    raise ValueError(f'Duplicate auxiliary resource: {name}')
                sources[name] = archive.read(info)
    metadata_source = pack.patch_metadata.get((code, slot), {})
    if folder is None:
        sidecar = pack.character/'SourceResources'/f'{code}-{slot}-metadata.json'
        if sidecar.is_file():
            if sidecar.is_symlink() or sidecar.stat().st_size > MAX_MANIFEST:
                raise ValueError('Unsafe character metadata')
            metadata_source = json.loads(sidecar.read_text(encoding='utf-8'))
            if not isinstance(metadata_source, dict):
                raise ValueError('Invalid character metadata')
    metadata = {key: value for key, value in metadata_source.items()
                if key not in ('base_character', 'slot', 'name', 'author', 'format', 'version')}
    character = {'base_character': code, 'name': skin.name, 'author': skin.author, 'metadata': metadata}
    manifest = {'format': FORMAT, 'version': VERSION, 'character': character, 'resources': []}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        records = [('asset', name, data) for name, data in assets] + [('source', name, data) for name, data in sorted(sources.items())]
        if len(records) + 1 > MAX_FILES or sum(len(data) for _, _, data in records) > MAX_TOTAL - MAX_MANIFEST:
            raise ValueError('Character exceeds package limits')
        for index, (role, name, data) in enumerate(records):
            path = f'resources/{index:05d}{PurePosixPath(name).suffix}'
            record = {'path': path, 'role': role, 'name': name, 'size': len(data),
                      'sha256': hashlib.sha256(data).hexdigest()}
            if role == 'asset':
                record['category'] = parse_asset(name, source_import=True).category
            manifest['resources'].append(record)
            archive.writestr(path, data)
        encoded = json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(encoded) > MAX_MANIFEST:
            raise ValueError('Character manifest exceeds 1 MiB')
        archive.writestr('manifest.json', encoded)
    payload = output.getvalue()
    read_package(io.BytesIO(payload))
    return payload


def write_package(target, payload, *, overwrite=True):
    """Validate the package, back up replacements, and save through a temporary file."""
    read_package(io.BytesIO(payload))
    target = Path(target).absolute()
    if target.suffix.lower() != '.mkchara' or target.is_symlink():
        raise ValueError('Choose a regular .mkchara output file')
    backup = None
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.mkchara-', delete=False) as stage:
            temporary = Path(stage.name)
            stage.write(payload); stage.flush(); os.fsync(stage.fileno())
        read_package(temporary)
        if not overwrite:
            # Do not overwrite a file created by another process while we save.
            from .portable_files import rename_new
            rename_new(temporary, target)
            return None
        if target.exists():
            backup = target.with_name(target.name + '.bak-' + uuid.uuid4().hex[:12])
            shutil.copy2(target, backup)
        os.replace(temporary, target)
        return backup
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
