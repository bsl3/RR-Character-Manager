"""Check resource headers and bounds before installation."""
import struct

from .brrescore import _resources, _sections, list_models
from .szs import U8Archive


def validate_brres(data, label='BRRES', require_model=False):
    try:
        resources = _resources(data)
        models = list_models(data) if resources.get('3DModels(NW4R)') or require_model else []

        def u32(at):
            if not 0 <= at <= len(data) - 4:
                raise ValueError(f'field at 0x{at:x} outside resource')
            return struct.unpack_from('>I', data, at)[0]

        def check_name(base):
            target = base + struct.unpack_from('>i', data, base)[0]
            if not 0 <= target < len(data):
                raise ValueError(f'name pointer 0x{target:x} outside BRRES')
            if data.find(b'\0', target) < 0:
                raise ValueError('unterminated texture name')

        for model in models:
            start, end = model.offset, model.offset + model.size
            if model.version != 11:
                continue
            sections = [_sections(data, start, end, i) for i in range(13)]
            for _, material in sections[8]:
                if material + 0x34 > end:
                    raise ValueError('truncated MDL0 material')
                count, offset = u32(material + 0x2c), u32(material + 0x30)
                if count > 8 or count and (offset < 0x34 or material + offset + count * 0x34 > end):
                    raise ValueError(f'invalid material layers at 0x{material:x}')
                for i in range(count):
                    check_name(material + offset + i * 0x34)
            for _, links in sections[11]:
                count = u32(links)
                if count > 65535 or links + 4 + count * 8 > end:
                    raise ValueError(f'invalid texture-link count at 0x{links:x}')

        for folder, entries in resources.items():
            for name, at in entries:
                if at + 12 > len(data):
                    raise ValueError(f'{folder}/{name}: truncated section header')
                if data[at:at + 4] in (b'TEX0', b'PLT0', b'CHR0', b'SRT0', b'PAT0', b'VIS0', b'CLR0', b'SHP0', b'SCN0'):
                    size = u32(at + 4)
                    if size < 12 or at + size > len(data):
                        raise ValueError(f'{folder}/{name}: invalid native section size')
        return [model.name for model in models]
    except (ValueError, struct.error, IndexError) as error:
        raise ValueError(f'{label}: {error}') from error


def validate_asset(data, category, label):
    if category == 'Driver':
        return validate_brres(data, label, True)
    if category in ('RaceKart', 'AllKart'):
        try:
            archive = U8Archive.read(data)
        except ValueError as error:
            raise ValueError(f'{label}: {error}') from error
        for name, raw in archive.files.items():
            if raw.startswith(b'bres') or name.lower().endswith('.brres'):
                validate_brres(raw, label + ' / ' + name)
