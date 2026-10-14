"""Focused mode routing, whole-character deletion and table selection checks."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_mkchara as packages
from wcm.bmg import CharacterBMG, name_id, author_id
from wcm.library import CODE_IDS
from wcm.mkchara import read_package
from wcm.szs import U8Archive

class InstallationAndDelete(unittest.TestCase):
    def setUp(self):
        self.fixture=packages.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_same_v1_package_both_modes_and_cleanup(self):
        f=self.fixture;data=read_package(f.package)
        for developer in (False,True):
            target=f.make_pack(f.root/str(developer),developer)
            if developer:
                plan=target.import_skin(f.package,'lg',12,insert=False,name='Imported',author='Artist')
                self.assertTrue(all(not path.is_relative_to(target.patches_path) for path in plan.writes))
            else:
                plan=target.import_patch_skin(f.package,'lg',12,name='Imported',author='Artist')
            target.commit(plan)
            for logical,payload in data.entries('lg'):
                from wcm.library import parse_asset
                destination=parse_asset(logical,source_import=True).destination(12)
                self.assertEqual(target.asset_path(destination).read_bytes(),payload)
            self.assertEqual(target.bmg.get_text(name_id(CODE_IDS['lg'],12)),'Imported')
            self.assertEqual(target.bmg.get_text(author_id(CODE_IDS['lg'],12)),'Artist')
            if developer:self.assertFalse(target.patches_path.exists())
            folder=target.patch_directories.get(('lg',12))
            target.commit(target.delete_characters([('lg',12)]))
            self.assertNotIn(('lg',12),target.inventory.skins)
            self.assertIsNone(target.bmg._lookup(name_id(CODE_IDS['lg'],12)))
            self.assertIsNone(target.bmg._lookup(author_id(CODE_IDS['lg'],12)))
            self.assertEqual(target.bmg.get_text(902),'Unrelated')
            self.assertFalse(any('lg-12' in path.name for path in target.character.rglob('*') if path.is_file()))
            if folder:self.assertFalse(folder.exists())
            if developer:self.assertFalse(target.patches_path.exists())

    def test_batch_delete_preserves_other_character_archives_and_unknown_files(self):
        f=self.fixture;pack=f.pack
        pack.commit(pack.import_patch_skin(f.source,'wr',9,name='Second',author='Other'))
        pack.commit(pack.import_patch_skin(f.source,'wr',10,name='Keep',author='Other'))
        folder=pack.patch_directories['wr',7]
        unrelated=folder/'unrelated.txt';unrelated.write_bytes(b'keep')
        pack.commit(pack.delete_characters([('wr',7),('wr',9)]))
        self.assertNotIn(('wr',7),pack.inventory.skins);self.assertNotIn(('wr',9),pack.inventory.skins)
        self.assertIn(('wr',10),pack.inventory.skins)
        self.assertEqual(unrelated.read_bytes(),b'keep')
        self.assertFalse((folder/pack.PATCH_META_FILENAME).exists())
        for path in pack._patch_name_archives():
            bmg=CharacterBMG.read(U8Archive.from_file(path).files['message/CharaName.bmg'])
            self.assertIsNone(bmg._lookup(name_id(CODE_IDS['wr'],7)))
            self.assertEqual(bmg.get_text(name_id(CODE_IDS['wr'],10)),'Keep')

    def test_permissions_shared_files_and_rollback(self):
        f=self.fixture;pack=f.pack
        original=pack.archive_path.read_bytes()
        # An original distribution character is protected in Patches mode.
        path=pack.character/'Driver/lg-3.brres';path.write_bytes(b'bres original');pack.reload()
        with self.assertRaises(PermissionError):pack.delete_characters([('lg',3)])
        def files():
            return {p:p.read_bytes() for root in (pack.character,pack.patches_path,pack.archive_path.parent)
                    for p in root.rglob('*') if p.is_file()}
        before=files();plan=pack.delete_characters([('wr',7)])
        with patch('wcm.operations.os.replace',side_effect=OSError('Injected delete failure')):
            with self.assertRaises(OSError):pack.commit(plan)
        self.assertEqual(files(),before);self.assertEqual(pack.archive_path.read_bytes(),original)
        index={'distribution':{},'patches':{'Driver/wr-7.brres':'Test Skin/wr-7.brres',
                                         'Driver/wr-9.brres':'Test Skin/wr-7.brres'}}
        pack._resource_index_path().write_bytes(pack._resource_index_bytes(index));pack.reload()
        with self.assertRaisesRegex(ValueError,'shared'):pack.delete_characters([('wr',7)])

    def test_delete_patch_overlay_restores_original_files_and_text(self):
        f=self.fixture;pack=f.pack
        path=pack.character/'Driver/wr-7.brres';path.write_bytes(b'bres original')
        archive=U8Archive.from_file(pack.archive_path)
        bmg=CharacterBMG.read(archive.files['message/CharaRR.bmg'])
        bmg.set_text(name_id(CODE_IDS['wr'],7),'Original');bmg.set_text(author_id(CODE_IDS['wr'],7),'Original author')
        archive.replace('message/CharaRR.bmg',bmg.encode());pack.archive_path.write_bytes(archive.encode());pack.reload()
        pack.commit(pack.delete_characters([('wr',7)]))
        self.assertEqual(path.read_bytes(),b'bres original')
        self.assertEqual(pack.inventory.skins['wr',7].name,'Original')
        self.assertFalse(pack.is_patch_skin('wr',7))

class TableAndWizard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        self.fixture=packages.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_ctrl_selection_two_action_menu_batch_export_and_cancel_delete(self):
        from PySide6.QtWidgets import QDialog, QMenu
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from wcm.gui import MainWindow
        f=self.fixture;pack=f.pack
        pack.commit(pack.import_patch_skin(f.source,'wr',9,name='Second',author='Other'))
        window=MainWindow(pack);window.change_base('wr');window.show();self.app.processEvents()
        for row,modifier in ((0,Qt.KeyboardModifier.NoModifier),(1,Qt.KeyboardModifier.ControlModifier)):
            point=window.table.visualItemRect(window.table.item(row,2)).center()
            QTest.mouseClick(window.table.viewport(),Qt.MouseButton.LeftButton,modifier,point)
        QTest.keyRelease(window.table,Qt.Key.Key_Control)
        self.assertEqual(window.selected_character_slots(),[7,9])
        seen=[]
        class MenuDouble:
            def __init__(self,*args):self.items=[]
            def addAction(self,text):
                from PySide6.QtGui import QAction
                action=QAction(text,window);self.items.append(action);return action
            def exec(self,*args):seen.extend(a.text() for a in self.items);return None
        with patch('wcm.gui.QMenu',MenuDouble):
            window.character_context_menu(window.table.visualItemRect(window.table.item(0,2)).center())
        self.assertEqual(seen,['Export as .mkchara','Delete Character'])
        self.assertEqual(window.selected_character_slots(),[7,9])
        out=f.root/'Export';out.mkdir()
        with patch('wcm.gui.QFileDialog.getExistingDirectory',return_value=str(out)),patch('wcm.gui.QMessageBox.information'),patch('wcm.gui.QMessageBox.exec'):
            window.export_character()
        self.assertEqual(len(list(out.glob('*.mkchara'))),2)
        before={p:p.read_bytes() for p in pack.patches_path.rglob('*') if p.is_file()}
        with patch('wcm.gui.PreviewDialog.exec',return_value=QDialog.DialogCode.Rejected):window.delete_characters()
        self.assertEqual(before,{p:p.read_bytes() for p in pack.patches_path.rglob('*') if p.is_file()})
        window.pending_patch_slots[('wr',7)]=12
        with patch('wcm.gui.QMessageBox.information'),patch.object(pack,'delete_characters') as delete:
            window.delete_characters();delete.assert_not_called()
        window.close();window.deleteLater();self.app.processEvents()

    def test_wizard_and_mass_import_route_by_current_mode(self):
        from PySide6.QtWidgets import QMessageBox
        from wcm.gui import MainWindow, ImportWizard
        f=self.fixture
        for developer in (False,True):
            pack=f.make_pack(f.root/('Gui'+str(developer)),developer)
            wizard=ImportWizard(pack,'wr');wizard.source.setText(str(f.package));wizard.probe();wizard.slot.setValue(12)
            self.assertEqual(wizard.target.currentData(),'library' if developer else 'patches')
            wizard.validate();self.assertIsNotNone(wizard.plan)
            self.assertTrue(all(not p.is_relative_to(pack.patches_path) for p in wizard.plan.writes) if developer
                            else all(p.is_relative_to(pack.patches_path) for p in wizard.plan.writes))
            wizard.close();wizard.deleteLater()
            folder=f.root/('Packages'+str(developer));folder.mkdir();(folder/'old-v1.mkchara').write_bytes(f.package.read_bytes())
            window=MainWindow(pack)
            with patch('wcm.gui.QFileDialog.getExistingDirectory',return_value=str(folder)),patch('wcm.gui.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes),patch('wcm.gui.QMessageBox.exec'):
                window.mass_import()
            self.assertEqual(len(pack.inventory.skins),1)
            self.assertTrue(all(pack.is_patch_skin(*key)==(not developer) for key in pack.inventory.skins))
            if developer:self.assertFalse(pack.patches_path.exists())
            window.close();window.deleteLater();self.app.processEvents()


class MassProgress(unittest.TestCase):
    def test_background_import_updates_progress_and_keeps_ui_timer_running(self):
        import time
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QTimer
        from wcm.gui import MassImportProgress
        app=QApplication.instance() or QApplication([])
        f=packages.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata')
        f.setUp();self.addCleanup(f.doCleanups)
        target=f.make_pack(f.root/'ProgressTarget',True)
        second=f.root/'second.mkchara';second.write_bytes(f.package.read_bytes())
        bad=f.root/'bad.mkchara';bad.write_bytes(b'bad package')
        dialog=MassImportProgress(target,[f.package,second,bad])
        messages=[];ticks=[]
        dialog.worker.progress.connect(lambda completed,text:messages.append((completed,text)))
        timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        original_commit=target.commit
        def slow_commit(plan, **kwargs):
            time.sleep(.08)
            return original_commit(plan, **kwargs)
        with patch.object(target,'commit',side_effect=slow_commit),patch.object(target,'import_patch_skin',side_effect=AssertionError('Developer called patches')):
            dialog.exec();dialog.worker.wait()
        timer.stop()
        self.assertGreater(len(ticks),5)
        self.assertEqual(dialog.bar.value(),3)
        self.assertEqual(len(dialog.worker.successes),2)
        self.assertEqual(len(dialog.worker.failures),1)
        self.assertTrue(any('Installing Test Skin' in text and 'second.mkchara' in text and 'Character' in text for _,text in messages))
        self.assertEqual([value for value,text in messages if text.startswith('Processed')],[1,2,3])
        self.assertIn('finished',dialog.current.text())
        self.assertFalse(target.patches_path.exists())
        dialog.close();dialog.deleteLater();app.processEvents()
