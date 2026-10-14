"""Developer staging/transactions and shared package slot allocation."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import io
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import QApplication, QDialog
import test_mkchara as fixtures
from wcm.gui import MainWindow, ImportWizard, MassImportWorker
from wcm.bmg import CharacterBMG, name_id, author_id
from wcm.library import CODE_IDS
from wcm.mkchara import build_package, read_package
from wcm.szs import U8Archive

class DeveloperSlots(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.f = fixtures.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.pack = self.f.make_pack(self.f.root/'Developer', True)
        for code, slot in [('wr', 3), ('wr', 5), ('wr', 7), ('wr', 12), ('lg', 6)]:
            self.pack.commit(self.pack.import_skin(self.f.package, code, slot, insert=False,
                name=f'{code}-{slot}', author=f'Author {slot}'))
        self.before = {key: read_package(io.BytesIO(build_package(self.pack, *key)))
                       for key in self.pack.inventory.skins}
        self.window = MainWindow(self.pack); self.window.show(); self.app.processEvents()
        self.window.change_base('wr')
        self.addCleanup(self.close)

    def close(self):
        self.window.close(); self.window.deleteLater(); self.app.processEvents()

    def save(self):
        with patch('wcm.gui.PreviewDialog.exec', return_value=QDialog.DialogCode.Accepted), \
             patch('wcm.gui.QMessageBox.information') as done, \
             patch('wcm.gui.QMessageBox.warning') as warning:
            self.window.save_patch_slot_changes()
            warning.assert_not_called(); done.assert_called_once()

    def check_payload(self, original, target):
        expected = self.before[original]
        actual = read_package(io.BytesIO(build_package(self.pack, *target)))
        self.assertEqual(dict(expected.assets), dict(actual.assets))
        self.assertEqual(dict(expected.sources), dict(actual.sources))
        self.assertEqual(expected.character, actual.character)
        cid, slot = CODE_IDS[target[0]], target[1]
        self.assertEqual(self.pack.bmg.get_text(name_id(cid, slot)), expected.character['name'])
        self.assertEqual(self.pack.bmg.get_text(author_id(cid, slot)), expected.character['author'])
        self.assertEqual(U8Archive.from_file(self.pack.archive_path).files['layout/untouched.bin'], b'layout')
        self.assertFalse(self.pack.patches_path.exists())

    def test_drag_reorder_save_and_revert(self):
        w = self.window
        self.assertTrue(w.patch_controls.isVisible())
        self.assertTrue(w.table.item(0, 0).flags() & Qt.ItemFlag.ItemIsDragEnabled)
        table = w.table
        class Drop:
            def source(self): return table
            def position(self): return QPointF(table.visualItemRect(table.item(1, 0)).center())
            def setDropAction(self,action): self.action=action
            def accept(self): self.accepted = True
            def ignore(self): raise AssertionError('Developer drop rejected')
        event = Drop(); table._drag_slot = 3; table.dropEvent(event); table._drag_slot = None
        QApplication.instance().processEvents()
        self.assertTrue(event.accepted)
        self.assertEqual(w.pending_slot_map(), {'wr': {3: 5, 5: 3}})
        self.assertTrue(w.slot_save_button.isEnabled()); self.assertTrue(w.slot_revert_button.isEnabled())
        self.check_payload(('wr',3), ('wr',3))  # staging changes no files
        w.revert_patch_slot_changes(); self.assertEqual(w.pending_slot_map(), {})
        w.stage_patch_drop(3, 5); self.save()
        self.check_payload(('wr',3), ('wr',5)); self.check_payload(('wr',5), ('wr',3))
        self.check_payload(('lg',6), ('lg',6))
        self.assertTrue(list((self.pack.character.parent/'RR Character Manager Backups').glob('*/manifest.json')))

    def test_bump_and_normalize_follow_staged_order_and_save_across_sections(self):
        w = self.window
        w.bump_patch_slots(2)
        self.assertEqual(w.pending_slot_map(), {'wr': {3: 5, 5: 7, 7: 9, 12: 14}})
        w.revert_patch_slot_changes(); w.stage_patch_drop(3, 5); w.normalize_slots()
        self.assertEqual(w.pending_slot_map(), {'wr': {5: 1, 3: 2, 7: 3, 12: 4}})
        w.change_base('lg'); w.bump_patch_slots(2); self.save()
        for old, new in [(5,1),(3,2),(7,3),(12,4)]: self.check_payload(('wr',old), ('wr',new))
        self.check_payload(('lg',6), ('lg',8))
        self.assertEqual(self.pack.movable_slots('wr'), {1,2,3,4})
        for old in (5,7,12):
            self.assertIsNone(self.pack.bmg._lookup(name_id(CODE_IDS['wr'], old)))

    def test_normalize_rejects_orphan_destination_and_bump_limits(self):
        orphan = self.pack.character/'Map/wr-1.tpl'
        orphan.parent.mkdir(exist_ok=True); orphan.write_bytes((self.f.source/'wr.tpl').read_bytes())
        self.pack.reload()
        with patch('wcm.gui.QMessageBox.warning') as warning:
            self.window.normalize_slots(); warning.assert_called_once()
        self.assertEqual(self.window.pending_slot_map(), {})
        with patch('wcm.gui.QMessageBox.warning') as warning:
            self.window.bump_patch_slots(100); warning.assert_called_once()
        self.assertEqual(self.window.pending_slot_map(), {})
        with self.assertRaisesRegex(ValueError, 'reserved'):
            self.pack.reassign_developer_slots({'wr': {3:1}})
        with self.assertRaisesRegex(ValueError, 'overlap'):
            self.pack.reassign_developer_slots({'wr': {3:5}})

    def test_staged_changes_block_import_and_immediate_moves(self):
        w = self.window; w.bump_patch_slots(2)
        pending = w.pending_slot_map()
        with patch('wcm.gui.QMessageBox.information') as message:
            w.import_character(); w.mass_import(); w.move_character()
            self.assertEqual(message.call_count,3)
        self.assertEqual(w.pending_slot_map(),pending)
        self.check_payload(('wr',3),('wr',3))

    def test_failed_developer_transaction_rolls_back_every_asset_and_archive(self):
        plan = self.pack.reassign_developer_slots({'wr': {3:5,5:3}, 'lg':{6:8}})
        snapshot = {p:p.read_bytes() for p in self.pack.character.rglob('*') if p.is_file()}
        archive = self.pack.archive_path.read_bytes()
        reload = self.pack.reload
        calls = 0
        def fail_once():
            nonlocal calls
            calls += 1
            if calls == 1: raise ValueError('validation failure')
            reload()
        with patch.object(self.pack, 'reload', side_effect=fail_once):
            with self.assertRaisesRegex(ValueError,'validation failure'): self.pack.commit(plan)
        self.assertEqual(snapshot, {p:p.read_bytes() for p in self.pack.character.rglob('*') if p.is_file()})
        self.assertEqual(self.pack.archive_path.read_bytes(), archive)
        self.assertFalse(self.pack.patches_path.exists())

class PackageAssignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QApplication.instance() or QApplication([])
    def setUp(self):
        self.f = fixtures.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
    def test_wizard_and_sequential_mass_import_append_in_both_modes(self):
        for developer in (False, True):
            with self.subTest(developer=developer):
                pack = self.f.make_pack(self.f.root/str(developer), developer)
                install = pack.import_skin if developer else pack.import_patch_skin
                kwargs = {'insert':False} if developer else {}
                for slot in (1,3):
                    pack.commit(install(self.f.package,'wr',slot,name=f'Old{slot}',author='Existing',**kwargs))
                wizard = ImportWizard(pack,'wr')
                wizard.source.setText(str(self.f.package)); wizard.probe()
                self.assertEqual(wizard.slot.value(),4)
                wizard.slot.setValue(2); wizard.probe(); self.assertEqual(wizard.slot.value(),2)
                wizard.validate(); self.assertIsNotNone(wizard.plan)
                pack.commit(wizard.plan)
                self.assertIn(('wr',2), pack.inventory.skins)
                wizard.base.setCurrentIndex(wizard.base.findData('lg')); self.assertEqual(wizard.slot.value(),1)
                wizard.close(); wizard.deleteLater()
                worker = MassImportWorker(pack,[self.f.package,self.f.package]); worker.run()
                self.assertEqual(worker.failures,[])
                self.assertEqual({slot for code,slot in pack.inventory.skins if code=='wr'}, {1,2,3,4,5})
                for slot in (4,5):
                    actual = read_package(io.BytesIO(build_package(pack,'wr',slot)))
                    expected = read_package(self.f.package)
                    self.assertEqual(actual.character, expected.character)
                    self.assertEqual(dict(actual.assets),dict(expected.assets))
                    self.assertEqual(dict(actual.sources),dict(expected.sources))
                if developer: self.assertFalse(pack.patches_path.exists())
    def test_allocator_includes_orphan_resources_text_and_slot_limit(self):
        pack = self.f.make_pack(self.f.root/'Reserved',True)
        (pack.character/'Map').mkdir(); (pack.character/'Map/wr-9.tpl').write_bytes(b'orphan')
        bmg = pack.base_bmg; bmg.set_text(author_id(CODE_IDS['wr'],11),'Reserved')
        archive = U8Archive.from_file(pack.archive_path)
        archive.replace('message/CharaRR.bmg', bmg.encode()); pack.archive_path.write_bytes(archive.encode()); pack.reload()
        # Baseline catalogs without files do not reserve a slot. Custom overrides do.
        self.assertEqual(pack.next_import_slot('wr'),10); self.assertEqual(pack.next_import_slot('lg'),1)
        custom = CharacterBMG.read(pack.bmg.encode()); custom.set_text(author_id(CODE_IDS['wr'],11), 'Custom reservation')
        plan = pack.update_character_text(); pack._stage_name_patches(plan, custom); pack.commit(plan)
        self.assertEqual(pack.next_import_slot('wr'),12)
        bmg = pack.base_bmg; bmg.set_text(name_id(CODE_IDS['wr'],100),'Full')
        archive.replace('message/CharaRR.bmg',bmg.encode()); pack.archive_path.write_bytes(archive.encode()); pack.reload()
        custom = CharacterBMG.read(pack.bmg.encode()); custom.set_text(name_id(CODE_IDS['wr'],100), 'Custom full')
        plan = pack.update_character_text(); pack._stage_name_patches(plan, custom); pack.commit(plan)
        with self.assertRaisesRegex(ValueError,'maximum 100'): pack.next_import_slot('wr')
