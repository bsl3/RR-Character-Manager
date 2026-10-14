from native_fixtures import valid_brres,valid_szs
from fixture_paths import fixture_path, require_fixture
"""Non-destructive, source-backed Patches installation checks."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from wcm.operations import CharacterPack
from wcm.bmg import CharacterBMG, name_id, author_id
from wcm.szs import U8Archive
from wcm.library import CODE_IDS

ASSETS = fixture_path('RRAssets.zip')


def rr_replaced():
    with zipfile.ZipFile(ASSETS) as z:
        return z.read('Assets/ReplacedAssets.szs')


def name_patch(pack):
    ui, race = pack._patch_name_archives()
    data = U8Archive.from_file(ui).files['message/CharaName.bmg']
    assert U8Archive.from_file(race).files['message/CharaName.bmg'] == data
    return CharacterBMG.read(data)


class TestPatches(unittest.TestCase):
    def setUp(self):
        if not ASSETS.is_file():
            self.skipTest('RRAssets.zip fixture unavailable')
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.characters = self.root / 'Character'
        (self.characters / 'Driver').mkdir(parents=True)
        (self.characters / 'Driver/lg-1.brres').write_bytes(b'base_model')
        self.archive = self.root / 'Assets/ReplacedAssets.szs'
        self.archive.parent.mkdir()
        self.archive.write_bytes(rr_replaced())
        self.orig_bmg = self.archive.read_bytes()
        self.patches = self.root / 'Patches'
        self.pack = CharacterPack(self.characters, self.archive, self.patches)
        self.skin = self.root / 'new_skin'
        self.skin.mkdir()
        (self.skin / 'lg.brres').write_bytes(valid_brres(b'bres' + bytes(32)))
        (self.skin / 'ma_kart-lg.szs').write_bytes(valid_szs(b'Yaz0' + bytes(20)))
        (self.skin / 'GRP_VO_LG_CAN_PC.brwsd').write_bytes(b'RWSD' + bytes(12))

    def tearDown(self):
        self.tmp.cleanup()

    def install(self, slot, name, author):
        plan = self.pack.import_patch_skin(self.skin, 'lg', slot, name=name, author=author)
        return self.pack.commit(plan)

    def test_organized_character_folder_and_bmg_member_patch(self):
        plan = self.pack.import_patch_skin(self.skin, 'lg', 8, name='New Luigi', author='Artist')
        self.assertEqual(len(plan.moves), 0)
        self.assertTrue(all(p.parent in (self.patches, self.patches / "New Luigi", self.patches / "CharacterNames") for p in plan.writes))
        self.assertIn('Patches', plan.description)
        backup = self.pack.commit(plan)
        self.assertTrue(backup.joinpath('manifest.json').is_file())
        self.assertTrue((self.patches / 'New Luigi' / 'lg-8.brres').is_file())
        self.assertTrue((self.patches / 'New Luigi' / 'ma_kart-lg-8.szs').is_file())
        self.assertTrue((self.patches / 'New Luigi' / 'GRP_VO_LG-8_CAN_PC.brwsd').is_file())
        bmg = name_patch(self.pack)
        self.assertEqual(bmg.get_text(name_id(CODE_IDS['lg'],8)), 'New Luigi')
        self.assertEqual(bmg.get_text(author_id(CODE_IDS['lg'],8)), 'Artist')
        self.assertEqual(self.archive.read_bytes(), self.orig_bmg)
        self.assertEqual((self.characters / 'Driver/lg-1.brres').read_bytes(), b'base_model')
        self.assertTrue(self.pack.is_patch_skin('lg', 8))
        self.assertEqual(self.pack.inventory.skins[('lg', 8)].name, 'New Luigi')

    def test_repeated_imports_preserve_previous_patch_entries(self):
        self.install(8, 'First', 'A')
        self.install(9, 'Second', 'B')
        bmg = name_patch(self.pack)
        self.assertEqual(bmg.get_text(name_id(CODE_IDS['lg'], 8)), 'First')
        self.assertEqual(bmg.get_text(author_id(CODE_IDS['lg'], 9)), 'B')
        self.assertEqual(self.archive.read_bytes(), self.orig_bmg)

    def test_collision_and_no_shift(self):
        self.install(8, 'First', 'A')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.pack.import_patch_skin(self.skin,'lg',8,name='Other',author='B')
        with self.assertRaisesRegex(PermissionError, 'Developer Mode'):
            self.pack.move_slot('lg',8,9)
        self.assertFalse((self.patches/'lg-9.brres').exists())

    def test_patch_skin_metadata_edits_only_patch_bmg(self):
        self.install(8, 'First', 'A')
        plan=self.pack.edit_text('lg',8,'Renamed','New Author')
        self.assertNotIn(self.archive,plan.writes)
        self.assertTrue(all(p in plan.writes for p in self.pack._patch_name_archives()))
        self.assertTrue(all(p in plan.replace_existing for p in self.pack._patch_name_archives()))
        self.pack.commit(plan)
        self.assertEqual(self.pack.inventory.skins[('lg',8)].author, 'New Author')
        self.assertEqual(self.archive.read_bytes(),self.orig_bmg)

    def test_existing_unrelated_patches_preserved(self):
        self.patches.mkdir()
        (self.patches / '001.MyMenu.menusingle.szs').write_bytes(b'mock-menu')
        self.install(8, 'First', 'A')
        self.assertEqual((self.patches / '001.MyMenu.menusingle.szs').read_bytes(), b'mock-menu')
        self.assertGreater(len(self.pack.inventory.skins),0)

    def test_real_rr_sonic_skin_into_loose_patches(self):
        real_zip = fixture_path('Character.zip')
        if not real_zip.is_file():
            self.skipTest('Character.zip fixture unavailable')
        source_zip = self.root / 'sonic.zip'
        with zipfile.ZipFile(real_zip) as source, zipfile.ZipFile(source_zip, 'w') as target:
            names = [n for n in source.namelist() if n.startswith('Character/') and
                     ('-lg-4' in n or '/lg-4' in n or 'GRP_VO_LG-4' in n)]
            self.assertEqual(len(names), 31)
            for n in names:
                target.writestr(n, source.read(n))
        plan = self.pack.import_patch_skin(source_zip, 'lg', 8, name='Sonic', author='Test')
        self.assertEqual(len(plan.writes), 34)  # 31 character files + 2 name archives + manifest
        self.pack.commit(plan)
        sonic = self.pack.inventory.skins[('lg', 8)]
        self.assertEqual(sonic.counts['RaceKart'], 12)
        self.assertEqual(sonic.counts['Sound'], 15)
        self.assertEqual(sonic.counts['Portrait'], 1)
        self.assertEqual(sonic.counts['Map'], 1)
        self.assertTrue((self.patches / 'Sonic' / 'lg-8-css.tpl').is_file())
        self.assertTrue((self.patches / 'Sonic' / 'lg-8.brres').is_file())
        self.assertEqual(self.archive.read_bytes(), self.orig_bmg)

    def test_developer_direct_import_keeps_active_name_patches_in_sync(self):
        self.install(8, 'First', 'A')
        with self.assertRaisesRegex(PermissionError, 'Developer Mode'):
            self.pack.import_skin(self.skin, 'lg', 9, insert=False, name='Second', author='B')
        developer = CharacterPack(self.characters, self.archive, self.patches, developer_mode=True)
        plan = developer.import_skin(self.skin, 'lg', 9, insert=False, name='Second', author='B')
        self.assertIn(self.archive, plan.writes)
        self.assertTrue(all(p in plan.writes for p in developer._patch_name_archives()))
        developer.commit(plan)
        self.assertEqual(CharacterBMG.read(U8Archive.from_file(self.archive).files['message/CharaRR.bmg']).get_text(
            name_id(CODE_IDS['lg'], 9)), 'Second')
        for path in developer._patch_name_archives():
            override = CharacterBMG.read(U8Archive.from_file(path).files['message/CharaName.bmg'])
            self.assertEqual(override.get_text(name_id(CODE_IDS['lg'], 9)), 'Second')
            self.assertEqual(override.get_text(name_id(CODE_IDS['lg'], 8)), 'First')

    def test_developer_cannot_move_distribution_through_installed_patch_slot(self):
        self.install(8, 'First', 'A')
        developer = CharacterPack(self.characters, self.archive, self.patches, developer_mode=True)
        with self.assertRaisesRegex(ValueError, 'Patches-installed skin'):
            developer.move_slot('lg', 1, 9)

    def test_custom_patches_directory(self):
        custom=self.root/'mods'/'overrides'
        pack=CharacterPack(self.characters,self.archive,custom)
        self.assertEqual(pack.patches_path,custom)
        with self.assertRaisesRegex(ValueError, 'separate folder'):
            CharacterPack(self.characters,self.archive,self.characters/'Sound')


if __name__ == '__main__': unittest.main()
