"""Targeted distribution normalization, mixed resource numbers, standalone priority."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QDialog
import test_mkchara as fixtures
from wcm.bmg import CharacterBMG,name_id,author_id
from wcm.library import CODE_IDS,parse_asset
from wcm.models import source_entries,automatic_driver_candidate,discover_models
from wcm.gui import MainWindow,ImportWizard
from wcm.szs import U8Archive
from wcm.operations import EditPlan

SNAKE=Path(r'C:\Users\kafia\Downloads\character\snake_big_boss_mkw')

class NormalizeIndependent(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.f=fixtures.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata');self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.pack=self.f.make_pack(self.f.root/'Independent',True)
  for slot in (3,7):
   self.pack.commit(self.pack.import_skin(self.f.package,'wr',slot,insert=False,name=f'Original {slot}',author=f'Base {slot}'))
  self.pack.commit(self.pack.import_patch_skin(self.f.package,'wr',1,name='Patch 1',author='Patch author'))
  # Simulate an existing distribution update shadowed by flat Patches files.
  for asset in self.pack.distribution_inventory.skins['wr',3].files:
   (self.pack.patches_path/asset.filename_for(3)).write_bytes((self.pack.character/asset.relpath).read_bytes())
  self.pack.reload()
  bmg=CharacterBMG.read(self.pack.bmg.encode());bmg.set_text(name_id(CODE_IDS['wr'],3),'Patch 3');bmg.set_text(author_id(CODE_IDS['wr'],3),'Patch author')
  plan=EditPlan('Fixture shadow text');self.pack._stage_name_patches(plan,bmg);self.pack.commit(plan)
  self.original={p:p.read_bytes() for p in self.pack.character.rglob('*') if p.is_file()}
  self.patches={p:p.read_bytes() for p in self.pack.patches_path.rglob('*') if p.is_file()}
  self.window=MainWindow(self.pack);self.window.show();self.window.change_base('wr');self.addCleanup(self.close)
 def close(self):self.window.close();self.window.deleteLater();self.app.processEvents()
 def test_normalize_shadowed_character_slots_preserves_patches_and_revert(self):
  w=self.window
  with patch('wcm.gui.QMessageBox.warning') as warn:
   w.normalize_slots();warn.assert_not_called()
  self.assertEqual(w.pending_slot_map(),{'wr':{3:1,7:2}})
  self.assertEqual(w.table.rowCount(),2)
  self.assertEqual([w.table.item(row,2).text() for row in range(2)],['Original 3','Original 7'])
  self.assertFalse(w.staged_conflicts());self.assertTrue(w.slot_save_button.isEnabled())
  self.assertEqual(self.patches,{p:p.read_bytes() for p in self.pack.patches_path.rglob('*') if p.is_file()})
  w.revert_patch_slot_changes();self.assertEqual(w.pending_slot_map(),{})
  self.assertEqual(self.original,{p:p.read_bytes() for p in self.pack.character.rglob('*') if p.is_file()})
  w.normalize_slots()
  with patch('wcm.gui.PreviewDialog.exec',return_value=QDialog.DialogCode.Accepted),patch('wcm.gui.QMessageBox.information'),patch('wcm.gui.QMessageBox.warning') as warn:
   w.save_patch_slot_changes();warn.assert_not_called()
  self.assertEqual(self.patches,{p:p.read_bytes() for p in self.pack.patches_path.rglob('*') if p.is_file()})
  self.assertEqual(self.pack.distribution_slots('wr'),{1,2})
  for old,new in ((3,1),(7,2)):
   for path,data in self.original.items():
    asset=parse_asset(path.relative_to(self.pack.character).as_posix())
    if asset and asset.slot==old:
     self.assertEqual((self.pack.character/asset.destination(new)).read_bytes(),data)
   self.assertEqual(self.pack.base_bmg.get_text(name_id(CODE_IDS['wr'],new)),f'Original {old}')
   self.assertEqual(self.pack.base_bmg.get_text(author_id(CODE_IDS['wr'],new)),f'Base {old}')
  self.assertEqual(self.pack.bmg.get_text(name_id(CODE_IDS['wr'],1)),'Patch 1')
 def test_text_only_reservations_are_preserved_in_freed_slots(self):
  archive=U8Archive.from_file(self.pack.archive_path)
  bmg=CharacterBMG.read(archive.files['message/CharaRR.bmg']);bmg.set_text(name_id(CODE_IDS['wr'],1),'');bmg.set_text(author_id(CODE_IDS['wr'],1),'')
  archive.replace('message/CharaRR.bmg',bmg.encode());self.pack.archive_path.write_bytes(archive.encode());self.pack.reload()
  plan=self.pack.reassign_developer_slots({'wr':{3:1,7:2}},independent_codes={'wr'})
  self.assertTrue(all(not p.is_relative_to(self.pack.patches_path) for p in plan.writes))
  bmg.set_text(name_id(CODE_IDS['wr'],1),'Reserved Character text')
  archive.replace('message/CharaRR.bmg',bmg.encode());self.pack.archive_path.write_bytes(archive.encode());self.pack.reload()
  before={(m.id,m.raw,m.metadata) for m in self.pack.base_bmg.messages}
  patch_bytes={p:p.read_bytes() for p in self.pack.patches_path.rglob('*') if p.is_file()}
  self.pack.commit(self.pack.reassign_developer_slots({'wr':{3:1,7:2}},independent_codes={'wr'}))
  self.assertEqual(self.pack.base_bmg.get_text(name_id(CODE_IDS['wr'],1)),'Original 3')
  self.assertEqual(self.pack.base_bmg.get_text(name_id(CODE_IDS['wr'],3)),'Reserved Character text')
  self.assertEqual(sorted((raw,metadata) for _,raw,metadata in before),
                   sorted((m.raw,m.metadata) for m in self.pack.base_bmg.messages))
  self.assertEqual(patch_bytes,{p:p.read_bytes() for p in self.pack.patches_path.rglob('*') if p.is_file()})


@unittest.skipUnless(SNAKE.is_dir(),'Snake Big Boss local source unavailable')
class SnakeImport(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.f=fixtures.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata');self.f.setUp();self.addCleanup(self.f.doCleanups)
 def test_snake_standalone_priority_and_both_import_modes_preserve_every_asset(self):
  entries=source_entries(SNAKE)
  with patch('wcm.models.U8Archive.read',side_effect=AssertionError('SZS searched before standalone')):
   chosen=automatic_driver_candidate(entries)
  self.assertEqual(chosen.source_path,'wl-6.brres');self.assertEqual(chosen.archive_member,'')
  for dev in (False,True):
   pack=self.f.make_pack(self.f.root/str(dev),dev)
   wizard=ImportWizard(pack,'wl');wizard.source.setText(str(SNAKE));wizard.probe()
   self.assertEqual(wizard.driver_choice.source_path,'wl-6.brres');self.assertIn('wl-6.brres',wizard.driver_note.text())
   wizard.slot.setValue(12);wizard.name.setText('Snake Big Boss');wizard.validate();self.assertIsNotNone(wizard.plan)
   pack.commit(wizard.plan);wizard.close();wizard.deleteLater()
   for filename,data in entries:
    asset=parse_asset(filename,source_import=True)
    if asset:
     destination=asset.destination(12)
     if asset.category in ('Portrait','Map'):
      from wcm.tpl import read_tpl
      destination=f'Portrait/wl-12-css.tpl' if read_tpl(data).size==(64,64) else f'Map/wl-12.tpl'
     self.assertEqual(pack.asset_path(destination).read_bytes(),data)
   self.assertEqual(pack.inventory.skins['wl',12].counts['Driver'],1)
   self.assertEqual(pack.inventory.skins['wl',12].counts['Sound'],12)
   if dev:self.assertFalse(pack.patches_path.exists())
 def test_arbitrary_standalone_name_is_usable_and_real_multiple_drivers_rejected(self):
  data=(SNAKE/'wl-6.brres').read_bytes()
  chosen=automatic_driver_candidate([('custom_character.brres',data),('la_bike-wl.szs',b'not needed')])
  self.assertEqual(chosen.source_path,'custom_character.brres')
  source=self.f.root/'Generic';source.mkdir();(source/'custom_character.brres').write_bytes(data)
  plan=self.f.pack.import_patch_skin(source,'wl',8,name='Standalone',author='Tester')
  self.f.pack.commit(plan);self.assertEqual(self.f.pack.asset_path('Driver/wl-8.brres').read_bytes(),data)
  (source/'wl-3.brres').write_bytes(data);(source/'wl-4.brres').write_bytes(data)
  with self.assertRaisesRegex(ValueError,'several different numbered skins'):
   self.f.pack.import_patch_skin(source,'wl',9,name='Separate',author='Tester')
