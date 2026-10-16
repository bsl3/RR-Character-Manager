"""Cross-section export/selection and measured optimization regression checks."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import io,unittest
from pathlib import Path
from unittest.mock import patch
import test_mkchara as packages
from wcm.mkchara import build_package,read_package,write_package
from wcm.gui import MainWindow,MassExportWorker,MassImportWorker
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest

class CrossSection(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.f=packages.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata');self.f.setUp();self.addCleanup(self.f.doCleanups)
  self.pack=self.f.pack
  for code,slot,name in [('rs',9,'Samus'),('mr',12,'Fire Mario Skin'),('mr',13,'Fire Mario Skin'),('lg',11,'Gooigi')]:
   self.pack.commit(self.pack.import_patch_skin(self.f.package,code,slot,name=name,author='Author'))
  self.window=MainWindow(self.pack);self.window.show();self.app.processEvents();self.addCleanup(self.close)
 def close(self):self.window.close();self.window.deleteLater();self.app.processEvents()
 def click(self,row,control=False):
  table=self.window.table;point=table.visualItemRect(table.item(row,2)).center()
  QTest.mouseClick(table.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.ControlModifier if control else Qt.KeyboardModifier.NoModifier,point)
  QTest.keyRelease(table,Qt.Key.Key_Control)
 def test_selection_persists_across_sections_toggles_and_normal_click_clears(self):
  w=self.window;w.change_base('rs');self.click(0,True)
  self.assertEqual(w.selected_character_keys(),[('rs',9)])
  w.change_base('mr');self.click(0,True);self.click(1,True)
  self.assertEqual(w.selected_character_keys(),[('mr',12),('mr',13),('rs',9)])
  self.assertEqual(w.selection_summary.text(),'3 selected across sections')
  w.change_base('rs');self.assertEqual(w.selected_character_slots(),[9]);self.click(0,True)
  self.assertEqual(w.selected_character_keys(),[('mr',12),('mr',13)])
  w.change_base('lg');self.click(0,True)
  w.change_base('mr');self.assertEqual(w.selected_character_slots(),[12,13])
  w.search.setText('nothing');self.assertEqual(len(w.selected_character_keys()),3)
  w.search.clear();self.click(1)
  self.assertEqual(w.selected_character_keys(),[('mr',13)])
  w.change_base('rs');self.click(0,True)
  # The top menu command exports hidden and visible selections with their own base IDs.
  out=self.f.root/'Export';out.mkdir()
  with patch('wcm.gui.QFileDialog.getExistingDirectory',return_value=str(out)),patch('wcm.gui.QMessageBox.exec'):
   w.mass_export()
  self.assertTrue((out/'CharacterExport/Mario/Fire Mario Skin.mkchara').is_file())
  self.assertTrue((out/'CharacterExport/Rosalina/Samus.mkchara').is_file())
  self.assertFalse((out/'CharacterExport/Luigi').exists())
 def test_distribution_rows_restore_theme_after_reusing_patch_items(self):
  driver=self.pack.character/'Driver'/'bmr-1.brres'
  driver.parent.mkdir(parents=True,exist_ok=True);driver.write_bytes(b'fixture model')
  self.pack.reload()
  w=self.window;w.change_base('wr')
  item=w.table.item(0,2)
  self.assertEqual(item.foreground().color().name(),'#fff0f5')
  self.assertEqual(item.background().color().name(),'#683c57')
  w.change_base('bmr')
  self.assertIs(w.table.item(0,2),item)
  for column in range(w.table.columnCount()):
   cell=w.table.item(0,column)
   self.assertIsNone(cell.data(Qt.ItemDataRole.BackgroundRole))
   self.assertIsNone(cell.data(Qt.ItemDataRole.ForegroundRole))
   self.assertEqual(cell.background().style(),Qt.BrushStyle.NoBrush)
   self.assertEqual(cell.foreground().style(),Qt.BrushStyle.NoBrush)
  w.refresh_table()
  self.assertIsNone(item.data(Qt.ItemDataRole.ForegroundRole))
  w.change_base('wr')
  self.assertEqual(item.foreground().color().name(),'#fff0f5')
  self.assertEqual(item.background().color().name(),'#683c57')
 def test_grouped_export_preserves_payloads_avoids_duplicates_continues_failure(self):
  out=self.f.root/'Output';existing=out/'CharacterExport/Mario/Fire Mario Skin.mkchara';existing.parent.mkdir(parents=True);existing.write_bytes(b'keep existing')
  keys=[('rs',9),('bk',99),('mr',12),('mr',13),('lg',11)]
  worker=MassExportWorker(self.pack,keys,out);worker.run()
  self.assertEqual(len(worker.successes),4);self.assertEqual(len(worker.failures),1)
  self.assertEqual(existing.read_bytes(),b'keep existing')
  self.assertFalse((out/'CharacterExport/Dry Bowser').exists())
  for code,slot in [key for key in keys if key in self.pack.inventory.skins]:
   base={'rs':'Rosalina','mr':'Mario','lg':'Luigi'}[code]
   expected=read_package(io.BytesIO(build_package(self.pack,code,slot)))
   files=[p for p in (out/'CharacterExport'/base).glob('*.mkchara') if p!=existing]
   matching=[read_package(p) for p in files]
   self.assertTrue(any(dict(p.assets)==dict(expected.assets) and dict(p.sources)==dict(expected.sources) and p.character==expected.character for p in matching))
  self.assertEqual(len(list(existing.parent.glob('*.mkchara'))),3)
  safe=self.pack._safe_folder_name('NUL:bad/name?')
  self.assertNotIn('/',safe);self.assertNotIn(':',safe)
 def test_no_replace_export_and_icon_file_invalidation(self):
  path=self.f.root/'test.mkchara';path.write_bytes(b'keep')
  with self.assertRaises(FileExistsError):write_package(path,build_package(self.pack,'wr',7),overwrite=False)
  self.assertEqual(path.read_bytes(),b'keep')
  skin=self.pack.inventory.skins['wr',7]
  from wcm.tpl import read_tpl
  with patch('wcm.gui.read_tpl',wraps=read_tpl) as decode:
   self.window.skin_image(skin,'Map');self.window.skin_image(skin,'Map')
   self.assertEqual(decode.call_count,1)
   self.pack.commit(self.pack.replace_map('wr',7,self.f.source/'wr-css.tpl'))
   self.window.skin_image(self.pack.inventory.skins['wr',7],'Map')
   self.assertEqual(decode.call_count,2)
  self.assertLessEqual(len(self.window._icon_cache),512)

class IncrementalImport(unittest.TestCase):
 def setUp(self):
  self.f=packages.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata');self.f.setUp();self.addCleanup(self.f.doCleanups)
 def test_incremental_matches_full_reload_in_both_modes_and_backup(self):
  f=self.f
  for dev in (False,True):
   pack=f.make_pack(f.root/str(dev),dev)
   method=pack.import_skin if dev else pack.import_patch_skin
   for slot in (12,13):
    kwargs={'insert':False} if dev else {}
    plan=method(f.package,'lg',slot,name=f'Imported {slot}',author='Author',**kwargs)
    with patch.object(pack,'reload',wraps=pack.reload) as reload:
     backup=pack.commit(plan,imported_character=('lg',slot));reload.assert_not_called()
    self.assertIsNone(backup)
    before={(key): (s.name,s.author,[a.relpath for a in s.files]) for key,s in pack.inventory.skins.items()}
    snapshot=dict(pack._snapshot);bmg=pack.bmg.encode();count=pack.inventory.scanned_file_count
    pack.reload()
    self.assertEqual(before,{key:(s.name,s.author,[a.relpath for a in s.files]) for key,s in pack.inventory.skins.items()})
    self.assertEqual(bmg,pack.bmg.encode());self.assertEqual(count,pack.inventory.scanned_file_count)
    for path,digest in snapshot.items():self.assertEqual(digest,pack._snapshot.get(path,digest))
   if dev:self.assertFalse(pack.patches_path.exists())
 def test_incremental_validation_failure_rolls_back_and_batch_scans_once(self):
  f=self.f;pack=f.make_pack(f.root/'Fail')
  before=pack.archive_path.read_bytes();plan=pack.import_patch_skin(f.package,'lg',12,name='Test',author='Author')
  with patch.object(pack,'_reload_imported_character',side_effect=ValueError('Injected failure')):
   with self.assertRaises(ValueError):pack.commit(plan,imported_character=('lg',12))
  self.assertNotIn(('lg',12),pack.inventory.skins);self.assertEqual(pack.archive_path.read_bytes(),before)
  worker=MassImportWorker(pack,[f.package]*3)
  with patch.object(pack,'reload',wraps=pack.reload) as reload:
   worker.run();self.assertEqual(reload.call_count,1)
  self.assertEqual(len(worker.successes),3);self.assertFalse(worker.failures)


class BackgroundIndex(unittest.TestCase):
 def test_indexing_keeps_ui_responsive_and_propagates_failures(self):
  import time,threading
  from wcm.gui import read_library_background
  app=QApplication.instance() or QApplication([])
  ui_thread=threading.get_ident();ticks=[]
  timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(1));timer.start()
  def read():time.sleep(.06);return threading.get_ident()
  self.assertNotEqual(read_library_background(read,None),ui_thread)
  self.assertGreater(len(ticks),3);timer.stop()
  def failure():raise ValueError('Bad archive')
  with self.assertRaisesRegex(ValueError,'Bad archive'):read_library_background(failure,None)
  app.processEvents()
