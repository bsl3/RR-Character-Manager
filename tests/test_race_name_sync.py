from native_fixtures import valid_brres,valid_szs
"""Menu-owned IDs published to both native name members, without slot shifts."""
import os,unittest,tempfile,shutil
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
from wcm.operations import CharacterPack,EditPlan
from wcm.szs import U8Archive
from wcm.bmg import CharacterBMG,name_id,author_id
from wcm.library import CODE_IDS
from wcm.mkchara import build_package,write_package
from test_text_reliability import bmg_bytes

class RaceNameSync(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.cid=CODE_IDS['mr']
        self.char=self.root/'Character';(self.char/'Driver').mkdir(parents=True);(self.char/'Driver/mr-1.brres').write_bytes(valid_brres(b'bres model'));(self.char/'Driver/mr.brres').write_bytes(valid_brres(b'bres vanilla'))
        self.assets=self.root/'Assets';self.assets.mkdir();self.archive=self.assets/'ReplacedAssets.szs'
        self.archive.write_bytes(U8Archive({'message/CharaRR.bmg':bmg_bytes({name_id(self.cid,1):'Menu Mario',author_id(self.cid,1):'Author',name_id(self.cid,0):'Mario',42:'Menu-only'}),'keep':b'original'}).encode())
        self.race=self.assets/'RaceAssets.szs';self.race.write_bytes(U8Archive({'message/CharaRR.bmg':bmg_bytes({name_id(self.cid,1):'Wrong race name',77:'Race-only'}),'keep':b'race resource'}).encode())
        self.pack=CharacterPack(self.char,self.archive,self.root/'Patches',developer_mode=True)
    def assert_names(self,pack,slot,text,patch=False):
        paths=pack._patch_name_archives() if patch else (pack.archive_path,pack.archive_path.parent/'RaceAssets.szs')
        for path in paths:
            tables={k:CharacterBMG.read(raw) for k,raw in U8Archive.from_file(path).files.items() if k in ('message/CharaName.bmg','message/CharaRR.bmg')}
            self.assertIn('message/CharaRR.bmg',tables)
            if patch:self.assertIn('message/CharaName.bmg',tables)
            for b in tables.values():self.assertEqual(b.get_text(name_id(self.cid,slot)),text);self.assertTrue(b.order_sorted)
    def test_developer_rename_and_vanilla_name_use_native_ids(self):
        self.pack.commit(self.pack.edit_text('mr',1,'Custom Mario','Author'));self.assert_names(self.pack,1,'Custom Mario')
        self.pack.commit(self.pack.edit_text('mr',0,'Vanilla renamed','Author'));self.assertEqual(name_id(0,0),9000);self.assert_names(self.pack,0,'Vanilla renamed')
        self.assertEqual(CharacterBMG.read(U8Archive.from_file(self.race).files['message/CharaRR.bmg']).get_text(77),'Race-only')
        self.pack.reload();self.assertEqual(self.pack.bmg.get_text(name_id(0,0)),'Vanilla renamed')
    def test_patch_repair_uses_menu_source_and_keeps_distribution_untouched(self):
        before={p:p.read_bytes() for p in self.assets.iterdir()};self.pack=CharacterPack(self.char,self.archive,self.root/'Patches')
        self.pack.commit(self.pack.update_character_text());self.assert_names(self.pack,1,'Menu Mario',patch=True);self.assertEqual(before,{p:p.read_bytes() for p in before})
        race=U8Archive.from_file(self.pack._patch_name_archives()[1]);self.assertEqual(CharacterBMG.read(race.files['message/CharaRR.bmg']).get_text(77),'Race-only')
        self.pack.reload();self.assertEqual(self.pack.inventory.skins['mr',1].name,'Menu Mario')
        self.assertFalse(self.pack.update_character_text().writes)
    def test_resource_update_automatically_repairs_text_without_reverting_resource(self):
        bundle=U8Archive.from_file(self.race);bundle.replace('keep',b'new race decoration')
        plan=EditPlan('Update resource',writes={self.race:bundle.encode()},replace_existing={self.race},expected=dict(self.pack._snapshot))
        self.pack.prepare_name_sync(plan);self.assertIn('Automatically repair',plan.preview());self.pack.commit(plan)
        self.assert_names(self.pack,1,'Menu Mario');self.assertEqual(U8Archive.from_file(self.race).files['keep'],b'new race decoration')
    def test_loose_race_rr_cannot_shadow_menu_name_and_keeps_private_text(self):
        self.pack.patches_path.mkdir();path=self.pack.patches_path/'[message]CharaRR.bmg.raceassets'
        path.write_bytes(bmg_bytes({name_id(self.cid,1):'Stale race',77:'Loose race text'}))
        self.pack.reload();self.assertEqual(self.pack.bmg.get_text(name_id(self.cid,1)),'Menu Mario')
        self.pack.commit(self.pack.update_character_text());table=CharacterBMG.read(path.read_bytes());self.assertEqual(table.get_text(name_id(self.cid,1)),'Menu Mario');self.assertEqual(table.get_text(77),'Loose race text')
    def test_vanilla_gui_rename_uses_one_transaction_for_both_names(self):
        from PySide6.QtWidgets import QApplication
        from wcm.gui import MainWindow
        from unittest.mock import patch
        app=QApplication.instance() or QApplication([]);window=MainWindow(self.pack);self.addCleanup(window.deleteLater);window.current_code='mr'
        with patch('wcm.gui.QInputDialog.getText',return_value=('Custom Mario',True)),patch.object(window,'run_plan') as review:
            window.rename_vanilla_character()
        self.pack.commit(review.call_args.args[0]);self.assert_names(self.pack,0,'Custom Mario')
    def test_missing_race_text_member_is_installed_on_resource_update(self):
        self.race.write_bytes(U8Archive({'keep':b'race resource'}).encode());self.pack.reload()
        target=self.char/'Driver/mr-1.brres';plan=EditPlan('Update model',writes={target:valid_brres(b'bres updated')},replace_existing={target},expected=dict(self.pack._snapshot))
        self.pack.commit(plan);self.assert_names(self.pack,1,'Menu Mario');self.assertEqual(U8Archive.from_file(self.race).files['keep'],b'race resource')
    def test_mkchara_import_rename_move_delete_reuse_both_modes(self):
        self.pack.commit(self.pack.edit_text('mr',1,'Portable Mario','Author'));package=self.root/'Mario.mkchara';write_package(package,build_package(self.pack,'mr',1))
        for developer in (False,True):
            with self.subTest(developer=developer):
                root=self.root/str(developer);char=root/'Character';(char/'Driver').mkdir(parents=True);assets=root/'Assets';assets.mkdir();archive=assets/'ReplacedAssets.szs';archive.write_bytes(U8Archive({'message/CharaRR.bmg':bmg_bytes({42:'Keep'})}).encode());(assets/'RaceAssets.szs').write_bytes(self.race.read_bytes())
                pack=CharacterPack(char,archive,root/'Patches',developer_mode=developer)
                plan=pack.import_skin(package,'mr',4,insert=False,name='Portable Mario',author='Author') if developer else pack.import_patch_skin(package,'mr',4,name='Portable Mario',author='Author')
                pack.commit(plan);self.assert_names(pack,4,'Portable Mario',patch=not developer);pack.commit(pack.edit_text('mr',4,'Renamed Mario','Author'));self.assert_names(pack,4,'Renamed Mario',patch=not developer)
                write_package(root/'Reexport.mkchara',build_package(pack,'mr',4))
                pack.commit(pack.reassign_developer_slots({'mr':{4:5}}) if developer else pack.reassign_patch_slots({'mr':{4:5}}));self.assert_names(pack,5,'Renamed Mario',patch=not developer)
                pack.commit(pack.delete_characters([('mr',5)]))
                for path in ((archive,assets/'RaceAssets.szs') if developer else pack._patch_name_archives()):
                    for member,raw in U8Archive.from_file(path).files.items():
                        if member in ('message/CharaRR.bmg','message/CharaName.bmg'):self.assertIsNone(CharacterBMG.read(raw)._lookup(name_id(self.cid,5)))
                plan=pack.import_skin(root/'Reexport.mkchara','mr',4,insert=False,name='Renamed Mario',author='Author') if developer else pack.import_patch_skin(root/'Reexport.mkchara','mr',4,name='Renamed Mario',author='Author')
                pack.commit(plan);self.assert_names(pack,4,'Renamed Mario',patch=not developer)

REAL=Path('C:/Users/kafia/Downloads/PulsarModdings/Release/WiiLoaded/WiiLoaded/MK WiiLoaded')
@unittest.skipUnless((REAL/'Assets/RaceAssets.szs').is_file(),'Actual assets unavailable')
class ActualRaceNames(unittest.TestCase):
    def test_chain_chomp_canonical_id_and_isolated_race_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);char=root/'Character';(char/'Driver').mkdir(parents=True);assets=root/'Assets';assets.mkdir()
            for name in ('ReplacedAssets.szs','RaceAssets.szs','UIAssets.szs'):shutil.copy2(REAL/'Assets'/name,assets/name)
            shutil.copy2(REAL/'Character/Driver/fk-1.brres',char/'Driver/fk-1.brres')
            cid=CODE_IDS['fk']
            stale=U8Archive.from_file(assets/'RaceAssets.szs');table=CharacterBMG.read(stale.files['message/CharaRR.bmg']);table.set_text(name_id(cid,1),'Zapple Kong');stale.replace('message/CharaRR.bmg',table.encode());(assets/'RaceAssets.szs').write_bytes(stale.encode())
            before={p:p.read_bytes() for p in assets.iterdir()};pack=CharacterPack(char,assets/'ReplacedAssets.szs',root/'Patches')
            self.assertEqual(pack.inventory.skins['fk',1].name,'Chain Chomp');self.assertEqual(CharacterBMG.read(U8Archive.from_file(assets/'RaceAssets.szs').files['message/CharaRR.bmg']).get_text(name_id(cid,1)),'Zapple Kong')
            pack.commit(pack.update_character_text())
            for path in pack._patch_name_archives():
                for member in ('message/CharaName.bmg','message/CharaRR.bmg'):
                    self.assertEqual(CharacterBMG.read(U8Archive.from_file(path).files[member]).get_text(name_id(cid,1)),'Chain Chomp')
            self.assertEqual(before,{p:p.read_bytes() for p in before});pack.reload();self.assertEqual(pack.inventory.skins['fk',1].name,'Chain Chomp')
    def test_actual_developer_names_and_nontext_members_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);char=root/'Character';(char/'Driver').mkdir(parents=True);assets=root/'Assets';assets.mkdir()
            for name in ('ReplacedAssets.szs','RaceAssets.szs','UIAssets.szs'):shutil.copy2(REAL/'Assets'/name,assets/name)
            shutil.copy2(REAL/'Character/Driver/fk-1.brres',char/'Driver/fk-1.brres');before={p:dict(U8Archive.from_file(p).files) for p in assets.iterdir()}
            pack=CharacterPack(char,assets/'ReplacedAssets.szs',root/'Patches',developer_mode=True);pack.commit(pack.synchronize_character_names())
            for path,files in before.items():
                after=U8Archive.from_file(path).files
                for member,raw in files.items():
                    if member not in ('message/CharaRR.bmg','message/CharaName.bmg'):self.assertEqual(after[member],raw)
                table=CharacterBMG.read(after['message/CharaRR.bmg']);self.assertEqual(table.get_text(name_id(CODE_IDS['fk'],1)),'Chain Chomp');self.assertTrue(table.order_sorted)
            self.assertFalse((root/'Patches').exists());pack.reload();self.assertFalse(pack.synchronize_character_names().writes)
