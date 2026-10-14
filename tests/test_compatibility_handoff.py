import unittest,struct,json,io,tempfile
from pathlib import Path
from unittest.mock import patch
from wcm.library import parse_asset,race_coverage,missing_race_requests
from wcm.native_validation import validate_brres,validate_asset
from wcm.updates import latest,repository,version,platform_key
from native_fixtures import valid_brres,valid_szs

class Compatibility(unittest.TestCase):
    def test_mode_slot_boundaries(self):
        for name,new in [('mdf_kart_red-ca-4_2.szs','mdf_kart_red-ca-9_2.szs'),('ma_bike-ca_2.szs','ma_bike-ca-9_2.szs')]:
            a=parse_asset(name,source_import=True);self.assertEqual(a.filename_for(9),new)
        assets=[parse_asset(f'm{i}_kart-ca{mode}.szs',source_import=True) for i in range(6) for mode in ('','_2')]
        self.assertEqual(len(race_coverage(assets)['normal']),6)
        self.assertEqual(len(race_coverage(assets)['2']),6)
        self.assertEqual(len(missing_race_requests('ca',{})['normal']),12)
    def test_resource_bounds_fail_closed_and_valid_bytes_unchanged(self):
        data=valid_brres();self.assertEqual(validate_brres(data,require_model=True),['driver']);self.assertEqual(data,valid_brres())
        with self.assertRaises(ValueError):validate_brres(data[:-3])
        with self.assertRaises(ValueError):validate_asset(b'Yaz0'+bytes(30),'RaceKart','broken.szs')
        # A real MDL0 texture-link dictionary whose link points outside its model.
        d=bytearray(data);d.extend(bytes(240));struct.pack_into('>I',d,8,len(d));struct.pack_into('>I',d,132,len(d)-128)
        dictionary=320;table=360
        struct.pack_into('>i',d,128+0x3c,dictionary-128);struct.pack_into('>II',d,dictionary,40,1)
        struct.pack_into('>ii',d,dictionary+32,110-dictionary,table-dictionary);d[110:114]=b'tex\0'
        struct.pack_into('>Iii',d,table,1,0x70000000,0x70000000)
        self.assertEqual(validate_brres(bytes(d)),['driver'])
    def test_release_version_download_and_configuration(self):
        self.assertEqual(version('v1.0'),version('1.0.0'))
        self.assertGreater(version('v1.1'),version('1.0.9'))
        self.assertGreater(version('v1.10.0'),version('1.9.9'))
        for url in ('http://github.com/a/b','https://evil.test/a/b','https://github.com/a/b?x=1'):
            with self.assertRaises(ValueError):repository(url)
        data={'tag_name':'v3.0.0','html_url':'https://github.com/a/b/releases/tag/v3.0.0','assets':[{'state':'uploaded','name':'manager-'+platform_key()+'.zip','browser_download_url':'https://github.com/a/b/releases/download/v3.0.0/manager-'+platform_key()+'.zip'}]}
        def opener(request,timeout):self.assertEqual(timeout,8);return io.BytesIO(json.dumps(data).encode())
        self.assertTrue(latest('https://github.com/a/b','1.0',opener)['download'].endswith('manager-'+platform_key()+'.zip'))
        self.assertIsNone(latest('https://github.com/a/b','3.0.0',opener));self.assertIsNone(latest('','1.0',opener))
        data['prerelease']=True;self.assertIsNone(latest('https://github.com/a/b','1.0',opener))

    def test_wiiloaded_developer_stages_pair_without_base_sources(self):
        from test_race_name_sync import RaceNameSync
        from wcm.operations import CharacterPack
        from wcm.szs import U8Archive
        from wcm.bmg import CharacterBMG,name_id
        fixture=RaceNameSync();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.race.unlink()
        pack=CharacterPack(fixture.char,fixture.archive,fixture.root/'Patches',developer_mode=True,deployment_profile='wiiloaded')
        plan=pack.edit_text('mr',1,'Same name','Creator');pack.commit(plan)
        report=pack.compatibility_report();self.assertEqual(report['deployment_profile'],'wiiloaded');self.assertEqual(report['characters'][0]['name'],'Same name')
        for path in pack._patch_name_archives():
            archive=U8Archive.from_file(path)
            for member in ('message/CharaName.bmg','message/CharaRR.bmg'):
                self.assertEqual(CharacterBMG.read(archive.files[member]).get_text(name_id(0,1)),'Same name')

    def test_matching_and_conflicting_aliases_preserve_other_text(self):
        from test_race_name_sync import bmg_bytes
        from wcm.textmerge import merged_archive,MEMBER,RACE_MEMBER
        from wcm.bmg import CharacterBMG,name_id
        from wcm.szs import U8Archive
        old=bmg_bytes({name_id(0,1):'Old',77:'Keep'})
        new=bmg_bytes({name_id(0,1):'New'})
        raw=merged_archive({RACE_MEMBER:old,'untouched':b'payload'},[],new)
        archive=U8Archive.read(raw)
        self.assertEqual(archive.files['untouched'],b'payload')
        alias=CharacterBMG.read(archive.files[RACE_MEMBER]);self.assertEqual(alias.get_text(77),'Keep');self.assertEqual(alias.get_text(name_id(0,1)),'New')

    def test_legacy_alias_import_and_conflict_warning(self):
        from test_race_name_sync import bmg_bytes
        from wcm.textmerge import find_sources,MEMBER,RACE_MEMBER
        from wcm.bmg import name_id
        from wcm.szs import U8Archive
        with tempfile.TemporaryDirectory() as root:
            p=Path(root);ui=p/'CharacterNames.uiassets.szs';race=p/'CharacterNames.raceassets.szs'
            ui.write_bytes(U8Archive({RACE_MEMBER:bmg_bytes({name_id(0,1):'Legacy'})}).encode())
            table,conflicts,_=find_sources(p,bmg_bytes({}),p/'absent',(ui,race))
            self.assertEqual(table.get_text(name_id(0,1)),'Legacy')
            ui.write_bytes(U8Archive({MEMBER:bmg_bytes({name_id(0,1):'Canonical'}),RACE_MEMBER:bmg_bytes({name_id(0,1):'Stale'})}).encode())
            table,conflicts,_=find_sources(p,bmg_bytes({}),p/'absent',(ui,race))
            self.assertEqual(table.get_text(name_id(0,1)),'Canonical');self.assertTrue(any('disagrees' in c for c in conflicts))

class DragRows(unittest.TestCase):
    def test_logical_drop_retains_source_and_target_until_refresh(self):
        from PySide6.QtWidgets import QApplication,QTableWidgetItem
        from PySide6.QtCore import Qt,QPointF,QMimeData
        from wcm.gui import PatchSlotTable
        app=QApplication.instance() or QApplication([])
        table=PatchSlotTable(2,1);table.resize(300,150);table.show();app.processEvents()
        for row in range(2):
            item=QTableWidgetItem(str(row));item.setData(Qt.ItemDataRole.UserRole,row+1);table.setItem(row,0,item)
        called=[];table.slotDropped.connect(lambda a,b:called.append((a,b)));table._drag_slot=1
        class Event:
            action=None
            def source(self):return table
            def position(self):return QPointF(5,table.rowViewportPosition(1)+5)
            def setDropAction(self,action):self.action=action
            def accept(self):pass
            def ignore(self):raise AssertionError('unexpected rejection')
        event=Event();table.dropEvent(event);self.assertEqual(event.action,Qt.DropAction.CopyAction)
        app.processEvents();self.assertEqual(called,[(1,2)]);self.assertEqual(table.rowCount(),2);self.assertIsNotNone(table.item(0,0));table.close()

    def test_drag_has_row_preview_without_removing_items(self):
        from PySide6.QtWidgets import QApplication,QTableWidgetItem
        from PySide6.QtCore import Qt
        from wcm.gui import PatchSlotTable
        app=QApplication.instance() or QApplication([])
        table=PatchSlotTable(1,1);table.resize(320,150);table.show();app.processEvents()
        item=QTableWidgetItem('Character slot');item.setData(Qt.ItemDataRole.UserRole,3)
        item.setData(Qt.ItemDataRole.UserRole+1,'patch');table.setItem(0,0,item);table.selectRow(0)
        preview={}
        class Drag:
            def __init__(self,parent):pass
            def setMimeData(self,data):preview['mime']=data
            def setPixmap(self,pixmap):preview['pixmap']=pixmap
            def setHotSpot(self,point):preview['hotspot']=point
            def exec(self,actions):preview['actions']=actions
        with patch('wcm.gui.QDrag',Drag):table.startDrag(Qt.DropAction.MoveAction)
        self.assertFalse(preview['pixmap'].isNull())
        self.assertTrue(preview['mime'].hasFormat('application/x-rrcm-slot'))
        self.assertEqual(preview['actions'],Qt.DropAction.CopyAction)
        self.assertIs(table.item(0,0),item);self.assertIsNone(table._drag_slot);table.close()
