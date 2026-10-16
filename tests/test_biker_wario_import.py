from fixture_paths import fixture_path, require_fixture
"""Regression tests for nested mod variants and complete vanilla MKWii skin ZIPs."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from wcm.library import available_import_variants, parse_asset
from wcm.operations import CharacterPack
from wcm.bmg import CharacterBMG, name_id, author_id
from wcm.library import CODE_IDS
from wcm.tpl import read_tpl
from wcm.szs import U8Archive

RR_ASSETS = fixture_path('RRAssets.zip')
BIKER = fixture_path('bikerwario-porko_v1.zip')
FULL = 'bikerwario-porko_v1/Full Slot'


class TestBikerWarioImport(unittest.TestCase):
    def setUp(self):
        if not RR_ASSETS.is_file() or not BIKER.is_file():
            self.skipTest('Uploaded sample ZIPs are required')
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / 'Character/Driver').mkdir(parents=True)
        (self.root / 'Character/Driver/wr-1.brres').write_bytes(b'bres' + bytes(20))
        (self.root / 'Assets').mkdir()
        with zipfile.ZipFile(RR_ASSETS) as z:
            (self.root / 'Assets/ReplacedAssets.szs').write_bytes(z.read('Assets/ReplacedAssets.szs'))
        self.pack = CharacterPack(self.root / 'Character', self.root / 'Assets/ReplacedAssets.szs',
                                  self.root / 'Patches')
        self.original_archive = self.pack.archive_path.read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def test_zip_requires_variant_instead_of_false_duplicate(self):
        with zipfile.ZipFile(BIKER) as z:
            variants = available_import_variants(z.namelist())
        self.assertEqual(variants, ['bikerwario-porko_v1/Bike Only', FULL])
        with self.assertRaisesRegex(ValueError, 'alternative installation variants'):
            self.pack.import_patch_skin(BIKER, 'wr', 7, name='Biker Wario', author='Porko')

    def test_full_slot_zip_installs_rr_assets_without_split_screen_variants(self):
        plan = self.pack.import_patch_skin(BIKER, 'wr', 7, name='Biker Wario', author='Porko',
                                           source_variant=FULL)
        names = {p.name for p in plan.writes}
        for name in ('wr-7-allkart.szs', 'wr-7-allkart_BT.szs', 'wr-7.brres',
                     'wr-7-css.tpl', 'wr-7.tpl'):
            self.assertIn(name, names)
        self.assertNotIn('ldf_bike-wr-7_4.szs', names)
        self.assertNotIn('ldf_kart-wr-7_4.szs', names)
        self.assertEqual(read_tpl(plan.writes[self.pack.patches_path / 'Biker Wario' / 'wr-7-css.tpl']).size, (64, 64))
        self.assertEqual(read_tpl(plan.writes[self.pack.patches_path / 'Biker Wario' / 'wr-7.tpl']).size, (32, 32))
        self.assertEqual(sum(p.suffix == '.brres' for p in plan.writes), 1)
        self.assertTrue(any('not activated' in w for w in plan.warnings))  # Award duplicate preserved as source only
        self.assertIn('wr-7-source.rrcm-source', names)
        self.pack.commit(plan)
        self.assertEqual(self.pack.archive_path.read_bytes(), self.original_archive)
        self.assertEqual(self.pack.inventory.skins[('wr', 7)].counts['RaceKart'], 32)
        bmg = CharacterBMG.read(U8Archive.from_file(self.pack._patch_name_archives()[0]).files['message/CharaName.bmg'])
        self.assertEqual(bmg.get_text(name_id(CODE_IDS['wr'], 7)), 'Biker Wario')
        self.assertEqual(bmg.get_text(author_id(CODE_IDS['wr'], 7)), 'Porko')

    def test_extracted_full_slot_folder_imports_without_variant(self):
        folder = self.root / 'Full Slot'
        with zipfile.ZipFile(BIKER) as z:
            for entry in z.infolist():
                if entry.is_dir() or not entry.filename.startswith(FULL + '/'):
                    continue
                dst = folder / entry.filename[len(FULL) + 1:]
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(entry))
        plan = self.pack.import_patch_skin(folder, 'wr', 7, name='Biker Wario', author='Porko')
        self.assertEqual(len(plan.writes), 41)
        self.assertIn(self.pack.patches_path / 'Biker Wario' / 'wr-7-css.tpl', plan.writes)

    def test_award_model_not_mistaken_for_second_driver(self):
        self.assertIsNone(parse_asset('Full Slot/Award/wr.brres', source_import=True))
        self.assertEqual(parse_asset('Full Slot/Driver/wr.brres', source_import=True).category, 'Driver')
        self.assertEqual(parse_asset('Full Slot/Race/la_bike-wr_4.szs', source_import=True).category, 'RaceKart')

    def test_bike_only_still_supported(self):
        plan = self.pack.import_patch_skin(BIKER, 'wr', 7, name='Biker Wario', author='Porko',
                                           source_variant='bikerwario-porko_v1/Bike Only')
        self.assertIn(self.pack.patches_path / 'Biker Wario' / 'wr-7-allkart_BT.szs', plan.writes)
        self.assertEqual(sum(p.suffix == '.szs' for p in plan.writes), 20)
        self.assertFalse(any(p.suffix == '.tpl' for p in plan.writes))


if __name__ == '__main__':
    unittest.main()
