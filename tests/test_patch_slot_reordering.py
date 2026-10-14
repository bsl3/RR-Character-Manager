from native_fixtures import valid_brres,valid_szs
from fixture_paths import fixture_path, require_fixture
"""Patches-only slot swaps / bumps are staged and backed up as one atomic edit."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from wcm.operations import CharacterPack
from wcm.bmg import CharacterBMG, name_id, author_id
from wcm.library import CODE_IDS
from wcm.szs import U8Archive

ASSETS = fixture_path('RRAssets.zip')

@unittest.skipUnless(ASSETS.is_file(), 'RR sample unavailable')
class PatchSlotReordering(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.character = self.root / 'Character'
        (self.character / 'Driver').mkdir(parents=True)
        (self.character / 'Driver/lg-1.brres').write_bytes(b'official')
        self.archive = self.root / 'Assets/ReplacedAssets.szs'
        self.archive.parent.mkdir()
        with zipfile.ZipFile(ASSETS) as zip_file:
            self.archive.write_bytes(zip_file.read('Assets/ReplacedAssets.szs'))
        self.unchanged_archive = self.archive.read_bytes()
        self.patches = self.root / 'Patches'
        self.pack = CharacterPack(self.character, self.archive, self.patches)

    def install(self, code, slot, name):
        src = self.root / f'source-{code}-{slot}'
        src.mkdir()
        (src / f'{code}.brres').write_bytes(valid_brres(b'bres' + bytes([slot]) * 32))
        (src / f'ma_kart-{code}.szs').write_bytes(valid_szs(b'Yaz0' + bytes([slot]) * 32))
        self.pack.commit(self.pack.import_patch_skin(src, code, slot, name=name, author='Creator'))

    def current_bmg(self):
        ui, race = self.pack._patch_name_archives()
        raw = U8Archive.from_file(ui).files['message/CharaName.bmg']
        self.assertEqual(raw, U8Archive.from_file(race).files['message/CharaName.bmg'])
        return CharacterBMG.read(raw)

    def test_single_move_rewrites_files_metadata_and_names(self):
        self.install('lg', 8, 'Test Luigi')
        initial = (self.patches / 'Test Luigi/lg-8.brres').read_bytes()
        plan = self.pack.reassign_patch_slots({'lg': {8: 9}})
        self.assertTrue((self.patches / 'Test Luigi/lg-8.brres').exists(), 'staging changed disk')
        backup = self.pack.commit(plan)
        self.assertTrue((backup / 'manifest.json').is_file())
        self.assertFalse((self.patches / 'Test Luigi/lg-8.brres').exists())
        self.assertEqual((self.patches / 'Test Luigi/lg-9.brres').read_bytes(), initial)
        self.assertTrue((self.patches / 'Test Luigi/ma_kart-lg-9.szs').is_file())
        self.assertEqual(json.loads((self.patches / 'Test Luigi/_rr_character.json').read_text(encoding='utf-8'))['slot'], 9)
        bmg = self.current_bmg()
        self.assertEqual(bmg.get_text(name_id(CODE_IDS['lg'],9)), 'Test Luigi')
        self.assertEqual(bmg.get_text(author_id(CODE_IDS['lg'],9)), 'Creator')
        self.assertEqual(self.archive.read_bytes(), self.unchanged_archive)
        self.assertIn(('lg',9), self.pack.inventory.skins)
        self.assertNotIn(('lg',8), self.pack.inventory.skins)

    def test_swap_updates_two_names_in_same_base_character(self):
        self.install('lg', 8, 'First Luigi')
        self.install('lg', 9, 'Second Luigi')
        original = (self.patches / 'First Luigi/lg-8.brres').read_bytes()
        self.pack.commit(self.pack.reassign_patch_slots({'lg': {8: 9, 9: 8}}))
        self.assertEqual((self.patches / 'First Luigi/lg-9.brres').read_bytes(), original)
        bmg = self.current_bmg()
        self.assertEqual(bmg.get_text(name_id(CODE_IDS['lg'],9)), 'First Luigi')
        self.assertEqual(bmg.get_text(name_id(CODE_IDS['lg'],8)), 'Second Luigi')
        self.assertEqual(self.archive.read_bytes(), self.unchanged_archive)
        self.assertEqual(self.pack.inventory.skins['lg', 9].name, 'First Luigi')
        self.assertEqual(self.pack.inventory.skins['lg', 8].name, 'Second Luigi')

    def test_bulk_bump_is_cross_character_and_keeps_folders(self):
        self.install('lg', 8, 'Test Luigi')
        self.install('wr', 7, 'Biker Wario')
        self.pack.commit(self.pack.reassign_patch_slots({'lg': {8: 10}, 'wr': {7: 9}}))
        self.assertIn(('lg',10),self.pack.inventory.skins)
        self.assertIn(('wr',9),self.pack.inventory.skins)
        self.assertTrue((self.patches / 'Biker Wario/wr-9.brres').exists())
        self.assertEqual(self.current_bmg().get_text(name_id(CODE_IDS['wr'],9)), 'Biker Wario')

    def test_detects_new_official_slot_and_rejects_collision(self):
        self.install('lg', 8, 'Test Luigi')
        (self.character / 'Driver/lg-8.brres').write_bytes(b'new official skin')
        self.pack.reload()
        self.assertEqual(self.pack.patch_overlaps()['lg'], {8})
        self.assertFalse(self.pack.reassign_patch_slots({'lg': {8: 8}}).moves)  # no-op
        # A move away frees the overlapping slot without touching RR.
        self.pack.commit(self.pack.reassign_patch_slots({'lg': {8: 9}}))
        self.assertFalse(self.pack.patch_overlaps())
        self.assertEqual((self.character / 'Driver/lg-8.brres').read_bytes(), b'new official skin')

    def test_rejects_distribution_target_without_modifying_anything(self):
        self.install('lg', 8, 'Test Luigi')
        with self.assertRaisesRegex(ValueError, 'overlap official'):
            self.pack.reassign_patch_slots({'lg': {8: 1}})
        self.assertTrue((self.patches / 'Test Luigi/lg-8.brres').is_file())
        self.assertEqual(self.archive.read_bytes(),self.unchanged_archive)

    def test_rejects_occupied_patch_target(self):
        self.install('lg', 8, 'Test Luigi')
        self.install('lg', 9, 'Second Luigi')
        with self.assertRaisesRegex(ValueError, 'overlap other Patches'):
            self.pack.reassign_patch_slots({'lg': {8: 9}})

    def test_custom_named_resource_remains_indexed_to_new_slot(self):
        self.install('lg', 8, 'Test Luigi')
        self.pack.commit(self.pack.rename_resources('lg', 8, {'Driver/lg-8.brres': 'odd-name.test'}))
        self.pack.commit(self.pack.reassign_patch_slots({'lg': {8: 9}}))
        self.assertEqual(self.pack.asset_path('Driver/lg-9.brres').name,'odd-name.test')
        self.assertEqual(self.pack.inventory.skins['lg',9].counts['Driver'],1)
        self.assertTrue((self.patches / 'Test Luigi/odd-name.test').exists())

if __name__ == '__main__':
    unittest.main()

class PatchGUIContracts(unittest.TestCase):
    def test_patch_controls_stage_changes_and_show_collisions(self):
        gui = (Path(__file__).parents[1] / 'wcm/gui.py').read_text(encoding='utf-8')
        self.assertIn('class PatchSlotTable(QTableWidget):', gui)
        self.assertIn('self.table.slotDropped.connect(self.stage_patch_drop)', gui)
        self.assertIn('self.pending_patch_slots = {}', gui)
        self.assertIn('self.slot_save_button = button(', gui)
        self.assertIn('self.slot_save_button.setEnabled(False)', gui)
        self.assertIn('self.slot_revert_button = button(', gui)
        self.assertIn('self.bump_amount = QLineEdit(', gui)
        self.assertIn("QColor('#a33347')", gui)
        self.assertIn("QColor('#683c57')", gui)
        self.assertIn("QColor('#563249')", gui)
        self.assertIn('self.pack.reassign_patch_slots(mapping)', gui)
        self.assertIn('self.bump_patch_slots(1)', gui)

@unittest.skipUnless(fixture_path('CharacterNames.uiassets(1).szs').is_file(), 'User BMG not mounted')
class UploadedBikerWarioBMG(unittest.TestCase):
    def test_name_and_author_present_in_both_uploaded_archives(self):
        names = []
        for file in ('CharacterNames.uiassets(1).szs', 'CharacterNames.raceassets(1).szs'):
            bundle = U8Archive.from_file(fixture_path(file))
            bmg = CharacterBMG.read(bundle.files['message/CharaName.bmg'])
            self.assertEqual(bmg.get_text(name_id(CODE_IDS['wr'], 7)), 'Biker Wario')
            self.assertEqual(bmg.get_text(author_id(CODE_IDS['wr'], 7)), 'Proker')
            names.append(bundle.files['message/CharaName.bmg'])
        self.assertEqual(names[0], names[1])
