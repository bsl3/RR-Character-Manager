"""Voice editor widget state and actual Qt WAV playback loading."""
import time,unittest
from PySide6.QtWidgets import QApplication,QMessageBox
from PySide6.QtMultimedia import QMediaPlayer
from unittest.mock import patch
import test_voices as backend
VANILLA=backend.VANILLA
from wcm.voice_editor import VoiceEditor
from wcm.voices import VoiceSession,wav_bytes
from wcm.gui import STYLESHEET
import numpy as np
@unittest.skipUnless(VANILLA.is_file(),'Requires vanilla baseline')
class VoiceUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.f=backend.VoiceTests('test_original_events_and_dsp_decode');self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.pack,self.session=self.f.install()
    def test_rows_staging_revert_and_readonly(self):
        dialog=VoiceEditor(self.session);self.addCleanup(dialog.deleteLater)
        self.assertEqual(len(dialog.items),sum(len(r.waves) for r in self.session.defaults.values()))
        self.assertFalse(dialog.save_button.isEnabled());self.assertTrue(dialog.replace_button.isEnabled())
        from PySide6.QtWidgets import QLabel
        self.assertFalse(any('baseline' in label.text().casefold() or label.text().startswith('Original voices:') for label in dialog.findChildren(QLabel)))
        key,index=self.session.rows[0];self.session.replace(key,index,wav_bytes(16000,np.zeros((100,1),np.int16)),'test.wav')
        dialog.refresh();self.assertTrue(dialog.save_button.isEnabled());dialog.revert();self.assertFalse(dialog.save_button.isEnabled())
        dialog.search.setText('cannon');self.assertTrue(any(item.isHidden() for item in dialog.items.values()))
        dialog.search.setText('zzzz-no-event');self.assertIsNone(dialog.selected());self.assertFalse(dialog.replace_button.isEnabled())
        dialog.close()
        self.pack.developer_mode=False;self.session.editable=False
        readonly=VoiceEditor(self.session);self.assertFalse(readonly.replace_button.isEnabled());readonly.close();readonly.deleteLater()
    def test_category_selection_ids_bulk_and_rollback(self):
        dialog=VoiceEditor(self.session);self.addCleanup(dialog.deleteLater)
        parent=dialog.table.topLevelItem(0);dialog.table.clearSelection();parent.setSelected(True)
        targets=dialog.selected_events();self.assertEqual(len(targets),parent.childCount())
        for target,item in dialog.items.items():
            self.assertEqual(int(item.text(1)),self.session.archive.banks[target[0]].file_id)
            self.assertEqual(int(item.text(2)),target[1])
        valid=[t for t in self.session.rows if t[0] not in self.session.errors][:2]
        raw=wav_bytes(16000,np.zeros((100,1),np.int16))
        dialog.stage_bulk({t:('test.wav',raw) for t in valid});self.assertEqual(len(self.session.pending),2)
        before=dict(self.session.pending)
        with self.assertRaises(ValueError):dialog.stage_bulk({valid[0]:('valid.wav',raw),valid[1]:('bad.wav',b'bad')})
        self.assertEqual(before,self.session.pending)
        self.session.revert()
        dialog.table.clearSelection()
        for t in valid:dialog.items[t].setSelected(True)
        dialog.restore();self.assertEqual(len(self.session.pending),2);dialog.revert();dialog.close()
    def test_real_numbered_folder_mapping_restricted_to_selection(self):
        from pathlib import Path
        for folder in ('mkw_-_miles_prower','mario_kart_wii_knuckles_13-07-20_'):
            root=Path(r'C:/Users/kafia/Downloads/character')/folder
            if not root.exists():continue
            code='ca' if 'miles' in folder else 'ys'
            from wcm.voices import VoiceArchive,map_wavs
            archive=VoiceArchive(VANILLA,code)
            entries=[(p.relative_to(root).as_posix(),p.read_bytes()) for p in root.rglob('*.wav')]
            mapped,unmatched=map_wavs(entries,archive)
            self.assertEqual(len(mapped),104 if code=='ca' else 116)
            self.assertTrue(all(archive.banks[k].file_id in (int(__import__('re').search(r'\[(\d+)\]',name)[1]),) for (k,i),(name,raw) in mapped.items()))
    def test_bulk_review_cancel_conflict_and_manual_assignment(self):
        from PySide6.QtWidgets import QDialog,QComboBox
        dialog=VoiceEditor(self.session);self.addCleanup(dialog.deleteLater)
        target=next(t for t in self.session.rows if t[0] not in self.session.errors)
        raw=wav_bytes(16000,np.zeros((100,1),np.int16));entries=[('unknown.wav',raw),('another.wav',raw)]
        def duplicate(review):
            for box in review.findChildren(QComboBox):box.setCurrentIndex(1)
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog,'exec',duplicate),patch.object(QMessageBox,'warning') as warning:
            dialog.review_bulk(entries,{},[n for n,r in entries],{target})
            warning.assert_called_once();self.assertFalse(self.session.pending)
        def assign(review):
            review.findChildren(QComboBox)[0].setCurrentIndex(1)
            return QDialog.DialogCode.Accepted
        with patch.object(QDialog,'exec',assign):dialog.review_bulk(entries,{},[n for n,r in entries],{target})
        self.assertEqual(set(self.session.pending),{target});self.assertEqual(self.session.pending_sources[target]['file_id'],self.session.archive.banks[target[0]].file_id)
        dialog.revert()
        with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Rejected):dialog.review_bulk(entries,{},[],{target})
        self.assertFalse(self.session.pending);dialog.close()
    def test_qt_loads_and_plays_decoded_original_and_replacement(self):
        dialog=VoiceEditor(self.session);dialog.output.setVolume(0);dialog.show()
        self.addCleanup(dialog.deleteLater)
        for raw in [self.session.audio('PC.brwsd',0),wav_bytes(16000,np.zeros((1600,1),np.int16))]:
            dialog.play(raw);deadline=time.monotonic()+5
            while time.monotonic()<deadline and dialog.player.mediaStatus() not in (QMediaPlayer.MediaStatus.LoadedMedia,QMediaPlayer.MediaStatus.BufferedMedia,QMediaPlayer.MediaStatus.EndOfMedia,QMediaPlayer.MediaStatus.InvalidMedia):self.app.processEvents();time.sleep(.01)
            self.assertNotEqual(dialog.player.mediaStatus(),QMediaPlayer.MediaStatus.InvalidMedia,dialog.player.errorString())
            self.assertNotEqual(dialog.player.mediaStatus(),QMediaPlayer.MediaStatus.LoadingMedia)
        dialog.setStyleSheet(STYLESHEET+' QWidget { font-family: Segoe UI; }');self.app.processEvents();dialog.grab().save(str(__import__('pathlib').Path(dialog.temp.name)/'voice-editor.png'))
        dialog.close()
