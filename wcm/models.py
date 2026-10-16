"""Read-only discovery and extraction of BRRES models in mod ZIPs and SZS files.

The shared embedded viewer renders selected payloads; optional BrawlCrate covers
advanced material/animation inspection. This module never poses or rewrites models.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import zipfile
from .szs import U8Archive

MAX_MODEL_SOURCE_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class ModelCandidate:
    source_path: str
    archive_member: str = ''
    size: int = 0
    category: str = ''

    @property
    def label(self) -> str:
        return f'{self.source_path}  →  {self.archive_member}' if self.archive_member else self.source_path

    @property
    def is_driver(self) -> bool:
        leaf = (self.archive_member or self.source_path).rsplit('/', 1)[-1].casefold()
        if self.archive_member:
            from .library import parse_asset
            asset = parse_asset(self.archive_member, source_import=True)
            return leaf == 'driver_model.brres' or bool(asset and asset.category == 'Driver' and self.category.startswith('Menu driver'))
        return (leaf.endswith('.brres') and leaf not in ('kart_model.brres', 'driver_anim.brres')
                and not self.category.startswith(('Award', 'Auxiliary', 'Vehicle', 'Animations')))



def source_entries(source: Path) -> list[tuple[str, bytes]]:
    """Load a bounded character source; never extract arbitrary ZIP paths to disk."""
    source = Path(source)
    if source.suffix.lower() == '.mkchara':
        from .mkchara import read_package
        return read_package(source).preview_entries()
    if source.is_dir():
        result = []
        total = 0
        for file in source.rglob('*'):
            if file.is_symlink():
                continue
            if file.is_file():
                size = file.stat().st_size
                total += size
                if size > MAX_MODEL_SOURCE_BYTES or total > 1024*1024*1024 or len(result) >= 10000:
                    raise ValueError('Mod folder exceeds import size or file-count limits')
                result.append((file.relative_to(source).as_posix(), file.read_bytes()))
        return result
    if source.suffix.lower() == '.zip':
        with zipfile.ZipFile(source) as archive:
            items = [i for i in archive.infolist() if not i.is_dir()]
            if len(items) > 10000 or sum(i.file_size for i in items) > 1024*1024*1024:
                raise ValueError('Mod ZIP is too large to inspect safely')
            result = []
            for info in items:
                path = PurePosixPath(info.filename.replace('\\', '/'))
                if path.is_absolute() or '..' in path.parts or info.file_size > MAX_MODEL_SOURCE_BYTES:
                    continue
                result.append((path.as_posix(), archive.read(info)))
            return result
    if source.stat().st_size > MAX_MODEL_SOURCE_BYTES:
        raise ValueError('Model source is too large')
    return [(source.name, source.read_bytes())]


def driver_model_role(path: str, payload: bytes) -> tuple[str, set[str]]:
    """Read existing BRRES dictionaries to identify menu/race/demo animation sets."""
    from .brrescore import _resources
    from struct import error as StructError
    from .library import driver_path_role
    try:
        resources = _resources(payload)
        animations = {name.casefold() for name, _ in resources.get('AnmChr(NW4R)', [])}
        if not resources.get('3DModels(NW4R)'):
            return 'Animations (not a driver model)', animations
    except (ValueError, StructError, IndexError):
        animations = set()
    leaf = PurePosixPath(path).name.casefold()
    if (leaf in ('kart_model.brres', 'driver_anim.brres') or 'allkart' in leaf
            or (animations and animations <= {'wait'})):
        return 'Auxiliary model (not a standalone driver)', animations
    if animations & {'sel_wait', 'sel_gut'}:
        return 'Menu driver (character selection)', animations
    if any(name.startswith('demo') for name in animations) or driver_path_role(path) == 'award':
        return 'Award / demo (not a menu or race driver)', animations
    if animations & {'drive', 'drift_l', 'drift_r', 'back', 'dash'}:
        return 'Race driver / standalone (no selection animations)', animations
    if driver_path_role(path) == 'menu':
        return 'Menu model (selection animations unverified)', animations
    return 'Driver / standalone', animations


def discover_models(entries: list[tuple[str, bytes]], *, source_variant: str | None = None,
                    include_auxiliary: bool = False) -> list[ModelCandidate]:
    """Find the exact embedded BRRES payloads; do not claim they are T-posed."""
    if source_variant:
        from .library import select_import_entries
        entries = select_import_entries(entries, source_variant)
    prefix = None
    results: list[ModelCandidate] = []
    for source_path, payload in entries:
        if prefix and not source_path.startswith(prefix):
            continue
        lower = source_path.casefold()
        if lower.endswith('.brres') and payload.startswith(b'bres'):
            category, _ = driver_model_role(source_path, payload)
            results.append(ModelCandidate(source_path, size=len(payload), category=category))
        if not lower.endswith('.szs'):
            continue
        # Do not offer unrelated stage/item models from Common.szs as a character driver.
        if not include_auxiliary and PurePosixPath(source_path).name.casefold() == 'common.szs':
            continue
        try:
            archive = U8Archive.read(payload)
        except ValueError:
            continue
        for member, data in archive.files.items():
            if not member.lower().endswith('.brres') or not data.startswith(b'bres'):
                continue
            label = PurePosixPath(member).name.casefold()
            if label == 'driver_model.brres':
                category = 'Race driver · Bike' if '_bike' in PurePosixPath(lower).name else 'Race driver · Kart' if '_kart' in PurePosixPath(lower).name else 'Race driver'
            elif label == 'kart_model.brres':
                category = 'Vehicle (not driver)'
            elif label == 'driver_anim.brres':
                category = 'Animations (not a driver model)'
            else:
                from .library import parse_asset
                asset = parse_asset(member, source_import=True)
                role, _ = driver_model_role(member, data)
                category = (role + ' · ' + asset.code.upper() if asset and asset.category == 'Driver'
                            and role.startswith('Menu driver') else 'AllKart / other model')
            results.append(ModelCandidate(source_path, member, len(data), category))
    return results


def extract_model_bytes(entries: list[tuple[str,bytes]], candidate: ModelCandidate) -> bytes:
    for name, data in entries:
        if name != candidate.source_path:
            continue
        result = U8Archive.read(data).files[candidate.archive_member] if candidate.archive_member else data
        if not result.startswith(b'bres'):
            raise ValueError('Selected entry is not a valid BRRES resource')
        return result
    raise ValueError(f'Model source not found: {candidate.source_path}')


def automatic_driver_candidate(entries: list[tuple[str,bytes]], code: str | None = None) -> ModelCandidate | None:
    """Choose the standalone menu resource separately from per-vehicle race models.

    Prefer verified selection animations, then a mapped standalone driver. Only
    fall back to embedded race geometry when no suitable standalone exists.
    Award/demo and auxiliary resources never replace the character driver.
    """
    from .library import parse_asset, preferred_import_code
    from .brrescore import list_models,default_model,decode_brres
    code = code or preferred_import_code(path for path, _ in entries)
    import hashlib
    standalone=[]
    # Do not open/decompress SZS archives when a suitable standalone exists.
    for candidate in discover_models([entry for entry in entries if entry[0].lower().endswith('.brres')]):
        if not candidate.is_driver:
            continue
        candidate_asset = parse_asset(candidate.source_path, source_import=True)
        if code and candidate_asset and candidate_asset.code != code:
            continue
        try:
            data=extract_model_bytes(entries,candidate)
            variants=list_models(data);index=default_model(variants)
            asset=parse_asset(candidate.source_path,source_import=True)
            rank=(not candidate.category.startswith('Menu driver'),
                  not bool(asset and asset.category=='Driver'),
                  not candidate.category.startswith('Menu model'),variants[index].is_lod,
                  -variants[index].size,candidate.label.casefold())
            standalone.append((rank,candidate))
        except ValueError:
            continue
    if standalone:
        return min(standalone,key=lambda item:item[0])[1]
    candidates = discover_models(entries)
    menus = []
    for candidate in candidates:
        if not candidate.archive_member or not candidate.category.startswith('Menu driver'):
            continue
        asset = parse_asset(candidate.archive_member, source_import=True)
        if not asset or (code and asset.code != code):
            continue
        try:
            data = extract_model_bytes(entries, candidate)
            models = list_models(data)
            menus.append(((models[default_model(models)].is_lod, candidate.label.casefold()), candidate))
        except ValueError:
            continue
    if menus:
        return min(menus, key=lambda item: item[0])[1]
    choices=[];cache={}
    for candidate in candidates:
        if candidate.archive_member!='driver_model.brres': continue
        asset = parse_asset(candidate.source_path, source_import=True)
        if code and asset and asset.code != code: continue
        try:
            data=extract_model_bytes(entries,candidate);key=hashlib.sha256(data).digest()
            if key not in cache:
                variants=list_models(data);index=default_model(variants)
                mesh=decode_brres(data,index)
                cache[key]=(variants[index].is_lod,len(mesh.triangles))
            lod,triangles=cache[key]
            path=PurePosixPath(candidate.source_path).name.lower()
            rank=(lod,'_bike' in path,any(t in path for t in ('_blue','_red','_bt')),
                  not any(t in path for t in ('sdf_kart','mdf_kart','ldf_kart')),
                  -triangles,candidate.label.casefold())
            choices.append((rank,candidate))
        except ValueError:
            continue
    return min(choices,key=lambda item:item[0])[1] if choices else None


def installed_model_label(path: Path, *, patches: Path | None = None,
                          character: Path | None = None) -> str:
    """Logical pack path for display and in-memory extraction; never a host path."""
    path=Path(path).resolve()
    for label,root in (('Patches',patches),('Character',character)):
        if root is not None and path.is_relative_to(Path(root).resolve()):
            return label+'/'+path.relative_to(Path(root).resolve()).as_posix()
    # Also works for standalone callers whose assets use the standard folders.
    for i,part in enumerate(path.parts):
        if part.casefold() in ('patches','character'):
            return '/'.join(path.parts[i:])
    return path.name


def find_installed_models(paths: list[Path], *, patches: Path | None = None,
                          character: Path | None = None) -> tuple[list[ModelCandidate], list[tuple[str,bytes]]]:
    """Read physical files using pack-relative source keys throughout the dialog."""
    entries = [(installed_model_label(path,patches=patches,character=character), path.read_bytes())
               for path in paths if path.is_file()]
    return discover_models(entries), entries
