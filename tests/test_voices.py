from native_fixtures import valid_brres,valid_szs
"""Verified voice conversion, ownership, backups and portable resource regression tests."""
from pathlib import Path
import hashlib,io,json,os,tempfile,unittest,wave,struct
from unittest.mock import patch
import numpy as np
from wcm.voices import (VoiceArchive,VoiceSession,WaveResource,baseline_path,decode_rwav,
    encode_rwav,generated_voices,map_wavs,wav_bytes,wav_pcm,rwav_info,u32)
from wcm.models import source_entries
from wcm.library import available_import_variants,DEFAULT_RESOURCE_VARIANT
from wcm.mkchara import build_package,read_package,write_package
import test_mkchara as fixtures

VANILLA=Path(os.environ.get('RRCM_VANILLA_BRSAR',r'C:\Users\kafia\Downloads\PulsarModdings\mkwii\pal\DATA\files\sound\revo_kart.brsar'))
COLLECTION=Path(os.environ.get('RRCM_CHARACTER_COLLECTION',r'C:\Users\kafia\Downloads\character'))

class PCMTests(unittest.TestCase):
    def test_pcm_formats_resample_channels_and_limits(self):
        original=np.arange(32000,dtype=np.int16).reshape(-1,2)
        rate,samples=wav_pcm(wav_bytes(32000,original),16000,1)
        self.assertEqual(rate,16000);self.assertEqual(samples.shape,(8000,1))
        with self.assertRaisesRegex(ValueError,'PCM WAV'):wav_pcm(b'RIFF bad')
        with self.assertRaisesRegex(ValueError,'30 seconds'):wav_pcm(wav_bytes(8000,np.zeros((240001,1),np.int16)))

@unittest.skipUnless(VANILLA.is_file(),'Requires original vanilla BRSAR (read-only)')
class VoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ys=VoiceArchive(VANILLA,'ys');cls.ca=VoiceArchive(VANILLA,'ca')
    def setUp(self):
        self.f=fixtures.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata');self.f.setUp();self.addCleanup(self.f.doCleanups)
    def install(self,developer=False,code='ys'):
        pack=self.f.make_pack(self.f.root/('voice'+str(developer)+code),developer)
        source=self.f.root/(code+'source');source.mkdir(exist_ok=True);(source/(code+'.brres')).write_bytes(valid_brres(b'bres'+bytes(32)))
        install=pack.import_skin if developer else pack.import_patch_skin
        pack.commit(install(source,code,4,**({'insert':False} if developer else {}),name='Voice Test',author='Artist'))
        return pack,VoiceSession(pack,code,4,VANILLA)
    def test_all_24_vanilla_sections_open_including_empty_and_shared_banks(self):
        from wcm.library import CHARACTER_CODES
        for code in CHARACTER_CODES:
            with self.subTest(code=code):
                archive=VoiceArchive(VANILLA,code)
                self.assertTrue(archive.banks)
                self.assertTrue(any(WaveResource(bank.resource).waves for bank in archive.banks.values()))
        rs=VoiceArchive(VANILLA,'rs');self.assertFalse(WaveResource(rs.banks['CAN_PC.brwsd'].resource).waves)
        self.assertTrue(any(not b.writable for b in rs.banks.values()))
        self.assertFalse(rs.banks['PC.brbnk'].writable);self.assertFalse(rs.banks['NPC.brbnk'].writable)
        bk=VoiceArchive(VANILLA,'bk');self.assertTrue(any('ambiguous-' in key for key in bk.banks))
    def test_failed_auto_audio_keeps_regular_import_compatible(self):
        source=self.f.root/'UnsupportedAudio';source.mkdir();(source/'ys.brres').write_bytes(valid_brres(b'bres'+bytes(32)))
        (source/'voice.wav').write_bytes(b'bad audio')
        with patch('wcm.voices.generated_voices',side_effect=ValueError('Unsupported voice bank')):
            plan=self.f.pack.import_patch_skin(source,'ys',4,name='Safe model',author='')
        self.assertTrue(any('WAV sources retained' in warning for warning in plan.warnings))
        self.f.pack.commit(plan);self.assertIn(('ys',4),self.f.pack.inventory.skins)

    def test_original_events_and_dsp_decode(self):
        self.assertEqual(self.ys.banks['PC.brwsd'].file_id,393)
        self.assertEqual(self.ca.banks['PC.brwsd'].file_id,659)
        r=WaveResource(self.ys.banks['PC.brwsd'].resource)
        rate,samples=wav_pcm(decode_rwav(r.waves[0]))
        self.assertEqual(rate,16000)
        self.assertEqual(samples[:10,0].tolist(),[0,8,13,-9,-8,1,-9,-15,-18,-35])
        self.assertTrue(self.ys.banks['PC.brwsd'].labels)
    def test_pcm16_encoding_and_runtime_end_address(self):
        default=WaveResource(self.ys.banks['PC.brwsd'].resource).waves[0]
        samples=np.arange(16000,dtype=np.int16).reshape(-1,1)
        generated=encode_rwav(wav_bytes(16000,samples),default)
        a,encoding,looped,ch,rate,count=rwav_info(generated)
        self.assertEqual((encoding,ch,rate,count),(1,1,16000,16000))
        self.assertEqual(u32(generated,a+12),15999) # AX inclusive end address
        np.testing.assert_array_equal(wav_pcm(decode_rwav(generated))[1],samples)
    def test_rebuild_preserves_other_waves_and_event_table(self):
        r=WaveResource(self.ys.banks['PC.brwsd'].resource)
        new=encode_rwav(wav_bytes(16000,np.zeros((4096,1),np.int16)),r.waves[2])
        changed=WaveResource(r.rebuild({2:new}))
        self.assertEqual(changed.prefix,r.prefix);self.assertEqual(changed.waves[2],new)
        self.assertEqual(changed.waves[:2],r.waves[:2]);self.assertEqual(changed.waves[3:],r.waves[3:])
        self.assertEqual(changed.data_wave_map(),r.data_wave_map())
        with self.assertRaises(ValueError):r.rebuild({len(r.waves):new})
    def test_verified_mapping_ambiguous_shared_and_wrong_base(self):
        raw=wav_bytes(16000,np.zeros((100,1),np.int16))
        paths=[('nested/[393] GRP_VO_YS_PC/Audio[0].wav',raw),('nested/[637] GRP/Audio[32].wav',raw),('wrong/[393] GRP_VO_CA_PC/Audio[1].wav',raw)]
        mapped,unmatched=map_wavs(paths,self.ys)
        self.assertEqual(set(mapped),{('PC.brwsd',0)});self.assertEqual(len(unmatched),2)
        mapped,unmatched=map_wavs(paths+[('duplicate/[393]/Audio[0].wav',raw)],self.ys)
        self.assertFalse(mapped);self.assertEqual(len(unmatched),4)
        mapped,unmatched=map_wavs(paths,self.ca);self.assertFalse(mapped)
    def test_editor_save_restore_revert_and_mode_ownership(self):
        baseline_hash=hashlib.sha256(VANILLA.read_bytes()).hexdigest()
        raw=wav_bytes(16000,np.full((1600,1),1234,np.int16))
        for developer in (False,True):
            with self.subTest(developer=developer):
                pack,session=self.install(developer)
                archive_before=pack.archive_path.read_bytes()
                session.replace('PC.brwsd',0,raw,'replacement.wav');session.restore('PC.brwsd',1)
                self.assertEqual(session.state('PC.brwsd',0),'Staged · Replaced')
                session.revert();self.assertFalse(session.pending)
                session.replace('PC.brwsd',0,raw,'replacement.wav');plan=session.plan()
                self.assertTrue(all(p.is_relative_to(pack.character if developer else pack.patches_path) for p in plan.writes))
                backup=pack.commit(plan);self.assertIsNone(backup)
                reloaded=VoiceSession(pack,'ys',4,VANILLA)
                self.assertEqual(reloaded.state('PC.brwsd',0),'Replaced');self.assertEqual(reloaded.state('PC.brwsd',1),'Original')
                reloaded.restore('PC.brwsd',0);pack.commit(reloaded.plan())
                restored=VoiceSession(pack,'ys',4,VANILLA);self.assertEqual(restored.state('PC.brwsd',0),'Original')
                self.assertEqual(pack.archive_path.read_bytes(),archive_before)
                if developer:self.assertFalse(pack.patches_path.exists())
        self.assertEqual(hashlib.sha256(VANILLA.read_bytes()).hexdigest(),baseline_hash)
    def test_preview_stale_write_rejected(self):
        pack,session=self.install();session.restore('PC.brwsd',0);pack.commit(session.plan())
        session=VoiceSession(pack,'ys',4,VANILLA)
        session.replace('PC.brwsd',0,wav_bytes(16000,np.zeros((100,1),np.int16)),'test.wav')
        plan=session.plan();target=session.paths['PC.brwsd'];target.write_bytes(target.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'changed'):pack.commit(plan)
    def test_voice_transaction_failure_rolls_back_resources_and_metadata(self):
        pack,session=self.install()
        session.replace('PC.brwsd',0,wav_bytes(16000,np.zeros((100,1),np.int16)),'voice.wav')
        session.restore('NPC.brwsd',0);plan=session.plan()
        before={p:p.read_bytes() if p.exists() else None for p in plan.writes}
        import os
        real_replace=os.replace;calls=0
        def fail_once(source,target):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('Injected voice installation failure')
            return real_replace(source,target)
        with patch('wcm.operations.os.replace',side_effect=fail_once):
            with self.assertRaises(OSError):pack.commit(plan)
        for p,raw in before.items():
            self.assertEqual(p.read_bytes() if p.exists() else None,raw)
    def test_shared_resource_and_foreign_event_table_are_protected(self):
        pack,session=self.install();session.restore('PC.brwsd',0);pack.commit(session.plan())
        session=VoiceSession(pack,'ys',4,VANILLA)
        path=session.paths['PC.brwsd'];pack.patch_assets['sound/grp_vo_ca-4_pc.brwsd']=path
        session.restore('PC.brwsd',0)
        with self.assertRaisesRegex(ValueError,'shared'):session.plan()
        pack.patch_assets.pop('sound/grp_vo_ca-4_pc.brwsd')
        resource=bytearray(path.read_bytes());base=u32(resource,16)+8
        entry=base+u32(resource,base+8);note=base+u32(resource,entry+20);note_entry=base+u32(resource,note+8)
        struct.pack_into('>I',resource,note_entry,1);path.write_bytes(resource)
        broken=VoiceSession(pack,'ys',4,VANILLA)
        self.assertEqual(broken.state('PC.brwsd',0),'Incompatible')
        with self.assertRaises(ValueError):broken.restore('PC.brwsd',0)

    def test_compatible_existing_event_parameters_are_preserved(self):
        pack,session=self.install();session.restore('PC.brwsd',0);pack.commit(session.plan())
        path=pack.asset_path('Sound/GRP_VO_YS-4_PC.brwsd');resource=bytearray(path.read_bytes());base=u32(resource,16)+8
        entry=base+u32(resource,base+8);note=base+u32(resource,entry+20);note_entry=base+u32(resource,note+8)
        resource[note_entry+8]^=1;path.write_bytes(resource)
        session=VoiceSession(pack,'ys',4,VANILLA);self.assertNotIn('PC.brwsd',session.errors)
        session.restore('PC.brwsd',0);plan=session.plan()
        self.assertEqual(WaveResource(plan.writes[path]).prefix,WaveResource(resource).prefix)
    def test_own_silence_cleanup_and_legacy_metadata_creation(self):
        pack,session=self.install();folder=pack.patch_directories['ys',4]
        driver=pack.asset_path('Driver/ys-4.brres');driver.rename(pack.patches_path/driver.name)
        (folder/pack.PATCH_META_FILENAME).unlink();pack.reload()
        self.assertNotIn(('ys',4),pack.patch_directories)
        mute=pack.patches_path/'ys-4.silent';mute.write_bytes(b'');pack.reload()
        session=VoiceSession(pack,'ys',4,VANILLA);session.restore('PC.brwsd',0);plan=session.plan()
        self.assertIn(mute,plan.deletes);pack.commit(plan);self.assertFalse(mute.exists())
        self.assertIn(('ys',4),pack.patch_metadata)
        self.assertIn('voice',pack.patch_metadata['ys',4])
        self.assertIn('voice',read_package(io.BytesIO(build_package(pack,'ys',4))).character['metadata'])

    def test_manual_replacement_wav_is_portable_and_other_sources_survive(self):
        for developer in (False,True):
            pack,session=self.install(developer,code='ca')
            raw=wav_bytes(16000,np.full((100,1),123,np.int16));session.replace('PC.brwsd',0,raw,'custom.wav')
            pack.commit(session.plan());package=read_package(io.BytesIO(build_package(pack,'ca',4)))
            record=package.character['metadata']['voice']['replacements'][0]
            self.assertEqual(dict(package.sources)[record['source_payload']],raw)
            session=VoiceSession(pack,'ca',4,VANILLA)
            other=wav_bytes(16000,np.full((100,1),456,np.int16));session.replace('PC.brwsd',1,other,'second.wav')
            pack.commit(session.plan());updated=read_package(io.BytesIO(build_package(pack,'ca',4)))
            self.assertEqual(dict(updated.sources)[record['source_payload']],raw)
            self.assertEqual(len(updated.character['metadata']['voice']['replacements']),2)
            if developer:self.assertFalse(pack.patches_path.exists())

    def test_existing_voice_alias_keeps_its_filename_and_ownership(self):
        pack,session=self.install();session.restore('PC.brwsd',0);pack.commit(session.plan())
        original=pack.asset_path('Sound/GRP_VO_YS-4_PC.brwsd');alias=original.with_name(original.name+'.CustomVoice')
        original.rename(alias);pack.reload()
        session=VoiceSession(pack,'ys',4,VANILLA);self.assertNotIn('PC.brwsd',session.errors)
        session.replace('PC.brwsd',0,wav_bytes(16000,np.zeros((100,1),np.int16)),'voice.wav')
        plan=session.plan();self.assertIn(alias,plan.writes);pack.commit(plan)
        self.assertFalse(original.exists());self.assertTrue(alias.exists())
        self.assertEqual(VoiceSession(pack,'ys',4,VANILLA).state('PC.brwsd',0),'Replaced')

    def test_legacy_mkchara_does_not_reconvert_sources(self):
        with patch('wcm.voices.generated_voices',side_effect=AssertionError('must not regenerate legacy package')):
            self.f.pack.commit(self.f.plan(slot=12))
    @unittest.skipUnless(COLLECTION.is_dir(),'Requires local example mods')
    def test_actual_mods_both_modes_and_mkchara_remap(self):
        for folder,code,expected,unmapped in [('mkw_-_miles_prower','ca',104,3),('mario_kart_wii_knuckles_13-07-20_','ys',116,6)]:
            source=COLLECTION/folder
            if not source.exists():source=COLLECTION/folder.rstrip('_')/'_'
            if not source.is_dir():self.skipTest('Example mod missing')
            entries=source_entries(source);output,metadata,unknown=generated_voices(entries,code,VANILLA)
            self.assertEqual(len(metadata),expected);self.assertEqual(len(unknown),unmapped)
            for developer in (False,True):
                with self.subTest(character=folder,developer=developer):
                    pack=self.f.make_pack(self.f.root/(folder+str(developer)),developer)
                    install=pack.import_skin if developer else pack.import_patch_skin
                    variants=available_import_variants(n for n,_ in entries)
                    with patch('wcm.voices.baseline_path',return_value=VANILLA):
                        plan=install(source,code,4,**({'insert':False} if developer else {}),name=folder,author='Test',source_variant=DEFAULT_RESOURCE_VARIANT if variants else None)
                    pack.commit(plan)
                    for stem,data in output.items():self.assertEqual(pack.asset_path(f'Sound/GRP_VO_{code.upper()}-4_{stem}').read_bytes(),data)
                    exported=build_package(pack,code,4);package=read_package(io.BytesIO(exported))
                    self.assertEqual(len(package.character['metadata']['voice']['replacements']),expected)
                    path=self.f.root/(folder+str(developer)+'.mkchara');write_package(path,exported)
                    pack.commit(install(path,code,5,**({'insert':False} if developer else {}),name=folder,author='Test'))
                    copied=read_package(io.BytesIO(build_package(pack,code,5)))
                    self.assertEqual(dict(copied.assets),dict(package.assets));self.assertEqual(copied.character['metadata'],package.character['metadata'])
                    if developer:self.assertFalse(pack.patches_path.exists())
                    print(folder,'Developer' if developer else 'Patches',expected,'mapped;',unmapped,'shared menu clips source-only; import/remap PASS',flush=True)
