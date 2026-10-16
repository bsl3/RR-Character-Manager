from native_fixtures import valid_brres,valid_szs
"""Package round trips, real assets, safe reading and transactional failure tests."""
from collections import OrderedDict
from pathlib import Path
import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from PIL import Image
from fixture_paths import fixture_path
from test_text_reliability import bmg_bytes, archive_bytes
from wcm.bmg import CharacterBMG, name_id, author_id
from wcm.library import CODE_IDS, parse_asset
from wcm.mkchara import build_package, read_package, write_package, logical_name
from wcm.models import source_entries, discover_models, extract_model_bytes
from wcm.operations import CharacterPack
from wcm.szs import U8Archive
from wcm.tpl import image_to_tpl


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pack = self.make_pack(self.root/'Pack')
        self.source = self.root/'Source'; self.source.mkdir()
        resources = {'wr.brres': valid_brres(b'bres'+bytes(32)),
                     'GRP_VO_WR_CAN_PC.brwsd': b'RWSD voice',
                     '10.wr.brseq': b'RSEQ sequence', 'wr.silent': b'',
                     'ma_kart-wr.szs': U8Archive(OrderedDict({'driver_model.brres': valid_brres(b'bres kart'), 'driver_anim.brres': valid_brres(b'bres anim')})).encode(),
                     'ma_bike-wr.szs': U8Archive(OrderedDict({'driver_model.brres': valid_brres(b'bres bike')})).encode(),
                     'mdf_kart_red-wr_2.szs': valid_szs(b'two-player-red'),
                     'mdf_kart_blue-wr_2.szs': valid_szs(b'two-player-blue'),
                     'ma_bike-wr_4.szs': U8Archive(OrderedDict({'textures': b'four-player'})).encode(),
                     'mdf_bike_blue-wr_BT.szs': U8Archive(OrderedDict({'textures': b'team'})).encode(),
                     'wr-allkart_BT.szs': U8Archive(OrderedDict({'menu_model.brres': valid_brres(b'bres menu')})).encode(),
                     'wr-css.tpl': image_to_tpl(Image.new('RGBA',(64,64),(255,0,0,255)),64),
                     'wr.tpl': image_to_tpl(Image.new('RGBA',(32,32),(0,255,0,255)),32),
                     'Common.szs': U8Archive(OrderedDict({'animation.brres': valid_brres(b'bres source only')})).encode(),
                     'extras/voice.wav': b'RIFF voice', 'credits.txt': b'Original credits'}
        for name,data in resources.items():
            path = self.source/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
        self.pack.commit(self.pack.import_patch_skin(self.source,'wr',7,name='Test Skin',author='Artist'))
        meta = self.pack.patch_directories['wr',7]/self.pack.PATCH_META_FILENAME
        data=json.loads(meta.read_text());data['compatibility']={'kart':'Power','bike':'Zero'}
        meta.write_text(json.dumps(data));self.pack.reload()
        self.package = self.root/'Test.mkchara'
        write_package(self.package,build_package(self.pack,'wr',7))

    def make_pack(self, root, developer=False):
        char=root/'Character';(char/'Driver').mkdir(parents=True)
        archive=root/'Assets/ReplacedAssets.szs';archive.parent.mkdir()
        archive.write_bytes(U8Archive(OrderedDict({'message/CharaRR.bmg':bmg_bytes({902:('Unrelated\0'.encode('utf-16-be'),b'ABCD')}, b'opaque'),
                                                  'layout/untouched.bin':b'layout'})).encode())
        return CharacterPack(char,archive,root/'Patches',developer_mode=developer)

    def plan(self, slot=12, code='wr', pack=None, **kwargs):
        return (pack or self.pack).import_patch_skin(self.package,code,slot,name='Test Skin',author='Artist',**kwargs)

    def test_roundtrip_different_slot_all_payloads_and_metadata(self):
        before=self.pack.archive_path.read_bytes()
        exported=read_package(self.package)
        self.assertNotIn('slot',exported.character)
        self.assertTrue(all(parse_asset(n,source_import=True).slot is None for n,_ in exported.assets))
        backup=self.pack.commit(self.plan())
        self.assertIsNone(backup)
        roundtrip=read_package(io.BytesIO(build_package(self.pack,'wr',12)))
        self.assertEqual(exported.character,roundtrip.character)
        self.assertEqual(dict(exported.assets),dict(roundtrip.assets))
        self.assertEqual(dict(exported.sources),dict(roundtrip.sources))
        self.assertEqual(self.pack.archive_path.read_bytes(),before)
        self.assertFalse((self.pack.patches_path/'Test Skin (WR-12)'/'Common.szs').exists())
        for path in self.pack._patch_name_archives():
            bmg=CharacterBMG.read(U8Archive.from_file(path).files['message/CharaName.bmg'])
            self.assertEqual(bmg.get_text(name_id(CODE_IDS['wr'],12)),'Test Skin')
            self.assertEqual(bmg.get_text(author_id(CODE_IDS['wr'],12)),'Artist')
            self.assertEqual(bmg._lookup(902).metadata,b'ABCD')
            self.assertEqual(bmg.get_text(name_id(CODE_IDS['wr'],7)),'Test Skin')
        self.pack.commit(self.pack.reassign_patch_slots({'wr':{12:16}}))
        moved=read_package(io.BytesIO(build_package(self.pack,'wr',16)))
        self.assertEqual(dict(exported.assets),dict(moved.assets))
        self.assertEqual(dict(exported.sources),dict(moved.sources))


    def test_existing_ui_and_race_members_and_unrelated_raw_text_survive(self):
        target=self.make_pack(self.root/'Target')
        for path in target._patch_name_archives():
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(archive_bytes({904:('Extra\0'.encode('utf-16-be'),b'WXYZ')},
                                          {'layout/'+path.name:b'keep this'}))
        target.reload();target.commit(self.plan(pack=target))
        for path in target._patch_name_archives():
            archive=U8Archive.from_file(path)
            self.assertEqual(archive.files['layout/'+path.name],b'keep this')
            bmg=CharacterBMG.read(archive.files['message/CharaName.bmg'])
            self.assertEqual(bmg._lookup(904).raw,'Extra\0'.encode('utf-16-be'))
            self.assertEqual(bmg._lookup(904).metadata,b'WXYZ')

    def test_source_tpl_icons_use_regular_installer_and_preserve_ui_race(self):
        original=dict(read_package(self.package).assets)
        for names in (('Portrait/wr-css.tpl','Map/wr.tpl'),('Icons/portrait.tpl','Icons/minimap.tpl')):
            with self.subTest(names=names):
                def source_icons(manifest,members):
                    for resource in manifest['resources']:
                        if resource.get('category') in ('Portrait','Map'):
                            resource['name']=names[0 if resource['category']=='Portrait' else 1]
                            resource['role']='source';resource.pop('category')
                package=self.root/'SourceIcons.mkchara'
                package.write_bytes(self.modified_package(source_icons).getvalue())
                target=self.make_pack(self.root/('Target'+str(len(names[0]))))
                for path in target._patch_name_archives():
                    path.parent.mkdir(parents=True,exist_ok=True)
                    path.write_bytes(archive_bytes({904:('Extra\0'.encode('utf-16-be'),b'WXYZ')},
                                                  {'layout/keep.bin':b'layout','icons/keep.tpl':b'untouched icon'}))
                target.reload()
                plan=target.import_patch_skin(package,'lg',12,name='Icons',author='Artist')
                folder=target.patches_path/'Icons'
                self.assertEqual(plan.writes.get(folder/'lg-12-css.tpl'),original['Portrait/wr-css.tpl'])
                self.assertEqual(plan.writes.get(folder/'lg-12.tpl'),original['Map/wr.tpl'])
                target.commit(plan)
                self.assertEqual((folder/'lg-12-css.tpl').read_bytes(),original['Portrait/wr-css.tpl'])
                self.assertEqual((folder/'lg-12.tpl').read_bytes(),original['Map/wr.tpl'])
                for path in target._patch_name_archives():
                    archive=U8Archive.from_file(path)
                    self.assertEqual(archive.files['icons/keep.tpl'],b'untouched icon')
                    self.assertEqual(archive.files['layout/keep.bin'],b'layout')
                    bmg=CharacterBMG.read(archive.files['message/CharaName.bmg'])
                    self.assertEqual(bmg.get_text(name_id(CODE_IDS['lg'],12)),'Icons')
                    self.assertEqual(bmg._lookup(904).raw,'Extra\0'.encode('utf-16-be'))
                    self.assertEqual(bmg._lookup(904).metadata,b'WXYZ')

    def test_base_change_maps_codes_sound_and_skips_unused_rr_variants(self):
        plan=self.plan(code='lg')
        self.assertTrue(any('not retargeted' in warning for warning in plan.warnings))
        self.pack.commit(plan)
        names={a.relpath for a in self.pack.inventory.skins['lg',12].files}
        self.assertIn('Sound/GRP_VO_LG-12_CAN_PC.brwsd',names)
        self.assertIn('Sound/10.lg-12.brseq',names)
        self.assertNotIn('mdf_bike_blue-lg-12_BT.szs',names)
        self.assertNotIn('ma_bike-lg-12_4.szs',names)
        exported=read_package(io.BytesIO(build_package(self.pack,'lg',12)))
        self.assertEqual(exported.character['base_character'],'lg')

    def test_occupied_orphan_text_and_orphan_resource_conflicts(self):
        with self.assertRaisesRegex(ValueError,'already exists'):
            self.plan(slot=7)
        path=self.pack.patches_path/'orphan'/'wr-12-css.tpl';path.parent.mkdir()
        path.write_bytes(dict(read_package(self.package).assets)['Portrait/wr-css.tpl']);self.pack.reload()
        with self.assertRaisesRegex(ValueError,'orphan resources'):
            self.plan()
        path.unlink();self.pack.reload()
        bmg=CharacterBMG.read(self.pack.bmg.encode());bmg.set_text(name_id(CODE_IDS['wr'],12),'Orphan')
        plan=self.pack.update_character_text();self.pack._stage_name_patches(plan,bmg);self.pack.commit(plan)
        with self.assertRaisesRegex(ValueError,'text metadata'):
            self.plan()

    def test_resource_editor_custom_physical_names_export_logical_identity(self):
        folder=self.pack.patch_directories['wr',7]
        old=folder/'wr-7.brres';new=folder/'custom-model.brres';old.rename(new)
        index={'distribution':{},'patches':{'Driver/wr-7.brres':new.relative_to(self.pack.patches_path).as_posix()}}
        path=self.pack._resource_index_path();path.write_bytes(self.pack._resource_index_bytes(index));self.pack.reload()
        packaged=read_package(io.BytesIO(build_package(self.pack,'wr',7)))
        self.assertEqual(dict(packaged.assets)['Driver/wr.brres'],new.read_bytes())
        self.assertNotIn('custom-model.brres',dict(packaged.sources))

    def test_manual_embedded_driver_override_keeps_original_driver_and_races(self):
        entries=source_entries(self.package)
        candidate=next(c for c in discover_models(entries) if c.source_path=='ma_bike-wr.szs')
        self.pack.commit(self.plan(driver_candidate=candidate))
        result=read_package(io.BytesIO(build_package(self.pack,'wr',12)))
        self.assertEqual(dict(result.assets)['Driver/wr.brres'],extract_model_bytes(entries,candidate))
        self.assertEqual(dict(result.assets)['ma_kart-wr.szs'],dict(entries)['ma_kart-wr.szs'])
        self.assertEqual(dict(result.sources)['OriginalDriver/wr.brres'],dict(entries)['Driver/wr.brres'])

    def test_developer_roundtrip_and_move_preserves_auxiliary_resources(self):
        target=self.make_pack(self.root/'Developer',True)
        original=read_package(self.package)
        plan=target.import_skin(self.package,'wr',12,insert=False,name='Test Skin',author='Artist')
        target.commit(plan);target.commit(target.move_slot('wr',12,14))
        result=read_package(io.BytesIO(build_package(target,'wr',14)))
        self.assertEqual(original.character,result.character)
        self.assertEqual(dict(original.assets),dict(result.assets))
        self.assertEqual(dict(original.sources),dict(result.sources))

    def test_mid_commit_failure_restores_files_and_text(self):
        plan=self.plan()
        before={p:p.read_bytes() for root in (self.pack.character,self.pack.patches_path,self.pack.archive_path.parent)
                for p in root.rglob('*') if p.is_file()}
        replace=os.replace;calls=0
        def fail_once(source,target):
            nonlocal calls
            calls+=1
            if calls==len(plan.writes): raise OSError('Injected install failure')
            return replace(source,target)
        with patch('wcm.operations.os.replace',side_effect=fail_once):
            with self.assertRaisesRegex(OSError,'Injected'):
                self.pack.commit(plan)
        after={p:p.read_bytes() for root in (self.pack.character,self.pack.patches_path,self.pack.archive_path.parent)
               for p in root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)
        self.assertNotIn(('wr',12),self.pack.inventory.skins)

    def test_export_rejects_changed_installed_resource_before_refresh(self):
        model=self.pack.asset_path('Driver/wr-7.brres')
        model.write_bytes(valid_brres(b'bres changed'))
        with self.assertRaisesRegex(ValueError,'Refresh'):
            build_package(self.pack,'wr',7)
        self.pack.reload()
        self.assertEqual(dict(read_package(io.BytesIO(build_package(self.pack,'wr',7))).assets)['Driver/wr.brres'],valid_brres(b'bres changed'))

    def test_atomic_export_replacement_backup_and_failed_publish(self):
        original=self.package.read_bytes()
        updated=self.modified_package(lambda m,f:m['character'].update(name='Updated')).getvalue()
        backup=write_package(self.package,updated)
        self.assertEqual(backup.read_bytes(),original)
        self.assertEqual(self.package.read_bytes(),updated)
        with patch('wcm.mkchara.os.replace',side_effect=OSError('Injected export failure')):
            with self.assertRaises(OSError): write_package(self.package,original)
        self.assertEqual(self.package.read_bytes(),updated)
        self.assertFalse(list(self.package.parent.glob('.mkchara-*')))

    def modified_package(self, mutate, extra=None):
        with zipfile.ZipFile(self.package) as archive:
            members={name:archive.read(name) for name in archive.namelist()}
        manifest=json.loads(members['manifest.json']);mutate(manifest,members)
        members['manifest.json']=json.dumps(manifest).encode()
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for name,data in members.items(): archive.writestr(name,data)
            if extra: archive.writestr(*extra)
        return io.BytesIO(output.getvalue())

    def test_reject_unsafe_corrupt_unknown_version_and_duplicate_resources(self):
        cases=[lambda m,f:m.update(version=2),
               lambda m,f:m['resources'][0].update(name='../escape.brres'),
               lambda m,f:m['resources'][0].update(name='C:/evil.brres'),
               lambda m,f:m['resources'][0].update(name='Driver/CON.brres'),
               lambda m,f:m['resources'][0].update(sha256='0'*64),
               lambda m,f:m['resources'][0].update(size=-1),
               lambda m,f:m['resources'][0].update(name='Driver/wr-7.brres'),
               lambda m,f:m['resources'].append(dict(m['resources'][0])),
               lambda m,f:m['character'].update(slot=7),
               lambda m,f:f.update({'../outside':b'bad'}),
               lambda m,f:f.update({'undeclared.txt':b'bad'})]
        for mutation in cases:
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError): read_package(self.modified_package(mutation))
        with self.assertRaisesRegex(ValueError,'Duplicate package path'):
            read_package(self.modified_package(lambda m,f:None,('MANIFEST.JSON',b'{}')))
        with patch('wcm.mkchara.MAX_TOTAL',16):
            with self.assertRaisesRegex(ValueError,'exceeds'): read_package(self.package)
        with patch('wcm.mkchara.MAX_FILE',16):
            with self.assertRaisesRegex(ValueError,'exceeds'): read_package(self.package)
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w') as archive:
            link=zipfile.ZipInfo('link');link.external_attr=(0o120777<<16);archive.writestr(link,'outside')
        with self.assertRaisesRegex(ValueError,'Links'):read_package(io.BytesIO(output.getvalue()))


class ActualAssets(unittest.TestCase):
    @unittest.skipUnless(fixture_path('samus_v10_hotfix.zip').is_file() and fixture_path('RRAssets.zip').is_file(), 'Optional real assets unavailable')
    def test_samus_export_import_different_slot_keeps_power_zero_suits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'Character/Driver').mkdir(parents=True);(root/'Assets').mkdir()
            with zipfile.ZipFile(fixture_path('RRAssets.zip')) as archive:
                original=archive.read('Assets/ReplacedAssets.szs')
            (root/'Assets/ReplacedAssets.szs').write_bytes(original)
            pack=CharacterPack(root/'Character',root/'Assets/ReplacedAssets.szs',root/'Patches')
            pack.commit(pack.import_patch_skin(fixture_path('samus_v10_hotfix.zip'),'rs',9,name='Samus',author='Samus author'))
            package=root/'Samus.mkchara';write_package(package,build_package(pack,'rs',9))
            exported=read_package(package)
            kart=[(n,d) for n,d in exported.assets if '_kart' in n]
            bike=[(n,d) for n,d in exported.assets if '_bike' in n]
            self.assertEqual((len(kart),len(bike)),(8,8))
            kart_driver=U8Archive.read(dict(kart)['la_kart-rs.szs']).files['driver_model.brres']
            bike_driver=U8Archive.read(dict(bike)['la_bike-rs.szs']).files['driver_model.brres']
            self.assertNotEqual(kart_driver,bike_driver)
            self.assertTrue(any(n.endswith('rs_menu.brres') for n,_ in exported.sources))
            pack.commit(pack.import_patch_skin(package,'rs',12,name='Samus',author='Samus author'))
            imported=read_package(io.BytesIO(build_package(pack,'rs',12)))
            self.assertEqual(dict(exported.assets),dict(imported.assets))
            self.assertEqual(dict(exported.sources),dict(imported.sources))
            self.assertEqual(pack.archive_path.read_bytes(),original)
            self.assertGreater(len(discover_models(source_entries(package))),16)
            menu=next(c for c in discover_models(source_entries(package)) if c.source_path.endswith('rs_menu.brres'))
            self.assertTrue(menu.source_path.startswith('SourceOnly/'))
            plan=pack.import_patch_skin(package,'rs',14,name='Samus Menu',author='Samus author',driver_candidate=menu)
            driver=next(data for path,data in plan.writes.items() if path.name=='rs-14.brres')
            self.assertEqual(driver,extract_model_bytes(source_entries(package),menu))
            self.assertEqual(sum(path.suffix=='.szs' and ('_kart' in path.name or '_bike' in path.name) for path in plan.writes),16)


    @unittest.skipUnless(fixture_path('Character.zip').is_file() and fixture_path('RRAssets.zip').is_file(), 'Optional real RR assets unavailable')
    def test_rr_character_identity_roundtrips_king_boo_dry_bowser_resources(self):
        from wcm.library import scan_paths
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'Character').mkdir();(root/'Assets').mkdir()
            with zipfile.ZipFile(fixture_path('RRAssets.zip')) as archive:
                (root/'Assets/ReplacedAssets.szs').write_bytes(archive.read('Assets/ReplacedAssets.szs'))
            bmg=CharacterBMG.read(U8Archive.from_file(root/'Assets/ReplacedAssets.szs').files['message/CharaRR.bmg'])
            with zipfile.ZipFile(fixture_path('Character.zip')) as archive:
                paths=[n.removeprefix('Character/') for n in archive.namelist() if n.startswith('Character/') and not n.endswith('/')]
                inventory=scan_paths(paths,bmg)
                for key in (('bk',3),('bk',4),('kt',3),('kt',4)):
                    for asset in inventory.skins[key].files:
                        path=root/'Character'/asset.relpath;path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(archive.read('Character/'+asset.relpath))
            pack=CharacterPack(root/'Character',root/'Assets/ReplacedAssets.szs',root/'Patches')
            for code,slot in (('bk',3),('bk',4),('kt',3),('kt',4)):
                skin=pack.inventory.skins[code,slot]
                package=root/f'{code}-{slot}.mkchara';write_package(package,build_package(pack,code,slot))
                exported=read_package(package);target=slot+10
                pack.commit(pack.import_patch_skin(package,code,target,name=skin.name,author=skin.author))
                imported=read_package(io.BytesIO(build_package(pack,code,target)))
                self.assertEqual(exported.character,imported.character)
                self.assertEqual(dict(exported.assets),dict(imported.assets))
            self.assertIn('Petey',pack.inventory.skins['bk',13].name)
            self.assertEqual(pack.inventory.skins['bk',14].name,'Plessie')
            self.assertEqual(pack.inventory.skins['kt',13].name,'Goku')
            self.assertEqual(pack.inventory.skins['kt',14].name,'King Boo (Aristocrat)')


if __name__=='__main__': unittest.main()
