"""Lossless message merging; precedence is explicit and reported before commit."""
from collections import OrderedDict
from pathlib import Path
import re
from .bmg import CharacterBMG, Message
from .szs import U8Archive

MEMBER = 'message/CharaName.bmg'
RACE_MEMBER = 'message/CharaRR.bmg'
TAGGED = re.compile(r'^\[message\]Chara(?:(?:Name|RR)\.bmg\.(?:uiassets|raceassets)|RR\.bmg\.replacedassets)$',re.I)


def merge_tables(sources):
    """Sources are low to high priority. Retain each winning raw entry + metadata.

    Unknown sections have no general merge semantics: incompatible copies fail
    closed instead of discarding opaque content. All sources must use one INF width.
    """
    result = CharacterBMG.read(sources[0][1])
    entries, owners, conflicts = {}, {}, []
    opaque = {}
    for label, raw in sources:
        table = CharacterBMG.read(raw)
        if table.entry_width != result.entry_width:
            raise ValueError(f'Cannot merge incompatible BMG metadata widths: {label}')
        for tag, chunk in table.sections:
            if tag in (b'INF1', b'DAT1', b'MID1'):
                continue
            if tag in opaque and opaque[tag] != chunk:
                raise ValueError(f'Incompatible opaque BMG section {tag!r} in {label}; preserve both sources and resolve externally')
            opaque[tag] = chunk
        for message in table.messages:
            old = entries.get(message.id)
            if old and (old.raw, old.metadata) != (message.raw, message.metadata):
                # Include both text values and metadata differences in the review.
                old_text = old.raw[:-2].decode('utf-16-be', errors='replace')
                new_text = message.raw[:-2].decode('utf-16-be', errors='replace')
                conflicts.append(f'0x{message.id:08x}: {owners[message.id]} {old_text!r} → {label} {new_text!r}'
                                 + (' (INF metadata differs)' if old.metadata != message.metadata else ''))
            entries[message.id] = Message(message.id, message.raw, message.metadata)
            owners[message.id] = label
    result.sections = [(tag, chunk) for tag, chunk in result.sections
                       if tag in (b'INF1', b'DAT1', b'MID1')]
    result.sections.extend(opaque.items())
    result.messages = sorted(entries.values(), key=lambda m: m.id)
    result.dirty = True
    return result, conflicts


def find_sources(patches: Path, base: bytes, loose: Path, canonical):
    """Distribution < loose legacy < other archives < root pair < nested pair.

    Within a pair Race precedes UI. Other archives are ordered by casefolded
    relative path, so outcomes do not depend on filesystem enumeration order.
    """
    sources = [('distribution CharaRR', base)]
    if loose.is_file():
        sources.append((loose.name, loose.read_bytes()))
    archives = {};alias_conflicts=[]
    paths = sorted((p for p in patches.rglob('*') if p.is_file() and not p.is_symlink() and p != loose and
                    (p.name.lower().endswith(('.uiassets.szs', '.raceassets.szs')) or TAGGED.match(p.name))),
                   key=lambda p: p.relative_to(patches).as_posix().casefold()) if patches.is_dir() else []
    root_pair = [patches / p.name for p in canonical]
    priorities = [*reversed(root_pair), *reversed(canonical)]
    paths = [p for p in paths if p not in priorities] + [p for p in priorities if p in paths]
    for path in paths:
        if TAGGED.match(path.name):
            archives[path] = None  # loose tagged BMG: no archive members to rewrite
            if not path.name.casefold().endswith('chararr.bmg.raceassets'):
                sources.append((path.relative_to(patches).as_posix(),path.read_bytes()))
            continue
        archive = U8Archive.from_file(path)
        if MEMBER not in archive.files and RACE_MEMBER not in archive.files:
            continue
        archives[path] = archive
        # Canonical wins; report conflicting character IDs before commit.
        if MEMBER in archive.files and RACE_MEMBER in archive.files:
            canonical_table=CharacterBMG.read(archive.files[MEMBER]);alias=CharacterBMG.read(archive.files[RACE_MEMBER])
            expected={m.id:(m.raw,m.metadata) for m in canonical_table.messages if character_text_id(m.id)}
            for m in alias.messages:
                if m.id in expected and expected[m.id]!=(m.raw,m.metadata):
                    alias_conflicts.append(f'{path.name}: CharaRR disagrees with canonical CharaName at 0x{m.id:08x}')
        if MEMBER in archive.files:
            sources.append((path.relative_to(patches).as_posix(), archive.files[MEMBER]))
        else:
            sources.append((path.relative_to(patches).as_posix()+' legacy CharaRR',archive.files[RACE_MEMBER]))
    table, conflicts = merge_tables(sources)
    return table, conflicts+alias_conflicts, archives


def merged_archive(files, contributors, encoded):
    """Preserve same-side legacy members; ambiguous payload conflicts fail closed."""
    files = OrderedDict(files)
    for archive in contributors:
        for member, payload in archive.files.items():
            if member in (MEMBER, RACE_MEMBER):
                continue
            if member in files and files[member] != payload:
                raise ValueError(f'Archive member conflict for {member}; refusing to discard either copy')
            files[member] = payload
    files[MEMBER] = encoded
    if RACE_MEMBER in files:
        files[RACE_MEMBER]=synchronized_character_text(files[RACE_MEMBER],CharacterBMG.read(encoded),character_text_id)
    archive = U8Archive(files, compressed=True)
    output = archive.encode()
    if dict(U8Archive.read(output).files) != dict(files):
        raise ValueError('Merged archive validation failed')
    return output


def synchronized_character_text(raw, menu, predicate, removed=()):
    """Copy canonical name/author entries, retaining destination-only game text."""
    table = CharacterBMG.read(raw)
    if table.entry_width != menu.entry_width:
        raise ValueError('Incompatible UI/Race character text metadata widths')
    entries = {m.id: m for m in menu.messages if predicate(m.id)}
    table.messages = [m for m in table.messages if m.id not in entries and m.id not in removed]
    table.messages.extend(Message(m.id, m.raw, m.metadata) for m in entries.values())
    table.dirty = True
    return table.encode()


def character_text_id(mid):
    from .library import CODE_IDS
    from .bmg import name_id
    return mid in {name_id(cid,0) for cid in CODE_IDS.values()} or (mid>>16 in CODE_IDS.values() and (mid&0xff00) in (0x6a00,0x7a00) and 0<=(mid&0xff)<=100)
