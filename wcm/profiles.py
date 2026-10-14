"""Persistent connection profiles for independent Character/Assets/Patches packs.

This module has no Qt dependency so profile migration and isolation can be tested
without a desktop environment. Only paths and profile names are persistent;
Developer Mode remains an explicit per-open choice.
"""
from __future__ import annotations

import json
import uuid

PROFILES_KEY = 'connectionProfilesV1'
ACTIVE_KEY = 'activeConnectionProfileId'


def default_profile(settings) -> dict[str, str]:
    """Migrate the previous single-library settings without losing its paths."""
    character = str(settings.value('characterPath', '') or '')
    archive = str(settings.value('archivePath', '') or '')
    patches = str(settings.value('patchesPath', '') or '')
    if character and not patches:
        from pathlib import Path
        patches = str(Path(character).parent / 'Patches')
    return {'id': 'default', 'name': 'Default', 'character': character,
            'archive': archive, 'patches': patches}


def load_profiles(settings) -> list[dict[str, str]]:
    fallback = default_profile(settings)
    saved = settings.value(PROFILES_KEY, '')
    if not saved:
        return [fallback]
    try:
        values = json.loads(str(saved))
        if not isinstance(values, list):
            raise ValueError('Profiles are not a list')
        result = []
        seen = set()
        for entry in values:
            if not isinstance(entry, dict):
                raise ValueError('Invalid profile')
            identity = entry.get('id')
            name = entry.get('name')
            if (not isinstance(identity, str) or not identity or identity in seen or
                    not isinstance(name, str) or not name.strip()):
                raise ValueError('Invalid profile identity or name')
            paths = (entry.get('character'), entry.get('archive'), entry.get('patches'))
            if not all(isinstance(path, str) for path in paths):
                raise ValueError('Invalid profile path')
            seen.add(identity)
            result.append({'id': identity, 'name': name.strip(),
                           'character': paths[0], 'archive': paths[1], 'patches': paths[2]})
        # Fall back to the original connection if saved profiles are invalid.
        if not result or result[0]['id'] != 'default':
            raise ValueError('Missing default profile')
        return result
    except (ValueError, TypeError):
        return [fallback]


def make_profile(name: str, ids=()) -> dict[str, str]:
    identifier = uuid.uuid4().hex
    while identifier in ids:
        identifier = uuid.uuid4().hex
    return {'id': identifier, 'name': name.strip(),
            'character': '', 'archive': '', 'patches': ''}


def save_profiles(settings, profiles: list[dict[str, str]], active_id: str) -> None:
    """Save every editor's snapshot without mutating other profile entries."""
    if not profiles or profiles[0]['id'] != 'default':
        raise ValueError('Default connection must be preserved')
    if active_id not in {profile['id'] for profile in profiles}:
        raise ValueError('Unknown active profile')
    settings.setValue(PROFILES_KEY, json.dumps(profiles, ensure_ascii=False))
    settings.setValue(ACTIVE_KEY, active_id)
    # Older app versions use the default profile paths.
    original = profiles[0]
    for old_key, key in (('characterPath', 'character'), ('archivePath', 'archive'),
                         ('patchesPath', 'patches')):
        settings.setValue(old_key, original[key])
    settings.sync()
