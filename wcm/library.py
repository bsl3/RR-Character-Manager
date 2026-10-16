"""Character filename inventory, with one parser for scan/import/renaming."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from collections import defaultdict
import re
from typing import Iterable
from .bmg import CharacterBMG, name_id, author_id

CHARACTER_CODES = ('mr','bpc','wl','kp','bds','ka','bmr','lg','ko','dk','ys','wr','blg','kk','nk','ds','pc','ca','dd','kt','jr','bk','fk','rs')
CHARACTER_NAMES = ('Mario','Baby Peach','Waluigi','Bowser','Baby Daisy','Dry Bones','Baby Mario','Luigi','Toad','Donkey Kong','Yoshi','Wario','Baby Luigi','Toadette','Koopa Troopa','Daisy','Peach','Birdo','Diddy Kong','King Boo','Bowser Jr.','Dry Bowser','Funky Kong','Rosalina')
CODE_IDS = {code:i for i, code in enumerate(CHARACTER_CODES)}

# Presentation order matches the Mario Kart Wii character-select screen.
# CHARACTER_CODES remains in native CharacterId order for BMG message IDs.
DISPLAY_GROUPS = (
    ('Lightweight', ('bmr', 'blg', 'bpc', 'bds', 'ko', 'kk', 'nk', 'ka')),
    ('Mediumweight', ('mr', 'lg', 'pc', 'ds', 'ys', 'ca', 'dd', 'jr')),
    ('Heavyweight', ('wr', 'wl', 'dk', 'kp', 'kt', 'rs', 'fk', 'bk')),
)
DISPLAY_CODES = tuple(code for _, codes in DISPLAY_GROUPS for code in codes)
assert len(DISPLAY_CODES) == 24 and set(DISPLAY_CODES) == set(CHARACTER_CODES)
CATEGORY_DIR = {'Driver':'Driver','AllKart':'AllKart','RaceKart':'', 'Map':'Map', 'Portrait':'Portrait', 'Sound':'Sound'}

PATTERNS = (
    ('Driver', re.compile(r'^(?P<code>[a-z]{2,3})(?:-(?P<slot>\d+))?\.brres$', re.I)),
    ('Driver', re.compile(r'^(?P<code>[a-z]{2,3})(?:-(?P<slot>\d+))?_(?:menu|driver)\.brres$', re.I)),
    ('AllKart', re.compile(r'^(?P<code>[a-z]{2,3})(?:-(?P<slot>\d+))?-allkart(?:_BT)?\.szs$', re.I)),
    ('Portrait', re.compile(r'^(?P<code>[a-z]{2,3})(?:-(?P<slot>\d+))?-css\.tpl$', re.I)),
    ('Map', re.compile(r'^(?P<code>[a-z]{2,3})(?:-(?P<slot>\d+))?\.tpl$', re.I)),
    ('Sound', re.compile(r'^GRP_VO_(?P<code>[a-z]{2,3})(?:-(?P<slot>\d+))?_.+\.(?:brwsd|brseq|brbnk)(?:\.[\w-]+)?$', re.I)),
    ('Sound', re.compile(r'^\d+\.(?P<code>[a-z]{2,3})(?:-(?P<slot>\d+))?\.[\w.-]+$', re.I)),
    ('Sound', re.compile(r'^(?P<code>[a-z]{2,3})(?:-(?P<slot>\d+))?\.silent$', re.I)),
    ('RaceKart', re.compile(r'^.+-(?P<code>[a-z]{2,3})(?:-(?P<slot>\d+))?(?:_BT|_2|_4)?\.szs$', re.I)),
)


@dataclass(frozen=True)
class Asset:
    relpath: str
    category: str
    code: str
    slot: int | None
    slot_bounds: tuple[int, int] | None
    insert_at: int

    def filename_for(self, new_slot: int) -> str:
        if not 1 <= new_slot <= 100:
            raise ValueError('Custom character slot must be 1–100')
        name = PurePosixPath(self.relpath).name
        if self.category == 'Driver' and name.casefold().endswith(('_menu.brres', '_driver.brres')):
            return f'{self.code}-{new_slot}.brres'
        if self.slot_bounds:
            start, end = self.slot_bounds
            return name[:start] + str(new_slot) + name[end:]
        return name[:self.insert_at] + '-' + str(new_slot) + name[self.insert_at:]

    def destination(self, new_slot: int) -> str:
        subfolder = CATEGORY_DIR[self.category]
        filename = self.filename_for(new_slot)
        return f'{subfolder}/{filename}' if subfolder else filename


def parse_asset(relative: str, *, source_import: bool = False) -> Asset | None:
    relpath = PurePosixPath(relative.replace('\\', '/'))
    if relpath.is_absolute() or '..' in relpath.parts or not relpath.parts:
        return None
    filename = relpath.name
    parent = relpath.parent.name if len(relpath.parts) > 1 else ''
    # Award models may share a filename with Driver models but do not represent
    # an additional selectable driver asset.
    if source_import and parent.casefold() == 'award':
        return None
    for cat, regex in PATTERNS:
        match = regex.fullmatch(filename)
        if not match:
            continue
        if cat == 'Driver' and filename.casefold().endswith(('_menu.brres', '_driver.brres')) and not source_import:
            continue
        code = match.group('code').lower()
        if code not in CODE_IDS:
            continue
        allowed_parent = CATEGORY_DIR[cat]
        if not source_import and parent != allowed_parent:
            continue
        if source_import and parent and parent in CATEGORY_DIR.values() and parent != allowed_parent:
            continue
        val = match.group('slot')
        if not source_import and val is None:
            return None
        if val is not None and not 1 <= int(val) <= 100:
            return None
        span = match.span('slot') if val is not None else None
        return Asset(relative, cat, code, int(val) if val is not None else None,
                     span, match.end('code'))
    return None


@dataclass
class Skin:
    code: str
    slot: int
    files: list[Asset] = field(default_factory=list)
    name: str = ''
    author: str = ''

    @property
    def counts(self) -> dict[str,int]:
        return {cat: sum(a.category == cat for a in self.files) for cat in CATEGORY_DIR}


@dataclass
class Inventory:
    skins: dict[tuple[str,int], Skin]
    orphans: list[str]
    unknown: list[str]
    scanned_file_count: int

    def by_character(self, code: str) -> list[Skin]:
        return [skin for (c,_),skin in sorted(self.skins.items()) if c == code]


def scan_paths(paths: Iterable[str], bmg: CharacterBMG | None = None) -> Inventory:
    matches = defaultdict(list)
    other = []
    count = 0
    for rel in paths:
        count += 1
        asset = parse_asset(rel)
        if asset:
            matches[(asset.code, asset.slot)].append(asset)
        else:
            other.append(rel)
    skins = {}
    orphans = []
    for (code, slot), files in matches.items():
        if not any(asset.category == 'Driver' for asset in files):
            orphans.extend(a.relpath for a in files)
            continue
        cid = CODE_IDS[code]
        skins[(code,slot)] = Skin(code,slot,sorted(files,key=lambda a:a.relpath),
            bmg.get_text(name_id(cid,slot)) if bmg else '',
            bmg.get_text(author_id(cid,slot)) if bmg else '')
    return Inventory(skins,sorted(orphans),sorted(other),count)


def scan_folder(folder: Path, bmg: CharacterBMG | None = None) -> Inventory:
    root = folder.resolve()
    if not root.is_dir():
        raise ValueError('Please choose the existing Character directory')
    files = (str(f.relative_to(root)).replace('\\','/') for f in root.rglob('*') if f.is_file())
    return scan_paths(files, bmg)


def normalized_import_files(paths: Iterable[str]) -> list[tuple[str, Asset]]:
    """Source entries may be in subfolders or raw; detect only recognized files."""
    found = []
    for path in paths:
        if path.endswith('/'):
            continue
        asset = parse_asset(path, source_import=True)
        if asset:
            found.append((path, asset))
    return found


def driver_path_role(path: str) -> str:
    """Distinguish resource-purpose folders from alternative skin folders."""
    parts = PurePosixPath(path.replace('\\', '/')).parts
    for part in reversed(parts):
        label = part.casefold()
        if re.match(r'^(award|demo)(?:$|[ _.(])', label):
            return 'award'
        if re.match(r'^(driver|menu)(?:$|[ _.(])', label) or label.endswith('_menu.brres'):
            return 'menu'
    return ''


def available_import_variants(paths: Iterable[str]) -> list[str]:
    """Identify independently installable skins inside one mod ZIP/folder.

    A typical ZIP includes e.g. "mod/Full Slot/Driver/wr.brres" and
    "mod/Bike Only/Driver/wr.brres". Keep the full source prefix so callers
    can filter the original ZIP entries without extracting them first.
    """
    paths = list(paths)
    roots: set[str] = set()
    for raw in paths:
        asset = parse_asset(raw, source_import=True)
        if not asset or asset.category != 'Driver' or driver_path_role(raw) == 'award':
            continue
        parts = PurePosixPath(raw.replace('\\', '/')).parts[:-1]
        if parts and re.match(r'^(driver|menu)(?:$|[ _.(])', parts[-1], re.I):
            parts = parts[:-1]
        roots.add('/'.join(parts))
    if len(roots) > 1:
        return sorted(roots, key=lambda name: (name.casefold(), name))
    overlays = resource_overlay_roots(paths)
    return [DEFAULT_RESOURCE_VARIANT, *overlays] if overlays else []


DEFAULT_RESOURCE_VARIANT = '@default-resources'


def resource_overlay_roots(paths: Iterable[str]) -> list[str]:
    """Find nested folders that explicitly replace same-destination parent assets."""
    groups = defaultdict(list)
    for path in paths:
        asset = parse_asset(path, source_import=True)
        if asset and asset.category not in ('Portrait', 'Map'):
            groups[asset.destination(1).casefold()].append(PurePosixPath(path.replace('\\', '/')))
    roots = set()
    for items in groups.values():
        for base in items:
            for replacement in items:
                if base.parent != replacement.parent and base.parent in replacement.parent.parents:
                    branch = replacement.parts[:len(base.parent.parts)+1]
                    roots.add('/'.join(branch))
    return sorted(roots, key=lambda item: (item.casefold(), item))


def select_import_entries(entries: list[tuple[str, bytes]], variant: str | None) -> list[tuple[str, bytes]]:
    """Apply existing skin prefixes or an explicitly selected nested resource overlay."""
    variants = available_import_variants(path for path, _ in entries)
    if not variants:
        if variant:
            raise ValueError('This source no longer contains the selected variant. Re-select the source.')
        return list(entries)
    if variant not in variants:
        raise ValueError('This mod contains alternative installation variants. Select one variant in the import wizard.')
    overlays = resource_overlay_roots(path for path, _ in entries)
    if DEFAULT_RESOURCE_VARIANT not in variants:
        prefix = variant.replace('\\', '/').strip('/') + '/'
        return [(path, data) for path, data in entries if path.replace('\\', '/').startswith(prefix)]
    shared = [(path, data) for path, data in entries
              if not any(path.replace('\\', '/').startswith(root + '/') for root in overlays)]
    if variant == DEFAULT_RESOURCE_VARIANT:
        return shared
    chosen = [(path, data) for path, data in entries if path.replace('\\', '/').startswith(variant + '/')]
    replacements = {asset.destination(1) for path, _ in chosen if (asset := parse_asset(path, source_import=True))}
    return [(path, data) for path, data in shared
            if not ((asset := parse_asset(path, source_import=True)) and asset.destination(1) in replacements)] + chosen


def preferred_import_code(paths: Iterable[str]) -> str | None:
    """Prefer the base with supplied race resources over secondary menu components."""
    scores = defaultdict(lambda: [0, 0, 0])
    for path in paths:
        asset = parse_asset(path, source_import=True)
        if not asset or driver_path_role(path) == 'award':
            continue
        scores[asset.code][0] += asset.category == 'RaceKart'
        scores[asset.code][1] += asset.category == 'Driver'
        scores[asset.code][2] += asset.category == 'AllKart'
    return max(sorted(scores), key=lambda code: scores[code]) if scores else None


def race_coverage(assets):
    result={}
    for asset in assets:
        if asset.category!='RaceKart':continue
        name=PurePosixPath(asset.relpath).name.lower()
        match=re.fullmatch(r'(?P<vehicle>.+?)(?:_(?P<team>red|blue))?-[a-z]{2,3}(?:-\d+)?(?P<mode>_bt|_2|_4)?\.szs',name)
        if not match:continue
        mode=(match['mode'] or 'normal').lstrip('_');key=match['vehicle']+':'+(match['team'] or 'standard')
        if key not in result.setdefault(mode,[]):result[mode].append(key)
    return {mode:sorted(vehicles) for mode,vehicles in sorted(result.items())}


def missing_race_requests(code,coverage):
    # Native weight-specific vehicle archive stems: five vehicles plus drift.
    group=next(i for i,(_,codes) in enumerate(DISPLAY_GROUPS) if code in codes)
    prefix=('s','m','l')[group]
    stems={prefix+vehicle+'_'+kind+':standard' for vehicle in ('a','b','c','d','df','e') for kind in ('kart','bike')}
    return {mode:sorted(stems-set(coverage.get(mode,[]))) for mode in ('normal','2','4')}


def unused_race_variant(relative):
    """Skip team/battle and split-screen vehicle variants during import."""
    asset = parse_asset(relative, source_import=True)
    if asset is None or asset.category != 'RaceKart':
        return False
    name = PurePosixPath(relative.replace('\\', '/')).name.lower()
    return bool(re.search(r'_(?:red|blue)-', name) or name.endswith(('_bt.szs', '_2.szs', '_4.szs')))
