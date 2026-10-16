from fixture_paths import fixture_path, require_fixture
"""Regression checks for the fullscreen resource editor backend and legacy migration."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from wcm.operations import CharacterPack
from wcm.library import CODE_IDS
from wcm.bmg import CharacterBMG, name_id

FIXTURE = fixture_path('RRAssets.zip')


@unittest.skipUnless(FIXTURE.is_file(), 'RR assets sample unavailable')
class ResourceManagement(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.character = self.root / 'Character'
        (self.character / 'Driver').mkdir(parents=True)
        (self.character / 'Driver/lg-1.brres').write_bytes(b'distribution-driver')
        self.archive = self.root / 'Assets/ReplacedAssets.szs'
        self.archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(FIXTURE) as z:
            self.archive.write_bytes(z.read('Assets/ReplacedAssets.szs'))
        self.patches = self.root / 'Patches'
        self.pack = CharacterPack(self.character, self.archive, self.patches)
        self.source = self.root / 'mod'
        self.source.mkdir()
        (self.source / 'lg.brres').write_bytes(b'bres' + bytes(32))
        (self.source / 'ma_kart-lg.szs').write_bytes(b'Yaz0' + bytes(32))
        from PIL import Image
        from wcm.tpl import image_to_tpl
        (self.source / 'lg-css.tpl').write_bytes(image_to_tpl(Image.new('RGBA', (64, 64), 'red'), 64))

    def install(self):
        self.pack.commit(self.pack.import_patch_skin(self.source, 'lg', 8, name='Luigi Custom', author='Artist'))

    def test_patch_rename_survives_reload_and_restores_default(self):
        self.install()
        skin = self.pack.inventory.skins['lg', 8]
        names = {a.relpath: a.filename_for(8) for a in skin.files}
        driver = next(a for a in skin.files if a.category == 'Driver')
        names[driver.relpath] = 'anything.special'
        plan = self.pack.rename_resources('lg', 8, names)
        self.assertIn('Custom filenames', '\n'.join(plan.warnings))
        self.pack.commit(plan)
        self.assertTrue((self.patches / 'Luigi Custom/anything.special').exists())
        self.assertEqual(self.pack.asset_path(driver.relpath).name, 'anything.special')
        self.assertEqual(self.pack.inventory.skins['lg', 8].counts['Driver'], 1)
        refreshed = CharacterPack(self.character, self.archive, self.patches)
        self.assertEqual(refreshed.asset_path(driver.relpath).name, 'anything.special')
        revert = refreshed.rename_resources('lg', 8, {driver.relpath: 'lg-8.brres'})
        refreshed.commit(revert)
        self.assertTrue((self.patches / 'Luigi Custom/lg-8.brres').exists())
        self.assertFalse((self.patches / 'Luigi Custom/anything.special').exists())
        self.assertEqual(refreshed.inventory.skins['lg', 8].counts['Driver'], 1)

    def test_patch_renames_collisions_and_invalid_names(self):
        self.install()
        skin = self.pack.inventory.skins['lg', 8]
        a = skin.files[0]
        b = skin.files[1]
        with self.assertRaisesRegex(ValueError, 'Duplicate destination'):
            self.pack.rename_resources('lg', 8, {a.relpath: 'same.ext', b.relpath: 'SAME.EXT'})
        for bad in ('../file', 'bad\\name', 'CON.txt', 'trailing.', 'a:b'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.pack.rename_resources('lg', 8, {a.relpath: bad})
        self.assertEqual(self.pack.inventory.skins['lg', 8].counts['Driver'], 1)

    def test_patch_folder_rename_updates_custom_name_mapping(self):
        self.install()
        asset = next(a for a in self.pack.inventory.skins['lg', 8].files if a.category == 'Driver')
        self.pack.commit(self.pack.rename_resources('lg', 8, {asset.relpath: 'custom.foo'}))
        self.pack.commit(self.pack.edit_text('lg', 8, 'Different Name', 'Other Author'))
        self.assertEqual(self.pack.asset_path(asset.relpath).name, 'custom.foo')
        self.assertTrue((self.patches / 'Different Name/custom.foo').is_file())
        self.assertEqual(self.pack.inventory.skins['lg', 8].name, 'Different Name')

    def test_patch_skin_does_not_grant_access_to_inherited_original_assets(self):
        # The same slot has a distributed CSS but a custom patch driver.
        (self.character / 'Map').mkdir()
        (self.character / 'Map/lg-8.tpl').write_bytes(b'inherited-map')
        self.install()
        asset = next(a for a in self.pack.inventory.skins['lg', 8].files if a.category == 'Map')
        self.assertEqual(self.pack.asset_path(asset.relpath), self.character / 'Map/lg-8.tpl')
        with self.assertRaisesRegex(PermissionError, 'Developer Mode'):
            self.pack.rename_resources('lg', 8, {asset.relpath: 'override.tpl'})
        driver = next(a for a in self.pack.inventory.skins['lg', 8].files if a.category == 'Driver')
        # Patches assets still editable when the original one is inherited.
        self.pack.commit(self.pack.rename_resources('lg', 8, {driver.relpath: 'new-driver.file'}))
        self.assertTrue((self.patches / 'Luigi Custom/new-driver.file').is_file())
        self.assertTrue((self.character / 'Map/lg-8.tpl').is_file())

    def test_standard_does_not_change_original_resources(self):
        with self.assertRaisesRegex(PermissionError, 'Developer Mode'):
            self.pack.rename_resources('lg', 1, {'Driver/lg-1.brres': 'custom.brres'})
        self.assertTrue((self.character / 'Driver/lg-1.brres').is_file())

    def test_developer_distribution_rename_survives_reopen(self):
        dev = CharacterPack(self.character, self.archive, self.patches, developer_mode=True)
        dev.commit(dev.rename_resources('lg', 1, {'Driver/lg-1.brres': 'development-model.dummy'}))
        self.assertFalse((self.character / 'Driver/lg-1.brres').is_file())
        self.assertEqual(dev.asset_path('Driver/lg-1.brres').name, 'development-model.dummy')
        reopened = CharacterPack(self.character, self.archive, self.patches, developer_mode=True)
        self.assertEqual(reopened.inventory.skins['lg', 1].counts['Driver'], 1)
        target = reopened.next_import_slot('lg')
        reopened.commit(reopened.move_slot('lg', 1, target))
        self.assertEqual(reopened.asset_path(f'Driver/lg-{target}.brres').name, 'development-model.dummy')
        reopened.commit(reopened.rename_resources('lg', target, {f'Driver/lg-{target}.brres': f'lg-{target}.brres'}))
        self.assertTrue((self.character / f'Driver/lg-{target}.brres').is_file())

    def test_automatic_organization_preserves_other_files(self):
        self.patches.mkdir()
        (self.patches / 'lg-8.brres').write_bytes(b'legacy')
        (self.patches / 'ma_kart-lg-8.szs').write_bytes(b'vehicle')
        (self.patches / 'my_course.szs').write_bytes(b'unrelated')
        (self.patches / 'wr-7.tpl').write_bytes(b'orphan')
        # Use real shared name archive format to exercise migration.
        bmg = CharacterBMG.read(self.pack.base_bmg.encode())
        bmg.set_text(name_id(CODE_IDS['lg'], 8), 'Custom Luigi')
        from wcm.szs import U8Archive
        from collections import OrderedDict
        archive = U8Archive(OrderedDict([('message/CharaName.bmg', bmg.encode())]), compressed=True).encode()
        for name in ('CharacterNames.uiassets.szs', 'CharacterNames.raceassets.szs'):
            (self.patches / name).write_bytes(archive)
        pack = CharacterPack(self.character, self.archive, self.patches)
        plan = pack.organize_existing_patches()
        self.assertEqual(len(plan.moves), 2)
        self.assertEqual(len(plan.deletes), 2)
        self.assertTrue(all(p in plan.writes for p in pack._patch_name_archives()))
        backup = pack.commit(plan)
        self.assertIsNone(backup)
        self.assertTrue((self.patches / 'Custom Luigi/lg-8.brres').is_file())
        self.assertTrue((self.patches / 'Custom Luigi/ma_kart-lg-8.szs').is_file())
        self.assertTrue((self.patches / 'Custom Luigi/_rr_character.json').is_file())
        self.assertTrue((self.patches / 'CharacterNames/CharacterNames.uiassets.szs').is_file())
        self.assertTrue((self.patches / 'CharacterNames/CharacterNames.raceassets.szs').is_file())
        self.assertTrue((self.patches / 'my_course.szs').is_file())
        self.assertTrue((self.patches / 'wr-7.tpl').is_file())
        self.assertEqual(pack.organize_existing_patches().moves, [])

if __name__ == '__main__':
    unittest.main()
