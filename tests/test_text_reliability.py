from native_fixtures import valid_brres,valid_szs
"""Asset-free regression cases, runnable on Windows and CI without game fixtures."""
import json
import struct
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from collections import OrderedDict
from wcm.bmg import CharacterBMG, name_id, author_id, align32
from wcm.szs import U8Archive
from wcm.operations import CharacterPack, EditPlan


def bmg_bytes(entries,opaque=None):
    inf=bytearray(16);inf[:4]=b'INF1';struct.pack_into('>HH',inf,8,len(entries),8)
    dat=bytearray(b'DAT1'+bytes(4)+b'\0\0')
    mid=bytearray(16);mid[:4]=b'MID1';struct.pack_into('>H',mid,8,len(entries))
    for id_,value in entries.items():
        raw,meta=value if isinstance(value,tuple) else ((value+'\0').encode('utf-16-be'),b'\x01\x02\x03\x04')
        inf+=struct.pack('>I',len(dat)-8)+meta;dat+=raw;mid+=struct.pack('>I',id_)
    chunks=[align32(x) for x in (inf,dat,mid)]
    if opaque: chunks.append(align32(b'USR1'+bytes(4)+opaque))
    for i,c in enumerate(chunks):
        c=bytearray(c);struct.pack_into('>I',c,4,len(c));chunks[i]=c
    h=bytearray(32);h[:8]=b'MESGbmg1';h[16]=2
    struct.pack_into('>II',h,8,32+sum(map(len,chunks)),len(chunks))
    return bytes(h)+b''.join(chunks)


def archive_bytes(entries,members=None):
    return U8Archive(OrderedDict({'message/CharaName.bmg':bmg_bytes(entries),**(members or {})})).encode()


class TextReliability(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'Pack';self.characters=self.root/'Character'
        (self.characters/'Driver').mkdir(parents=True)
        (self.characters/'Driver/wr-1.brres').write_bytes(b'official')
        self.archive=self.root/'Assets/ReplacedAssets.szs';self.archive.parent.mkdir()
        self.archive.write_bytes(U8Archive(OrderedDict({'message/CharaRR.bmg':bmg_bytes({name_id(11,1):'Official',902:'Other text'}),
                                                      'layout/untouched.bin':b'private layout'})).encode())
        self.original=self.archive.read_bytes();self.patches=self.root/'Patches'
        self.pack=CharacterPack(self.characters,self.archive,self.patches)
        self.source=Path(self.temp.name)/'Source';self.source.mkdir()
        (self.source/'wr.brres').write_bytes(valid_brres(b'bres'+bytes(32)))

    def install(self,slot,name='Custom',author='Author'):
        self.pack.commit(self.pack.import_patch_skin(self.source,'wr',slot,name=name,author=author))

    def put_archive(self,relative,entries,members=None):
        p=self.patches/relative;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes(archive_bytes(entries,members));return p

    def pair(self):
        ui,race=self.pack._patch_name_archives()
        a,b=U8Archive.from_file(ui),U8Archive.from_file(race)
        self.assertEqual(a.files['message/CharaName.bmg'],b.files['message/CharaName.bmg'])
        return CharacterBMG.read(a.files['message/CharaName.bmg'])

    def test_sequential_import_rename_reopen_and_move(self):
        self.install(7,'First');self.install(8,'Second')
        self.pack.commit(self.pack.edit_text('wr',7,'Renamed','New credit'))
        self.pack=CharacterPack(self.characters,self.archive,self.patches)
        self.assertEqual(self.pack.inventory.skins['wr',7].name,'Renamed')
        self.pack.commit(self.pack.reassign_patch_slots({'wr':{7:9}}))
        table=self.pair()
        self.assertEqual(table.get_text(name_id(11,9)),'Renamed')
        self.assertEqual(table.get_text(author_id(11,9)),'New credit')
        self.assertEqual(table.get_text(name_id(11,8)),'Second')
        self.assertIsNone(table._lookup(name_id(11,7)))
        self.assertEqual(self.archive.read_bytes(),self.original)

    def test_divergent_incomplete_pairs_legacy_and_third_party_union(self):
        ui=self.put_archive('CharacterNames/CharacterNames.uiassets.szs',{42:'UI',50:'Only UI'},{'layout/a':b'A'})
        race=self.put_archive('CharacterNames/CharacterNames.raceassets.szs',{42:'Race',51:'Only Race'},{'layout/b':b'B'})
        root=self.put_archive('CharacterNames.uiassets.szs',{52:'Legacy'},{'layout/c':b'C'})
        other=self.put_archive('UserText.raceassets.szs',{53:'Private text'},{'message/Other.bmg':b'opaque'})
        self.pack.reload();plan=self.pack.update_character_text()
        self.assertIn('Text conflict resolved: 0x0000002a',plan.preview())
        self.assertIn("'Race'",plan.preview());self.assertIn("'UI'",plan.preview())
        before={p:p.read_bytes() for p in (ui,race,root,other)}
        self.assertEqual(before,{p:p.read_bytes() for p in before},'plan generation changed files')
        backup=self.pack.commit(plan);self.assertTrue((backup/'manifest.json').is_file())
        table=self.pair()
        for id_,text in {42:'UI',50:'Only UI',51:'Only Race',52:'Legacy',53:'Private text',902:'Other text'}.items():
            self.assertEqual(table.get_text(id_),text)
        self.assertEqual(U8Archive.from_file(ui).files['layout/a'],b'A')
        self.assertEqual(U8Archive.from_file(ui).files['layout/c'],b'C')
        self.assertEqual(U8Archive.from_file(race).files['layout/b'],b'B')
        self.assertEqual(U8Archive.from_file(other).files['message/Other.bmg'],b'opaque')
        self.assertFalse(root.exists())
        self.assertFalse(self.pack.update_character_text().writes,'repeated merge is not idempotent')

    def test_missing_race_recovered_without_losing_ui(self):
        self.put_archive('CharacterNames/CharacterNames.uiassets.szs',{123:'Private'})
        self.pack.reload();self.pack.commit(self.pack.update_character_text())
        self.assertEqual(self.pair().get_text(123),'Private')

    def test_tagged_ui_race_and_nested_legacy_bmg_are_merged_and_synced(self):
        self.patches.mkdir()
        ui=self.patches/'[message]CharaName.bmg.uiassets';ui.write_bytes(bmg_bytes({170:'UI user'}))
        race=self.patches/'[message]CharaName.bmg.raceassets';race.write_bytes(bmg_bytes({171:'Race user'}))
        legacy=self.patches/'Older/[message]CharaRR.bmg.replacedassets';legacy.parent.mkdir()
        legacy.write_bytes(bmg_bytes({172:'Legacy user'}))
        self.pack.reload();self.pack.commit(self.pack.update_character_text())
        table=self.pair()
        for id_,text in ((170,'UI user'),(171,'Race user'),(172,'Legacy user')):
            self.assertEqual(table.get_text(id_),text)
        for p in (ui,race,legacy): self.assertEqual(CharacterBMG.read(p.read_bytes()).encode(),table.encode())

    def test_metadata_fill_preserves_unknown_keys_and_message_metadata_on_move(self):
        self.install(7)
        folder=self.pack.patch_directories['wr',7];p=folder/self.pack.PATCH_META_FILENAME
        meta=json.loads(p.read_text(encoding='utf-8'));meta['license_note']={'keep':'this'};p.write_text(json.dumps(meta))
        self.pack.reload();self.pack.commit(self.pack.edit_text('wr',7,'Edited','Credit'))
        folder=self.pack.patch_directories['wr',7]
        self.assertEqual(json.loads((folder/self.pack.PATCH_META_FILENAME).read_text(encoding='utf-8'))['license_note'],{'keep':'this'})
        original=self.pack.bmg._lookup(name_id(11,7));expected=original.metadata
        self.pack.commit(self.pack.reassign_patch_slots({'wr':{7:9}}))
        self.assertEqual(self.pair()._lookup(name_id(11,9)).metadata,expected)
        self.assertEqual(json.loads((folder/self.pack.PATCH_META_FILENAME).read_text(encoding='utf-8'))['license_note'],{'keep':'this'})

    def test_existing_override_does_not_hide_metadata_missing_entries(self):
        self.install(7)
        for p in self.pack._patch_name_archives(): p.write_bytes(archive_bytes({902:'Other text'}))
        self.pack.reload()
        self.assertEqual(self.pack.inventory.skins['wr',7].name,'Custom')
        self.pack.commit(self.pack.update_character_text())
        self.assertEqual(self.pair().get_text(name_id(11,7)),'Custom')

    def test_bmg_metadata_disagreement_is_reviewed_and_synced_without_dropping_json(self):
        self.install(7)
        path=self.pack.patch_directories['wr',7]/self.pack.PATCH_META_FILENAME
        meta=json.loads(path.read_text());meta['name']='Old JSON';meta['note']='retain';path.write_text(json.dumps(meta))
        self.pack.reload();plan=self.pack.update_character_text()
        self.assertIn('Old JSON',plan.preview());self.assertIn('BMG wins',plan.preview())
        self.pack.commit(plan)
        self.assertEqual(json.loads(path.read_text())['name'],'Custom')
        self.assertEqual(json.loads(path.read_text())['note'],'retain')


    def test_member_conflict_aborts_without_discarding(self):
        a=self.put_archive('CharacterNames/CharacterNames.uiassets.szs',{12:'Nested'},{'same/path':b'NEW'})
        b=self.put_archive('CharacterNames.uiassets.szs',{13:'Legacy'},{'same/path':b'OLD'})
        self.pack.reload();before=[p.read_bytes() for p in (a,b)]
        with self.assertRaisesRegex(ValueError,'Archive member conflict'): self.pack.update_character_text()
        self.assertEqual(before,[p.read_bytes() for p in (a,b)])

    def test_stale_preview_rejected_and_failure_restores_all_paths(self):
        self.install(7);plan=self.pack.edit_text('wr',7,'Changed','Credit')
        ui=self.pack._patch_name_archives()[0];old=ui.read_bytes();ui.write_bytes(old+b'changed')
        with self.assertRaisesRegex(ValueError,'changed since preview'): self.pack.commit(plan)
        ui.write_bytes(old);self.pack.reload();plan=self.pack.edit_text('wr',7,'Changed','Credit')
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        import wcm.operations as op
        replace=op.os.replace;calls=0
        def fail_once(a,b):
            nonlocal calls
            calls+=1
            if calls==2: raise OSError('simulated disk failure')
            return replace(a,b)
        with patch('wcm.operations.os.replace',side_effect=fail_once):
            with self.assertRaises(OSError): self.pack.commit(plan)
        after={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file() and 'RR Character Manager Backups' not in p.parts}
        expected={p:b for p,b in before.items() if 'RR Character Manager Backups' not in p.parts}
        self.assertEqual(after,expected)

    def test_developer_sync_retains_patches_and_standard_cannot_write_distribution(self):
        self.install(7)
        with self.assertRaises(PermissionError): self.pack.edit_text('wr',1,'Bad','Bad')
        dev=CharacterPack(self.characters,self.archive,self.patches,developer_mode=True)
        dev.commit(dev.edit_text('wr',1,'Edited official','Maintainer'))
        self.assertEqual(CharacterBMG.read(U8Archive.from_file(self.archive).files['message/CharaRR.bmg']).get_text(name_id(11,1)),'Edited official')
        self.pack.reload();self.assertEqual(self.pair().get_text(name_id(11,7)),'Custom')
        self.assertEqual(self.pair().get_text(name_id(11,1)),'Edited official')
        with self.assertRaises(PermissionError): self.pack.commit(EditPlan('unsafe',writes={self.archive:b'bad'}))

    def test_orphan_message_collision_cannot_be_overwritten_by_move(self):
        self.install(7)
        p=self.pack._patch_name_archives()[0]
        table=CharacterBMG.read(U8Archive.from_file(p).files['message/CharaName.bmg']);table.set_text(name_id(11,9),'Unowned')
        bundle=U8Archive.from_file(p);bundle.replace('message/CharaName.bmg',table.encode());p.write_bytes(bundle.encode())
        self.pack.reload()
        with self.assertRaisesRegex(ValueError,'already belongs'): self.pack.reassign_patch_slots({'wr':{7:9}})


    def test_zero_bytes_inside_control_sequence_are_preserved(self):
        raw='A'.encode('utf-16-be')+bytes.fromhex('001a080100000000')+'B\0'.encode('utf-16-be')
        data=bmg_bytes({12:(raw,b'ATTR'),13:'Other'})
        b=CharacterBMG.read(data);b.set_text(13,'Edited')
        self.assertEqual(CharacterBMG.read(b.encode())._lookup(12).raw,raw)

    def test_unsorted_tables_rebuild_sorted_and_duplicate_ids_are_rejected(self):
        b=CharacterBMG.read(bmg_bytes({900:'High',5:'Low'}));b.set_text(6,'New')
        self.assertEqual([m.id for m in CharacterBMG.read(b.encode()).messages],[5,6,900])
        b.messages.append(b.messages[0]);b.dirty=True
        with self.assertRaisesRegex(ValueError,'duplicate'): b.encode()

    def test_opaque_sections_with_different_content_fail_closed(self):
        from wcm.textmerge import merge_tables
        with self.assertRaisesRegex(ValueError,'opaque BMG section'):
            merge_tables([('A',bmg_bytes({12:'A'},b'one')),('B',bmg_bytes({13:'B'},b'two'))])

if __name__=='__main__': unittest.main()
