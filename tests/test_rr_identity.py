"""Actual RR name/icon/model correspondence, using independent native IDs."""
import tempfile
import unittest
import zipfile
from pathlib import Path
from fixture_paths import fixture_path
from wcm.operations import CharacterPack
from wcm.models import find_installed_models,extract_model_bytes
from wcm.tpl import read_tpl
from wcm.library import parse_asset

@unittest.skipUnless(fixture_path('Character.zip').is_file() and fixture_path('RRAssets.zip').is_file(),
                     'Optional actual RR assets unavailable')
class RRIdentity(unittest.TestCase):
    def test_king_boo_dry_bowser_names_portraits_models_and_all_resources_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);character=root/'Character';character.mkdir()
            with zipfile.ZipFile(fixture_path('Character.zip')) as archive:
                originals={name:archive.read(name) for name in archive.namelist()
                           if not name.endswith('/') and
                           (a:=parse_asset(name.removeprefix('Character/'))) and a.code in ('bk','kt')}
            for name,payload in originals.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(payload)
            assets=root/'Assets/ReplacedAssets.szs';assets.parent.mkdir()
            with zipfile.ZipFile(fixture_path('RRAssets.zip')) as z: assets.write_bytes(z.read('Assets/ReplacedAssets.szs'))
            pack=CharacterPack(character,assets)
            expected={('bk',3):'Petey Piranha',('bk',4):'Plessie',('kt',3):'Goku',('kt',4):'King Boo (Aristocrat)'}
            for key,name in expected.items():
                skin=pack.inventory.skins[key];self.assertEqual(skin.name,name)
                for asset in skin.files:
                    self.assertEqual((asset.code,asset.slot),key)
                    self.assertEqual(pack.asset_path(asset.relpath).read_bytes(),originals['Character/'+asset.relpath])
                drivers=[pack.asset_path(a.relpath) for a in skin.files if a.category=='Driver']
                candidates,entries=find_installed_models(drivers,character=character)
                selected=next(c for c in candidates if not c.archive_member)
                self.assertEqual(selected.source_path,f'Character/Driver/{key[0]}-{key[1]}.brres')
                self.assertEqual(extract_model_bytes(entries,selected),originals['Character/Driver/'+drivers[0].name])
            plessie=pack.inventory.skins['bk',4]
            portrait=next(a for a in plessie.files if a.category=='Portrait')
            self.assertEqual(portrait.relpath,'Portrait/bk-4-css.tpl')
            self.assertIsNotNone(read_tpl(pack.asset_path(portrait.relpath).read_bytes()).getbbox())
