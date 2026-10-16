"""Validated, backed-up and rollback-capable character pack edits."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import datetime
import json
import os
import shutil
import tempfile
import uuid
import zipfile
import io
import re
import hashlib
from .textmerge import find_sources, merged_archive, merge_tables, MEMBER, RACE_MEMBER, synchronized_character_text
from .szs import U8Archive
from .bmg import CharacterBMG, Message, name_id, author_id
from .library import CODE_IDS, parse_asset, scan_paths, available_import_variants, select_import_entries, DEFAULT_RESOURCE_VARIANT, preferred_import_code
from .models import ModelCandidate, extract_model_bytes, automatic_driver_candidate, driver_model_role


@dataclass
class EditPlan:
    description: str
    moves: list[tuple[Path, Path]] = field(default_factory=list)
    writes: dict[Path, bytes] = field(default_factory=dict)
    deletes: set[Path] = field(default_factory=set)
    replace_existing: set[Path] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    metadata: list[str] = field(default_factory=list)
    expected: dict[Path, str | None] = field(default_factory=dict)
    character_metadata: dict = field(default_factory=dict)
    names_synchronized: bool = False

    def preview(self) -> str:
        lines = [self.description, '', f'{len(self.moves)} file moves, {len(self.writes)} file writes, {len(self.deletes)} deletions']
        if self.metadata:
            lines += ['', 'Character text changes:', *('  ' + s for s in self.metadata)]
        if self.moves:
            lines += ['', 'File renames:']
            lines += [f'  {src.name}  â†’  {dst.name}' for src,dst in self.moves[:90]]
            if len(self.moves) > 90: lines.append(f'  â€¦ plus {len(self.moves)-90} additional moves')
        if self.replace_existing:
            lines += ['', 'Files being replaced:', *('  '+str(p) for p in sorted(self.replace_existing))]
        if self.deletes:
            lines += ['', 'Files being removed:', *('  '+str(p) for p in sorted(self.deletes))]
        if self.writes:
            lines += ['', 'File updates:']
            lines += [f'  {p.name} ({len(contents):,} bytes)' for p,contents in list(self.writes.items())[:50]]
        if self.warnings:
            lines += ['', 'Warnings:', *('  â€¢ '+warning for warning in self.warnings)]
        return '\n'.join(lines)


class CharacterPack:
    PATCH_BMG_FILENAME = "[message]CharaRR.bmg.replacedassets"
    PATCH_META_FILENAME = "_rr_character.json"
    # UI and race name patches share the character text.
    PATCH_UI_BMG_FILENAME = 'CharacterNames.uiassets.szs'
    PATCH_RACE_BMG_FILENAME = 'CharacterNames.raceassets.szs'
    PATCH_NAMES_DIR = 'CharacterNames'
    RESOURCE_INDEX_NAME = '_rrcm_resources.json'

    def compatibility_report(self):
        """Optional desktop report; never placed among runtime assets."""
        from .library import race_coverage,missing_race_requests
        characters=[]
        for (code,slot),skin in sorted(self.inventory.skins.items()):
            resources=[]
            for asset in skin.files:
                path=self.asset_path(asset.relpath)
                resources.append({'logical':asset.relpath,'role':asset.category,'source':str(path),
                                  'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
            characters.append({'character_id':CODE_IDS[code],'postfix':code,'slot':slot,
                'name_id':name_id(CODE_IDS[code],slot),'author_id':author_id(CODE_IDS[code],slot),
                'name':skin.name,'author':skin.author,'resources':resources,'vehicle_coverage':race_coverage(skin.files),'missing_vehicle_requests':missing_race_requests(code,race_coverage(skin.files))})
        return {'format':'rrcm-compatibility-report/1','deployment_profile':self.deployment_profile,
                'canonical':'message/CharaName.bmg','name_source':'manager merged menu table',
                'text_archives':[str(p) for p in self.text_archives],
                'conflicts':[*self.text_conflicts,*self.metadata_conflicts],
                'orphans':list(self.inventory.orphans),
                'runtime_config_inspected':False,'characters':characters}

    def _resource_index_path(self) -> Path:
        return self.patches_path / self.PATCH_NAMES_DIR / self.RESOURCE_INDEX_NAME

    def _read_resource_index(self) -> dict[str, dict[str, str]]:
        path = self._resource_index_path()
        if not path.is_file():
            return {'distribution': {}, 'patches': {}}
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('format') != 'rrcm-resource-index/1':
            raise ValueError('Invalid manager resource index in CharacterNames/')
        result = {}
        for kind in ('distribution', 'patches'):
            entries = data.get(kind, {})
            if not isinstance(entries, dict):
                raise ValueError('Invalid resource index entries')
            result[kind] = {}
            for logical, physical in entries.items():
                if (not isinstance(logical, str) or parse_asset(logical) is None
                        or not isinstance(physical, str)):
                    raise ValueError('Invalid resource index mapping')
                rel = Path(physical.replace('\\', '/'))
                if (rel.is_absolute() or not rel.parts or '..' in rel.parts
                        or str(rel) in ('', '.') or ':' in physical):
                    raise ValueError('Unsafe resource index target')
                result[kind][logical] = rel.as_posix()
        return result

    @staticmethod
    def _resource_index_bytes(index: dict[str, dict[str, str]]) -> bytes:
        return (json.dumps({'format': 'rrcm-resource-index/1', **index},
                           ensure_ascii=False, indent=2) + '\n').encode('utf-8')

    def _stage_resource_index(self, plan: EditPlan, index: dict[str, dict[str, str]]):
        target = self._resource_index_path()
        plan.writes[target] = self._resource_index_bytes(index)
        if target.exists():
            plan.replace_existing.add(target)

    def _patch_name_archives(self) -> tuple[Path, Path]:
        folder = self.patches_path / self.PATCH_NAMES_DIR
        return (folder / self.PATCH_UI_BMG_FILENAME,
                folder / self.PATCH_RACE_BMG_FILENAME)

    def _legacy_name_archives(self) -> tuple[Path, Path]:
        """Find shared name archives from earlier folder layouts."""
        return (self.patches_path / self.PATCH_UI_BMG_FILENAME,
                self.patches_path / self.PATCH_RACE_BMG_FILENAME)

    @staticmethod
    def _read_name_archive_pair(targets: tuple[Path, Path]) -> bytes | None:
        ui, race = targets
        if ui.is_file() != race.is_file():
            raise ValueError('One CharacterNames name archive is missing. Restore both from a backup.')
        if not ui.is_file():
            return None
        bmg_path = 'message/CharaName.bmg'
        ui_bundle = U8Archive.from_file(ui)
        race_bundle = U8Archive.from_file(race)
        contents = ui_bundle.files.get(bmg_path)
        if contents is None or contents != race_bundle.files.get(bmg_path):
            raise ValueError('UIAssets and RaceAssets character name patches differ')
        return contents


    @staticmethod
    def _safe_folder_name(name: str) -> str:
        """Use the displayed skin name as a portable Windows folder component."""
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')
        if not value or value.split('.')[0].upper() in {
            'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
            *(f'LPT{i}' for i in range(1, 10))
        }:
            value = 'Character_' + value
        return value[:90].rstrip(' .')

    def _character_patch_directory(self, name: str, code: str, slot: int,
                                   *, existing: Path | None = None) -> Path:
        base = self._safe_folder_name(name)
        candidate = self.patches_path / base
        if existing is not None and candidate.name.casefold() == existing.name.casefold():
            return existing
        if candidate.exists():
            candidate = self.patches_path / f'{base} ({code.upper()}-{slot})'
            if existing is None or candidate != existing:
                if candidate.exists():
                    raise ValueError(f'Character patch folder already exists: {candidate.name}')
        return candidate

    @staticmethod
    def _skin_metadata(code: str, slot: int, name: str, author: str) -> bytes:
        return (json.dumps({'format': 'rr-character-manager/1', 'base_character': code,
                            'slot': slot, 'name': name, 'author': author},
                           indent=2, ensure_ascii=False) + '\n').encode('utf-8')

    def _updated_skin_metadata(self, code, slot, name, author, *, source_slot=None):
        meta = dict(self.patch_metadata.get((code, source_slot if source_slot is not None else slot), {}))
        meta.update(json.loads(self._skin_metadata(code, slot, name, author)))
        return (json.dumps(meta, ensure_ascii=False, indent=2) + '\n').encode('utf-8')

    def __init__(self, character_folder: Path, replaced_assets: Path, patches_folder: Path | None = None, *, developer_mode: bool = False, deployment_profile: str = "rr", backup_root: Path | None = None):
        self.developer_mode = bool(developer_mode)
        self.deployment_profile=deployment_profile
        if deployment_profile not in ("rr","wiiloaded","direct"):raise ValueError("Invalid deployment profile")
        self.character = Path(character_folder).expanduser().resolve()
        self.archive_path = Path(replaced_assets).expanduser().resolve()
        self.patches_path = (Path(patches_folder).expanduser().resolve() if patches_folder
                             else self.character.parent / 'Patches')
        if self.patches_path == self.character or self.patches_path.is_relative_to(self.character):
            raise ValueError('Patches must be a separate folder from Character')
        if self.patches_path.exists() and not self.patches_path.is_dir():
            raise ValueError('Patches path must be a directory')
        if not self.character.is_dir():
            raise ValueError('Character directory does not exist')
        if not self.archive_path.is_file():
            raise ValueError('ReplacedAssets.szs does not exist')
        if self.archive_path.name.lower() != 'replacedassets.szs':
            raise ValueError('Select ReplacedAssets.szs, not UIAssets.szs or RaceAssets.szs')
        from .backups import default_root,validate_root
        self.backup_root=validate_root(backup_root or default_root(),self.character.parent,self.patches_path,self.archive_path.parent)
        self.reload()

    def reload(self):
        self.revision = getattr(self, 'revision', 0) + 1
        self.archive = U8Archive.from_file(self.archive_path)
        if 'message/CharaRR.bmg' not in self.archive.files:
            raise ValueError('ReplacedAssets.szs does not contain message/CharaRR.bmg')
        self.distribution_text_paths = self._distribution_name_archives()
        self.patch_bmg_path = self.patches_path / self.PATCH_BMG_FILENAME  # legacy override
        self.base_bmg = CharacterBMG.read(self.archive.files['message/CharaRR.bmg'])
        self.bmg, self.text_conflicts, self.text_archives = find_sources(
            self.patches_path, self.base_bmg.encode(), self.patch_bmg_path,
            self._patch_name_archives())
        self.active_name_archive = 'merged distribution / Patches text (see update preview)'
        # Inventory both legacy flat patches and managed character folders.
        # The stock RR SD patch loader does NOT recursively index these folders.
        self.resource_index = self._read_resource_index()
        self.distribution_assets: dict[str, Path] = {}
        dist_mapping = self.resource_index['distribution']
        patched_mapping = self.resource_index['patches']
        mapped_distribution = {(self.character / physical).resolve() for physical in dist_mapping.values()}
        mapped_patches = {(self.patches_path / physical).resolve() for physical in patched_mapping.values()}
        paths = {}
        for p in self.character.rglob('*'):
            if not p.is_file() or (mapped_distribution and p.resolve() in mapped_distribution):
                continue
            relative = p.relative_to(self.character).as_posix()
            paths[relative.casefold()] = relative
        for logical, physical in dist_mapping.items():
            target = (self.character / physical).resolve()
            if not target.is_relative_to(self.character):
                raise ValueError('Resource index points outside Character/')
            if target.is_file():
                paths[logical.casefold()] = logical
                self.distribution_assets[logical.casefold()] = target
        self._distribution_slot_index = {code:set() for code in CODE_IDS}
        for relative in paths.values():
            asset = parse_asset(relative)
            if asset and asset.category == 'Driver' and asset.slot is not None:
                self._distribution_slot_index[asset.code].add(asset.slot)
        self.distribution_inventory = scan_paths(paths.values(), self.base_bmg)
        self._patch_slot_index = None
        self.patch_assets: dict[str, Path] = {}
        self.rr_icon_sources = {}
        self.patch_directories: dict[tuple[str, int], Path] = {}
        if self.patches_path.is_dir():
            for p in self.patches_path.rglob('*'):
                if not p.is_file() or p.is_symlink():
                    continue
                if mapped_patches and p.resolve() in mapped_patches:
                    continue
                if p.name == self.PATCH_META_FILENAME:
                    try:
                        meta = json.loads(p.read_text(encoding='utf-8'))
                        code, slot = meta['base_character'], int(meta['slot'])
                        if code not in CODE_IDS or not 1 <= slot <= 100:
                            continue
                    except (ValueError, KeyError, TypeError, UnicodeError, json.JSONDecodeError):
                        continue
                    key = (code, slot)
                    if key in self.patch_directories and self.patch_directories[key] != p.parent:
                        raise ValueError(f'Two patch folders claim {code.upper()} slot {slot}')
                    self.patch_directories[key] = p.parent
                    continue
                asset = parse_asset(p.name, source_import=True)
                if asset is None and p.suffix.lower()=='.png':
                    candidate=parse_asset(p.stem+'.tpl',source_import=True)
                    if candidate and candidate.category in ('Portrait','Map') and candidate.slot in self.distribution_slots(candidate.code):asset=candidate
                if asset is None or asset.slot is None:
                    continue
                rel = asset.destination(asset.slot)
                rr_icon=(asset.category in ('Portrait','Map') and asset.slot in self.distribution_slots(asset.code))
                if rr_icon:
                    try:
                        self.rr_icon_bytes(p,asset.category)
                    except (OSError,ValueError):continue
                    self.rr_icon_sources.setdefault(rel.casefold(),[]).append(p)
                    candidates=self.rr_icon_sources[rel.casefold()]
                    candidates.sort(key=lambda q:(q.parent!=self.patches_path/'RRIcons',q.relative_to(self.patches_path).as_posix().casefold()))
                    paths[rel.casefold()]=rel
                    self.patch_assets[rel.casefold()]=candidates[0]
                    continue
                if rel.casefold() in self.patch_assets:
                    raise ValueError(f'Multiple Patches files provide {rel}: '
                                     f'{self.patch_assets[rel.casefold()]} and {p}')
                paths[rel.casefold()] = rel
                self.patch_assets[rel.casefold()] = p
        for logical, physical in patched_mapping.items():
            target = (self.patches_path / physical).resolve()
            if not target.is_relative_to(self.patches_path):
                raise ValueError('Resource index points outside Patches/')
            if target.is_file():
                asset=self._indexed_asset(logical)
                rr_icon=asset and asset.category in ('Portrait','Map') and asset.slot in self.distribution_slots(asset.code)
                if rr_icon:
                    try:self.rr_icon_bytes(target,asset.category)
                    except (OSError,ValueError):continue
                    candidates=self.rr_icon_sources.setdefault(logical.casefold(),[])
                    if target not in candidates:candidates.append(target)
                    candidates.sort(key=lambda q:(q.parent!=self.patches_path/'RRIcons',q.relative_to(self.patches_path).as_posix().casefold()))
                    paths[logical.casefold()]=logical
                    self.patch_assets[logical.casefold()]=candidates[0]
                else:
                    if logical.casefold() in self.patch_assets:
                        raise ValueError(f'Conflicting mapped Patches asset: {logical}')
                    paths[logical.casefold()] = logical
                    self.patch_assets[logical.casefold()] = target
        # Ignore any metadata referring to skins that are no longer installed.
        self.patch_directories = {key: folder for key, folder in self.patch_directories.items()
                                  if f'Driver/{key[0]}-{key[1]}.brres'.casefold() in self.patch_assets}
        self.inventory = scan_paths(paths.values(), self.bmg)
        # Use metadata only for names missing from the BMG.
        self.patch_metadata = {}
        self.metadata_conflicts = []
        for key, folder in self.patch_directories.items():
            skin = self.inventory.skins.get(key)
            if skin is None:
                continue
            meta = json.loads((folder / self.PATCH_META_FILENAME).read_text(encoding='utf-8'))
            self.patch_metadata[key] = meta
            for fn, field in ((name_id, 'name'), (author_id, 'author')):
                mid = fn(CODE_IDS[key[0]], key[1])
                if self.bmg._lookup(mid) is None:
                    self.bmg.set_text(mid, str(meta.get(field, '')))
                elif field in meta and self.bmg.get_text(mid) != str(meta[field]):
                    self.metadata_conflicts.append(f'{key[0].upper()}-{key[1]} {field}: editor JSON '
                        f'{str(meta[field])!r} differs from merged BMG {self.bmg.get_text(mid)!r}; BMG wins')
            skin.name = self.bmg.get_text(name_id(CODE_IDS[key[0]], key[1]))
            skin.author = self.bmg.get_text(author_id(CODE_IDS[key[0]], key[1]))
        self._snapshot = {p: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in {self.archive_path, *self.distribution_text_paths, *self.text_archives,
                                    *self.patch_assets.values(),
                                    *(f / self.PATCH_META_FILENAME for f in self.patch_directories.values())}
                          if p.is_file()}
        for p in (*self._patch_name_archives(), *self._legacy_name_archives(),
                  self.patch_bmg_path, self._resource_index_path()):
            self._snapshot[p] = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None

    @staticmethod
    def _indexed_asset(logical: str):
        """Inventory dictionary keys are casefolded; restore category casing."""
        if '/' in logical:
            folder, filename = logical.split('/', 1)
            folder = {'driver':'Driver', 'allkart':'AllKart', 'portrait':'Portrait',
                      'map':'Map', 'sound':'Sound'}.get(folder.casefold(), folder)
            logical = f'{folder}/{filename}'
        return parse_asset(logical)

    def distribution_slots(self, code: str) -> set[int]:
        """Driver slots physically owned by RR, regardless of patch shadows."""
        return set(self._distribution_slot_index.get(code, ()))

    def patch_slots(self, code: str) -> set[int]:
        if self._patch_slot_index is None:
            self._patch_slot_index = {c:set() for c in CODE_IDS}
            for relative in self.patch_assets:
                asset = self._indexed_asset(relative)
                if asset and asset.category == 'Driver' and asset.slot is not None:
                    self._patch_slot_index[asset.code].add(asset.slot)
        return set(self._patch_slot_index.get(code, ()))

    def patch_overlaps(self) -> dict[str, set[int]]:
        return {code: overlap for code in CODE_IDS
                if (overlap := self.patch_slots(code) & self.distribution_slots(code))}

    def reserved_slots(self, code: str) -> set[int]:
        """Include orphan resources and text-only reservations in slot allocation."""
        slots = {slot for c, slot in self.inventory.skins if c == code}
        for logical in (*self.inventory.orphans, *self.distribution_assets, *self.patch_assets):
            asset = self._indexed_asset(logical)
            if asset and asset.code == code and asset.slot is not None:
                slots.add(asset.slot)
        slots.update(self.text_reservations(code))
        return slots

    def text_reservations(self, code: str) -> set[int]:
        """Only nonempty custom overrides reserve a file-less slot.

        Distribution BMG catalogs commonly outlive their resources. A copy of
        that catalog in a merged patch is not evidence of another installation.
        Distinct, nonempty override text is retained as an explicit reservation.
        """
        result = set()
        base_messages = {message.id: message for message in self.base_bmg.messages}
        for message in self.bmg.messages:
            slot = message.id & 0xff
            if (message.id >> 16 != CODE_IDS[code] or
                    (message.id & 0xff00) not in (0x6a00, 0x7a00) or not 1 <= slot <= 100):
                continue
            base = base_messages.get(message.id)
            if message.raw[:-2].decode('utf-16-be', errors='replace').strip() and (base is None or
                    (message.raw, message.metadata) != (base.raw, base.metadata)):
                result.add(slot)
        return result

    def slot_destinations_reserved(self, code: str, *, patches: bool) -> set[int]:
        """Shared destination policy for GUI staging and backend validation."""
        current = self.patch_slots(code) if patches else self.movable_slots(code)
        reserved = self.reserved_slots(code) - current
        return reserved | self.distribution_reserved_slots(code) if patches else reserved

    @staticmethod
    def _carry_catalog_text(bmg: CharacterBMG, code: str, pairs: dict[int, int], current: set[int], plan: EditPlan):
        # Preserve unowned distribution text at incoming destinations in freed
        # source slots, rather than deleting it or mistaking it for a character.
        text_pairs = dict(pairs)
        vacant = iter(sorted(set(pairs) - set(pairs.values())))
        for target in sorted(set(pairs.values()) - current):
            if any(bmg._lookup(fn(CODE_IDS[code], target)) is not None for fn in (name_id, author_id)):
                retained = next(vacant)
                text_pairs[target] = retained
                plan.metadata.append(f'{code.upper()} text-only slot {target} â†’ {retained} (preserved)')
        bmg.remap(CODE_IDS[code], text_pairs)

    def distribution_reserved_slots(self, code: str) -> set[int]:
        slots = self.distribution_slots(code)
        for logical in self.distribution_inventory.orphans:
            asset = parse_asset(logical)
            if asset and asset.code == code:
                slots.add(asset.slot)
        return slots

    def next_import_slot(self, code: str) -> int:
        slot = max(self.reserved_slots(code), default=0) + 1
        if slot > 100:
            raise ValueError(f'No slot after the highest occupied {code.upper()} slot (maximum 100)')
        return slot

    def movable_slots(self, code: str) -> set[int]:
        return (self.distribution_slots(code) - self.patch_slots(code)
                if self.developer_mode else self.patch_slots(code))

    def _require_developer(self, operation: str):
        if not self.developer_mode:
            raise PermissionError(f'{operation} requires Developer Mode. Reopen the pack and enable it to edit distribution files.')

    def can_edit_skin(self, code: str, slot: int) -> bool:
        return self.developer_mode or self.is_patch_skin(code, slot)

    @staticmethod
    def rr_icon_bytes(path,kind='Portrait'):
        from .tpl import read_tpl,image_to_tpl
        size=64 if kind=='Portrait' else 32
        if path.suffix.lower()=='.png':
            from PIL import Image
            with Image.open(path) as image:
                if max(image.size)>4096:raise ValueError('Icon PNG is too large')
                return image_to_tpl(image.convert('RGBA'),size)
        raw=path.read_bytes()
        if read_tpl(raw).size!=(size,size):raise ValueError(f'RR {kind} icons must be {size}x{size}')
        return raw

    def can_replace_portrait(self,code,slot):
        return self.can_edit_skin(code,slot) or self.is_rr_skin(code,slot)

    def is_rr_skin(self,code,slot):
        return slot in self.distribution_slots(code) and not self.is_patch_skin(code,slot)

    def organize_rr_icons(self):
        plan=EditPlan('Organize existing RR skin icons')
        plan.names_synchronized=True
        index={kind:dict(entries) for kind,entries in self.resource_index.items()}
        occupied=set()
        def retain(source,folder,suffix):
            raw=source.read_bytes();digest=hashlib.sha256(raw).hexdigest()[:16]
            dest=self.patches_path/'RRIcons'/folder/(source.name+'.'+digest+suffix)
            if dest in occupied or dest.exists() and dest.read_bytes()==raw:plan.deletes.add(source)
            else:plan.moves.append((source,dest));occupied.add(dest)
        for logical,sources in self.rr_icon_sources.items():
            asset=self._indexed_asset(logical)
            if not self.is_rr_skin(asset.code,asset.slot):continue
            filename=f'{asset.code}-{asset.slot}-css.tpl' if asset.category=='Portrait' else f'{asset.code}-{asset.slot}.tpl'
            target=self.patches_path/'RRIcons'/filename
            chosen=sources[0];content=self.rr_icon_bytes(chosen,asset.category)
            for key in index['patches']:
                if key.casefold()==logical:index['patches'][key]=target.relative_to(self.patches_path).as_posix()
            if chosen!=target:
                if target.exists() and target not in sources:retain(target,'Conflicts','.inactive')
                if chosen.suffix.lower()=='.png':
                    plan.writes[target]=content
                    if target.exists():plan.replace_existing.add(target)
                    retain(chosen,'Sources','.source')
                else:plan.moves.append((chosen,target))
            for source in sources[1:]:
                if source.suffix.lower()=='.png':retain(source,'Sources','.source')
                elif self.rr_icon_bytes(source,asset.category)==content:
                    if source!=target:plan.deletes.add(source)
                else:retain(source,'Conflicts','.inactive')
        if index!=self.resource_index:self._stage_resource_index(plan,index)
        for path in {p for pair in plan.moves for p in pair} | set(plan.deletes) | set(plan.writes):
            plan.expected[path]=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        return plan

    def _distribution_name_archives(self):
        """Only supported UI/Race siblings of the selected ReplacedAssets."""
        paths=[]
        for path in self.archive_path.parent.glob('*.szs'):
            if not re.fullmatch(r'(?:UIAssets|RaceAssets)(?:_[a-z]{1,3})?\.szs', path.name, re.I):
                continue
            if path.is_symlink() or path.resolve().parent != self.archive_path.parent:
                raise ValueError('UI/Race name archive must be an ordinary file beside ReplacedAssets')
            if path.is_file():paths.append(path.resolve())
        return tuple(sorted(paths,key=str))


    @staticmethod
    def _custom_text_id(mid):
        return (mid in {name_id(cid,0) for cid in CODE_IDS.values()} or
                mid >> 16 in CODE_IDS.values() and (mid & 0xff00) in (0x6a00, 0x7a00) and
                (1 <= (mid & 0xff) <= 100 or (mid & 0xffff) == 0x7a00))

    def _archive_write(self, bmg: CharacterBMG) -> dict[Path, bytes]:
        self._require_developer('Changing ReplacedAssets.szs')
        writes = {}
        # Sorting must also repair old, unchanged MID tables for binary lookup.
        if not bmg.order_sorted:
            bmg.dirty = True
        archive = U8Archive.read(self.archive_path.read_bytes())
        encoded = bmg.encode()
        if archive.files['message/CharaRR.bmg'] != encoded:
            archive.replace('message/CharaRR.bmg', encoded)
            output = archive.encode()
            if U8Archive.read(output).files['message/CharaRR.bmg'] != encoded:
                raise ValueError('Rebuilt archive failed message validation')
            writes[self.archive_path] = output
        authoritative = {m.id:m for m in bmg.messages if self._custom_text_id(m.id)}
        removed = {m.id for m in self.base_bmg.messages if self._custom_text_id(m.id)} - authoritative.keys()
        for path in self._distribution_name_archives():
            bundle = U8Archive.from_file(path)
            if RACE_MEMBER not in bundle.files:
                bundle.files[RACE_MEMBER] = encoded
                bundle.dirty = True
            for member, raw in list(bundle.files.items()):
                if not re.fullmatch(r'message/Chara(?:RR|Name)\.bmg', member, re.I):
                    continue
                table = CharacterBMG.read(raw)
                if table.entry_width != bmg.entry_width:
                    raise ValueError(f'Incompatible character text metadata width in {path.name}/{member}')
                # Keep unrelated messages/opaque sections exactly; synchronize only
                # native custom-character name/author IDs, including removals.
                table.messages = [m for m in table.messages if m.id not in authoritative and m.id not in removed]
                table.messages.extend(Message(m.id,m.raw,m.metadata) for m in authoritative.values())
                table.dirty = True
                updated = table.encode()
                if updated != raw:bundle.replace(member, updated)
            if bundle.dirty:
                output = bundle.encode()
                if dict(U8Archive.read(output).files) != dict(bundle.files):
                    raise ValueError(f'Rebuilt {path.name} failed archive validation')
                writes[path] = output
        return writes

    def is_patch_skin(self, code: str, slot: int) -> bool:
        return f'Driver/{code}-{slot}.brres'.casefold() in self.patch_assets

    def asset_path(self, relative: str) -> Path:
        return self.patch_assets.get(relative.casefold(), self.distribution_assets.get(relative.casefold(), self.character / relative))

    def _patch_bmg_write(self, bmg: CharacterBMG) -> dict[Path, bytes]:
        """Build the two packed CharaName archive overrides RR reads in menus/races."""
        bmg.dirty = True  # sort IDs for RR lookup even after an old unsorted import
        encoded = bmg.encode()
        if [(m.id, m.raw, m.metadata) for m in CharacterBMG.read(encoded).messages] != sorted(
                [(m.id, m.raw, m.metadata) for m in bmg.messages]):
            raise ValueError('Patched BMG did not preserve message data')
        writes = {}
        canonical = self._patch_name_archives()
        legacy = self._legacy_name_archives()
        removed = {m.id for m in self.bmg.messages if self._custom_text_id(m.id)} - {m.id for m in bmg.messages}
        def race_text(target, contributors):
            # Preserve each side's unrelated messages; menu BMG owns character IDs.
            raw = self.base_bmg.encode()
            side = 'RaceAssets' if '.raceassets.' in target.name.lower() else 'UIAssets'
            baseline = self.archive_path.parent / (side + '.szs')
            if baseline.is_file():
                raw = U8Archive.from_file(baseline).files.get(RACE_MEMBER, raw)
            sources = [('distribution', raw)] + [(f'existing override {i}', c.files[RACE_MEMBER]) for i,c in enumerate(contributors) if RACE_MEMBER in c.files]
            if len(sources)>1:raw = merge_tables(sources)[0].encode()
            return synchronized_character_text(raw, bmg, self._custom_text_id, removed)
        for target, old in zip(canonical, legacy):
            contributors = [self.text_archives[p] for p in (old, target) if p in self.text_archives]
            files = {RACE_MEMBER: race_text(target, contributors)}
            payload = merged_archive(files, contributors, encoded)
            if not target.is_file() or target.read_bytes() != payload:
                writes[target] = payload
        # Synchronize all other contributing CharaName archives too, retaining
        # their members. Otherwise runtime enumeration priority could shadow us.
        for target, archive in self.text_archives.items():
            if target in (*canonical, *legacy):
                continue
            if archive is not None:
                files = dict(archive.files)
                files[RACE_MEMBER] = race_text(target, [archive])
                payload = merged_archive(files, [], encoded)
            elif target.name.casefold().endswith('chararr.bmg.raceassets'):
                payload = synchronized_character_text(target.read_bytes(), bmg, self._custom_text_id, removed)
            else:payload = encoded
            if target.read_bytes() != payload:
                writes[target] = payload
        return writes

    def _sync_developer_text(self, plan: EditPlan, original: CharacterBMG,
                             overridden: CharacterBMG | None = None) -> None:
        """Persist distribution text and keep any active UI/Race overrides in step."""
        plan.expected.update(self._snapshot)
        plan.names_synchronized = True
        text_writes = self._archive_write(original)
        plan.writes.update(text_writes)
        plan.replace_existing.update(path for path in text_writes if path.exists())
        plan.metadata.extend(f'Synchronize distribution character names/authors: {path.name}' for path in text_writes)
        if overridden is not None or self.deployment_profile=="wiiloaded":
            self._stage_name_patches(plan, overridden if overridden is not None else original)
            plan.metadata.append('Synced distribution BMG with UI/Race name overrides; WiiLoaded requires Patches enabled for this pair')
        elif not any(p.name.lower().startswith('raceassets') for p in self._distribution_name_archives()):
            plan.warnings.append('No RaceAssets source was found beside ReplacedAssets. Race names cannot take effect from ReplacedAssets alone. Select the WiiLoaded deployment profile to stage the UI/Race name patch pair, or supply the actual UI/Race archives for direct editing.')

    def _active_name_override(self) -> bool:
        return (bool(self.text_archives) or self.patch_bmg_path.is_file()
                or any(path.is_file() for path in (*self._patch_name_archives(),
                                                     *self._legacy_name_archives())))

    def _stage_name_patches(self, plan: EditPlan, bmg: CharacterBMG) -> None:
        # The new folder is the canonical location. Any legacy root pair is
        # removed in the same transaction as the updated BMG write.
        plan.expected.update(self._snapshot)
        plan.names_synchronized = True
        plan.warnings.extend('Text conflict resolved: ' + c for c in self.text_conflicts)
        plan.warnings.extend(self.metadata_conflicts)
        plan.metadata.append('Preserve all unrelated raw messages, INF metadata and archive members; '
                             'priority: distribution < loose legacy < other archives < root pair < nested pair; UI wins within each pair')
        name_writes = self._patch_bmg_write(bmg)
        plan.writes.update(name_writes)
        for target in name_writes:
            if target.exists():
                plan.replace_existing.add(target)
        legacy = self._legacy_name_archives()
        if any(p.is_file() for p in legacy):
            plan.deletes.update(p for p in legacy if p.is_file())
            plan.metadata.append('Migrating shared CharacterNames archives from Patches root '
                                 'into Patches/CharacterNames/')
        if self.patch_bmg_path.exists():
            plan.deletes.add(self.patch_bmg_path)
            plan.metadata.append('Migrating legacy CharaRR.bmg patch to packed CharaName UI/Race patches')

    def organize_character_names(self) -> EditPlan:
        """Move shared name archives into their own folder."""
        plan = EditPlan('Organize existing shared character-name archives')
        if not self._active_name_override():
            plan.metadata.append('No existing name overrides to migrate.')
            return plan
        self._stage_name_patches(plan, CharacterBMG.read(self.bmg.encode()))
        plan.warnings.append('Nested archives require a compatible recursive loader. '
                             'Some RR builds also omit CharaName in their name fallback check; see README.')
        return plan

    def update_character_text(self) -> EditPlan:
        plan = EditPlan('Merge and synchronize existing character text')
        self._stage_name_patches(plan, CharacterBMG.read(self.bmg.encode()))
        for (code, slot), folder in self.patch_directories.items():
            skin = self.inventory.skins[code, slot]
            path = folder / self.PATCH_META_FILENAME
            payload = self._updated_skin_metadata(code, slot, skin.name, skin.author)
            # Preserve original JSON formatting when all fields already agree.
            expected = json.loads(payload)
            if self.patch_metadata[code, slot] != expected:
                plan.writes[path] = payload
                plan.replace_existing.add(path)
                plan.metadata.append(f'Synchronize {code.upper()}-{slot} editor metadata to merged text; retain unknown fields')
        return plan

    def synchronize_character_names(self) -> EditPlan:
        """Repair legacy race copies from the names currently displayed in menus."""
        if not self.developer_mode:
            return self.update_character_text()
        plan = EditPlan('Synchronize menu and in-race character names')
        original = CharacterBMG.read(self.base_bmg.encode())
        # Patch-only slots remain patches. Existing distribution IDs and vanilla
        # names use the displayed menu values, never stale race archive values.
        owned = {m.id for m in original.messages}
        owned.update(name_id(cid,0) for cid in CODE_IDS.values())
        entries = {m.id:m for m in self.bmg.messages if m.id in owned and self._custom_text_id(m.id)}
        original.messages = [m for m in original.messages if m.id not in entries]
        original.messages.extend(Message(m.id,m.raw,m.metadata) for m in entries.values())
        original.dirty = True
        self._sync_developer_text(plan, original, CharacterBMG.read(self.bmg.encode()) if self._active_name_override() else None)
        return plan

    def prepare_name_sync(self, plan: EditPlan) -> EditPlan:
        """Include legacy name repair in resource updates before preview/commit."""
        if plan.names_synchronized or not (plan.moves or plan.writes or plan.deletes):return plan
        entries = {m.id:m.raw for m in self.bmg.messages if self._custom_text_id(m.id)}
        mismatch = False
        paths = set(self.distribution_text_paths) | {p for p,a in self.text_archives.items() if a is not None}
        if self._active_name_override():
            mismatch = any(not p.is_file() or RACE_MEMBER not in U8Archive.from_file(p).files for p in self._patch_name_archives())
        for path in paths:
            files = U8Archive.from_file(path).files
            if entries and re.fullmatch(r'RaceAssets(?:_[a-z]{1,3})?\.szs',path.name,re.I) and RACE_MEMBER not in files:
                mismatch = True
            for member,raw in files.items():
                if member not in (MEMBER,RACE_MEMBER):continue
                table = CharacterBMG.read(raw)
                if any(table._lookup(mid) is None or table._lookup(mid).raw != value for mid,value in entries.items()):mismatch=True
        if mismatch:
            repair = self.synchronize_character_names()
            for path,payload in repair.writes.items():
                if path in plan.writes:
                    # An icon/model operation may already have changed this
                    # archive. Merge only text, never restore old resource bytes.
                    if path.suffix.lower()!='.szs':continue
                    bundle = U8Archive.read(plan.writes[path])
                    for member,raw in U8Archive.read(payload).files.items():
                        if member in (MEMBER,RACE_MEMBER):
                            if member in bundle.files:bundle.replace(member,raw)
                            else:bundle.files[member]=raw;bundle.dirty=True
                    payload = bundle.encode()
                plan.writes[path] = payload
            plan.expected.update(repair.expected)
            plan.replace_existing.update(p for p in repair.replace_existing if p in plan.writes)
            if repair.deletes & (set(plan.writes) | {src for src,_ in plan.moves}):
                raise ValueError('Character text migration conflicts with this resource update; synchronize names first.')
            plan.deletes.update(repair.deletes)
            plan.warnings.extend(repair.warnings)
            plan.metadata.extend(repair.metadata)
            plan.metadata.append('Automatically repair stale in-race names from menu names')
        plan.names_synchronized = True
        return plan

    def organize_characters(self, mappings=None, *, patches=None, independent_codes=()) -> EditPlan:
        """Compose existing slot/folder/text plans in one reviewed transaction."""
        mappings = mappings or {}
        patches = not self.developer_mode if patches is None else patches
        plan = (self.reassign_patch_slots(mappings) if patches else
                self.reassign_developer_slots(mappings, independent_codes=independent_codes))
        plan.description = 'Organize Characters: slots, ownership and UI/Race names'
        folders = self.organize_existing_patches()
        # Collapse root-file relocation and slot renaming into one direct move.
        renamed = dict(plan.moves)
        for src,dst in folders.moves:
            final = renamed.pop(src, src)
            plan.moves = [(a,b) for a,b in plan.moves if a != src]
            plan.moves.append((src,dst.with_name(final.name)))
        for path,payload in folders.writes.items():
            if path.name != self.PATCH_META_FILENAME:
                continue
            meta = json.loads(payload)
            meta['slot'] = mappings.get(meta['base_character'],{}).get(meta['slot'],meta['slot']) if patches else meta['slot']
            plan.writes[path] = (json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        plan.warnings.extend(folders.warnings)
        plan.metadata.extend(folders.metadata)
        plan.expected.update(folders.expected)
        # Slot plans already contain remapped tables. Never merge the old slot
        # ordering over those results, which would restore displaced names.
        original = CharacterBMG.read(U8Archive.read(plan.writes[self.archive_path]).files['message/CharaRR.bmg']) if self.archive_path in plan.writes else CharacterBMG.read(self.base_bmg.encode())
        original.dirty = True
        names = next((CharacterBMG.read(U8Archive.read(plan.writes[p]).files[MEMBER])
                      for p in self._patch_name_archives() if p in plan.writes),None)
        names = names or CharacterBMG.read(self.bmg.encode())
        if self.developer_mode and not patches:
            # Distribution owns its IDs; actual patch owners retain their overrides.
            ids = {m.id:m for m in original.messages if self._custom_text_id(m.id)}
            patch_ids = {fn(CODE_IDS[code],slot) for code in CODE_IDS for slot in self.patch_slots(code) for fn in (name_id,author_id)}
            changed_ids = set(ids) | {m.id for m in self.base_bmg.messages if self._custom_text_id(m.id)}
            for mid in changed_ids - patch_ids:
                before = names._lookup(mid);after = ids.get(mid)
                if before and after and (before.raw,before.metadata) != (after.raw,after.metadata):
                    plan.warnings.append(f'Synchronize name/author 0x{mid:08x}: {names.get_text(mid)!r} → {original.get_text(mid)!r}; use Backup Patches to preserve the original')
            names.messages = [m for m in names.messages if m.id not in changed_ids - patch_ids]
            names.messages.extend(Message(m.id,m.raw,m.metadata) for m in ids.values() if m.id not in patch_ids)
            names.dirty = True
            self._sync_developer_text(plan,original,names if self._active_name_override() or self.patch_assets else None)
        elif self._active_name_override() or self.patch_assets:
            self._stage_name_patches(plan,names)
        for (code,slot),folder in self.patch_directories.items():
            path = folder/self.PATCH_META_FILENAME
            meta = dict(self.patch_metadata[code,slot]);target = mappings.get(code,{}).get(slot,slot) if patches else slot
            meta.update(slot=target,name=names.get_text(name_id(CODE_IDS[code],target)),author=names.get_text(author_id(CODE_IDS[code],target)))
            if meta != self.patch_metadata[code,slot]:
                plan.writes[path] = (json.dumps(meta,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
                plan.replace_existing.add(path)
        plan.expected.update(self._snapshot)
        plan.expected.update({src:hashlib.sha256(src.read_bytes()).hexdigest() for src,_ in plan.moves})
        return plan

    def import_patch_skin(self, source: Path, code: str, slot: int, *,
                          name: str, author: str, extra_images: dict[str, Path] | None = None,
                          source_variant: str | None = None,
                          driver_candidate: ModelCandidate | None = None) -> EditPlan:
        """Stage organized character assets and shared BMG patches; leave originals intact."""
        if not 1 <= slot <= 100:
            raise ValueError('Patches supports custom slots 1â€“100')
        if (code, slot) in self.inventory.skins:
            raise ValueError('Slot already exists in the Character library or Patches. Choose a free slot.')
        if slot in self.text_reservations(code):
            raise ValueError('This slot already has text metadata. Choose another slot or clean up the orphan record.')
        direct_plan = self.import_skin(source, code, slot, insert=False,
                                       name=name, author=author, extra_images=extra_images,
                                       source_variant=source_variant, driver_candidate=driver_candidate,
                                       _patch_preview=True)
        plan = EditPlan(f'Install {name} as {code.upper()} slot {slot} via Patches')
        plan.warnings.extend(direct_plan.warnings)
        plan.metadata.extend(direct_plan.metadata)
        skin_folder = self._character_patch_directory(name, code, slot)
        seen: set[str] = set()
        for path, payload in direct_plan.writes.items():
            if path == self.archive_path:
                continue
            dest = skin_folder / path.name
            key = dest.name.casefold()
            if key in seen:
                raise ValueError(f'Patches has an ambiguous duplicate basename: {dest.name}')
            seen.add(key)
            if dest.exists():
                raise ValueError(f'Patches already contains {dest.name}. Refusing to overwrite an existing patch.')
            # Existing root files still collide in the loose-file loader.
            if (self.patches_path / dest.name).exists():
                raise ValueError(f'A legacy flat patch already uses {dest.name}.')
            plan.writes[dest] = payload
        metadata = dict(direct_plan.character_metadata)
        metadata.update(json.loads(self._skin_metadata(code, slot, name, author)))
        plan.writes[skin_folder / self.PATCH_META_FILENAME] = json.dumps(metadata, ensure_ascii=False, indent=2).encode('utf-8')
        bmg = CharacterBMG.read(self.bmg.encode())
        bmg.set_text(name_id(CODE_IDS[code], slot), name)
        bmg.set_text(author_id(CODE_IDS[code], slot), author)
        self._stage_name_patches(plan, bmg)
        plan.metadata.extend([f'{name} â†’ {code.upper()} slot {slot}', f'Author: {author}',
                             f'Assets: Patches/{skin_folder.name}/',
                             'BMG: Patches/CharacterNames/ (both shared UIAssets/RaceAssets archives)'])
        plan.warnings.append('IMPORTANT: Stock RR on SD/Dolphin scans only the Patches root. '
                             'Neither character folders nor Patches/CharacterNames/ are loadable by '
                             'that patch loader without recursive scanning.')
        plan.warnings.append('Patches mode installs into an empty slot only; it does not shift distributed skins.')
        plan.warnings.append('RR name/author text is synchronized through TWO shared packed UI/Race archives '
                             'in Patches/CharacterNames/. Each character owns its own asset folder.')
        if self.patches_path.is_dir():
            competing = [p.name for p in self.patches_path.iterdir() if p.is_file() and
                         (p.name.casefold() == 'chararr.bmg' or
                          p.name.casefold().endswith(('.uiassets.szs', '.raceassets.szs'))) and
                         p.name.casefold() not in (self.PATCH_UI_BMG_FILENAME.casefold(),
                                                   self.PATCH_RACE_BMG_FILENAME.casefold())]
            if competing:
                plan.warnings.append('Other character/text overrides found: ' + ', '.join(competing[:6]) +
                                     '. Verify their priority in-game.')
        return plan

    @staticmethod
    def _valid_resource_filename(filename: str) -> str:
        """Accept unconventional names, but never paths or invalid Windows filenames."""
        if not isinstance(filename, str) or not filename or filename.strip(' .') != filename:
            raise ValueError('Filename must not be empty or have leading/trailing spaces or dots')
        if (filename in ('.', '..') or len(filename) > 180
                or re.search(r'[<>:"/\\|?*\x00-\x1f]', filename)):
            raise ValueError(f'Unsafe filename: {filename!r} (enter a filename, not a path)')
        stem = filename.split('.')[0].upper()
        if stem in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                    *(f'LPT{i}' for i in range(1, 10))}:
            raise ValueError(f'Reserved Windows filename: {filename}')
        return filename

    def rename_resources(self, code: str, slot: int, names: dict[str, str]) -> EditPlan:
        """Rename physical resources while retaining their logical identity in our UI.

        RR may no longer load nonstandard filenames; never rewrite file contents.
        """
        skin = self.inventory.skins.get((code, slot))
        if skin is None:
            raise ValueError('Select an installed character before renaming its resources')
        if not self.can_edit_skin(code, slot):
            self._require_developer('Renaming a distribution resource')
        known = {asset.relpath: asset for asset in skin.files}
        if set(names) - set(known):
            raise ValueError('A requested resource does not belong to the selected skin')
        plan = EditPlan(f'Rename files for {skin.name or code.upper()} (slot {slot})')
        index = {kind: dict(entries) for kind, entries in self.resource_index.items()}
        destinations: set[str] = set()
        for logical, asset in known.items():
            source = self.asset_path(logical)
            if not source.is_file():
                raise ValueError(f'Resource file missing: {source}')
            new_name = self._valid_resource_filename(names.get(logical, source.name))
            dest = source.with_name(new_name)
            if str(dest).casefold() in destinations:
                raise ValueError(f'Duplicate destination filename: {new_name}')
            destinations.add(str(dest).casefold())
            # A patch-installed character can inherit distribution assets that
            # are not overridden. Those files remain read-only in Standard Mode.
            root = self.patches_path if source.resolve().is_relative_to(self.patches_path) else self.character
            scope = 'patches' if root == self.patches_path else 'distribution'
            if not source.resolve().is_relative_to(root):
                raise ValueError(f'Unsafe resource location: {source}')
            if source != dest:
                if scope == 'distribution':
                    self._require_developer('Renaming an inherited distribution resource')
                plan.moves.append((source, dest))
                plan.metadata.append(f'{asset.category}: {source.name} â†’ {new_name}')
            canonical = root / logical
            if dest == canonical:
                index[scope].pop(logical, None)
            else:
                index[scope][logical] = dest.relative_to(root).as_posix()
        if not plan.moves:
            return plan
        source_set = {src.resolve() for src, _ in plan.moves}
        for _, dest in plan.moves:
            if dest.exists() and dest.resolve() not in source_set:
                raise ValueError(f'Another resource already exists: {dest.name}')
        self._stage_resource_index(plan, index)
        plan.warnings.append('Custom filenames can break Retro Rewind asset loading. '
                             'Revert to default names to restore compatibility.')
        return plan

    def delete_resource(self, code: str, slot: int, logical: str) -> EditPlan:
        """Delete one selected resource and clean up its mapping."""
        skin = self.inventory.skins.get((code, slot))
        if skin is None:
            raise ValueError('Select an installed character')
        asset = next((a for a in skin.files if a.relpath == logical), None)
        if asset is None:
            raise ValueError('This resource does not belong to the selected character')
        physical = self.asset_path(logical)
        if physical.is_symlink() or not physical.is_file():
            raise ValueError('Resource is missing or linked')
        resolved = physical.resolve()
        in_patch = resolved.is_relative_to(self.patches_path)
        in_distribution = resolved.is_relative_to(self.character)
        if not (in_patch or in_distribution):
            raise ValueError('Resource outside the active character library')
        if not in_patch:
            self._require_developer('Deleting a distribution resource')
        plan = EditPlan(f'Delete {physical.name} from {skin.name or code.upper()} slot {slot}')
        plan.deletes.add(physical)
        index = {kind: dict(items) for kind, items in self.resource_index.items()}
        scope = 'patches' if in_patch else 'distribution'
        if logical in index[scope]:
            index[scope].pop(logical)
            self._stage_resource_index(plan, index)
        plan.warnings.append('This resource will be removed from the character installation. '
                             'Use Backup Patches before deleting if needed; removing a Driver can hide the entire slot.')
        return plan

    def delete_characters(self, characters) -> EditPlan:
        """Remove selected installations in a single transaction."""
        keys = set(characters)
        if not keys:
            raise ValueError('Select an installed character')
        plan = EditPlan(f'Delete {len(keys)} character installation(s)')
        plan.expected.update(self._snapshot)
        index = {kind:dict(items) for kind,items in self.resource_index.items()}
        removed_distribution = set()
        merged = CharacterBMG.read(self.bmg.encode())
        original = CharacterBMG.read(self.base_bmg.encode())
        owners = {}
        for key,skin in self.inventory.skins.items():
            for asset in skin.files:
                owners.setdefault(self.asset_path(asset.relpath).resolve(),set()).add(key)
        for key in sorted(keys):
            code,slot = key
            skin = self.inventory.skins.get(key)
            if skin is None:
                raise ValueError('Character no longer exists')
            if not self.can_edit_skin(code,slot):
                self._require_developer('Deleting a distribution character')
            patched = self.is_patch_skin(code,slot)
            plan.metadata.append(f'Remove {skin.name or code.upper()} â€” {code.upper()} slot {slot}')
            for asset in skin.files:
                physical = self.asset_path(asset.relpath)
                if patched and not physical.resolve().is_relative_to(self.patches_path):
                    continue  # A patch may inherit assets belonging to the distribution.
                resource_plan = self.delete_resource(code,slot,asset.relpath)
                plan.deletes.update(resource_plan.deletes)
                if not patched:
                    # Include a distribution copy hidden by a partial icon override.
                    underlying = self.distribution_assets.get(asset.relpath.casefold(),self.character/asset.relpath)
                    if underlying.is_file():
                        plan.deletes.add(underlying)
            folder = self.patch_directories.get(key) if patched else None
            if folder is not None:
                plan.deletes.add(folder/self.PATCH_META_FILENAME)
                foreign = any(path.parent==folder and owner-keys for path,owner in owners.items())
                if not foreign and sum(parent==folder for parent in self.patch_directories.values()) == 1:
                    plan.deletes.update(folder.glob(f'{code}-*-source.rrcm-source'))
                else:
                    bundle=folder/f'{code}-{slot}-source.rrcm-source'
                    if bundle.is_file():
                        plan.deletes.add(bundle)
            else:
                root = (self.asset_path(f'Driver/{code}-{slot}.brres').parent if patched
                        else self.character/'SourceResources')
                for suffix in ('source.rrcm-source','metadata.json'):
                    path = root/f'{code}-{slot}-{suffix}'
                    if path.is_file():
                        plan.deletes.add(path)
            for scope,items in index.items():
                if patched and scope!='patches':
                    continue
                for logical in list(items):
                    asset = parse_asset(logical)
                    if (asset.code,asset.slot)==key:
                        items.pop(logical)
            merged.remap(CODE_IDS[code],{},delete_slots={slot})
            if patched:
                # Removing an overlay must reveal the original character's text.
                # Retain the distribution catalog even without a Driver.
                for fn in (name_id,author_id):
                    message = self.base_bmg._lookup(fn(CODE_IDS[code],slot))
                    if message is not None:
                        merged.messages.append(Message(message.id,message.raw,message.metadata))
            else:
                original.remap(CODE_IDS[code],{},delete_slots={slot})
                removed_distribution.add(key)
        shared_archives = {path.resolve() for path in (self.archive_path,self.patch_bmg_path,
            self._resource_index_path(),*self.text_archives,*self._patch_name_archives(),*self._legacy_name_archives())}
        for path in plan.deletes:
            resolved = path.resolve()
            if resolved in shared_archives:
                raise ValueError('Cannot delete a shared archive or manager index: '+path.name)
            if path.is_symlink() or not path.is_file() or not (
                    resolved.is_relative_to(self.character) or resolved.is_relative_to(self.patches_path)):
                raise ValueError('Unsafe or missing character resource: '+path.name)
            if owners.get(resolved,set())-keys:
                raise ValueError('Resource is shared with another character: '+path.name)
            # Also protect indexed references that are not presently visible in inventory.
            for scope,items in index.items():
                root = self.character if scope=='distribution' else self.patches_path
                if any((root/value).resolve()==resolved for value in items.values()):
                    raise ValueError('Resource has a remaining shared index reference: '+path.name)
            plan.expected[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        if index != self.resource_index:
            self._stage_resource_index(plan,index)
        if removed_distribution:
            self._sync_developer_text(plan,original,merged if self._active_name_override() else None)
        if keys-removed_distribution and not (removed_distribution and self._active_name_override()):
            self._stage_name_patches(plan,merged)
        plan.warnings.append('Selected installation files and name/author entries will be removed. '
                             'Shared archives and unrelated files are retained; use Backup Patches before deletion if needed.')
        return plan

    def organize_existing_patches(self) -> EditPlan:
        """Organize recognized legacy flat skins and shared names, preserving extras."""
        plan = self.organize_character_names()
        plan.description = 'Organize existing Patches characters and shared character names'
        if not self.patches_path.is_dir():
            return plan
        groups: dict[tuple[str, int], list[Path]] = {}
        tracked_physical = {(self.patches_path / rel).resolve()
                            for rel in self.resource_index['patches'].values()}
        for path in self.patches_path.iterdir():
            if not path.is_file() or path.is_symlink() or path.resolve() in tracked_physical:
                continue
            asset = parse_asset(path.name, source_import=True)
            if asset is not None and asset.slot is not None:
                groups.setdefault((asset.code, asset.slot), []).append(path)
        planned_folders = set()
        for (code, slot), paths in sorted(groups.items()):
            if not any(parse_asset(path.name, source_import=True).category == 'Driver' for path in paths):
                # Unmatched loose files may be intentional overrides.
                continue
            if (code, slot) in self.patch_directories:
                plan.warnings.append(f'Skipped {code.upper()} slot {slot}: an organized folder already exists.')
                continue
            skin = self.inventory.skins.get((code, slot))
            name = (skin.name if skin else '') or f'{code.upper()} Slot {slot}'
            author = skin.author if skin else ''
            try:
                folder = self._character_patch_directory(name, code, slot)
                if folder.name.casefold() in planned_folders:
                    folder = self._character_patch_directory(f'{name} ({code.upper()}-{slot})', code, slot)
                if folder.name.casefold() in planned_folders:
                    raise ValueError('Character folder name conflicts with another staged character')
                planned_folders.add(folder.name.casefold())
            except ValueError as exc:
                plan.warnings.append(f'Skipped {code.upper()} slot {slot}: {exc}')
                continue
            for path in paths:
                plan.moves.append((path, folder / path.name))
            plan.writes[folder / self.PATCH_META_FILENAME] = self._skin_metadata(code, slot, name, author)
            plan.metadata.append(f'Existing {code.upper()} slot {slot} â†’ Patches/{folder.name}/ ({len(paths)} assets)')
        if plan.moves:
            plan.warnings.append('Stock RR SD/Dolphin does not recursively index Patches subfolders; '
                                 'loading requires a compatible launcher or loader.')
        return plan

    def edit_text(self, code: str, slot: int, name: str, author: str) -> EditPlan:
        if code not in CODE_IDS or slot != 0 and (code, slot) not in self.inventory.skins:
            raise ValueError('That character slot is not installed')
        if not self.can_edit_skin(code, slot):
            self._require_developer('Editing a distribution character')
        plan = EditPlan(f'Edit {code.upper()} custom slot {slot}' if slot else f'Edit {code.upper()} vanilla name')
        message_name = name_id(CODE_IDS[code], slot)
        message_author = author_id(CODE_IDS[code], slot)
        if self.is_patch_skin(code, slot):
            bmg = CharacterBMG.read(self.bmg.encode())
            bmg.set_text(message_name, name)
            bmg.set_text(message_author, author)
            self._stage_name_patches(plan, bmg)
        else:
            # Developer edits belong in the distribution's CharaRR.bmg, even
            # when a user-installed CharaName override is currently active.
            self._require_developer('Editing distribution names')
            original = CharacterBMG.read(self.archive.files['message/CharaRR.bmg'])
            original.set_text(message_name, name)
            original.set_text(message_author, author)
            overridden = CharacterBMG.read(self.bmg.encode()) if self._active_name_override() else None
            if overridden is not None:
                overridden.set_text(message_name, name)
                overridden.set_text(message_author, author)
            self._sync_developer_text(plan, original, overridden)
        folder = self.patch_directories.get((code, slot))
        if folder:
            new_folder = self._character_patch_directory(name, code, slot, existing=folder)
            new_meta = new_folder / self.PATCH_META_FILENAME
            old_meta = folder / self.PATCH_META_FILENAME
            if new_folder != folder:
                if new_folder.exists():
                    raise ValueError(f'Cannot rename patch folder: {new_folder.name} already exists')
                for original_file in folder.rglob('*'):
                    if original_file.is_file() and original_file != old_meta:
                        plan.moves.append((original_file, new_folder / original_file.relative_to(folder)))
                plan.deletes.add(old_meta)
                plan.metadata.append(f'Folder: {folder.name} â†’ {new_folder.name}')
            else:
                plan.replace_existing.add(old_meta)
            plan.writes[new_meta] = self._updated_skin_metadata(code, slot, name, author)
            if new_folder != folder:
                index = {kind: dict(entries) for kind, entries in self.resource_index.items()}
                changed = False
                for logical, location in index['patches'].items():
                    physical = self.patches_path / location
                    if physical.is_relative_to(folder):
                        index['patches'][logical] = (new_folder / physical.relative_to(folder)).relative_to(self.patches_path).as_posix()
                        changed = True
                if changed:
                    self._stage_resource_index(plan, index)
        if plan.writes:
            skin = self.inventory.skins.get((code, slot))
            old_name = skin.name if skin else self.bmg.get_text(message_name)
            old_author = skin.author if skin else self.bmg.get_text(message_author)
            plan.metadata.extend([f'Name: {old_name!r} -> {name!r}', f'Author: {old_author!r} -> {author!r}'])
        return plan

    def reassign_patch_slots(self, mappings: dict[str, dict[int, int]]) -> EditPlan:
        """Atomically remap only Patches-owned skins, including their BMG IDs.

        Mapping keys always refer to slots on disk, not previously staged UI
        locations. Destinations may exchange numbers, but must never overwrite
        an official distribution slot, or another stationary patch skin.
        """
        mapping = {code: {int(src): int(dst) for src, dst in pairs.items() if int(src) != int(dst)}
                   for code, pairs in mappings.items() if pairs}
        mapping = {code: pairs for code, pairs in mapping.items() if pairs}
        plan = EditPlan('Save Patches character slot changes')
        if not mapping:
            return plan
        for code, pairs in mapping.items():
            if code not in CODE_IDS:
                raise ValueError(f'Unknown base character: {code}')
            current = self.patch_slots(code)
            for src, dst in pairs.items():
                if src not in current:
                    raise ValueError(f'{code.upper()} slot {src} is not a Patches-installed skin')
                if not 1 <= dst <= 100:
                    raise ValueError(f'{code.upper()} target slot {dst} is outside 1â€“100')
            final = {pairs.get(slot, slot) for slot in current}
            if len(final) != len(current):
                raise ValueError(f'{code.upper()} new slot numbers would overlap other Patches skins')
            conflicting = final & self.distribution_reserved_slots(code)
            if conflicting:
                raise ValueError(f'{code.upper()} slot(s) {sorted(conflicting)} overlap official RR slots. '
                                 'Use Bump by X or pick free numbers before saving.')
            if set(pairs.values()) & (self.text_reservations(code) - current):
                raise ValueError(f'{code.upper()} destination contains reserved text metadata that already belongs to an existing character')
            # Protect unmatched resources with existing slot IDs from being
            # silently appropriated, even when no driver was found for them.
            for logical in self.patch_assets:
                asset = self._indexed_asset(logical)
                if (asset and asset.code == code and asset.slot in final
                        and asset.slot not in current):
                    raise ValueError(f'{code.upper()} destination uses an orphan Patches resource: {logical}')

        index = {kind: dict(entries) for kind, entries in self.resource_index.items()}
        destinations = set()
        indexed_changes = {}
        for code, pairs in mapping.items():
            for source_slot, target_slot in pairs.items():
                skin = self.inventory.skins.get((code, source_slot))
                if skin is None:
                    raise ValueError(f'No installed Patches skin for {code.upper()} slot {source_slot}')
                plan.metadata.append(f'{skin.name or code.upper()}: {code.upper()} {source_slot} â†’ {target_slot}')
                for asset in skin.files:
                    logical = asset.relpath
                    physical = self.patch_assets.get(logical.casefold())
                    if physical is None:
                        continue  # Inherited distribution resources must not move.
                    physical = physical.resolve()
                    if not physical.is_relative_to(self.patches_path) or not physical.is_file():
                        raise ValueError(f'Unsafe or missing Patches resource: {physical}')
                    new_logical = asset.destination(target_slot)
                    # An intentionally custom filename from the resource editor
                    # stays custom; its index moves to the new logical slot.
                    canonical_old = asset.filename_for(source_slot)
                    if physical.name.casefold() == canonical_old.casefold():
                        new_physical = physical.with_name(asset.filename_for(target_slot))
                    else:
                        new_physical = physical
                    if new_physical != physical:
                        plan.moves.append((physical, new_physical))
                    if new_logical.casefold() in destinations:
                        raise ValueError(f'Duplicate output resource: {new_logical}')
                    destinations.add(new_logical.casefold())
                    indexed_changes[logical] = (new_logical, new_physical)

                folder = self.patch_directories.get((code, source_slot))
                if folder is not None:
                    meta = folder / self.PATCH_META_FILENAME
                    if meta.is_file():
                        plan.writes[meta] = self._updated_skin_metadata(code, target_slot, skin.name, skin.author, source_slot=source_slot)
                        plan.replace_existing.add(meta)
        for logical in indexed_changes:
            index['patches'].pop(logical, None)
        for new_logical, physical in indexed_changes.values():
            if physical.name.casefold() != Path(new_logical).name.casefold():
                index['patches'][new_logical] = physical.relative_to(self.patches_path).as_posix()
        # Update index mappings for other indexed resources not carried by a
        # matched inventory entry (should be rare, but don't drop existing data).
        if index != self.resource_index:
            self._stage_resource_index(plan, index)
        sources = {src for src, _ in plan.moves}
        for src, dst in plan.moves:
            if dst.exists() and dst not in sources:
                raise ValueError(f'Target resource already exists: {dst}')

        # Remap name and author entries as a group. Restore original RR text at
        # vacated overlap slots, which otherwise could retain the old patch name.
        bmg = CharacterBMG.read(self.bmg.encode())
        base = self.base_bmg
        carried = {}
        removed_ids = set()
        for code, pairs in mapping.items():
            cid = CODE_IDS[code]
            for source_slot, target_slot in pairs.items():
                skin = self.inventory.skins[(code, source_slot)]
                for label, message_fn, value in (('name', name_id, skin.name),
                                                 ('author', author_id, skin.author)):
                    old_id = message_fn(cid, source_slot)
                    new_id = message_fn(cid, target_slot)
                    original_message = self.bmg._lookup(old_id)
                    carried[new_id] = (Message(new_id, original_message.raw, original_message.metadata)
                                       if original_message is not None else value)
                    removed_ids.add(old_id)
        bmg.messages = [msg for msg in bmg.messages if msg.id not in removed_ids]
        bmg.dirty = True
        for old_id in sorted(removed_ids):
            if old_id not in carried and base._lookup(old_id) is not None:
                original = base._lookup(old_id)
                bmg.messages.append(Message(original.id, original.raw, original.metadata))
        # Final mappings may overwrite leftover BMG entries for a never
        # installed skin. Reject that instead of silently discarding its text.
        for key, value in carried.items():
            if bmg._lookup(key) is not None:
                baseline = base._lookup(key)
                existing = bmg._lookup(key)
                if bmg.get_text(key).strip() and (baseline is None or
                        (existing.raw, existing.metadata) != (baseline.raw, baseline.metadata)):
                    raise ValueError(f'Name entry 0x{key:06x} already belongs to an existing character')
                bmg.messages = [msg for msg in bmg.messages if msg.id != key]
            if isinstance(value, Message):
                bmg.messages.append(value)
            else:
                bmg.set_text(key, value)
        self._stage_name_patches(plan, bmg)
        if any(src != dst for src, dst in plan.moves):
            plan.warnings.append('Renaming slots changes RR references and may affect saved ghosts or leaderboard data.')
        plan.warnings.append('Stock RR may not discover files inside Patches subfolders without compatible loading support.')
        plan.expected.update({src: hashlib.sha256(src.read_bytes()).hexdigest() for src, _ in plan.moves})
        return plan

    def reassign_developer_slots(self, mappings: dict[str, dict[int, int]],
                                 description='Save Developer character slot changes', *, _allow_text_only=False, independent_codes=()) -> EditPlan:
        """Reuse direct distribution renumbering in one transaction across sections."""
        self._require_developer('Reordering character slots')
        mapping = {code: {int(src): int(dst) for src, dst in pairs.items() if int(src) != int(dst)}
                   for code, pairs in mappings.items() if pairs}
        mapping = {code: pairs for code, pairs in mapping.items() if pairs}
        plan = EditPlan(description)
        if not mapping:
            return plan
        original = CharacterBMG.read(self.archive.files['message/CharaRR.bmg'])
        overridden = CharacterBMG.read(self.bmg.encode()) if self._active_name_override() else None
        index = {kind: dict(entries) for kind, entries in self.resource_index.items()}
        indexed_moves = {}
        for code, pairs in mapping.items():
            if code not in CODE_IDS:
                raise ValueError(f'Unknown base character: {code}')
            independent = code in independent_codes
            current = self.distribution_slots(code) if independent else self.movable_slots(code)
            if _allow_text_only:
                # Existing insertion also shifts BMG-only entries above its slot.
                text_slots = {m.id & 0xff for m in self.bmg.messages
                              if m.id >> 16 == CODE_IDS[code] and
                              (m.id & 0xff00) in (0x6a00, 0x7a00)}
                current |= set(pairs) & text_slots
            if not set(pairs) <= current:
                raise ValueError('Only unshadowed Character/ slots can be moved in Developer Mode')
            if any(not 1 <= dst <= 100 for dst in pairs.values()):
                raise ValueError('Target slot is outside 1â€“100')
            final = {pairs.get(slot, slot) for slot in current}
            if len(final) != len(current):
                raise ValueError(f'{code.upper()} target overlaps another character slot')
            affected = set(pairs) | set(pairs.values())
            if not independent and affected & self.patch_slots(code):
                raise ValueError('A Patches-installed skin occupies an affected slot. '
                                 'Remove or relocate that override before moving distribution slots.')
            reserved = self.distribution_reserved_slots(code) if independent else self.reserved_slots(code)
            if set(pairs.values()) & (reserved - current):
                raise ValueError(f'{code.upper()} destination contains reserved text or orphan resources')
            self._carry_catalog_text(original, code, pairs, current, plan)
            if overridden is not None and not independent:
                self._carry_catalog_text(overridden, code, pairs, current, plan)
            for src_slot, dst_slot in sorted(pairs.items()):
                inventory = self.distribution_inventory if independent else self.inventory
                skin = inventory.skins.get((code, src_slot))
                if skin is None:
                    continue
                plan.metadata.append(f'{code.upper()} {src_slot} â†’ {dst_slot}: {skin.name or "Unnamed"}')
                for suffix in ('source.rrcm-source', 'metadata.json'):
                    src = self.character/'SourceResources'/f'{code}-{src_slot}-{suffix}'
                    if src.is_file():
                        plan.moves.append((src, src.with_name(f'{code}-{dst_slot}-{suffix}')))
                for asset in skin.files:
                    src = self.distribution_assets.get(asset.relpath.casefold(), self.character / asset.relpath)
                    if src is None or not src.is_file():
                        raise ValueError(f'Distribution source is missing: {asset.relpath}')
                    if not independent and asset.relpath.casefold() in self.patch_assets:
                        raise ValueError(f'A Patches override shadows distribution resource: {asset.relpath}')
                    new_logical = asset.destination(dst_slot)
                    canonical = src.name.casefold() == asset.filename_for(src_slot).casefold()
                    dst = src.with_name(asset.filename_for(dst_slot)) if canonical else src
                    if src != dst:
                        plan.moves.append((src, dst))
                    if asset.relpath in index['distribution']:
                        indexed_moves[asset.relpath] = (new_logical, dst.relative_to(self.character).as_posix())
        # Remove old mappings together before adding exchanged destinations.
        for logical in indexed_moves:
            index['distribution'].pop(logical)
        for logical, location in indexed_moves.values():
            index['distribution'][logical] = location
        if index != self.resource_index:
            self._stage_resource_index(plan, index)
        sources = {src for src, _ in plan.moves}
        for _, dst in plan.moves:
            if dst.exists() and dst not in sources:
                raise ValueError(f'Target resource already exists: {dst}')
        if mapping.keys() <= set(independent_codes):
            # Normalization is a distribution-only edit. Keep every patch archive
            # byte-for-byte; its overrides retain their original slot identities.
            plan.expected.update(self._snapshot)
            self._sync_developer_text(plan, original)
            plan.warnings.append('Patches resources/text keep their existing slots and may still override Character slots at runtime.')
        else:
            self._sync_developer_text(plan, original, overridden)
        plan.warnings.append('Existing ghost and leaderboard slot references can change meaning.')
        plan.expected.update({src: hashlib.sha256(src.read_bytes()).hexdigest() for src, _ in plan.moves})
        return plan

    def _renumber(self, code: str, mapping: dict[int, int], description: str) -> EditPlan:
        return self.reassign_developer_slots({code: mapping}, description, _allow_text_only=True)

    def move_slot(self, code: str, from_slot: int, to_slot: int) -> EditPlan:
        self._require_developer('Moving character slots')
        if (code,from_slot) not in self.inventory.skins:
            raise ValueError('Source slot does not exist')
        if not 1 <= to_slot <= 100:
            raise ValueError('Target slot is outside 1â€“100')
        if from_slot == to_slot:
            return EditPlan('No changes')
        active = sorted(s for c,s in self.inventory.skins if c == code)
        # Stable insertion-style move: everything between these slots shifts one.
        mapping = {from_slot:to_slot}
        if from_slot < to_slot:
            mapping.update({s:s-1 for s in active if from_slot < s <= to_slot})
        else:
            mapping.update({s:s+1 for s in active if to_slot <= s < from_slot})
        return self._renumber(code,mapping,f'Move {code.upper()} slot {from_slot} to {to_slot}')

    def import_skin(self, source: Path, code: str, slot: int, *, insert: bool,
                    name: str, author: str, extra_images: dict[str, Path] | None = None,
                    source_variant: str | None = None,
                    driver_candidate: ModelCandidate | None = None,
                    _patch_preview: bool = False) -> EditPlan:
        if not _patch_preview:
            self._require_developer('Installing directly into Character/')
        if code not in CODE_IDS:
            raise ValueError('Unknown Mario Kart Wii base character')
        if not 1 <= slot <= 100:
            raise ValueError('Choose a custom slot from 1 to 100')
        source = source.expanduser().resolve()
        if not source.exists():
            raise ValueError('Source character mod does not exist')
        entries: list[tuple[str,bytes]] = []
        package = None
        package_sources = []
        package_selection_entries = None
        if source.suffix.lower() == '.mkchara':
            from .mkchara import read_package
            package = read_package(source)
            original_entries = package.entries()
            entries = package.entries(code)
            package_sources = package.sources
            if driver_candidate is not None:
                if not isinstance(driver_candidate, ModelCandidate):
                    raise ValueError('Invalid model selection')
                # Active labels follow a changed base. Source-only labels retain
                # their provenance and are read only for explicit model extraction.
                from .mkchara import logical_name
                if driver_candidate.source_path in dict(original_entries):
                    original_asset = parse_asset(driver_candidate.source_path, source_import=True)
                    driver_candidate = ModelCandidate(logical_name(original_asset, code),
                        driver_candidate.archive_member, driver_candidate.size, driver_candidate.category)
                elif driver_candidate.source_path in dict(package.preview_entries()):
                    package_selection_entries = package.preview_entries()
                else:
                    raise ValueError('Selected model is not a package resource')
        else:
            from .models import source_entries
            entries = source_entries(source)
        from .library import unused_race_variant
        skipped_variants = [rel for rel, _ in entries if unused_race_variant(rel)]
        entries = [(rel, data) for rel, data in entries if not unused_race_variant(rel)]
        package_sources = [(rel, data) for rel, data in package_sources if not unused_race_variant(rel)]
        all_entries = entries
        variants = available_import_variants(rel for rel, _ in entries)
        entries = select_import_entries(entries, source_variant)
        preserved_choices = []
        if DEFAULT_RESOURCE_VARIANT in variants:
            active_names = {rel for rel, _ in entries}
            preserved_choices = [(rel, data) for rel, data in all_entries if rel not in active_names]
        parsed = []
        for rel,data in entries:
            match = parse_asset(rel,source_import=True)
            if match:
                if match.category == 'Driver' and driver_model_role(rel, data)[0].startswith(('Award', 'Auxiliary', 'Animations')):
                    continue  # Keep award/demo payloads as source data, never as Driver/.
                parsed.append((rel,match,data))
        component_codes = {asset.code for _, asset, _ in parsed}
        if package is None and len(component_codes) > 1:
            if code not in component_codes:
                raise ValueError('This bundle provides components for ' + ', '.join(sorted(component_codes)) +
                                 f', not {code}. Choose a supplied base character; skeletons are not converted.')
            preserved_choices.extend((rel, data) for rel, asset, data in parsed if asset.code != code)
            if code != preferred_import_code(rel for rel, _, _ in parsed):
                # Unlabelled bundle portraits cannot be associated with a secondary
                # component safely. Explicit optional images remain available.
                unlabelled = [(rel,data) for rel,data in entries
                              if rel.lower().endswith(('.png','.tpl')) and not parse_asset(rel,source_import=True)]
                preserved_choices.extend(unlabelled)
                unknown_names = {rel for rel,_ in unlabelled}
                entries = [(rel,data) for rel,data in entries if rel not in unknown_names]
            entries = [(rel, data) for rel, data in entries
                       if not ((asset := parse_asset(rel, source_import=True)) and asset.code != code)]
            parsed = [item for item in parsed if item[1].code == code]
        # Multiple numbered drivers indicate separate skins. Ancillary assets
        # may use a different source number (e.g. Snake's sound bank 5/model 6).
        driver_slots = {asset.slot for _, asset, _ in parsed
                        if asset.category == 'Driver' and asset.slot is not None}
        if len(driver_slots) > 1:
            raise ValueError('Import contains several different numbered skins. Import one at a time.')
        # A conventional <code>_menu.brres is a menu/standalone driver candidate.
        # Prefer an explicitly packaged Driver resource when both are supplied.
        ordinary_driver=any(a.category=='Driver' and not rel.casefold().endswith('_menu.brres')
                            for rel,a,_ in parsed)
        if ordinary_driver:
            parsed=[item for item in parsed if not (item[1].category=='Driver' and
                                                    item[0].casefold().endswith('_menu.brres'))]
        if driver_candidate is None:
            driver_candidate=automatic_driver_candidate(entries, code=code)
        # Some complete Wii mods (e.g. Samus) bundle their driver_model.brres
        # inside per-vehicle SZS archives, rather than shipping Driver/rs.brres.
        # Automatic selection prioritizes standalone files; embedded drivers
        # remain a fallback, and the explorer permits an explicit override.
        if driver_candidate is not None:
            if not isinstance(driver_candidate, ModelCandidate):
                raise ValueError('Invalid model selection')
            selection_entries = package_selection_entries or entries
            selected_asset = (parse_asset(driver_candidate.archive_member, source_import=True)
                              if driver_candidate.archive_member else None) or parse_asset(driver_candidate.source_path, source_import=True)
            if package is None and selected_asset and selected_asset.code != code:
                raise ValueError('Selected model belongs to '+selected_asset.code.upper()+
                                 '; choosing another base does not convert its skeleton.')
            if driver_candidate.source_path not in {path for path, _ in selection_entries}:
                raise ValueError('Selected model no longer exists in the chosen import variant')
            if not driver_candidate.is_driver:
                raise ValueError('Choose a menu or driver BRRES, not a vehicle/animation archive')
            driver_data = extract_model_bytes(selection_entries, driver_candidate)
            selected_role, _ = driver_model_role(driver_candidate.archive_member or driver_candidate.source_path, driver_data)
            if selected_role.startswith(('Award', 'Auxiliary', 'Animations')):
                raise ValueError('Selected BRRES is an award/demo or auxiliary model, not a driver resource')
            # A conventional Driver is already mapped correctly. Keep its source
            # slot for validation and preserve every other resource unchanged.
            selected_driver = next((item for item in parsed if item[0] == driver_candidate.source_path
                                    and item[1].category == 'Driver'), None)
            if selected_driver is not None and not driver_candidate.archive_member:
                driver_candidate = None
            if driver_candidate is not None:
                parsed=[item for item in parsed if item[1].category!='Driver']
                driver_asset = parse_asset(f'{code}.brres', source_import=True)
                if driver_asset is None:
                    raise ValueError('Unable to assign extracted model to base character')
                parsed.append((driver_candidate.label, driver_asset, driver_data))
        if not parsed:
            raise ValueError('No supported character assets found in the import')
        source_codes = {match.code for _,match,_ in parsed}
        if source_codes != {code}:
            raise ValueError('Imported assets target ' + ', '.join(sorted(source_codes)) +
                             f', not {code}. Renaming alone cannot convert a different character skeleton.')
        if not any(m.category == 'Driver' for _,m,_ in parsed):
            raise ValueError('A standalone Driver BRRES is missing. Use Explore / View Modelsâ€¦ to select one\n'
                             'from an SZS archive. Inspect it in BrawlCrate to confirm its bind pose first.')
        # Distinct bike/kart archives are copied byte-for-byte, preserving mods
        # with different in-race models for the two vehicle classes.
        # A standalone driver BRRES primarily covers the RR driver/menu path.
        # Additional menu animation resources and Common.szs are NOT auto patched.
        # Check file structure without changing models or skeletons.
        for source_name, asset, contents in parsed:
            from .native_validation import validate_asset
            validate_asset(contents,asset.category,source_name)
            if asset.category == 'Driver' and not contents.startswith(b'bres'):
                raise ValueError(f'Not a BRRES driver model: {source_name}')
            if asset.category in ('AllKart', 'RaceKart') and not contents.startswith((b'Yaz0', b'\x55\xaa\x38\x2d')):
                raise ValueError(f'Not a valid SZS archive header: {source_name}')
            if asset.category in ('Map','Portrait') and not contents.startswith(bytes.fromhex('0020af30')):
                raise ValueError(f'Not a TPL image: {source_name}')
        unique = {}
        for rel, asset, data in parsed:
            destination = asset.destination(slot)
            key = destination.casefold()
            if key in unique:
                previous = unique[key]
                if previous[2] != data:
                    raise ValueError(f'Import has conflicting output filename: {destination} '
                                     f'({previous[0]} versus {rel}). Select one resource variant.')
                preserved_choices.extend(((previous[0],previous[2]),(rel,data)))
            else:
                unique[key] = (rel, asset, data)
        parsed = list(unique.values())
        skipped = len(entries)-len(parsed)
        existing = sorted(s for c,s in self.inventory.skins if c == code)
        # Include orphan metadata entries as well: BMG may contain slots whose
        # driver files were removed. Leaving those IDs behind causes collisions.
        bmg_slots = {m.id & 0xff for m in self.bmg.messages
                     if m.id >> 16 == CODE_IDS[code]
                     and (m.id & 0xff00) in (0x6a00, 0x7a00)}
        if insert:
            moved = {s:s+1 for s in set(existing) | bmg_slots if s >= slot}
            if any(s > 100 for s in moved.values()):
                raise ValueError('Cannot insert: one or more skins would exceed slot 100')
            plan = self._renumber(code,moved,f'Insert {name} into {code.upper()} slot {slot}')
        else:
            if (code,slot) in self.inventory.skins:
                raise ValueError('Slot occupied. Choose Insert or a free slot.')
            if slot in self.text_reservations(code):
                raise ValueError('This slot already has text metadata. Choose another slot or clean up the orphan record.')
            if any((asset := parse_asset(rel)) is not None and asset.code == code and asset.slot == slot
                   for rel in self.inventory.orphans):
                raise ValueError('Destination slot has orphan resources. Choose another slot or clean up those resources.')
            plan = EditPlan(f'Install {name} into {code.upper()} slot {slot}')
        bmg = CharacterBMG.read(self.archive.files['message/CharaRR.bmg'])
        overridden = (CharacterBMG.read(self.bmg.encode())
                      if self._active_name_override() and not _patch_preview else None)
        if insert:
            bmg.remap(CODE_IDS[code], moved)
            if overridden is not None:
                overridden.remap(CODE_IDS[code], moved)
        bmg.set_text(name_id(CODE_IDS[code], slot), name)
        bmg.set_text(author_id(CODE_IDS[code], slot), author)
        if overridden is not None:
            overridden.set_text(name_id(CODE_IDS[code], slot), name)
            overridden.set_text(author_id(CODE_IDS[code], slot), author)
        if not _patch_preview:
            self._sync_developer_text(plan, bmg, overridden)
        if driver_candidate is not None:
            plan.warnings.append('Extracted standalone driver from ' + driver_candidate.label +
                 '. Verify its skeleton, bind pose and in-game menus. Separate kart/bike SZS files '
                 'are preserved unchanged. This selection does not replace their embedded drivers.')
        elif any(a.category=='Driver' and rel.casefold().endswith('_menu.brres') for rel,a,_ in parsed):
            plan.metadata.append('Menu BRRES mapped to the standalone Driver resource; kart/bike SZS drivers remain separate.')
            plan.warnings.append('The menu model is installed unchanged. Its runtime animation/material visibility '
                                 'may require additional game-side support; inspect the bind pose and test menus in-game.')
        if package is None and len(component_codes) > 1:
            plan.metadata.append('Importing '+code.upper()+' component only; other base-character resources are preserved as source data. No skeletons are renamed or retargeted.')
        if skipped_variants:
            plan.metadata.append(f'Skipped {len(skipped_variants)} unused team/battle and split-screen vehicle archives; original source unchanged.')
        if preserved_choices:
            plan.metadata.append(f'{len(preserved_choices)} unselected overlay/component or identical duplicate resources preserved as source data.')
        registered = set()
        categories = set()
        for source_name,asset,payload in parsed:
            if asset.category in ('Portrait', 'Map'):
                continue  # Shared dimension-based detection also handles canonical TPLs.
            if asset.category == 'Driver':
                role, animations = driver_model_role(source_name, payload)
                from .brrescore import list_models
                try:
                    drawable = bool(list_models(payload))
                except ValueError:
                    drawable = False
                if drawable and not animations & {'sel_wait', 'sel_gut'}:
                    plan.warnings.append('Driver model has no sel_wait/sel_gut character-selection animations: '
                                         + source_name + '. Menus may remain in bind pose; no animations are synthesized.')
            rel = asset.destination(slot)
            target = self.character / rel
            if str(target).casefold() in registered:
                raise ValueError(f'Import has duplicate output filename: {rel}')
            registered.add(str(target).casefold())
            plan.writes[target] = payload
            categories.add(asset.category)
        # Detect CSS portraits and minimaps in Icon/Icons, independently of
        # filename and whether the user supplied PNG or RGB5A3 TPL.
        from PIL import Image
        from .tpl import read_tpl, image_to_tpl

        def prepare_icon(contents: bytes, path: str, expected: int) -> bytes:
            if contents.startswith(b'\x89PNG\r\n\x1a\n'):
                with Image.open(io.BytesIO(contents)) as picture:
                    if max(picture.size) > 4096:
                        raise ValueError(f'Icon is too large: {path}')
                    return image_to_tpl(picture, expected)
            if contents.startswith(bytes.fromhex('0020af30')):
                picture = read_tpl(contents)
                return contents if picture.size == (expected, expected) else image_to_tpl(picture, expected)
            raise ValueError(f'Unsupported image data: {path}. Choose PNG or RGB5A3 TPL.')

        from .tpl import detected_icons
        icon_entries = list(entries)
        if package is not None:
            icon_entries.extend(package_sources)
        candidates = detected_icons(icon_entries)

        auto_icons = 0
        installed_icons=set()
        for kind, target_size in (('Portrait',64),('Map',32)):
            if kind in categories or kind in (extra_images or {}):
                continue
            if len(candidates[kind]) > 1:
                plan.metadata.append(f'Multiple {kind} icons found; selected {candidates[kind][0][0]} by dimensions/name hints. Optional image selection overrides it.')
            if candidates[kind]:
                path, contents = candidates[kind][0]
                data = prepare_icon(contents,path,target_size)
                filename = f'{code}-{slot}-css.tpl' if kind == 'Portrait' else f'{code}-{slot}.tpl'
                plan.writes[self.character / kind / filename] = data
                categories.add(kind)
                auto_icons += 1
                installed_icons.add(path)
        for kind, source_path in (extra_images or {}).items():
            if kind not in ('Map','Portrait'):
                raise ValueError('Only Map and Portrait icons are supported')
            if kind in categories:
                raise ValueError(f'The imported mod already contains a {kind} icon; remove the extra image')
            source_path = Path(source_path)
            if not source_path.is_file():
                raise ValueError(f'Icon file not found: {source_path}')
            expected = 32 if kind == 'Map' else 64
            filename = f'{code}-{slot}.tpl' if kind == 'Map' else f'{code}-{slot}-css.tpl'
            data = prepare_icon(source_path.read_bytes(),str(source_path),expected)
            plan.writes[self.character / kind / filename] = data
            categories.add(kind)
        if auto_icons:
            plan.metadata.append(f'Auto-detected {auto_icons} PNG/TPL icons by size and type')
        # BrawlBox exports identify BRSAR files and waves, not event IDs.
        # Activate only clips validated against this base's dedicated groups.
        if package is None and any(rel.lower().endswith('.wav') for rel,_ in entries):
            from .voices import baseline_path, generated_voices
            baseline = baseline_path(self)
            if baseline:
                try:
                    voices, replacements, unmatched = generated_voices(entries, code, baseline)
                except ValueError as exc:
                    # Unsupported/ambiguous banks must not break a model import,
                    # and must never be activated using guessed event identities.
                    voices, replacements = {}, []
                    unmatched = [rel for rel,_ in entries if rel.lower().endswith('.wav')]
                    plan.warnings.append('Automatic voices unavailable; WAV sources retained: '+str(exc))
                installed_groups = set()
                for stem, payload in voices.items():
                    target = self.character/'Sound'/f'GRP_VO_{code.upper()}-{slot}_{stem}'
                    file_ids={v.get('file_id') for v in replacements if v['group']==stem}
                    if any(path.parent==target.parent and (path.name.casefold()==target.name.casefold() or
                            path.name.casefold().startswith(target.name.casefold()+'.') or
                            any(path.name.casefold().startswith(f'{fid}.{code}-{slot}.') for fid in file_ids))
                           for path in plan.writes):
                        plan.warnings.append(f'Provided {stem} bank retained; overlapping loose WAVs were not applied.')
                        continue
                    plan.writes[target] = payload
                    categories.add('Sound'); installed_groups.add(stem)
                if installed_groups:
                    plan.character_metadata['voice'] = {'version':1, 'base_character':code,
                        'encoding':'PCM16BE', 'replacements':[v for v in replacements if v['group'] in installed_groups]}
                    plan.metadata.append(f'Converted {sum(v["group"] in installed_groups for v in replacements)} verified WAV clips in {len(installed_groups)} voice groups')
                    plan.warnings.append('Custom voices require the compatible loose RWSD/RBNK voice loader; PCM audio increases wave memory. Verify the deployed runtime in Dolphin/Wii.')
                if unmatched:
                    plan.warnings.append(f'{len(unmatched)} WAV clips lack a verified per-character mapping (including shared menu banks); preserved as sources for manual mapping in Edit Sounds.')
            else:
                plan.warnings.append('WAVs preserved as sources. Configure an original revo_kart.brsar in Edit Sounds to map and convert them safely.')
        if 'AllKart' not in categories:
            plan.warnings.append('Missing optional AllKart menu archive; game may show a native fallback.')
        if 'Portrait' not in categories:
            plan.warnings.append('No CSS portrait; original portrait may appear.')
        if 'Map' not in categories:
            plan.warnings.append('No minimap TPL; original map icon may appear.')
        if 'Sound' not in categories:
            plan.warnings.append('No custom sounds; vanilla voice fallback may be used.')
        from .library import race_coverage,missing_race_requests
        coverage=race_coverage(a for _,a,_ in parsed)
        if coverage:
            plan.character_metadata['vehicle_coverage']=coverage
            for mode,vehicles in coverage.items():
                count=len({v.split(':')[0] for v in vehicles})
                plan.metadata.append(f'Race coverage {mode}: {count} distinct vehicles; '+', '.join(vehicles))
            normal=coverage.get('normal',[])
            count=len({v.split(':')[0] for v in normal})
            if count<12:plan.warnings.append(f'Only {count}/12 distinct normal-mode vehicles supplied; team colors and split-screen copies do not increase coverage. Unsupported vehicles use native fallback.')
        else:plan.warnings.append('No race vehicle archives supplied; native vehicle fallback will be used.')
        missing=missing_race_requests(code,coverage)
        missing={'normal':missing['normal']}
        plan.character_metadata['missing_vehicle_requests']=missing
        for mode,requests in missing.items():
            if requests:
                suffix='' if mode=='normal' else '_'+mode
                plan.warnings.append('Missing '+mode+' vehicle requests: '+', '.join(v.split(':')[0]+f'-{code}-{slot}'+suffix+'.szs' for v in requests))
        handled={rel for rel,_,_ in parsed}
        handled.update(installed_icons)
        extras=[(rel,data) for rel,data in entries
                if rel not in handled or rel.casefold().endswith('_menu.brres')]
        extra_names = {rel for rel,_ in extras}
        for rel,data in preserved_choices:
            if rel not in extra_names:
                extras.append((rel,data));extra_names.add(rel)
        if package is not None:
            # Preserve original auxiliary files, including copies of detected
            # icons. Never activate global archives through this source bundle.
            extras = list(package_sources)
            if driver_candidate is not None:
                for rel,data in entries:
                    if parse_asset(rel, source_import=True).category != 'Driver':
                        continue
                    saved_name='OriginalDriver/'+Path(rel).name
                    prior=dict(extras).get(saved_name)
                    if prior == data:
                        continue
                    if prior is not None:
                        saved_name='OriginalDriver/'+hashlib.sha256(data).hexdigest()+'/'+Path(rel).name
                    extras.append((saved_name,data))
            plan.character_metadata = {key:value for key,value in package.character.get('metadata', {}).items()
                                       if key not in ('base_character','slot','name','author','format','version')}
            if plan.character_metadata and not _patch_preview:
                plan.writes[self.character/'SourceResources'/f'{code}-{slot}-metadata.json'] = json.dumps(
                    plan.character_metadata, ensure_ascii=False, indent=2).encode('utf-8')
            plan.metadata.append('Validated mkchara v1: slot-independent resources and SHA-256 payloads')
            if package.character['base_character'] != code:
                plan.warnings.append('Base changed from '+package.character['base_character'].upper()+' to '+code.upper()+
                    ': filenames and text IDs are mapped; bones, animations and vehicle classes are not retargeted. Verify skeleton compatibility in-game.')
        if package is None and plan.character_metadata and not _patch_preview:
            plan.writes[self.character/'SourceResources'/f'{code}-{slot}-metadata.json'] = json.dumps(
                plan.character_metadata, ensure_ascii=False, indent=2).encode('utf-8')
        if extras:
            # Preserve resources with no per-skin loader mapping as inert source
            # data, rather than installing a global Common.szs over every skin.
            # The non-game extension is ignored by the game-resource inventory.
            from pathlib import PurePosixPath
            bundle=io.BytesIO()
            with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
                names=set()
                for rel,data in extras:
                    path=PurePosixPath(rel.replace('\\','/'))
                    if path.is_absolute() or '..' in path.parts or ':' in str(path):
                        raise ValueError(f'Unsafe source resource path: {rel}')
                    key=path.as_posix().casefold()
                    if key in names: raise ValueError(f'Duplicate source resource path: {rel}')
                    names.add(key);z.writestr(path.as_posix(),data)
            filename=f'{code}-{slot}-source.rrcm-source'
            plan.writes[self.character/'SourceResources'/filename]=bundle.getvalue()
            plan.metadata.append(f'{len(extras)} auxiliary/source files preserved in {filename} (ZIP format; kept inactive).')
            plan.warnings.append('Source-only resources preserved, not activated: '+', '.join(rel.rsplit('/',1)[-1] for rel,_ in extras[:8])+
                                 '. Common/menu animations and WAVs without verified mappings need separate loader/audio support; '
                                 'files in this source bundle are not activated as overrides.')
        race_assets=[a for _,a,_ in parsed if a.category=='RaceKart']
        kart=sum('_kart' in a.relpath.casefold() for a in race_assets)
        bike=sum('_bike' in a.relpath.casefold() for a in race_assets)
        if kart and bike:
            plan.metadata.append(f'Separate race resources preserved byte-for-byte: {kart} kart and {bike} bike archives, including vehicle textures and driver animations.')
        plan.metadata += [f'New slot {slot}: {name}',f'Author: {author}']
        return plan

    def replace_image(self, code: str, slot: int, source: Path, kind: str) -> EditPlan:
        """Replace or create a CSS portrait or minimap image."""
        if kind not in ('Portrait','Map'):
            raise ValueError('Unsupported image type')
        if (code,slot) not in self.inventory.skins:
            raise ValueError('Select an installed skin before replacing its icon')
        rr_icon=not self.developer_mode and self.is_rr_skin(code,slot)
        if not self.can_edit_skin(code, slot) and not rr_icon:
            self._require_developer('Editing distribution portraits or minimaps')
        source = Path(source).expanduser().resolve()
        if not source.is_file():
            raise ValueError('Selected image file does not exist')
        from .tpl import png_to_tpl, read_tpl, image_to_tpl
        size = 64 if kind == 'Portrait' else 32
        suffix = source.suffix.lower()
        if suffix == '.png':
            content = png_to_tpl(source,size)
        elif suffix == '.tpl':
            content = source.read_bytes()
            image = read_tpl(content)
            if image.size != (size,size):
                content = image_to_tpl(image,size)
        else:
            raise ValueError('Choose a PNG image or a TPL texture')
        if read_tpl(content).size != (size,size):
            raise ValueError(f'{kind} must decode to {size} x {size} RGB5A3')
        filename = f'{code}-{slot}-css.tpl' if kind == 'Portrait' else f'{code}-{slot}.tpl'
        folder = self.patch_directories.get((code, slot), self.patches_path)
        destination = (folder / filename if self.is_patch_skin(code, slot)
                       else self.character / kind / filename)
        if rr_icon:destination=self.patches_path/'RRIcons'/filename
        canonical_rel = f'{kind}/{filename}'
        if not rr_icon and (canonical_rel.casefold() in self.patch_assets or canonical_rel.casefold() in self.distribution_assets):
            destination = self.asset_path(canonical_rel)
        if destination.exists() and destination.read_bytes() == content:
            return EditPlan('Image already up to date')
        plan = EditPlan(f'Replace {kind} for {code.upper()} slot {slot}')
        if rr_icon:plan.names_synchronized=True
        plan.writes[destination] = content
        plan.expected[destination]=hashlib.sha256(destination.read_bytes()).hexdigest() if destination.is_file() else None
        if destination.exists():
            plan.replace_existing.add(destination)
        plan.metadata.append(f'{kind} <- {source.name} ({size} x {size} RGB5A3)')
        return plan

    def can_revert_rr_icon(self, code, slot, kind):
        filename=f'{code}-{slot}-css.tpl' if kind=='Portrait' else f'{code}-{slot}.tpl'
        return self.is_rr_skin(code,slot) and bool(self.rr_icon_sources.get(f'{kind}/{filename}'.casefold()))

    def revert_rr_icon(self, code, slot, kind):
        if kind not in ('Portrait','Map') or not self.is_rr_skin(code,slot):
            raise ValueError('Select a base RR skin icon to revert')
        filename=f'{code}-{slot}-css.tpl' if kind=='Portrait' else f'{code}-{slot}.tpl'
        logical=f'{kind}/{filename}'.casefold()
        plan=EditPlan(f'Revert {kind} for {code.upper()} slot {slot}')
        plan.names_synchronized=True
        for path in self.rr_icon_sources.get(logical,[]):
            plan.deletes.add(path)
            plan.expected[path]=hashlib.sha256(path.read_bytes()).hexdigest()
        index={key:dict(entries) for key,entries in self.resource_index.items()}
        for key in list(index['patches']):
            if key.casefold()==logical:del index['patches'][key]
        if index!=self.resource_index:self._stage_resource_index(plan,index)
        return plan

    def replace_portrait(self, code: str, slot: int, source: Path) -> EditPlan:
        return self.replace_image(code,slot,source,'Portrait')

    def replace_map(self, code: str, slot: int, source: Path) -> EditPlan:
        return self.replace_image(code,slot,source,'Map')

    def _reload_imported_character(self, plan, key):
        """Validate/update a newly committed import without scanning old resources.

        Complex edits retain full reload. A batch performs one final full scan;
        failed commits still roll back and reload the complete library.
        """
        if (plan.moves or plan.deletes or self._resource_index_path() in plan.writes or
                key in self.inventory.skins or any(
                    (a.code,a.slot)==key for rel in self.inventory.orphans
                    if (a:=parse_asset(rel)) is not None)):
            self.reload()
            return
        paths = {}
        metadata = None
        for path in plan.writes:
            if path == self.archive_path:
                continue
            asset = parse_asset(path.name, source_import=True)
            if asset and (asset.code,asset.slot)==key:
                paths[asset.destination(key[1])] = path
            elif asset:
                self.reload()
                return
            if path.name == self.PATCH_META_FILENAME:
                metadata = json.loads(path.read_text(encoding='utf-8'))
        if not any(parse_asset(rel).category=='Driver' for rel in paths):
            self.reload()
            return
        if self.archive_path in plan.writes:
            self.archive = U8Archive.from_file(self.archive_path)
            self.base_bmg = CharacterBMG.read(self.archive.files['message/CharaRR.bmg'])
        self.bmg, self.text_conflicts, self.text_archives = find_sources(
            self.patches_path, self.base_bmg.encode(), self.patch_bmg_path, self._patch_name_archives())
        imported = scan_paths(paths, self.bmg)
        if key not in imported.skins:
            raise ValueError('Imported character did not validate')
        self.inventory.skins.update(imported.skins)
        self.inventory.scanned_file_count += len(paths)
        for relative,path in paths.items():
            if path.is_relative_to(self.patches_path):
                self.patch_assets[relative.casefold()] = path
            else:
                self.distribution_assets[relative.casefold()] = path
        if metadata is not None:
            folder = next(path.parent for path in plan.writes if path.name==self.PATCH_META_FILENAME)
            self.patch_directories[key] = folder
            self.patch_metadata[key] = metadata
        if not self.is_patch_skin(*key):
            self._distribution_slot_index[key[0]].add(key[1])
            self.distribution_inventory.skins.update(scan_paths(paths, self.base_bmg).skins)
            for path in plan.writes:
                if path.is_relative_to(self.character) and path not in paths.values():
                    relative = path.relative_to(self.character).as_posix()
                    if relative not in self.inventory.unknown:
                        self.inventory.unknown.append(relative)
                        self.inventory.scanned_file_count += 1
        for path in plan.writes:
            self._snapshot[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        self._patch_slot_index = None
        self.revision += 1

    def commit(self, plan: EditPlan, *, imported_character=None) -> Path | None:
        """Prepare complete staged outputs, back up all inputs, commit, rollback on errors."""
        self.prepare_name_sync(plan)
        if not plan.moves and not plan.writes and not plan.deletes:
            return None
        for path, expected in plan.expected.items():
            actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            if actual != expected:
                raise ValueError(f'File changed since preview: {path}. Refresh and review a new plan.')
        current_sources = find_sources(self.patches_path, self.base_bmg.encode(),
                                       self.patch_bmg_path, self._patch_name_archives())[2]
        if plan.expected and set(current_sources) != set(self.text_archives):
            raise ValueError('Text archives changed since preview. Refresh and review a new plan.')
        if self.developer_mode and plan.expected and self._distribution_name_archives() != self.distribution_text_paths:
            raise ValueError('Distribution UI/Race archives changed since preview. Refresh and review a new plan.')
        moves = [(a.resolve(),b.resolve()) for a,b in plan.moves]
        writes = {p.resolve():data for p,data in plan.writes.items()}
        replace_existing = {p.resolve() for p in plan.replace_existing}
        deletes = {p.resolve() for p in plan.deletes}
        if not self.developer_mode:
            if (any(not a.is_relative_to(self.patches_path) or not b.is_relative_to(self.patches_path)
                    for a,b in moves)
                    or any(not p.is_relative_to(self.patches_path) for p in writes)
                    or any(not p.is_relative_to(self.patches_path) for p in deletes)):
                raise PermissionError('Standard Mode can only install or edit files inside Patches/. '
                                      'Reopen in Developer Mode to change distribution files.')
        if not replace_existing <= set(writes):
            raise ValueError('Replacement authorization without matching file update')
        sources = [src for src,_ in moves]
        outputs = [dst for _,dst in moves] + list(writes)
        if len({str(p).casefold() for p in sources}) != len(sources):
            raise ValueError('Duplicate move sources')
        if set(sources) & deletes:
            raise ValueError('Cannot both move and delete the same file')
        if deletes & set(outputs):
            raise ValueError('Cannot both write and delete the same file')
        if len({str(p).casefold() for p in outputs}) != len(outputs):
            raise ValueError('Two operations target the same destination')
        for src in sources:
            if not src.is_file() or (not src.is_relative_to(self.character)
                                     and not src.is_relative_to(self.patches_path)):
                raise ValueError(f'Unsafe or missing source: {src}')
        for path in deletes:
            if (not path.is_file() or
                    not (path.is_relative_to(self.patches_path) or
                         (self.developer_mode and path.is_relative_to(self.character)))):
                raise ValueError(f'Unsafe or missing resource deletion: {path}')
        for path in outputs:
            if (not path.is_relative_to(self.character) and path != self.archive_path
                    and not path.is_relative_to(self.patches_path)
                    and path not in self.distribution_text_paths):
                raise ValueError(f'Output outside the Character folder: {path}')
        source_keys = {str(p).casefold() for p in sources}
        for path in outputs:
            if path.exists() and str(path).casefold() not in source_keys and path not in writes:
                raise ValueError(f'Destination already exists: {path}')
            if path in writes and path.exists() and path != self.archive_path and str(path).casefold() not in source_keys and path not in replace_existing:
                raise ValueError(f'Cannot overwrite an existing asset: {path}')
        touched = set(sources) | set(outputs) | deletes
        backup_map: dict[Path, Path] = {}
        with tempfile.TemporaryDirectory(prefix='.rrcm-stage-') as temp:
            stage = Path(temp)
            staged: list[tuple[Path,Path]] = []
            for i,(src,dst) in enumerate(moves):
                staged_path = stage / f'move-{i:05d}'
                shutil.copy2(src,staged_path)
                staged.append((staged_path,dst))
            for i,(dst,blob) in enumerate(writes.items()):
                staged_path = stage / f'write-{i:05d}'
                staged_path.write_bytes(blob)
                staged.append((staged_path,dst))
            rollback=stage/'rollback';rollback.mkdir()
            for i,path in enumerate(sorted(touched,key=str)):
                if path.exists():
                    target = rollback / str(i)
                    shutil.copy2(path,target)
                    backup_map[path] = target
            report = {
                'description':plan.description,
                'backups': {str(path):f'files/{loc.name}' for path,loc in backup_map.items()},
                'moves': [(str(s),str(d)) for s,d in moves],
                'writes': [str(s) for s in writes],
                'deletes': [str(s) for s in sorted(deletes)],
                'warnings':plan.warnings,
            }
            (stage/'transaction.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            try:
                for src in sources + sorted(deletes):
                    src.unlink()
                for staged_path,dst in staged:
                    dst.parent.mkdir(parents=True,exist_ok=True)
                    # Replace on the destination volume, even with external staging.
                    with tempfile.NamedTemporaryFile(dir=dst.parent,prefix='.rrcm-',delete=False) as f:
                        tmp_path=Path(f.name)
                        with staged_path.open('rb') as stream:shutil.copyfileobj(stream,f)
                    try:os.replace(tmp_path,dst)
                    finally:tmp_path.unlink(missing_ok=True)
                # Validate the installed archive and its file inventory while
                # temporary copies remain available for rollback.
                if imported_character is None:
                    self.reload()
                else:
                    self._reload_imported_character(plan, imported_character)
            except Exception:
                for dst in outputs:
                    if dst.exists():
                        dst.unlink()
                for path,copied in backup_map.items():
                    path.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(copied,path)
                self.reload()
                raise
        # Remove only empty, former per-character folders. No active assets are deleted.
        for source in sources + sorted(deletes):
            parent = source.parent
            while parent != self.patches_path and parent.is_relative_to(self.patches_path):
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        return None
