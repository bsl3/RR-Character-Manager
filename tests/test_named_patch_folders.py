from fixture_paths import fixture_path, require_fixture
"""Character folder grouping, BMG synchronization and safe renames."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image
from wcm.operations import CharacterPack
from wcm.bmg import CharacterBMG, author_id, name_id
from wcm.library import CODE_IDS
from wcm.szs import U8Archive

RR_ASSETS = fixture_path('RRAssets.zip')


class TestNamedPatchFolders(unittest.TestCase):
    def setUp(self):
        if not RR_ASSETS.is_file():
            self.skipTest('RR assets missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.characters = self.root / 'Character'
        (self.characters / 'Driver').mkdir(parents=True)
        (self.characters / 'Driver/wr-1.brres').write_bytes(b'bres' + b'0'*20)
        self.archive = self.root / 'Assets/ReplacedAssets.szs'
        self.archive.parent.mkdir()
        with zipfile.ZipFile(RR_ASSETS) as z:
            self.archive.write_bytes(z.read('Assets/ReplacedAssets.szs'))
        self.original = self.archive.read_bytes()
        self.patches = self.root / 'Patches'
        self.pack = CharacterPack(self.characters, self.archive, self.patches)
        self.mod = self.root / 'mod'
        self.mod.mkdir()
        (self.mod / 'wr.brres').write_bytes(b'bres' + b'1'*20)
        (self.mod / 'ma_kart-wr.szs').write_bytes(b'Yaz0' + b'2'*20)
        (self.mod / 'GRP_VO_WR_CAN_PC.brwsd').write_bytes(b'RWSD' + b'3'*16)

    def install(self, slot=7, name='Biker Wario', author='Porko'):
        plan = self.pack.import_patch_skin(self.mod, 'wr', slot, name=name, author=author)
        return self.pack.commit(plan)

    def test_named_folder_and_synced_bmg(self):
        self.install()
        folder = self.patches / 'Biker Wario'
        self.assertTrue((folder / 'wr-7.brres').exists())
        self.assertTrue((folder / 'ma_kart-wr-7.szs').exists())
        self.assertTrue((folder / 'GRP_VO_WR-7_CAN_PC.brwsd').exists())
        self.assertFalse((self.patches / 'wr-7.brres').exists())
        meta = json.loads((folder / '_rr_character.json').read_text(encoding='utf-8'))
        self.assertEqual((meta['name'], meta['author'], meta['slot']), ('Biker Wario', 'Porko', 7))
        text = CharacterBMG.read(U8Archive.from_file(self.pack._patch_name_archives()[0]).files['message/CharaName.bmg'])
        self.assertEqual(text.get_text(name_id(CODE_IDS['wr'], 7)), 'Biker Wario')
        self.assertEqual(text.get_text(author_id(CODE_IDS['wr'], 7)), 'Porko')
        self.assertEqual(self.archive.read_bytes(), self.original)
        self.assertTrue(self.pack.is_patch_skin('wr', 7))

    def test_rename_folder_and_message_transactionally(self):
        self.install()
        edit = self.pack.edit_text('wr', 7, 'Biker Wario (Porko)', 'Porko Jr.')
        self.assertIn(self.patches / 'Biker Wario' / '_rr_character.json', edit.deletes)
        self.assertTrue(edit.moves)
        self.pack.commit(edit)
        old, new = self.patches / 'Biker Wario', self.patches / 'Biker Wario (Porko)'
        self.assertFalse(old.exists())
        self.assertTrue((new / 'wr-7.brres').exists())
        self.assertTrue((new / 'ma_kart-wr-7.szs').exists())
        self.assertEqual(self.pack.patch_directories[('wr',7)], new)
        meta = json.loads((new / '_rr_character.json').read_text(encoding='utf-8'))
        self.assertEqual((meta['name'], meta['author']), ('Biker Wario (Porko)', 'Porko Jr.'))
        self.assertEqual(self.pack.inventory.skins[('wr',7)].name, 'Biker Wario (Porko)')
        self.assertEqual(self.pack.bmg.get_text(author_id(CODE_IDS['wr'],7)), 'Porko Jr.')
        self.assertEqual(self.archive.read_bytes(), self.original)

    def test_png_updates_into_named_folder(self):
        self.install()
        icon = self.root / 'icon.png'
        Image.new('RGBA', (32,32), 'green').save(icon)
        plan = self.pack.replace_map('wr',7,icon)
        self.assertEqual(list(plan.writes)[0].parent, self.patches / 'Biker Wario')
        self.pack.commit(plan)
        self.assertTrue((self.patches / 'Biker Wario' / 'wr-7.tpl').exists())

    def test_recover_metadata_after_flat_bmg_removed(self):
        self.install()
        for archive in self.pack._patch_name_archives():
            archive.unlink()
        self.pack.reload()
        self.assertEqual(self.pack.inventory.skins[('wr',7)].name, 'Biker Wario')
        self.assertEqual(self.pack.inventory.skins[('wr',7)].author, 'Porko')
        self.pack.commit(self.pack.edit_text('wr',7,'Biker Wario','Porko'))
        self.assertTrue(all(p.exists() for p in self.pack._patch_name_archives()))

    def test_duplicate_names_get_distinct_folders(self):
        self.install()
        self.install(8)
        self.assertTrue((self.patches / 'Biker Wario (WR-8)' / 'wr-8.brres').exists())
        self.assertEqual(self.pack.inventory.skins[('wr',8)].name, 'Biker Wario')
        self.assertEqual(self.pack.patch_directories[('wr',8)].name, 'Biker Wario (WR-8)')

    def test_windows_folder_unsafe_characters(self):
        self.install(name='Biker: Wario?')
        self.assertTrue((self.patches / 'Biker_ Wario_' / 'wr-7.brres').exists())

    def test_legacy_flat_patches_still_scanned(self):
        self.patches.mkdir()
        (self.patches / 'wr-8.brres').write_bytes(b'bres')
        self.pack.reload()
        self.assertTrue(self.pack.is_patch_skin('wr',8))
        self.assertNotIn(('wr',8), self.pack.patch_directories)
        self.assertEqual(self.pack.asset_path('Driver/wr-8.brres'), self.patches / 'wr-8.brres')


if __name__ == '__main__':
    unittest.main()
