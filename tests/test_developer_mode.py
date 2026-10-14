from fixture_paths import fixture_path, require_fixture
"""Standard users cannot accidentally modify Retro Rewind distribution assets."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from PIL import Image
from wcm.operations import CharacterPack, EditPlan
from wcm.szs import U8Archive
from wcm.bmg import CharacterBMG


class TestDeveloperMode(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.characters = self.root / 'Character'
        (self.characters / 'Driver').mkdir(parents=True)
        (self.characters / 'Driver/lg-1.brres').write_bytes(b'bres' + b'X' * 32)
        self.archive = self.root / 'Assets/ReplacedAssets.szs'
        self.archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(require_fixture('RRAssets.zip')) as rr:
            self.archive.write_bytes(rr.read('Assets/ReplacedAssets.szs'))
        self.original_archive = self.archive.read_bytes()
        self.patches = self.root / 'Patches'
        self.pack = CharacterPack(self.characters, self.archive, self.patches)
        self.mod = self.root / 'mod'
        self.mod.mkdir()
        (self.mod / 'lg.brres').write_bytes(b'bres' + b'Y' * 32)

    def tearDown(self):
        self.temp.cleanup()

    def test_defaults_to_standard_mode(self):
        self.assertFalse(self.pack.developer_mode)
        self.assertFalse(self.pack.can_edit_skin('lg', 1))

    def test_cannot_edit_distribution_via_any_public_operation(self):
        with self.assertRaisesRegex(PermissionError, 'Developer Mode'):
            self.pack.move_slot('lg', 1, 2)
        with self.assertRaisesRegex(PermissionError, 'Developer Mode'):
            self.pack.edit_text('lg', 1, 'Other', 'Other')
        with self.assertRaisesRegex(PermissionError, 'Developer Mode'):
            self.pack.import_skin(self.mod, 'lg', 2, insert=False, name='New', author='X')
        icon = self.root / 'icon.png'
        Image.new('RGBA', (32, 32), 'red').save(icon)
        with self.assertRaisesRegex(PermissionError, 'Developer Mode'):
            self.pack.replace_map('lg', 1, icon)
        self.assertEqual(self.archive.read_bytes(), self.original_archive)

    def test_commit_rejects_distribution_write_or_move(self):
        bad_write = EditPlan('Direct write', writes={self.archive: b'bad'})
        with self.assertRaisesRegex(PermissionError, 'Standard Mode'):
            self.pack.commit(bad_write)
        bad_move = EditPlan('Direct move', moves=[(self.characters / 'Driver/lg-1.brres',
                                                 self.characters / 'Driver/lg-2.brres')])
        with self.assertRaisesRegex(PermissionError, 'Standard Mode'):
            self.pack.commit(bad_move)
        self.assertEqual((self.characters / 'Driver/lg-1.brres').read_bytes(), b'bres' + b'X'*32)

    def test_standard_can_install_and_edit_own_patch(self):
        plan = self.pack.import_patch_skin(self.mod, 'lg', 8, name='New', author='Creator')
        self.pack.commit(plan)
        self.assertTrue((self.patches / 'New/lg-8.brres').exists())
        self.assertFalse(self.pack.can_edit_skin('lg', 1))
        self.assertTrue(self.pack.can_edit_skin('lg', 8))
        edit = self.pack.edit_text('lg', 8, 'New name', 'New author')
        self.assertTrue(all(p.is_relative_to(self.patches) for p in edit.writes))
        self.pack.commit(edit)
        self.assertEqual(self.pack.inventory.skins[('lg', 8)].name, 'New name')
        self.assertEqual(self.archive.read_bytes(), self.original_archive)

    def test_developer_can_edit_distributed_text(self):
        developer = CharacterPack(self.characters, self.archive, self.patches, developer_mode=True)
        self.assertTrue(developer.can_edit_skin('lg', 1))
        plan = developer.edit_text('lg', 1, 'Developer Name', 'Creator')
        self.assertIn(self.archive, plan.writes)
        developer.commit(plan)
        self.assertEqual(developer.inventory.skins[('lg', 1)].name, 'Developer Name')


if __name__ == '__main__':
    unittest.main()
