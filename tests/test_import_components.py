from native_fixtures import valid_brres,valid_szs
"""Compatibility checks for shared resources, costume overlays and mixed bases."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
import io
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
import test_mkchara as fixtures
from wcm.library import available_import_variants,select_import_entries,DEFAULT_RESOURCE_VARIANT,parse_asset
from wcm.models import ModelCandidate,source_entries,extract_model_bytes
from wcm.gui import ImportWizard
from wcm.mkchara import read_package,build_package
from wcm.szs import U8Archive

METAL=Path(r'C:\Users\kafia\Downloads\character\mkw_metalsonic')
KNUCKLES=Path(r'C:\Users\kafia\Downloads\character\mario_kart_wii_knuckles_13-07-20_')

class ResourceChoices(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.f=fixtures.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata');self.f.setUp();self.addCleanup(self.f.doCleanups)
 def test_nested_costumes_keep_shared_assets_and_replace_only_explicit_choice(self):
  entries=[('Menu/wr_Driver.brres',b'menu'),('Icons/icon.png',b'icon'),
           ('Race/ma_bike-wr.szs',b'default'),('Race/ma_kart-wr.szs',b'kart'),
           ('Race/Costume/ma_bike-wr.szs',b'costume')]
  self.assertEqual(available_import_variants(n for n,_ in entries),[DEFAULT_RESOURCE_VARIANT,'Race/Costume'])
  with self.assertRaisesRegex(ValueError,'Select one variant'):select_import_entries(entries,None)
  default=dict(select_import_entries(entries,DEFAULT_RESOURCE_VARIANT));chosen=dict(select_import_entries(entries,'Race/Costume'))
  self.assertEqual(default['Race/ma_bike-wr.szs'],b'default')
  self.assertNotIn('Race/ma_bike-wr.szs',chosen)
  self.assertEqual(chosen['Race/Costume/ma_bike-wr.szs'],b'costume')
  self.assertEqual(chosen['Race/ma_kart-wr.szs'],b'kart');self.assertEqual(chosen['Menu/wr_Driver.brres'],b'menu')
  self.assertEqual(parse_asset('Menu/wr_Driver.brres',source_import=True).destination(4),'Driver/wr-4.brres')
  self.assertEqual(parse_asset('Race/ma_bike-wr_2.szs',source_import=True).destination(4),'ma_bike-wr-4_2.szs')
 def test_identical_duplicates_preserved_but_differing_unselected_collisions_refused(self):
  duplicate=self.f.source/'copy'/'WR-allkart_BT.szs';duplicate.parent.mkdir()
  original=(self.f.source/'wr-allkart_BT.szs').read_bytes()
  other=self.f.source/'original'/'wr-allkart_BT.szs';other.parent.mkdir();other.write_bytes(original)
  (self.f.source/'wr-allkart_BT.szs').unlink();duplicate.write_bytes(original)
  plan=self.f.pack.import_patch_skin(self.f.source,'wr',9,name='Copies',author='')
  self.f.pack.commit(plan)
  package=read_package(io.BytesIO(build_package(self.f.pack,'wr',9)))
  self.assertEqual(dict(package.sources)['copy/WR-allkart_BT.szs'],original)
  archive=U8Archive.read(original);archive.replace('menu_model.brres',valid_brres(b'bres different'));duplicate.write_bytes(archive.encode())
  before=self.f.pack.archive_path.read_bytes()
  with self.assertRaisesRegex(ValueError,'conflicting output filename'):
   self.f.pack.import_patch_skin(self.f.source,'wr',10,name='Conflict',author='')
  self.assertEqual(self.f.pack.archive_path.read_bytes(),before)
 def test_foreign_component_is_preserved_and_wrong_skeleton_override_refused(self):
  foreign=self.f.source/'lg-allkart.szs';foreign.write_bytes((self.f.source/'wr-allkart_BT.szs').read_bytes())
  plan=self.f.pack.import_patch_skin(self.f.source,'wr',9,name='Bundle',author='')
  self.f.pack.commit(plan)
  package=read_package(io.BytesIO(build_package(self.f.pack,'wr',9)))
  self.assertEqual(dict(package.sources)['lg-allkart.szs'],foreign.read_bytes())
  self.assertFalse(any(parse_asset(n,source_import=True).code=='lg' for n,_ in package.assets))
  with self.assertRaisesRegex(ValueError,'does not convert its skeleton'):
   self.f.pack.import_patch_skin(self.f.source,'lg',10,name='Wrong',author='',driver_candidate=ModelCandidate('wr.brres'))
 @unittest.skipUnless(METAL.is_dir(),'Metal Sonic source unavailable')
 def test_metal_component_selection_rebinds_model_and_rejects_unsupported_base(self):
  dialog=ImportWizard(self.f.pack,'bmr');dialog.source.setText(str(METAL));dialog.probe();self.addCleanup(dialog.close)
  self.assertEqual(dialog.base.currentData(),'ca');self.assertEqual(dialog.driver_choice.archive_member,'ca.brres')
  dialog.base.setCurrentIndex(dialog.base.findData('lg'))
  self.assertEqual(dialog.driver_choice.archive_member,'lg.brres')
  dialog.base.setCurrentIndex(dialog.base.findData('bmr'));dialog.name.setText('Metal Sonic');dialog.slot.setValue(10)
  with patch('wcm.gui.QMessageBox.warning') as warning:
   dialog.validate();self.assertIsNone(dialog.plan);self.assertIn('not bmr',warning.call_args.args[2])
 @unittest.skipUnless(KNUCKLES.is_dir(),'Knuckles source unavailable')
 def test_exported_overlay_package_has_usable_wizard_and_preserves_other_costume(self):
  plan=self.f.pack.import_patch_skin(KNUCKLES,'ys',4,name='Knuckles',author='',source_variant='Race/Riders')
  self.f.pack.commit(plan);payload=build_package(self.f.pack,'ys',4);package=read_package(io.BytesIO(payload))
  self.assertEqual(dict(package.sources)['Race/ma_bike-ys.szs'],(KNUCKLES/'Race/ma_bike-ys.szs').read_bytes())
  path=self.f.root/'Knuckles.mkchara';path.write_bytes(payload)
  dialog=ImportWizard(self.f.pack,'ys');dialog.source.setText(str(path));dialog.probe();self.addCleanup(dialog.close)
  self.assertIsNotNone(dialog.driver_choice);self.assertFalse(dialog.variant_box.isVisible())
  dialog.name.setText('Knuckles');dialog.slot.setValue(5);dialog.validate();self.assertIsNotNone(dialog.plan)
