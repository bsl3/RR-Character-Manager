from fixture_paths import fixture_path, require_fixture
"""Developer distribution edits use the same icon importer and BMG sync as Patches."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from PIL import Image
from wcm.operations import CharacterPack
from wcm.szs import U8Archive
from wcm.bmg import CharacterBMG, name_id, author_id
from wcm.library import CODE_IDS
from wcm.tpl import read_tpl, image_to_tpl

ASSET_ZIP = fixture_path('RRAssets.zip')


class TestDeveloperSynchronization(unittest.TestCase):
    def setUp(self):
        if not ASSET_ZIP.is_file():
            self.skipTest('RR asset fixture unavailable')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.character = self.root / 'Character'
        (self.character / 'Driver').mkdir(parents=True)
        self.replaced = self.root / 'Assets' / 'ReplacedAssets.szs'
        self.replaced.parent.mkdir(parents=True)
        with zipfile.ZipFile(ASSET_ZIP) as z:
            self.replaced.write_bytes(z.read('Assets/ReplacedAssets.szs'))
        self.patches = self.root / 'Patches'
        self.mod = self.root / 'mod'
        (self.mod / 'Driver').mkdir(parents=True)
        (self.mod / 'Driver' / 'lg.brres').write_bytes(b'bres' + b'\x00' * 64)
        self.pack = CharacterPack(self.character, self.replaced, self.patches, developer_mode=True)

    def names(self):
        return CharacterBMG.read(U8Archive.from_file(self.replaced).files['message/CharaRR.bmg'])

    def override(self):
        ui, race = self.pack._patch_name_archives()
        contents = U8Archive.from_file(ui).files['message/CharaName.bmg']
        self.assertEqual(contents, U8Archive.from_file(race).files['message/CharaName.bmg'])
        return CharacterBMG.read(contents)

    def test_direct_import_autodetects_tpl_css_and_png_minimap(self):
        icons = self.mod / 'Icons'
        icons.mkdir()
        (icons/'picture.tpl').write_bytes(image_to_tpl(Image.new('RGBA', (64,64), 'red'), 64))
        Image.new('RGBA', (32,32), 'blue').save(icons/'untitled.png')
        plan = self.pack.import_skin(self.mod, 'lg', 99, insert=False, name='Test', author='Maker')
        self.assertIn(self.character / 'Portrait/lg-99-css.tpl', plan.writes)
        self.assertIn(self.character / 'Map/lg-99.tpl', plan.writes)
        self.assertIn(self.replaced, plan.writes)
        self.assertNotIn(self.patches / 'CharacterNames.uiassets.szs', plan.writes)
        before = self.replaced.read_bytes()
        self.pack.commit(plan)
        self.assertNotEqual(before, self.replaced.read_bytes())
        self.assertEqual(read_tpl((self.character/'Portrait/lg-99-css.tpl').read_bytes()).size,(64,64))
        self.assertEqual(read_tpl((self.character/'Map/lg-99.tpl').read_bytes()).size,(32,32))
        self.assertEqual(self.names().get_text(name_id(CODE_IDS['lg'],99)), 'Test')
        self.assertEqual(self.names().get_text(author_id(CODE_IDS['lg'],99)), 'Maker')
        self.assertFalse((self.patches / 'Test').exists())

    def test_direct_import_with_existing_name_patch_updates_both(self):
        user_mod = self.root / 'patchmod'
        user_mod.mkdir()
        (user_mod/'wr.brres').write_bytes(b'bres' + b'\0'*40)
        self.pack.commit(self.pack.import_patch_skin(user_mod, 'wr', 90, name='User', author='Player'))
        plan = self.pack.import_skin(self.mod, 'lg', 99, insert=False, name='Developer', author='Builder')
        self.assertIn(self.replaced, plan.writes)
        self.assertIn(self.patches/'CharacterNames/CharacterNames.uiassets.szs', plan.writes)
        self.assertIn(self.patches/'CharacterNames/CharacterNames.raceassets.szs', plan.writes)
        self.pack.commit(plan)
        self.assertEqual(self.names().get_text(name_id(CODE_IDS['lg'],99)), 'Developer')
        self.assertEqual(self.override().get_text(name_id(CODE_IDS['lg'],99)), 'Developer')
        self.assertEqual(self.override().get_text(name_id(CODE_IDS['wr'],90)), 'User')
        self.assertEqual(self.names().get_text(name_id(CODE_IDS['wr'],90)), '')

    def test_developer_edits_distribution_name_and_existing_override(self):
        (self.character/'Driver/lg-4.brres').write_bytes(b'bres' + b'\0'*32)
        self.pack.reload()
        user_mod = self.root / 'patchmod'
        user_mod.mkdir()
        (user_mod/'wr.brres').write_bytes(b'bres' + b'\0'*40)
        self.pack.commit(self.pack.import_patch_skin(user_mod, 'wr', 90, name='User', author='Player'))
        plan = self.pack.edit_text('lg', 4, 'New Sonic', 'Developer')
        self.assertIn(self.replaced, plan.writes)
        self.assertIn(self.patches/'CharacterNames/CharacterNames.uiassets.szs', plan.writes)
        self.pack.commit(plan)
        self.assertEqual(self.names().get_text(name_id(CODE_IDS['lg'],4)), 'New Sonic')
        self.assertEqual(self.override().get_text(name_id(CODE_IDS['lg'],4)), 'New Sonic')
        self.assertEqual(self.override().get_text(name_id(CODE_IDS['wr'],90)), 'User')

    def test_developer_insertion_renumbers_files_and_bmg_with_active_unrelated_patch(self):
        original = self.character / 'Driver/lg-4.brres'
        original.write_bytes(b'bres' + b'old skin')
        self.pack.reload()
        user_mod = self.root / 'patchmod'
        user_mod.mkdir()
        (user_mod/'wr.brres').write_bytes(b'bres' + b'\0'*40)
        self.pack.commit(self.pack.import_patch_skin(user_mod, 'wr', 90, name='User', author='Player'))
        old_name = self.names().get_text(name_id(CODE_IDS['lg'],4))
        plan = self.pack.import_skin(self.mod, 'lg', 4, insert=True, name='New at Four', author='Dev')
        self.assertIn((original, self.character / 'Driver/lg-5.brres'), plan.moves)
        self.pack.commit(plan)
        self.assertEqual((self.character/'Driver/lg-5.brres').read_bytes(), b'bres' + b'old skin')
        self.assertEqual(self.names().get_text(name_id(CODE_IDS['lg'],4)), 'New at Four')
        self.assertEqual(self.names().get_text(name_id(CODE_IDS['lg'],5)), old_name)
        self.assertEqual(self.override().get_text(name_id(CODE_IDS['lg'],5)), old_name)
        self.assertEqual(self.override().get_text(name_id(CODE_IDS['wr'],90)), 'User')

    def test_developer_move_keeps_unrelated_patch_names_and_distribution_in_sync(self):
        (self.character/'Driver/lg-5.brres').write_bytes(b'bres' + b'last')
        self.pack.reload()
        user_mod = self.root / 'patchmod'
        user_mod.mkdir()
        (user_mod/'wr.brres').write_bytes(b'bres' + b'\0'*40)
        self.pack.commit(self.pack.import_patch_skin(user_mod, 'wr', 90, name='User', author='Player'))
        old_name = self.names().get_text(name_id(CODE_IDS['lg'],5))
        plan = self.pack.move_slot('lg', 5, 99)
        self.assertIn(self.replaced, plan.writes)
        self.assertTrue(all(p in plan.writes for p in self.pack._patch_name_archives()))
        self.pack.commit(plan)
        self.assertTrue((self.character/'Driver/lg-99.brres').is_file())
        self.assertFalse((self.character/'Driver/lg-5.brres').exists())
        self.assertEqual(self.names().get_text(name_id(CODE_IDS['lg'],99)), old_name)
        self.assertEqual(self.override().get_text(name_id(CODE_IDS['lg'],99)), old_name)
        self.assertEqual(self.override().get_text(name_id(CODE_IDS['wr'],90)), 'User')

    def test_developer_reorder_is_blocked_when_override_slot_would_shift(self):
        (self.character/'Driver/lg-4.brres').write_bytes(b'bres' + b'old')
        self.pack.reload()
        patchmod = self.root/'patchmod'
        patchmod.mkdir()
        (patchmod/'lg.brres').write_bytes(b'bres' + b'user')
        self.pack.commit(self.pack.import_patch_skin(patchmod, 'lg', 7, name='Patch', author='Player'))
        with self.assertRaisesRegex(ValueError, 'Patches-installed skin'):
            self.pack.move_slot('lg',4,8)


if __name__=='__main__':
    unittest.main()
