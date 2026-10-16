from native_fixtures import valid_brres,valid_szs
"""Actual local collection import/resource checks; no claim of emulator playback."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import io
import unittest
from unittest.mock import patch
from wcm.native_validation import validate_asset
import zipfile
from PIL import Image
from PySide6.QtWidgets import QApplication
import test_mkchara as fixtures
from wcm.gui import ImportWizard
from wcm.models import source_entries, discover_models, automatic_driver_candidate, driver_model_role, extract_model_bytes
from wcm.brrescore import list_models
from wcm.library import parse_asset, available_import_variants, select_import_entries, preferred_import_code, unused_race_variant
from wcm.tpl import detected_icons, read_tpl, image_to_tpl
from wcm.szs import U8Archive
from wcm.mkchara import build_package, write_package, read_package

COLLECTION=Path(r'C:\Users\kafia\Downloads\character')

class DimensionDetection(unittest.TestCase):
 def test_dimensions_beat_names_and_candidates_have_stable_hints(self):
  def png(size,color):
   out=io.BytesIO();Image.new('RGBA',(size,size),color).save(out,format='PNG');return out.getvalue()
  entries=[('nested/unknown/x.png',png(64,'red')),('elsewhere/css.png',png(32,'blue')),
           ('other/portrait.png',png(64,'green')),('deep/64.tpl',image_to_tpl(Image.new('RGBA',(32,32),'yellow'),32))]
  icons=detected_icons(entries)
  self.assertEqual(icons['Portrait'][0][0],'other/portrait.png')
  self.assertEqual(len(icons['Portrait']),2);self.assertEqual(len(icons['Map']),2)
  self.assertEqual(icons,detected_icons(list(reversed(entries))))

 def test_nested_icons_install_and_canonical_icon_can_be_overridden(self):
  f=fixtures.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata');f.setUp();self.addCleanup(f.doCleanups)
  source=f.root/'Dimensions';source.mkdir();(source/'wr.brres').write_bytes(valid_brres(b'bres fixture'))
  deep=source/'nested'/'misc';deep.mkdir(parents=True)
  Image.new('RGBA',(64,64),'red').save(deep/'unknown.png')
  (deep/'portrait.tpl').write_bytes(image_to_tpl(Image.new('RGBA',(32,32),'blue'),32))
  for dev in (False,True):
   pack=f.make_pack(f.root/('IconMode'+str(dev)),dev)
   install=pack.import_skin if dev else pack.import_patch_skin
   plan=install(source,'wr',10,**({'insert':False} if dev else {}),name='Dimensions',author='')
   pack.commit(plan)
   self.assertEqual(read_tpl(pack.asset_path('Portrait/wr-10-css.tpl').read_bytes()).size,(64,64))
   self.assertEqual(read_tpl(pack.asset_path('Map/wr-10.tpl').read_bytes()).size,(32,32))
  manual=f.root/'manual.png';Image.new('RGBA',(64,64),'green').save(manual)
  plan=f.pack.import_patch_skin(f.source,'wr',9,name='Override',author='',extra_images={'Portrait':manual})
  self.assertEqual(read_tpl(plan.writes[f.pack.patches_path/'Override/wr-9-css.tpl']).getpixel((0,0)),(0,131,0,255))

@unittest.skipUnless(COLLECTION.is_dir(),'Local character collection unavailable')
class EntireCollection(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def setUp(self):
  self.f=fixtures.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata');self.f.setUp();self.addCleanup(self.f.doCleanups)
  warnings=patch('wcm.gui.QMessageBox.warning');warnings.start();self.addCleanup(warnings.stop)
 def test_every_folder_both_modes_and_package_roundtrip(self):
  for folder in sorted(COLLECTION.iterdir()):
   if not folder.is_dir():continue
   original_entries=source_entries(folder)
   variants=available_import_variants(n for n,_ in original_entries)
   for variant in variants or [None]:
    entries=select_import_entries(original_entries,variant)
    code=preferred_import_code(n for n,_ in entries)
    choice=automatic_driver_candidate(entries,code=code);self.assertIsNotNone(choice,folder.name)
    self.assertFalse(choice.category.startswith(('Award','Auxiliary')))
    assets=[(n,a,d) for n,d in entries if not unused_race_variant(n) and (a:=parse_asset(n,source_import=True)) and a.code==code and
            not (a.category=='Driver' and driver_model_role(n,d)[0].startswith('Award'))]
    scoped=[(n,d) for n,d in entries if not ((a:=parse_asset(n,source_import=True)) and a.code!=code)]
    icons=detected_icons(scoped)
    race_models=[c for c in discover_models([(n,d) for n,d in scoped if not unused_race_variant(n)]) if c.archive_member=='driver_model.brres']
    self.assertEqual(len(race_models),sum(a.category=='RaceKart' for _,a,_ in assets))
    for candidate in race_models:self.assertTrue(list_models(extract_model_bytes(scoped,candidate)))
    corrupt=None
    for name,asset,data in assets:
     try:validate_asset(data,asset.category,name)
     except ValueError as error:corrupt=error;break
    for dev in (False,True):
     with self.subTest(character=folder.name,variant=variant,developer=dev):
      import hashlib
      suffix=hashlib.sha256(str(variant).encode()).hexdigest()[:8]
      pack=self.f.make_pack(self.f.root/(folder.name+suffix+str(dev)),dev)
      dialog=ImportWizard(pack,code);dialog.source.setText(str(folder));dialog.probe()
      if variant:dialog.variant.setCurrentIndex(dialog.variant.findData(variant))
      self.assertEqual(dialog.driver_choice,choice)
      for kind in ('Portrait','Map'):
       label,_=dialog.package_icon_previews[kind]
       if icons[kind]:self.assertFalse(label.pixmap().isNull())
       else:self.assertEqual(label.text(),'Not detected')
      dialog.slot.setValue(12);dialog.name.setText(folder.name)
      with patch('wcm.gui.QMessageBox.warning') as warning:dialog.validate()
      if corrupt:
       self.assertIsNone(dialog.plan);self.assertTrue(warning.called)
       self.assertNotIn((code,12),pack.inventory.skins)
       dialog.close();dialog.deleteLater();print(folder.name,'CONFIRMED CORRUPT REFUSED',str(corrupt),flush=True);continue
      self.assertIsNotNone(dialog.plan)
      if choice.category.startswith('Race driver / standalone'):
       self.assertTrue(any('no sel_wait/sel_gut' in warning for warning in dialog.plan.warnings))
      pack.commit(dialog.plan);dialog.close();dialog.deleteLater()
      self.assertEqual(pack.asset_path(f'Driver/{code}-12.brres').read_bytes(),extract_model_bytes(entries,choice))
      for name,asset,data in assets:
       if asset.category in ('Portrait','Map'):continue
       self.assertEqual(pack.asset_path(asset.destination(12)).read_bytes(),data,name)
       if asset.category in ('AllKart','RaceKart'):
        installed=U8Archive.from_file(pack.asset_path(asset.destination(12)))
        self.assertEqual(installed.files,U8Archive.read(data).files)
      for kind,size in (('Portrait',64),('Map',32)):
       if icons[kind]:
        filename=f'{code}-12-css.tpl' if kind=='Portrait' else f'{code}-12.tpl'
        self.assertEqual(read_tpl(pack.asset_path(kind+'/'+filename).read_bytes()).size,(size,size))
      if dev:self.assertFalse(pack.patches_path.exists())
      payload=build_package(pack,code,12);package=read_package(io.BytesIO(payload))
      path=self.f.root/(folder.name+suffix+str(dev)+'.mkchara');write_package(path,payload)
      install=pack.import_skin if dev else pack.import_patch_skin
      plan=install(path,code,13,**({'insert':False} if dev else {}),name=folder.name,author='')
      pack.commit(plan);copied=read_package(io.BytesIO(build_package(pack,code,13)))
      self.assertEqual(dict(package.assets),dict(copied.assets));self.assertEqual(dict(package.sources),dict(copied.sources))
      print(folder.name,variant,'Developer' if dev else 'Patches','PASS',choice.category,'race',sum(a.category=='RaceKart' for _,a,_ in assets),'icons',','.join(k for k,v in icons.items() if v),flush=True)
