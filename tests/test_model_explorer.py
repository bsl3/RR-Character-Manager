from fixture_paths import fixture_path, require_fixture
"""Model discovery regression tests using the user's two real mod archives."""
from pathlib import Path
import tempfile
import unittest
import zipfile
from wcm.models import discover_models, extract_model_bytes, source_entries, automatic_driver_candidate
from wcm.szs import U8Archive
from wcm.operations import CharacterPack

SAMUS = fixture_path('samus_v10_hotfix.zip')
BIKER = fixture_path('bikerwario-porko_v1(1).zip')
ASSETS = fixture_path('RRAssets.zip')

@unittest.skipUnless(SAMUS.is_file() and BIKER.is_file(), 'Real mod assets unavailable')
class ModelDiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samus_entries = source_entries(SAMUS)
        cls.samus_models = discover_models(cls.samus_entries)

    def test_samus_sources_are_extractable_with_transparent_u8_dot_folder(self):
        model = next(c for c in self.samus_models if
                     c.source_path.endswith('/la_bike-rs.szs') and c.archive_member == 'driver_model.brres')
        self.assertEqual(model.category, 'Race driver · Bike')
        data = extract_model_bytes(self.samus_entries, model)
        self.assertTrue(data.startswith(b'bres'))
        self.assertGreater(len(data), 100000)
        with zipfile.ZipFile(SAMUS) as z:
            archive = U8Archive.read(z.read(model.source_path))
        self.assertEqual(archive.files['driver_model.brres'], data)
        self.assertEqual(len(archive.files), 3)

    def test_kart_and_bike_drivers_differ_and_are_not_merged(self):
        bike = next(c for c in self.samus_models if c.source_path.endswith('/la_bike-rs.szs')
                    and c.archive_member == 'driver_model.brres')
        kart = next(c for c in self.samus_models if c.source_path.endswith('/la_kart-rs.szs')
                    and c.archive_member == 'driver_model.brres')
        self.assertNotEqual(extract_model_bytes(self.samus_entries, bike),
                            extract_model_bytes(self.samus_entries, kart))
        self.assertTrue(any(c.source_path.endswith('/rs_menu.brres') for c in self.samus_models))
        self.assertFalse(any(c.source_path.endswith('/Common.szs') for c in self.samus_models))

    def test_biker_wario_has_standalone_driver(self):
        candidates = discover_models(source_entries(BIKER), source_variant='bikerwario-porko_v1/Full Slot')
        self.assertTrue(any(c.source_path.endswith('Driver/wr.brres') for c in candidates))

@unittest.skipUnless(ASSETS.is_file() and SAMUS.is_file(), 'RR sample unavailable')
class SamusImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root/'Character/Driver').mkdir(parents=True)
        (root/'Character/Driver/rs-1.brres').write_bytes(b'bres'+bytes(40))
        (root/'Assets').mkdir()
        with zipfile.ZipFile(ASSETS) as z:
            (root/'Assets/ReplacedAssets.szs').write_bytes(z.read('Assets/ReplacedAssets.szs'))
        self.pack = CharacterPack(root/'Character', root/'Assets/ReplacedAssets.szs', root/'Patches')

    def test_samus_embedded_driver_is_selected_without_losing_vehicle_drivers(self):
        plan=self.pack.import_patch_skin(SAMUS,'rs',9,name='Samus',author='Tester')
        entries=source_entries(SAMUS);models=discover_models(entries)
        selected=automatic_driver_candidate(entries)
        self.assertEqual(selected.archive_member,'')
        self.assertTrue(selected.source_path.endswith('rs_menu.brres'))
        root=self.pack.patches_path/'Samus'
        self.assertEqual(plan.writes[root/'rs-9.brres'],extract_model_bytes(entries,selected))
        for rel,data in entries:
            from wcm.library import parse_asset
            asset=parse_asset(rel,source_import=True)
            if asset and asset.category in ('RaceKart','AllKart','Sound'):
                self.assertEqual(plan.writes[root/asset.filename_for(9)],data)
        self.assertTrue(any('8 kart and 8 bike' in text for text in plan.metadata))
        bundle=plan.writes[root/'rs-9-source.rrcm-source']
        import io
        with zipfile.ZipFile(io.BytesIO(bundle)) as z:
            for rel,data in entries:
                if rel.endswith(('Common.szs','GRP_VO_RS.brbnk','.wav','rs_menu.brres')):
                    self.assertEqual(z.read(rel),data)
        self.assertTrue(any('not activated' in w for w in plan.warnings))

    def test_automatic_selection_works_without_menu_and_never_chooses_vehicle_or_animation(self):
        entries=[e for e in source_entries(SAMUS) if not e[0].endswith('_menu.brres')]
        selected=automatic_driver_candidate(entries)
        self.assertEqual(selected.archive_member,'driver_model.brres')
        self.assertIn('_kart',selected.source_path)
        bike=automatic_driver_candidate([e for e in entries if '_bike' in e[0]])
        self.assertIn('_bike',bike.source_path)
        # A header-only invalid standalone must not suppress valid embedded fallback.
        self.assertEqual(automatic_driver_candidate(entries+[('Driver/rs.brres',b'bres')]).archive_member,'driver_model.brres')

    def test_explicit_race_extraction_keeps_menu_source_and_both_suits(self):
        entries=source_entries(SAMUS);models=discover_models(entries)
        for suffix in ('la_kart-rs.szs','la_bike-rs.szs'):
            choice=next(c for c in models if c.source_path.endswith(suffix) and c.archive_member=='driver_model.brres')
            plan=self.pack.import_patch_skin(SAMUS,'rs',9,name='Samus',author='Tester',driver_candidate=choice)
            root=self.pack.patches_path/'Samus'
            self.assertEqual(plan.writes[root/'rs-9.brres'],extract_model_bytes(entries,choice))
            for rel,data in entries:
                if rel.endswith(('la_kart-rs.szs','la_bike-rs.szs')):
                    from wcm.library import parse_asset
                    self.assertEqual(plan.writes[root/parse_asset(rel,source_import=True).filename_for(9)],data)
            import io
            with zipfile.ZipFile(io.BytesIO(plan.writes[root/'rs-9-source.rrcm-source'])) as z:
                menu=next((rel,data) for rel,data in entries if rel.endswith('rs_menu.brres'))
                self.assertEqual(z.read(menu[0]),menu[1])

    def test_standard_commit_reopen_keeps_source_bundle_inactive(self):
        original_driver=(self.pack.character/'Driver/rs-1.brres').read_bytes()
        original_archive=self.pack.archive_path.read_bytes()
        plan=self.pack.import_patch_skin(SAMUS,'rs',9,name='Samus',author='Tester')
        self.pack.commit(plan)
        reopened=CharacterPack(self.pack.character,self.pack.archive_path,self.pack.patches_path)
        bundle=reopened.patches_path/'Samus/rs-9-source.rrcm-source'
        self.assertTrue(bundle.is_file())
        self.assertFalse(any(p==bundle for p in reopened.patch_assets.values()))
        self.assertEqual((reopened.character/'Driver/rs-1.brres').read_bytes(),original_driver)
        self.assertEqual(reopened.archive_path.read_bytes(),original_archive)

    def test_samus_import_with_explicit_menu_model_preserves_both_suits_and_voice(self):
        models = discover_models(source_entries(SAMUS))
        choice = next(c for c in models if c.source_path.endswith('rs_menu.brres'))
        plan = self.pack.import_patch_skin(SAMUS, 'rs', 9, name='Samus', author='Tester',
                                           driver_candidate=choice)
        root = self.pack.patches_path/'Samus'
        self.assertEqual(plan.writes[root/'rs-9.brres'], extract_model_bytes(source_entries(SAMUS), choice))
        self.assertTrue((root/'la_bike-rs-9.szs') in plan.writes)
        self.assertTrue((root/'la_kart-rs-9.szs') in plan.writes)
        self.assertTrue(any(path.name.endswith('.brwsd') for path in plan.writes))
        self.assertTrue((root/'rs-9.tpl') in plan.writes)
        self.assertTrue((root/'rs-9-css.tpl') in plan.writes)
        self.assertTrue(any('bind pose' in w for w in plan.warnings))

    def test_non_driver_brres_rejected(self):
        models = discover_models(source_entries(SAMUS))
        choice = next(c for c in models if c.archive_member == 'kart_model.brres')
        with self.assertRaisesRegex(ValueError, 'Choose a menu or driver BRRES'):
            self.pack.import_patch_skin(SAMUS, 'rs', 9, name='Samus', author='Tester',
                                       driver_candidate=choice)


if __name__ == '__main__':
    unittest.main()
