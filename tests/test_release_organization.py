"""Distribution UI/Race text and unified staged organization regressions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import shutil, zipfile, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QDialog
from wcm.operations import CharacterPack
from wcm.szs import U8Archive
from wcm.bmg import CharacterBMG,name_id,author_id
from wcm.library import CODE_IDS
from wcm.gui import MainWindow
from test_text_reliability import bmg_bytes
from fixture_paths import fixture_path

class ReleaseOrganization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.char=self.root/'Character';(self.char/'Driver').mkdir(parents=True)
        self.assets=self.root/'Assets';self.assets.mkdir();self.archive=self.assets/'ReplacedAssets.szs'
        self.cid=CODE_IDS['fk']
        self.write_archive(self.archive,'message/CharaRR.bmg',{name_id(self.cid,3):'Correct first',author_id(self.cid,3):'Author one',name_id(self.cid,5):'Correct second',author_id(self.cid,5):'Author two',42:'Unrelated'})
        for slot in (3,5):(self.char/'Driver'/f'fk-{slot}.brres').write_bytes(f'model-{slot}'.encode())
        for filename,member in [('UIAssets.szs','message/CharaName.bmg'),('RaceAssets.szs','message/CharaRR.bmg')]:
            self.write_archive(self.assets/filename,member,{name_id(self.cid,3):'Stale name',author_id(self.cid,3):'Stale author',77:'Race-only text'})
        self.pack=CharacterPack(self.char,self.archive,self.root/'Patches',developer_mode=True)
    def write_archive(self,path,member,entries):
        path.write_bytes(U8Archive({member:bmg_bytes(entries),'layout/keep.bin':b'layout'}).encode())
    def assert_pair(self,slot,name,author):
        for path in (self.archive,self.assets/'UIAssets.szs',self.assets/'RaceAssets.szs'):
            arc=U8Archive.from_file(path)
            member=next(m for m in arc.files if m.endswith('.bmg'));b=CharacterBMG.read(arc.files[member])
            self.assertEqual(b.get_text(name_id(self.cid,slot)),name,path.name)
            self.assertEqual(b.get_text(author_id(self.cid,slot)),author,path.name)
            self.assertEqual(arc.files['layout/keep.bin'],b'layout')
            self.assertEqual([m.id for m in b.messages],sorted(m.id for m in b.messages))
            self.assertEqual(b.get_text(42 if path==self.archive else 77),'Unrelated' if path==self.archive else 'Race-only text')
    def test_name_edit_updates_every_existing_table_and_preserves_members(self):
        self.pack.commit(self.pack.edit_text('fk',3,'New name','New author'));self.assert_pair(3,'New name','New author')
        self.assertFalse(self.pack.patches_path.exists())
    def test_organize_preserves_order_and_names_after_reorder(self):
        self.pack.commit(self.pack.organize_characters({'fk':{3:2,5:1}},independent_codes={'fk'}))
        self.assert_pair(2,'Correct first','Author one');self.assert_pair(1,'Correct second','Author two')
        self.assertEqual((self.char/'Driver/fk-2.brres').read_bytes(),b'model-3')
        self.assertEqual((self.char/'Driver/fk-1.brres').read_bytes(),b'model-5')
        reopened=CharacterPack(self.char,self.archive,self.root/'Patches',developer_mode=True)
        self.assertFalse(reopened.organize_characters().writes)
    def test_staging_revert_cancel_and_text_only_save(self):
        window=MainWindow(self.pack);self.addCleanup(window.deleteLater);window.change_base('fk')
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        window.organize_characters();self.assertEqual(window.pending_slot_map(),{'fk':{3:1,5:2}})
        self.assertTrue(window.slot_save_button.isEnabled());self.assertTrue(window.slot_revert_button.isEnabled())
        window.revert_patch_slot_changes();self.assertFalse(window.has_staged_changes())
        window.organize_characters()
        with patch('wcm.gui.PreviewDialog.exec',return_value=QDialog.DialogCode.Rejected):window.save_patch_slot_changes()
        self.assertEqual(before,{p:p.read_bytes() for p in before});self.assertTrue(window.pending_organization)
        with patch('wcm.gui.PreviewDialog.exec',return_value=QDialog.DialogCode.Accepted),patch('wcm.gui.QMessageBox.information'):
            window.save_patch_slot_changes()
        self.assert_pair(1,'Correct first','Author one');self.assertFalse(window.has_staged_changes())
        window.organize_characters();self.assertFalse(window.pending_slot_map());self.assertTrue(window.slot_save_button.isEnabled())
        window.revert_patch_slot_changes();window.close()
    def test_race_changes_since_preview_abort_and_transaction_rolls_back(self):
        race=self.assets/'RaceAssets.szs';plan=self.pack.edit_text('fk',3,'Edited','Maker');old=race.read_bytes();race.write_bytes(old+b'changed')
        with self.assertRaisesRegex(ValueError,'changed since preview'):self.pack.commit(plan)
        race.write_bytes(old);self.pack.reload();plan=self.pack.organize_characters({'fk':{3:1,5:2}},independent_codes={'fk'})
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        import wcm.operations as operations
        original=operations.os.replace;calls=0
        def fail(a,b):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('disk failure')
            return original(a,b)
        with patch('wcm.operations.os.replace',side_effect=fail):
            with self.assertRaises(OSError):self.pack.commit(plan)
        self.assertEqual(before,{p:p.read_bytes() for p in before})
    def test_patch_mode_organizes_flat_overlap_without_touching_distribution(self):
        self.pack.patches_path.mkdir();(self.pack.patches_path/'fk-3.brres').write_bytes(b'custom patch')
        self.pack=CharacterPack(self.char,self.archive,self.pack.patches_path)
        window=MainWindow(self.pack);self.addCleanup(window.deleteLater);window.change_base('fk');window.organize_characters()
        mapping=window.pending_slot_map();self.assertEqual(mapping,{'fk':{3:4}})
        before={p:p.read_bytes() for p in self.assets.iterdir()};plan=self.pack.organize_characters(mapping)
        self.pack.commit(plan);self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertEqual(self.pack.asset_path('Driver/fk-4.brres').read_bytes(),b'custom patch')
        self.assertEqual(self.pack.patch_metadata['fk',4]['slot'],4)
        self.assertFalse((self.pack.patches_path/'fk-3.brres').exists());window.revert_patch_slot_changes();window.close()
    def test_duplicate_legacy_names_get_independent_owned_folders(self):
        self.pack.patches_path.mkdir()
        for slot in (8,9):(self.pack.patches_path/f'fk-{slot}.brres').write_bytes(f'patch-{slot}'.encode())
        table=CharacterBMG.read(self.pack.base_bmg.encode())
        for slot in (8,9):table.set_text(name_id(self.cid,slot),'Duplicate')
        legacy=self.pack.patch_bmg_path;legacy.write_bytes(table.encode())
        self.pack=CharacterPack(self.char,self.archive,self.pack.patches_path)
        self.pack.commit(self.pack.organize_characters())
        self.assertEqual(len(set(self.pack.patch_directories.values())),2)
        for slot in (8,9):self.assertEqual(self.pack.asset_path(f'Driver/fk-{slot}.brres').read_bytes(),f'patch-{slot}'.encode())
    def test_deletion_and_slot_reuse_remove_stale_race_ids(self):
        self.pack.commit(self.pack.organize_characters())
        self.pack.commit(self.pack.delete_characters([('fk',3)]))
        for path in (self.archive,self.assets/'UIAssets.szs',self.assets/'RaceAssets.szs'):
            files=U8Archive.from_file(path).files;table=CharacterBMG.read(next(v for k,v in files.items() if k.endswith('.bmg')))
            self.assertIsNone(table._lookup(name_id(self.cid,3)));self.assertIsNone(table._lookup(author_id(self.cid,3)))
        self.pack.commit(self.pack.reassign_developer_slots({'fk':{5:3}}));self.assert_pair(3,'Correct second','Author two')
    def test_single_organization_button_no_deployment_or_baseline_text(self):
        window=MainWindow(self.pack);self.addCleanup(window.deleteLater)
        labels=[a.text() for menu in window.menuBar().actions() for a in menu.menu().actions()]
        self.assertFalse(any('Flat Deployment' in x or 'Organize Character Names' in x or 'Organize Existing Patches' in x or 'Update Character Text' in x for x in labels))
        menus={menu.text().replace('&',''):[a.text() for a in menu.menu().actions()] for menu in window.menuBar().actions()}
        self.assertIn('Set revo_kart.brsar…',menus['File'])
        self.assertFalse(any(label in menus['Characters'] for label in ('Save Name / Author','Replace CSS Portrait…','Replace Minimap Icon…','Edit Sounds…','Set Vanilla Voice Archive…','Set revo_kart.brsar…')))
        self.assertEqual(window.organize_button.text(),'Organize Characters');window.close()

REAL_ROOT=Path(r'C:/Users/kafia/Downloads/PulsarModdings/Release/WiiLoaded/WiiLoaded/MK WiiLoaded')
@unittest.skipUnless((REAL_ROOT/'Assets/RaceAssets.szs').is_file() and fixture_path('Character.zip').is_file(),'Optional real WiiLoaded/RR assets unavailable')
class ActualRaceNames(unittest.TestCase):
    def test_actual_chain_chomp_identity_race_sync_and_other_resources_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);char=root/'Character';(char/'Driver').mkdir(parents=True);assets=root/'Assets';assets.mkdir()
            with zipfile.ZipFile(fixture_path('Character.zip')) as z:
                for source in (REAL_ROOT/'Character/Driver').glob('fk-*.brres'):
                    payload=source.read_bytes();(char/'Driver'/source.name).write_bytes(payload)
                    if source.name=='fk-1.brres':self.assertEqual(payload,z.read('Character/Driver/fk-2.brres'))
            for filename in ('ReplacedAssets.szs','UIAssets.szs','RaceAssets.szs'):shutil.copy2(REAL_ROOT/'Assets'/filename,assets/filename)
            before={p:U8Archive.from_file(p).files.copy() for p in assets.iterdir()}
            pack=CharacterPack(char,assets/'ReplacedAssets.szs',root/'Patches',developer_mode=True)
            self.assertEqual(pack.distribution_inventory.skins['fk',1].name,'Chain Chomp')
            pack.commit(pack.organize_characters())
            for p,files in before.items():
                after=U8Archive.from_file(p).files
                for member,raw in files.items():
                    if member not in ('message/CharaRR.bmg','message/CharaName.bmg'):self.assertEqual(after[member],raw)
                if 'message/CharaRR.bmg' in after:
                    table=CharacterBMG.read(after['message/CharaRR.bmg'])
                    self.assertEqual(table.get_text(name_id(CODE_IDS['fk'],1)),'Chain Chomp')
                    self.assertEqual(table.get_text(author_id(CODE_IDS['fk'],1)),'UltraWario')
            self.assertFalse((root/'Patches').exists())
