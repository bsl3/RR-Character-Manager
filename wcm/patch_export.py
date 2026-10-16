"""Export a Patches tree for RR's non-recursive SD loader."""
from pathlib import Path
import shutil
from .backups import files
from .library import parse_asset


def export(pack,destination):
    destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Choose a new export folder; existing files are never overwritten.')
    if destination.is_relative_to(pack.character.parent) or destination.is_relative_to(pack.patches_path):
        raise ValueError('Export outside the RR installation.')
    outputs={}
    indexed={p.resolve():logical for logical,p in pack.patch_assets.items()}
    for path in files(pack.patches_path):
        relative=path.relative_to(pack.patches_path)
        if path==pack._resource_index_path():continue
        logical=indexed.get(path.resolve())
        runtime=parse_asset(path.name,source_import=True) or logical or path.name.lower().endswith(('.uiassets.szs','.raceassets.szs','.replacedassets.szs'))
        key=Path(logical).name if logical else path.name
        target=Path(key) if runtime else relative
        folded=target.as_posix().casefold()
        if folded in outputs and outputs[folded][1].read_bytes()!=path.read_bytes():
            raise ValueError('Conflicting runtime patch filenames: '+key)
        outputs[folded]=(target,path)
    destination.mkdir(parents=True)
    try:
        for relative,path in outputs.values():
            target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    except Exception:
        shutil.rmtree(destination);raise
    return destination
