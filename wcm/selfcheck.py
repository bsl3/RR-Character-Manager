"""Offline checks for packaged releases; all files stay in a temporary folder."""
import json
import tempfile
import time
from pathlib import Path


def run(report):
    import numpy as np
    import certifi
    from PIL import Image
    from PySide6.QtWidgets import QApplication, QTableWidgetItem
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from .gui import PatchSlotTable
    from .gl_preview import GLPreview
    from .brrescore import PreviewMesh
    from .raster import render_mesh
    from .szs import U8Archive
    from .tpl import image_to_tpl, read_tpl
    from .voices import wav_bytes, wav_pcm
    from .portable_files import rename_new

    app = QApplication.instance() or QApplication([])
    checks = {}
    try:
        mesh = PreviewMesh('check', [(-1,-1,0), (1,-1,0), (0,1,0)], [(0,1,2,0)])
        pixels = render_mesh(mesh, 64, 64)
        if not np.any(pixels[:,:,:3] != [16,27,43]):
            raise ValueError('Preview renderer produced no geometry')
        checks['preview'] = True
        np.linalg.inv(np.eye(4))
        checks['numpy_linalg'] = True
        image = Image.new('RGBA', (32,32), (20,80,150,255))
        if read_tpl(image_to_tpl(image,32)).size != (32,32):
            raise ValueError('TPL roundtrip failed')
        archive = U8Archive({'keep': b'payload'}).encode()
        if U8Archive.read(archive).files['keep'] != b'payload':
            raise ValueError('Archive roundtrip failed')
        checks['resources'] = True
        table = PatchSlotTable(1,1);table.setItem(0,0,QTableWidgetItem('slot'));table.close()
        checks['widgets'] = True
        if not Path(certifi.where()).is_file():
            raise ValueError('Bundled certificate roots missing')
        checks['updates_certificates'] = True
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            src = root/'a';dst = root/'b';src.write_bytes(b'keep');rename_new(src,dst)
            checks['native_export'] = dst.read_bytes() == b'keep'
            raw = wav_bytes(16000, np.zeros((1600,1),dtype=np.int16));wav_pcm(raw)
            wave = root/'sound.wav';wave.write_bytes(raw)
            player = QMediaPlayer();audio = QAudioOutput();player.setAudioOutput(audio)
            player.setSource(QUrl.fromLocalFile(str(wave)))
            deadline = time.monotonic()+10
            while time.monotonic()<deadline and player.mediaStatus() not in (QMediaPlayer.MediaStatus.LoadedMedia,QMediaPlayer.MediaStatus.InvalidMedia):
                app.processEvents();time.sleep(.02)
            if player.mediaStatus() != QMediaPlayer.MediaStatus.LoadedMedia:
                raise ValueError('Audio decoder failed: '+player.errorString())
            player.stop();player.setSource(QUrl());app.processEvents()
            checks['audio_decode'] = True
        Path(report).write_text(json.dumps({'ok':True,'checks':checks},indent=2),encoding='utf-8')
        return 0
    except Exception as error:
        Path(report).write_text(json.dumps({'ok':False,'error':str(error),'checks':checks},indent=2),encoding='utf-8')
        return 1
