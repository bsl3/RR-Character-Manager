"""Regression tests for icon previews, batch imports and context menus."""
import unittest
from pathlib import Path
import tempfile
import test_mkchara as package_tests
from wcm.operations import CharacterPack
from wcm.library import parse_asset
from wcm.mkchara import read_package


class ResourceActions(unittest.TestCase):
    def setUp(self):
        self.fixture = package_tests.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.pack = self.fixture.pack

    def test_manual_backup_before_icon_delete_preserves_other_assets(self):
        asset = next(a for a in self.pack.inventory.skins['wr', 7].files if a.category == 'Portrait')
        original_path = self.pack.asset_path(asset.relpath)
        original = original_path.read_bytes()
        model = next(a for a in self.pack.inventory.skins['wr', 7].files if a.category == 'Driver')
        model_path = self.pack.asset_path(model.relpath)
        plan = self.pack.delete_resource('wr', 7, asset.relpath)
        self.assertIn(original_path, plan.deletes)
        from wcm.backups import snapshot
        backup = snapshot(self.pack.patches_path,self.pack.backup_root,'Manual backup')
        self.assertIsNone(self.pack.commit(plan))
        self.assertFalse(original_path.exists())
        self.assertTrue(model_path.exists())
        self.assertTrue((backup/'manifest.json').exists())
        self.assertNotIn('Portrait', [a.category for a in self.pack.inventory.skins['wr', 7].files])
        self.assertEqual((backup/'Patches'/original_path.relative_to(self.pack.patches_path)).read_bytes(),original)

    def test_original_asset_delete_protected_unless_developer(self):
        f = self.fixture
        source_pack = f.make_pack(f.root/'Inherited')
        driver = source_pack.character/'Driver'/'lg-1.brres'
        driver.write_bytes(b'distribution model')
        source_pack.reload()
        with self.assertRaises(PermissionError):
            source_pack.delete_resource('lg', 1, 'Driver/lg-1.brres')
        self.assertTrue(driver.is_file())
        developer = CharacterPack(source_pack.character, source_pack.archive_path,
                                  source_pack.patches_path, developer_mode=True)
        plan = developer.delete_resource('lg', 1, 'Driver/lg-1.brres')
        developer.commit(plan)
        self.assertFalse(driver.exists())

    def test_deleting_renamed_patch_clears_mapping(self):
        asset = next(a for a in self.pack.inventory.skins['wr', 7].files if a.category == 'Map')
        names = {asset.relpath: 'renamed-map.tpl'}
        self.pack.commit(self.pack.rename_resources('wr', 7, names))
        self.assertTrue(self.pack.asset_path(asset.relpath).is_file())
        self.assertIn(asset.relpath, self.pack.resource_index['patches'])
        self.pack.commit(self.pack.delete_resource('wr', 7, asset.relpath))
        self.assertNotIn(asset.relpath, self.pack.resource_index['patches'])
        self.assertFalse((self.pack.patch_directories['wr', 7] / 'renamed-map.tpl').exists())

    def test_sequential_package_imports_use_distinct_slots(self):
        packages = [read_package(self.fixture.package), read_package(self.fixture.package)]
        used = {slot for c, slot in self.pack.inventory.skins if c == 'wr'}
        chosen = []
        for package in packages:
            slot = next(i for i in range(1, 101) if i not in used)
            self.pack.commit(self.pack.import_patch_skin(self.fixture.package, 'wr', slot,
                 name=package.character['name'], author=package.character['author']))
            chosen.append(slot)
            used = {slot for c, slot in self.pack.inventory.skins if c == 'wr'}
        self.assertEqual(chosen, [1, 2])
        self.assertEqual(len(set(chosen)), 2)


class TargetedSourceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui_source = (Path(__file__).resolve().parents[1]/'wcm/gui.py').read_text(encoding='utf-8')

    def test_package_icon_preview_and_fallback(self):
        self.assertIn('def show_package_icons(self, package=None, entries=None):', self.gui_source)
        self.assertIn('list(package.assets + package.sources)', self.gui_source)
        self.assertIn('self.show_package_icons(package)', self.gui_source)

    def test_mass_import_kept_in_characters_menu_not_bottom(self):
        self.assertIn('def mass_import(self):', self.gui_source)
        self.assertNotIn("button('Mass Import…',self.mass_import)", self.gui_source)
        self.assertIn("self.action(actions,'Mass Import (.mkchara folder)…',self.mass_import)", self.gui_source)

    def test_character_menu_restored_resource_list_unchanged(self):
        self.assertIn('self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)', self.gui_source)
        self.assertIn('self.resource_list.viewport().setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)', self.gui_source)
        self.assertIn('self.table.customContextMenuRequested.connect(self.character_context_menu)', self.gui_source)
        self.assertNotIn('resourceMenuRequested.connect(', self.gui_source)
        self.assertNotIn('def viewportEvent(self, event):', self.gui_source)

    def test_package_previews_appear_above_manual_icon_selectors(self):
        self.assertIn("optional_layout.insertRow(0, 'Detected icons:', self.package_preview_widget)", self.gui_source)

    def test_bump_targets_selected_character_only(self):
        bump = self.gui_source.split('    def bump_patch_slots(self, amount=None):', 1)[1].split('    def show_patch_collision', 1)[0]
        self.assertIn('code = self.current_code', bump)
        self.assertIn('for old in self.editable_slot_set(code):', bump)
        self.assertNotIn('for code in CODE_IDS:', bump)
        self.assertIn('updates[(code, old)] = dest', bump)

if __name__ == '__main__':
    unittest.main()
