"""Slot ownership, catalog reuse, grouped remaps and collision warning regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import io
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
import test_mkchara as fixtures
from wcm.operations import CharacterPack
from wcm.bmg import CharacterBMG, name_id, author_id
from wcm.library import CODE_IDS
from wcm.mkchara import build_package, read_package
from wcm.szs import U8Archive
from wcm.gui import MainWindow

class SlotOwnership(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.f = fixtures.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata')
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.pack = self.f.make_pack(self.f.root/'Isolated', True)
        self.cid = CODE_IDS['wr']

    def catalog(self, slot, name='Old catalog', author='Old author'):
        bmg = CharacterBMG.read(self.pack.base_bmg.encode())
        bmg.set_text(name_id(self.cid, slot), name); bmg.set_text(author_id(self.cid, slot), author)
        arc = U8Archive.from_file(self.pack.archive_path)
        arc.replace('message/CharaRR.bmg', bmg.encode()); self.pack.archive_path.write_bytes(arc.encode())
        self.pack.reload()

    def install(self, slot, name='Custom', patches=True):
        method = self.pack.import_patch_skin if patches else self.pack.import_skin
        args = {} if patches else {'insert':False}
        self.pack.commit(method(self.f.package, 'wr', slot, name=name, author='Maker', **args))

    def restart(self):
        self.pack = CharacterPack(self.pack.character, self.pack.archive_path, self.pack.patches_path, developer_mode=True)

    def assert_text(self, slot, name, author='Maker'):
        self.assertEqual(self.pack.bmg.get_text(name_id(self.cid,slot)), name)
        self.assertEqual(self.pack.bmg.get_text(author_id(self.cid,slot)), author)
        ids = [m.id for m in self.pack.bmg.messages]
        self.assertEqual(len(ids), len(set(ids)))
        for path in self.pack._patch_name_archives():
            if path.exists():
                table = CharacterBMG.read(U8Archive.from_file(path).files['message/CharaName.bmg'])
                self.assertEqual(table.get_text(name_id(self.cid,slot)),name)
                self.assertEqual(table.get_text(author_id(self.cid,slot)),author)
                self.assertEqual([m.id for m in table.messages], sorted(m.id for m in table.messages))

    def window(self):
        w = MainWindow(self.pack); w.change_base('wr')
        def close():
            w.pending_patch_slots.clear(); w.close(); w.deleteLater(); self.app.processEvents()
        self.addCleanup(close)
        return w

    def save(self, w):
        with patch('wcm.gui.PreviewDialog.exec', return_value=QDialog.DialogCode.Accepted), \
             patch('wcm.gui.QMessageBox.information') as success, \
             patch('wcm.gui.QMessageBox.warning') as warning, \
             patch('wcm.gui.QMessageBox.critical') as failure:
            w.save_patch_slot_changes()
            warning.assert_not_called(); failure.assert_not_called(); success.assert_called_once()

    def test_patch_move_into_catalog_slot_repeat_delete_and_reuse(self):
        self.catalog(4); original = self.pack.archive_path.read_bytes()
        self.install(3)
        expected = read_package(io.BytesIO(build_package(self.pack,'wr',3)))
        for src,dst in [(3,4),(4,5),(5,4)]:
            self.pack.commit(self.pack.reassign_patch_slots({'wr':{src:dst}})); self.restart()
            self.assert_text(dst,'Custom')
            actual = read_package(io.BytesIO(build_package(self.pack,'wr',dst)))
            self.assertEqual(dict(expected.assets),dict(actual.assets)); self.assertEqual(dict(expected.sources),dict(actual.sources))
        self.pack.commit(self.pack.delete_characters([('wr',4)])); self.restart()
        self.assert_text(4,'Old catalog','Old author')
        self.assertEqual(self.pack.next_import_slot('wr'),1)
        self.install(4); self.assert_text(4,'Custom')
        self.assertEqual(self.pack.archive_path.read_bytes(),original)

    def test_import_catalog_slot_in_both_modes_and_auto_append(self):
        for mode in (False,True):
            self.pack = self.f.make_pack(self.f.root/f'Mode-{mode}',mode)
            self.catalog(70)
            self.assertEqual(self.pack.next_import_slot('wr'),1)
            self.install(1,patches=not mode)
            self.assertEqual(self.pack.next_import_slot('wr'),2)
            self.install(2,patches=not mode)
            self.install(70,patches=not mode)
            self.restart(); self.assert_text(70,'Custom')
            if mode:self.assertFalse(self.pack.patches_path.exists())

    def test_custom_text_and_distribution_orphans_remain_protected(self):
        self.install(3)
        table=CharacterBMG.read(self.pack.bmg.encode()); table.set_text(author_id(self.cid,4),'Explicit reservation')
        plan=self.pack.update_character_text(); self.pack._stage_name_patches(plan,table); self.pack.commit(plan)
        with self.assertRaisesRegex(ValueError,'reserved text'):
            self.pack.reassign_patch_slots({'wr':{3:4}})
        with self.assertRaisesRegex(ValueError,'text metadata'): self.install(4)
        orphan=self.pack.character/'Map/wr-5.tpl'; orphan.parent.mkdir(exist_ok=True)
        orphan.write_bytes((self.f.source/'wr.tpl').read_bytes()); self.pack.reload()
        with self.assertRaisesRegex(ValueError,'overlap official'):
            self.pack.reassign_patch_slots({'wr':{3:5}})
        self.assertEqual(self.pack.next_import_slot('wr'),6)

    def test_developer_move_carries_catalog_and_preserves_patch_text(self):
        self.catalog(4); self.install(3,patches=False)
        self.install(10,'Patch',patches=True)
        self.pack.commit(self.pack.reassign_developer_slots({'wr':{3:4}})); self.restart()
        self.assert_text(4,'Custom'); self.assert_text(3,'Old catalog','Old author'); self.assert_text(10,'Patch')
        self.pack.commit(self.pack.reassign_developer_slots({'wr':{4:3}})); self.restart()
        self.assert_text(3,'Custom'); self.assert_text(4,'Old catalog','Old author')

    def test_collision_warning_bump_save_both_modes(self):
        for developer in (False,True):
            self.pack=self.f.make_pack(self.f.root/f'Collision-{developer}',developer)
            self.catalog(4)
            self.install(3,'First'); self.install(5,'Second')
            (self.pack.character/'Driver/wr-3.brres').write_bytes(b'new RR skin')
            self.pack.reload(); before=self.pack.archive_path.read_bytes()
            w=self.window()
            with patch('wcm.gui.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
                w.show_patch_collision('wr',3)
            self.assertEqual(w.pending_slot_map(),{'wr':{3:4,5:6}})
            self.assertTrue(w.slot_save_button.isEnabled())
            self.save(w); self.assertFalse(w.staging_patches)
            self.restart(); self.assert_text(4,'First'); self.assert_text(6,'Second')
            self.assertEqual(self.pack.archive_path.read_bytes(),before)
            self.assertEqual((self.pack.character/'Driver/wr-3.brres').read_bytes(),b'new RR skin')

    def test_custom_index_swap_does_not_drop_destination_mapping(self):
        self.install(3,'First'); self.install(4,'Second')
        for slot in (3,4):
            self.pack.commit(self.pack.rename_resources('wr',slot,{f'Driver/wr-{slot}.brres':f'custom-{slot}.test'}))
        self.pack.commit(self.pack.reassign_patch_slots({'wr':{3:4,4:3}})); self.restart()
        self.assertEqual(self.pack.asset_path('Driver/wr-4.brres').name,'custom-3.test')
        self.assertEqual(self.pack.asset_path('Driver/wr-3.brres').name,'custom-4.test')
        self.assert_text(4,'First'); self.assert_text(3,'Second')

    def test_developer_preview_rejects_changed_model_and_rollback_restores_all(self):
        self.install(3,patches=False)
        path=self.pack.character/'Driver/wr-3.brres'
        plan=self.pack.reassign_developer_slots({'wr':{3:4}})
        path.write_bytes(b'external change')
        with self.assertRaisesRegex(ValueError,'changed since preview'):self.pack.commit(plan)
        self.assertFalse((path.parent/'wr-4.brres').exists()); self.pack.reload()
        before={p:p.read_bytes() for p in self.pack.character.rglob('*') if p.is_file()}
        archive=self.pack.archive_path.read_bytes()
        plan=self.pack.reassign_developer_slots({'wr':{3:4}})
        real_reload=self.pack.reload
        calls=[]
        def fail_once():
            calls.append(1)
            if len(calls)==1:raise RuntimeError('injected validation failure')
            real_reload()
        with patch.object(self.pack,'reload',side_effect=fail_once):
            with self.assertRaisesRegex(RuntimeError,'injected'):self.pack.commit(plan)
        self.assertEqual({p:p.read_bytes() for p in self.pack.character.rglob('*') if p.is_file()},before)
        self.assertEqual(self.pack.archive_path.read_bytes(),archive)

    def test_unrelated_archive_members_and_raw_text_survive_bulk_save(self):
        self.install(3,'First'); self.install(4,'Second')
        for path in self.pack._patch_name_archives():
            files=dict(U8Archive.from_file(path).files); files['layout/keep.bin']=path.name.encode()
            path.write_bytes(U8Archive(files,compressed=True).encode())
        self.pack.reload(); unrelated=self.pack.bmg._lookup(902)
        raw=(unrelated.raw,unrelated.metadata)
        self.pack.commit(self.pack.reassign_patch_slots({'wr':{3:5,4:6}}))
        self.restart(); self.assert_text(5,'First'); self.assert_text(6,'Second')
        for _ in range(2):self.pack.commit(self.pack.update_character_text());self.restart()
        msg=self.pack.bmg._lookup(902); self.assertEqual((msg.raw,msg.metadata),raw)
        for path in self.pack._patch_name_archives():
            self.assertEqual(U8Archive.from_file(path).files['layout/keep.bin'],path.name.encode())

    def test_empty_override_entry_does_not_block_move(self):
        self.install(3)
        table=CharacterBMG.read(self.pack.bmg.encode()); table.set_text(name_id(self.cid,4),'')
        plan=self.pack.update_character_text(); self.pack._stage_name_patches(plan,table); self.pack.commit(plan)
        self.assertNotIn(4,self.pack.text_reservations('wr'))
        self.pack.commit(self.pack.reassign_patch_slots({'wr':{3:4}})); self.restart()
        self.assert_text(4,'Custom')

    def test_mixed_normalize_and_other_section_move_sync_active_text(self):
        self.install(3,patches=False); self.install(10,'Patch')
        self.pack.commit(self.pack.import_skin(self.f.package,'lg',5,insert=False,name='Luigi custom',author='Builder'))
        patch_text={m.id:(m.raw,m.metadata) for m in self.pack.bmg.messages if m.id >> 16 == self.cid}
        plan=self.pack.reassign_developer_slots({'wr':{3:1},'lg':{5:6}},independent_codes={'wr'})
        self.pack.commit(plan); self.restart()
        self.assertEqual(self.pack.base_bmg.get_text(name_id(self.cid,1)),'Custom')
        for path in self.pack._patch_name_archives():
            table=CharacterBMG.read(U8Archive.from_file(path).files['message/CharaName.bmg'])
            self.assertEqual({m.id:(m.raw,m.metadata) for m in table.messages if m.id >> 16 == self.cid},patch_text)
            self.assertEqual(table.get_text(name_id(CODE_IDS['lg'],6)),'Luigi custom')
            self.assertIsNone(table._lookup(name_id(CODE_IDS['lg'],5)))

    def test_unresolved_bump_reports_conflict_and_revert_clears_owner(self):
        self.install(3)
        for slot in (3,4):(self.pack.character/f'Driver/wr-{slot}.brres').write_bytes(b'RR')
        self.pack.reload(); w=self.window()
        with patch('wcm.gui.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):
            w.show_patch_collision('wr',3)
        self.assertTrue(w.slot_save_button.isEnabled())
        with patch('wcm.gui.QMessageBox.warning') as warning, patch('wcm.gui.PreviewDialog.exec') as preview:
            w.save_patch_slot_changes(); warning.assert_called_once(); preview.assert_not_called()
            self.assertIn('WR #4',warning.call_args.args[2])
        w.revert_patch_slot_changes(); self.assertFalse(w.staging_patches); self.assertFalse(w.pending_slot_map())
        self.assertIn(('wr',3),self.pack.inventory.skins)

    def test_developer_collision_cannot_mix_pending_distribution_moves(self):
        self.install(3); self.install(8,patches=False)
        (self.pack.character/'Driver/wr-3.brres').write_bytes(b'RR'); self.pack.reload()
        w=self.window(); w._stage_patch_destination('wr',8,9)
        before=dict(w.pending_patch_slots)
        with patch('wcm.gui.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes), \
             patch('wcm.gui.QMessageBox.warning') as warning:
            w.show_patch_collision('wr',3); warning.assert_called_once()
        self.assertEqual(w.pending_patch_slots,before); self.assertFalse(w.staging_patches)

    def test_actual_rr_catalog_reuse_for_every_base_section(self):
        import zipfile
        from fixture_paths import fixture_path
        assets=fixture_path('RRAssets.zip')
        if not assets.is_file():self.skipTest('RR asset fixture unavailable')
        with zipfile.ZipFile(assets) as archive:
            self.pack.archive_path.write_bytes(archive.read('Assets/ReplacedAssets.szs'))
        self.pack.reload(); original=self.pack.archive_path.read_bytes()
        baseline={m.id:(m.raw,m.metadata) for m in self.pack.base_bmg.messages}
        for code,cid in CODE_IDS.items():
            with self.subTest(base=code):
                slots=sorted(m.id & 0xff for m in self.pack.base_bmg.messages if
                    m.id >> 16 == cid and m.id & 0xff00 == 0x6a00 and
                    1 <= m.id & 0xff <= 100 and self.pack.base_bmg.get_text(m.id).strip())
                self.assertGreaterEqual(len(slots),2)
                src,dst=slots[:2]
                self.assertEqual(self.pack.next_import_slot(code),1)
                self.pack.commit(self.pack.import_patch_skin(self.f.package,code,src,name='Catalog test',author='Maker'))
                self.pack.commit(self.pack.reassign_patch_slots({code:{src:dst}})); self.restart()
                self.assertEqual(self.pack.bmg.get_text(name_id(cid,dst)),'Catalog test')
                self.assertEqual(self.pack.bmg.get_text(author_id(cid,dst)),'Maker')
                self.pack.commit(self.pack.delete_characters([(code,dst)])); self.restart()
                self.assertEqual({m.id:(m.raw,m.metadata) for m in self.pack.bmg.messages},baseline)
                self.assertEqual(self.pack.archive_path.read_bytes(),original)

    def test_noop_normalize_leaves_no_hidden_staging_scope(self):
        self.install(1,patches=False); w=self.window(); w.normalize_slots()
        self.assertFalse(w.pending_slot_map()); self.assertFalse(w.independent_normalize_codes)
        self.assertFalse(w.slot_revert_button.isEnabled())
        w._stage_patch_destination('wr',1,2); w.normalize_slots()
        self.assertFalse(w.pending_slot_map()); self.assertFalse(w.independent_normalize_codes)

    def test_failed_collision_bump_does_not_leave_patch_scope_active(self):
        self.install(100)
        (self.pack.character/'Driver/wr-100.brres').write_bytes(b'RR'); self.pack.reload(); w=self.window()
        with patch('wcm.gui.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes), \
             patch('wcm.gui.QMessageBox.warning') as warning:
            w.show_patch_collision('wr',100); warning.assert_called_once()
        self.assertFalse(w.staging_patches); self.assertFalse(w.pending_slot_map())
