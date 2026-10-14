from fixture_paths import fixture_path, require_fixture
"""Patch name archive and image auto-detection regression tests."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image
from wcm.operations import CharacterPack
from wcm.bmg import CharacterBMG, name_id, author_id
from wcm.library import CODE_IDS
from wcm.szs import U8Archive
from wcm.tpl import image_to_tpl, read_tpl

RR_ASSETS = fixture_path('RRAssets.zip')

class TestPatchNamesAndIcons(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = self.root/'Character'
        (self.library/'Driver').mkdir(parents=True)
        (self.library/'Driver/wr-1.brres').write_bytes(b'bres'+bytes(40))
        self.archive = self.root/'Assets/ReplacedAssets.szs'
        self.archive.parent.mkdir()
        with zipfile.ZipFile(require_fixture('RRAssets.zip')) as z:
            self.archive.write_bytes(z.read('Assets/ReplacedAssets.szs'))
        self.before = self.archive.read_bytes()
        self.patches = self.root/'Patches'
        self.pack = CharacterPack(self.library,self.archive,self.patches)
        self.mod = self.root/'source'
        (self.mod/'Driver').mkdir(parents=True)
        (self.mod/'Driver/wr.brres').write_bytes(b'bres'+bytes(40))

    def bmg(self):
        ui,race = self.pack._patch_name_archives()
        bmg_ui = U8Archive.from_file(ui).files['message/CharaName.bmg']
        bmg_race = U8Archive.from_file(race).files['message/CharaName.bmg']
        self.assertEqual(bmg_ui,bmg_race)
        return CharacterBMG.read(bmg_ui)

    def test_generic_tpl_and_png_detected_by_dimensions(self):
        icons=self.mod/'Icon'
        icons.mkdir()
        (icons/'picture.tpl').write_bytes(image_to_tpl(Image.new('RGBA',(64,64),'red'),64))
        Image.new('RGBA',(32,32),'blue').save(icons/'something.png')
        plan=self.pack.import_patch_skin(self.mod,'wr',7,name='Biker Wario',author='Porko')
        self.assertIn(self.patches/'Biker Wario/wr-7-css.tpl',plan.writes)
        self.assertIn(self.patches/'Biker Wario/wr-7.tpl',plan.writes)
        self.assertEqual(read_tpl(plan.writes[self.patches/'Biker Wario/wr-7-css.tpl']).size,(64,64))
        self.pack.commit(plan)
        self.assertEqual(self.bmg().get_text(name_id(CODE_IDS['wr'],7)),'Biker Wario')
        self.assertEqual(self.bmg().get_text(author_id(CODE_IDS['wr'],7)),'Porko')
        self.assertEqual(self.archive.read_bytes(),self.before)

    def test_tpl_explicit_selection_supported(self):
        img=self.root/'my_portrait.tpl'
        img.write_bytes(image_to_tpl(Image.new('RGBA',(64,64),'green'),64))
        plan=self.pack.import_patch_skin(self.mod,'wr',7,name='Skin',author='Author',extra_images={'Portrait':img})
        self.assertEqual(plan.writes[self.patches/'Skin/wr-7-css.tpl'],img.read_bytes())

    def test_bmg_edit_updates_both_and_folder(self):
        self.pack.commit(self.pack.import_patch_skin(self.mod,'wr',7,name='Original',author='One'))
        plan=self.pack.edit_text('wr',7,'Renamed Wario','Two')
        self.assertTrue(all(a in plan.writes for a in self.pack._patch_name_archives()))
        self.pack.commit(plan)
        self.assertFalse((self.patches/'Original').exists())
        self.assertTrue((self.patches/'Renamed Wario/wr-7.brres').is_file())
        self.assertEqual(self.bmg().get_text(name_id(CODE_IDS['wr'],7)),'Renamed Wario')
        self.assertEqual(self.bmg().get_text(author_id(CODE_IDS['wr'],7)),'Two')

    def test_migrates_old_raw_chara_rr(self):
        self.patches.mkdir()
        legacy=self.patches/'[message]CharaRR.bmg.replacedassets'
        bmg=CharacterBMG.read(U8Archive.from_file(self.archive).files['message/CharaRR.bmg'])
        bmg.set_text(name_id(CODE_IDS['wr'],7),'Old Name')
        legacy.write_bytes(bmg.encode())
        self.pack.reload()
        self.assertEqual(self.pack.bmg.get_text(name_id(CODE_IDS['wr'],7)),'Old Name')
        plan=self.pack.import_patch_skin(self.mod,'wr',8,name='New Name',author='New Artist')
        self.assertIn(legacy,plan.deletes)
        self.pack.commit(plan)
        self.assertFalse(legacy.exists())
        self.assertEqual(self.bmg().get_text(name_id(CODE_IDS['wr'],7)),'Old Name')
        self.assertEqual(self.bmg().get_text(name_id(CODE_IDS['wr'],8)),'New Name')

    def test_multiple_imports_accumulate_one_shared_name_archive(self):
        self.pack.commit(self.pack.import_patch_skin(self.mod,'wr',7,name='A',author='Artist A'))
        self.pack.commit(self.pack.import_patch_skin(self.mod,'wr',8,name='B',author='Artist B'))
        bmg=self.bmg()
        self.assertEqual(bmg.get_text(name_id(CODE_IDS['wr'],7)),'A')
        self.assertEqual(bmg.get_text(name_id(CODE_IDS['wr'],8)),'B')
        self.assertEqual(len(list((self.patches/'CharacterNames').glob('*.uiassets.szs'))),1)

    def test_ambiguous_icons_choose_deterministically_with_explicit_override(self):
        folder=self.mod/'Icons'
        folder.mkdir()
        Image.new('RGBA',(64,64),'red').save(folder/'one.png')
        Image.new('RGBA',(64,64),'blue').save(folder/'two.png')
        automatic=self.pack.import_patch_skin(self.mod,'wr',7,name='A',author='A')
        self.assertTrue(any('Multiple Portrait icons' in line for line in automatic.metadata))
        # Explicit choice overrides automatic duplicates.
        plan=self.pack.import_patch_skin(self.mod,'wr',7,name='A',author='A',extra_images={'Portrait':folder/'one.png'})
        self.assertIn(self.patches/'A/wr-7-css.tpl',plan.writes)

if __name__=='__main__':unittest.main()
