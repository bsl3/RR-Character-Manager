from native_fixtures import valid_brres,valid_szs
from fixture_paths import fixture_path, require_fixture
"""Tests include the actual RR binary assets supplied for this project, if present."""
from pathlib import Path
import tempfile
import unittest
import zipfile
import io
from PIL import Image
from wcm.szs import U8Archive,yaz0_encode,yaz0_decode
from wcm.bmg import CharacterBMG,name_id,author_id
from wcm.library import scan_paths,parse_asset,CHARACTER_CODES,CHARACTER_NAMES,CODE_IDS,DISPLAY_CODES,DISPLAY_GROUPS
from wcm.operations import CharacterPack
from wcm.tpl import image_to_tpl,read_tpl

ASSET_ZIP=fixture_path('RRAssets.zip')
CHAR_ZIP=fixture_path('Character.zip')


def sample_archive():
    if ASSET_ZIP.exists():
        with zipfile.ZipFile(ASSET_ZIP) as z:
            return z.read('Assets/ReplacedAssets.szs')
    raise unittest.SkipTest('RRAssets.zip is needed for real-archive integration test')


class TestArchive(unittest.TestCase):
    def test_yaz0_variants(self):
        samples=[b'',b'X',b'abcdefgh' * 500,b'AB'*512,bytes(range(256))*200]
        for sample in samples:
            self.assertEqual(yaz0_decode(yaz0_encode(sample)),sample)

    def test_archive_edit_and_roundtrip(self):
        src=sample_archive();a=U8Archive.read(src)
        self.assertEqual(len(a.files),290)
        self.assertEqual(a.encode(),src)
        old=a.files['message/CharaRR.bmg']
        a.replace('message/CharaRR.bmg',old+b'1234')
        repacked=U8Archive.read(a.encode())
        self.assertEqual(list(repacked.files),list(a.files))
        self.assertEqual(repacked.files,a.files)

    def test_archive_reject_invalid(self):
        with self.assertRaises(ValueError):U8Archive.read(b'bad')
        with self.assertRaises(ValueError):yaz0_decode(b'Yaz0'+(1).to_bytes(4,'big')+bytes(8))


class TestBMG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig=U8Archive.read(sample_archive()).files['message/CharaRR.bmg']

    def test_identity(self):
        bmg=CharacterBMG.read(self.orig)
        self.assertEqual(bmg.encode(),self.orig)
        self.assertEqual(len(bmg.messages),248)
        self.assertEqual(bmg.get_text(name_id(7,4)),'Sonic')

    def test_edit_messages_without_affecting_others(self):
        b=CharacterBMG.read(self.orig)
        previous={m.id:m.raw for m in b.messages}
        b.set_text(name_id(7,4),'A brand new Sonic')
        b.set_text(author_id(7,4),'Test Developer')
        after=CharacterBMG.read(b.encode())
        self.assertEqual(after.get_text(name_id(7,4)),'A brand new Sonic')
        for m in after.messages:
            if m.id not in (name_id(7,4),author_id(7,4)):
                self.assertEqual(m.raw,previous[m.id])

    def test_add_new_messages_and_midl_count(self):
        b=CharacterBMG.read(self.orig)
        b.set_text(name_id(7,8),'Added character')
        b.set_text(author_id(7,8),'Somebody')
        out=b.encode();c=CharacterBMG.read(out)
        self.assertEqual(len(c.messages),250)
        self.assertEqual(c.get_text(name_id(7,8)),'Added character')
        self.assertEqual(c.get_text(author_id(7,8)),'Somebody')
        pos=out.index(b'MID1')
        self.assertEqual(int.from_bytes(out[pos+8:pos+10],'big'),250)

    def test_remap_id_preserves_value(self):
        b=CharacterBMG.read(self.orig)
        orig=b.get_text(name_id(7,4))
        b.remap(7,{3:4,4:3})
        c=CharacterBMG.read(b.encode())
        self.assertEqual(c.get_text(name_id(7,3)),orig)


class TestInventory(unittest.TestCase):
    def test_reality(self):
        if not CHAR_ZIP.exists():self.skipTest('Character.zip required')
        with zipfile.ZipFile(CHAR_ZIP) as z:
            paths=[n.removeprefix('Character/') for n in z.namelist() if n.startswith('Character/') and not n.endswith('/')]
        b=CharacterBMG.read(U8Archive.read(sample_archive()).files['message/CharaRR.bmg'])
        inv=scan_paths(paths,b)
        self.assertEqual(len(inv.skins),124)
        self.assertEqual(sum(s.counts['RaceKart'] for s in inv.skins.values()),1488)
        self.assertEqual(inv.skins[('lg',4)].name,'Sonic')
        self.assertEqual(inv.skins[('lg',4)].counts['Driver'],1)
        self.assertIn('AllKart/sb_kart-bmr-5.szs',inv.unknown)

    def test_filename_parser_preserves_sounds(self):
        sound='Sound/GRP_VO_LG-3_CAN_PC.brwsd.luigi'
        asset=parse_asset(sound)
        self.assertEqual(asset.destination(4),'Sound/GRP_VO_LG-4_CAN_PC.brwsd.luigi')
        v=parse_asset('ma_kart-lg-2.szs')
        self.assertEqual(v.destination(7),'ma_kart-lg-7.szs')
        self.assertEqual(parse_asset('Sound/688.fk-7.brbnk').destination(3),'Sound/688.fk-3.brbnk')
        self.assertIsNone(parse_asset('MiiOutfitC/la_bike-lc_mii_m.szs'))

    def test_unumbered_import(self):
        self.assertEqual(parse_asset('Driver/kk.brres',source_import=True).destination(2),'Driver/kk-2.brres')
        self.assertEqual(parse_asset('la_kart-kk.szs',source_import=True).destination(2),'la_kart-kk-2.szs')


class TestCharacterDisplayOrder(unittest.TestCase):
    def test_mkwii_character_select_order(self):
        expected = (
            'Baby Mario','Baby Luigi','Baby Peach','Baby Daisy',
            'Toad','Toadette','Koopa Troopa','Dry Bones',
            'Mario','Luigi','Peach','Daisy',
            'Yoshi','Birdo','Diddy Kong','Bowser Jr.',
            'Wario','Waluigi','Donkey Kong','Bowser',
            'King Boo','Rosalina','Funky Kong','Dry Bowser',
        )
        self.assertEqual(tuple(CHARACTER_NAMES[CODE_IDS[c]] for c in DISPLAY_CODES),expected)
        self.assertEqual([len(c) for _,c in DISPLAY_GROUPS],[8,8,8])
        self.assertEqual(set(DISPLAY_CODES),set(CHARACTER_CODES))
        # Display order must not mutate BMG native character IDs.
        self.assertEqual(CODE_IDS['lg'],7)
        self.assertEqual(name_id(CODE_IDS['lg'],4),0x76a04)
        self.assertEqual(CODE_IDS['kt'],0x13)  # King Boo's native ID / filename postfix
        self.assertEqual(CODE_IDS['bk'],0x15)  # Dry Bowser's native ID / filename postfix


class TestTPL(unittest.TestCase):
    def test_roundtrip(self):
        im=Image.new('RGBA',(70,80),(180,20,30,200))
        for size in (32,64):
            data=image_to_tpl(im,size)
            self.assertEqual(read_tpl(data).size,(size,size))
            self.assertEqual(len(data),0x40+size*size*2)

    def test_actual_rr_portrait(self):
        if not CHAR_ZIP.exists():self.skipTest('Character.zip required')
        with zipfile.ZipFile(CHAR_ZIP) as z:
            im=read_tpl(z.read('Character/Portrait/lg-4-css.tpl'))
        self.assertEqual(im.size,(64,64))


class TestTransactions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        root=Path(self.tmp.name)
        self.character=root/'Character';self.character.mkdir()
        (self.character/'Driver').mkdir()
        (self.character/'Sound').mkdir()
        (self.character/'Driver/lg-1.brres').write_bytes(b'skin-1')
        (self.character/'Driver/lg-2.brres').write_bytes(b'skin-2')
        (self.character/'ma_kart-lg-1.szs').write_bytes(b'kart-1')
        (self.character/'ma_kart-lg-2.szs').write_bytes(b'kart-2')
        (self.character/'Sound/GRP_VO_LG-2_CAN_PC.brwsd.luigi').write_bytes(b'voice-2')
        self.archive=root/'ReplacedAssets.szs';self.archive.write_bytes(sample_archive())
        self.pack=CharacterPack(self.character,self.archive,developer_mode=True)

    def tearDown(self):self.tmp.cleanup()

    def test_move_and_backup(self):
        backup=self.pack.commit(self.pack.move_slot('lg',2,1))
        self.assertTrue((backup/'manifest.json').is_file())
        self.assertEqual((self.character/'Driver/lg-1.brres').read_bytes(),b'skin-2')
        self.assertEqual((self.character/'Driver/lg-2.brres').read_bytes(),b'skin-1')
        self.assertEqual((self.character/'Sound/GRP_VO_LG-1_CAN_PC.brwsd.luigi').read_bytes(),b'voice-2')
        self.assertEqual(self.pack.inventory.skins[('lg',1)].name,'Luigi (Vacation)')

    def test_insert_creates_bmg_and_shifts_all(self):
        mod=Path(self.tmp.name)/'mod.zip'
        with zipfile.ZipFile(mod,'w') as z:
            z.writestr('Driver/lg.brres',valid_brres(b'bres'+b'new-driver'))
            z.writestr('ma_kart-lg.szs',valid_szs(b'Yaz0'+b'new-race'))
        plan=self.pack.import_skin(mod,'lg',1,insert=True,name='New Sonic',author='My name')
        self.assertTrue(plan.writes)
        self.pack.commit(plan)
        self.assertEqual((self.character/'Driver/lg-1.brres').read_bytes(),valid_brres(b'bresnew-driver'))
        self.assertEqual((self.character/'Driver/lg-2.brres').read_bytes(),b'skin-1')
        self.assertEqual((self.character/'Driver/lg-3.brres').read_bytes(),b'skin-2')
        self.assertEqual(self.pack.inventory.skins[('lg',1)].name,'New Sonic')
        self.assertEqual(self.pack.inventory.skins[('lg',2)].name,'Luigi (Ice)')

    def test_prevent_overwrites(self):
        mod=Path(self.tmp.name)/'mod.zip'
        with zipfile.ZipFile(mod,'w') as z:z.writestr('Driver/lg.brres',valid_brres(b'bresabc'))
        with self.assertRaisesRegex(ValueError,'Slot occupied'):
            self.pack.import_skin(mod,'lg',1,insert=False,name='X',author='Y')

    def test_prevent_mismatch(self):
        mod=Path(self.tmp.name)/'mod.zip'
        with zipfile.ZipFile(mod,'w') as z:z.writestr('Driver/kk.brres',valid_brres(b'bresabc'))
        with self.assertRaisesRegex(ValueError,'different character skeleton'):
            self.pack.import_skin(mod,'lg',3,insert=False,name='X',author='Y')

    def test_add_css_portrait_png(self):
        original_bmg=self.archive.read_bytes()
        src=Path(self.tmp.name)/'portrait.png'
        Image.new('RGBA',(125,84),(70,140,230,180)).save(src)
        plan=self.pack.replace_portrait('lg',2,src)
        dest=self.character/'Portrait/lg-2-css.tpl'
        self.assertIn(dest,plan.writes)
        self.assertFalse(plan.replace_existing)
        backup=self.pack.commit(plan)
        self.assertTrue(backup.is_dir())
        self.assertEqual(read_tpl(dest.read_bytes()).size,(64,64))
        self.assertEqual(self.archive.read_bytes(),original_bmg)
        self.assertEqual(self.pack.inventory.skins[('lg',2)].counts['Portrait'],1)

    def test_add_map_icon_png(self):
        old_archive=self.archive.read_bytes()
        src=Path(self.tmp.name)/'new-map.png'
        Image.new('RGBA',(96,64),(10,180,90,255)).save(src)
        plan=self.pack.replace_map('lg',1,src)
        dest=self.character/'Map/lg-1.tpl'
        self.assertIn(dest,plan.writes)
        self.pack.commit(plan)
        self.assertEqual(read_tpl(dest.read_bytes()).size,(32,32))
        self.assertEqual(self.archive.read_bytes(),old_archive)
        self.assertEqual(self.pack.inventory.skins[('lg',1)].counts['Map'],1)

    def test_replace_existing_map_tpl(self):
        folder=self.character/'Map';folder.mkdir()
        dest=folder/'lg-2.tpl'
        old=image_to_tpl(Image.new('RGBA',(32,32),(255,0,0,255)),32)
        dest.write_bytes(old)
        source=Path(self.tmp.name)/'other-map.tpl'
        new=image_to_tpl(Image.new('RGBA',(32,32),(20,20,230,255)),32)
        source.write_bytes(new)
        plan=self.pack.replace_map('lg',2,source)
        self.assertIn(dest,plan.replace_existing)
        backup=self.pack.commit(plan)
        self.assertEqual(dest.read_bytes(),new)
        self.assertTrue(any(x.read_bytes()==old for x in (backup/'files').iterdir()))

    def test_replace_existing_css_tpl_and_back_up_original(self):
        portrait_dir=self.character/'Portrait'
        portrait_dir.mkdir()
        dest=portrait_dir/'lg-2-css.tpl'
        old=image_to_tpl(Image.new('RGBA',(64,64),(255,0,0,255)),64)
        dest.write_bytes(old)
        source=Path(self.tmp.name)/'new.tpl'
        new=image_to_tpl(Image.new('RGBA',(64,64),(0,255,0,255)),64)
        source.write_bytes(new)
        self.pack.reload()
        plan=self.pack.replace_portrait('lg',2,source)
        self.assertEqual(plan.replace_existing,{dest})
        self.assertIn('replaced',plan.preview().lower())
        backup=self.pack.commit(plan)
        self.assertEqual(dest.read_bytes(),new)
        files=list((backup/'files').iterdir())
        self.assertTrue(any(f.read_bytes()==old for f in files))
        self.assertEqual(self.pack.replace_portrait('lg',2,source).writes,{})

    def test_reject_corrupt_tpl_and_other_slot_write(self):
        bad=Path(self.tmp.name)/'bad.tpl'
        bad.write_bytes(b'not a texture')
        with self.assertRaises(ValueError):
            self.pack.replace_portrait('lg',2,bad)
        from wcm.operations import EditPlan
        outside=Path(self.tmp.name)/'outside.txt'
        plan=EditPlan('Unsafe')
        plan.writes[outside]=b'bad'
        plan.replace_existing.add(outside)
        with self.assertRaisesRegex(ValueError,'outside the Character folder'):
            self.pack.commit(plan)

    def test_text_only_and_noop(self):
        plan=self.pack.edit_text('lg',1,'Luigi (Ice)','Author')
        self.assertIn(self.archive,plan.writes)
        self.pack.commit(plan)
        self.assertEqual(self.pack.inventory.skins[('lg',1)].author,'Author')
        plan2=self.pack.edit_text('lg',1,'Luigi (Ice)','Author')
        self.assertEqual(len(plan2.writes),0)

if __name__=='__main__':unittest.main()
