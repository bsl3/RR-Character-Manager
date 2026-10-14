"""Profile persistence and isolation checks, no Qt needed."""
import unittest
from wcm.profiles import (ACTIVE_KEY, PROFILES_KEY, default_profile, load_profiles,
                          make_profile, save_profiles)


class FakeSettings:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.synced = 0

    def value(self, key, default=''):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value

    def sync(self):
        self.synced += 1


class ProfilePersistence(unittest.TestCase):
    def setUp(self):
        self.settings = FakeSettings({'characterPath': 'RR/Character',
                                      'archivePath': 'RR/Assets/ReplacedAssets.szs',
                                      'patchesPath': 'RR/Patches'})

    def test_migrate_legacy_saved_default_paths(self):
        self.assertEqual(load_profiles(self.settings), [
            {'id': 'default', 'name': 'Default', 'character': 'RR/Character',
             'archive': 'RR/Assets/ReplacedAssets.szs', 'patches': 'RR/Patches'}])

    def test_new_profile_has_no_shared_paths(self):
        rr = load_profiles(self.settings)[0]
        wiiloaded = make_profile('WiiLoaded', {rr['id']})
        self.assertNotEqual(wiiloaded['id'], rr['id'])
        self.assertEqual(wiiloaded['character'], '')
        self.assertEqual(wiiloaded['archive'], '')
        self.assertEqual(wiiloaded['patches'], '')

    def test_round_trip_keeps_paths_independent_and_old_default_settings(self):
        rr = load_profiles(self.settings)[0]
        wiiloaded = make_profile('WiiLoaded')
        wiiloaded.update(character='WL/Character', archive='WL/Assets/ReplacedAssets.szs',
                         patches='WL/Patches')
        save_profiles(self.settings, [rr, wiiloaded], wiiloaded['id'])
        after = load_profiles(self.settings)
        self.assertEqual(after[0], rr)
        self.assertEqual(after[1], wiiloaded)
        self.assertEqual(self.settings.value('characterPath'), 'RR/Character')
        self.assertEqual(self.settings.value('archivePath'), 'RR/Assets/ReplacedAssets.szs')
        self.assertEqual(self.settings.value('patchesPath'), 'RR/Patches')
        self.assertEqual(self.settings.value(ACTIVE_KEY), wiiloaded['id'])
        self.assertEqual(self.settings.synced, 1)
        # Updating one profile never changes any other profile's paths.
        after[1]['character'] = 'WL2/Character'
        save_profiles(self.settings, after, 'default')
        self.assertEqual(load_profiles(self.settings)[0], rr)
        self.assertEqual(load_profiles(self.settings)[1]['character'], 'WL2/Character')

    def test_removed_profile_is_not_preserved(self):
        rr = load_profiles(self.settings)[0]
        added = make_profile('Test')
        save_profiles(self.settings, [rr, added], added['id'])
        save_profiles(self.settings, [rr], 'default')
        self.assertEqual(load_profiles(self.settings), [rr])

    def test_invalid_saved_data_falls_back_to_original_profile(self):
        self.settings.setValue(PROFILES_KEY, '{not-json')
        self.assertEqual(load_profiles(self.settings)[0]['character'], 'RR/Character')
        self.settings.setValue(PROFILES_KEY, '[]')
        self.assertEqual(load_profiles(self.settings)[0]['archive'], 'RR/Assets/ReplacedAssets.szs')

    def test_cannot_save_without_default_or_active_profile(self):
        rr = load_profiles(self.settings)[0]
        with self.assertRaises(ValueError):
            save_profiles(self.settings, [make_profile('Not Default')], 'default')
        with self.assertRaises(ValueError):
            save_profiles(self.settings, [rr], 'not-found')


if __name__ == '__main__':
    unittest.main()
