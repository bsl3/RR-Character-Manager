"""Windows Qt runtime checks; offscreen, not a human interactive/game test."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import time
import tempfile
import unittest
from unittest.mock import patch
import importlib.util
if importlib.util.find_spec('PySide6') is None:
    raise unittest.SkipTest('PySide6 is unavailable; install requirements for Qt runtime checks')
from pathlib import Path
from collections import OrderedDict
from PIL import Image
from fixture_paths import fixture_path
from test_text_reliability import bmg_bytes
from wcm.szs import U8Archive
from wcm.tpl import image_to_tpl
from wcm.operations import CharacterPack
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from wcm.gui import MainWindow, ModelExplorerDialog, ImportWizard, STYLESHEET
from wcm.preview_widget import MeshPreviewWidget
from wcm.preview3d import PreviewMesh, PreviewMaterial
from wcm.models import source_entries, extract_model_bytes


def wait_until(predicate,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        QApplication.processEvents()
        if predicate(): return True
        time.sleep(.01)  # release the GIL as the real Qt app.exec event loop does
    return False


class QtRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion');cls.app.setStyleSheet(STYLESHEET)

    def pack(self,root,dev):
        char=root/'Character';(char/'Driver').mkdir(parents=True)
        (char/'Map').mkdir();(char/'Driver/wr-1.brres').write_bytes(b'base')
        map_image=Image.new('RGBA',(32,32),(0,0,0,0));map_image.paste((255,30,20,255),(8,4,24,28))
        (char/'Map/wr-1.tpl').write_bytes(image_to_tpl(map_image,32))
        archive=root/'Assets/ReplacedAssets.szs';archive.parent.mkdir()
        archive.write_bytes(U8Archive(OrderedDict({'message/CharaRR.bmg':bmg_bytes({0xb6a01:'Test'})})).encode())
        return CharacterPack(char,archive,developer_mode=dev)

    def test_character_table_has_two_action_context_menu(self):
        from PySide6.QtGui import QContextMenuEvent
        from PySide6.QtCore import QTimer
        with tempfile.TemporaryDirectory() as tmp:
            pack=self.pack(Path(tmp),True)
            window=MainWindow(pack);window.show();window.change_base('wr');self.app.processEvents()
            self.assertEqual(window.table.contextMenuPolicy(),Qt.ContextMenuPolicy.CustomContextMenu)
            self.assertEqual(window.resource_list.viewport().contextMenuPolicy(),Qt.ContextMenuPolicy.NoContextMenu)
            local=window.table.visualItemRect(window.table.item(0,2)).center()
            captured=[]
            def close_menu():
                menu=QApplication.activePopupWidget()
                if menu:
                    captured.extend(action.text() for action in menu.actions());menu.close()
            QTimer.singleShot(50,close_menu)
            event=QContextMenuEvent(QContextMenuEvent.Reason.Mouse,local,window.table.viewport().mapToGlobal(local))
            QApplication.sendEvent(window.table.viewport(),event)
            self.assertEqual(captured,['Export as .mkchara','Delete Character'])
            window.close();window.deleteLater();self.app.processEvents()

    def test_css_first_minimap_second_placeholder_last_in_both_modes(self):
        for dev in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);pack=self.pack(root,dev)
                before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
                window=MainWindow(pack);window.change_base('wr');window.show();self.app.processEvents()
                skin=pack.inventory.skins['wr',1]
                map_pix=window.skin_thumbnail(skin)
                self.assertIsNotNone(map_pix)
                self.assertEqual(map_pix.toImage().pixelColor(5,5).red(),255)
                self.assertFalse(window.table.item(0,1).icon().isNull())
                portrait=root/'Character/Portrait/wr-1-css.tpl';portrait.parent.mkdir()
                portrait.write_bytes(image_to_tpl(Image.new('RGBA',(64,64),(10,255,20,255)),64))
                pack.reload();window.reload_view();window.change_base('wr')
                css_pix=window.skin_thumbnail(pack.inventory.skins['wr',1])
                self.assertEqual(css_pix.toImage().pixelColor(5,5).green(),255)
                portrait.unlink();(root/'Character/Map/wr-1.tpl').unlink()
                pack.reload();window.reload_view();window.change_base('wr')
                self.assertIsNone(window.skin_thumbnail(pack.inventory.skins['wr',1]))
                self.assertTrue(window.table.item(0,1).icon().isNull())
                # Showing/fallback never wrote a generated portrait or changed bytes.
                self.assertEqual((root/'Character/Driver/wr-1.brres').read_bytes(),before[root/'Character/Driver/wr-1.brres'])
                self.assertEqual(pack.archive_path.read_bytes(),before[pack.archive_path])
                window.close();window.deleteLater();self.app.processEvents()

    def test_native_orbit_reset_wireframe_renders_off_thread(self):
        mesh=PreviewMesh('Triangle',[(-1,-1,0),(1,-1,0),(0,1,0)],[(0,1,2,0)],[(0,1),(1,1),(.5,0)],
                         [PreviewMaterial('texture',Image.new('RGBA',(2,2),(20,180,50,255)))])
        view=MeshPreviewWidget();view.resize(400,350);view.set_mesh(mesh);view.show()
        self.assertTrue(wait_until(lambda:view._frame is not None))
        old=view.yaw
        QTest.mousePress(view,Qt.MouseButton.LeftButton,pos=QPoint(150,100))
        QTest.mouseMove(view,QPoint(175,120))
        QTest.mouseRelease(view,Qt.MouseButton.LeftButton,pos=QPoint(175,120))
        self.assertNotEqual(view.yaw,old)
        view.set_wireframe(True);self.assertTrue(view.wireframe)
        view.reset_view();self.assertEqual(view.yaw,24)
        self.assertTrue(wait_until(lambda:view._render_key==view._key()))
        view.close();view.deleteLater();self.app.processEvents()

    def test_cancelled_review_never_commits_and_opening_does_not_migrate(self):
        from PySide6.QtWidgets import QDialog
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);pack=self.pack(root,False);pack.patches_path.mkdir()
            old=pack.patches_path/'wr-8.brres';old.write_bytes(b'legacy skin')
            pack.reload();window=MainWindow(pack);window.show();self.app.processEvents()
            self.assertTrue(old.exists(),'opening a pack migrated without review')
            plan=pack.update_character_text()
            with patch('wcm.gui.PreviewDialog.exec',return_value=QDialog.DialogCode.Rejected),patch.object(pack,'commit') as commit:
                window.run_plan(plan)
                commit.assert_not_called()
            self.assertTrue(old.exists());self.assertFalse(pack._patch_name_archives()[0].exists())
            window.close();window.deleteLater();self.app.processEvents()

    @unittest.skipUnless(fixture_path('samus_v10_hotfix.zip').is_file(),'Optional Samus archive unavailable')
    def test_model_dialog_selects_one_normal_or_lod_and_driver_bytes_stay_whole(self):
        entries=source_entries(fixture_path('samus_v10_hotfix.zip'))
        entries=[e for e in entries if e[0].endswith('la_kart-rs.szs')]
        dialog=ModelExplorerDialog(entries,allow_driver=True);dialog.show()
        self.assertTrue(wait_until(lambda:dialog.viewport.mesh is not None))
        self.assertEqual(dialog.model_combo.count(),2)
        self.assertNotIn('lod',dialog.viewport.mesh.name)
        main_count=len(dialog.viewport.mesh.triangles)
        original=extract_model_bytes(dialog.entries,dialog.candidates[dialog.table.currentRow()])
        dialog.model_combo.setCurrentIndex(1)
        self.assertTrue(wait_until(lambda:dialog.viewport.mesh is not None and 'lod' in dialog.viewport.mesh.name))
        self.assertLess(len(dialog.viewport.mesh.triangles),main_count)
        self.assertEqual(original,extract_model_bytes(dialog.entries,dialog.candidates[dialog.table.currentRow()]))
        self.assertTrue(any(m.texture is not None for m in dialog.viewport.mesh.materials))
        self.assertTrue(wait_until(lambda:dialog.viewport._frame is not None))
        self.assertEqual(dialog.use_button.text(),'Extract standalone Driver BRRES')
        with patch('wcm.gui.QMessageBox.question') as confirm:
            dialog.choose_driver()
            confirm.assert_not_called()
        self.assertEqual(extract_model_bytes(dialog.entries,dialog.chosen),original)
        dialog.close();dialog.deleteLater();self.app.processEvents()

    @unittest.skipUnless(fixture_path('samus_v10_hotfix.zip').is_file(),'Optional Samus archive unavailable')
    def test_samus_import_discovery_explains_separate_suits_and_menu(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack=self.pack(Path(tmp),False)
            wizard=ImportWizard(pack,'wr');wizard.show()
            wizard.source.setText(str(fixture_path('samus_v10_hotfix.zip')));wizard.probe()
            self.assertEqual(wizard.base.currentData(),'rs')
            self.assertIn('8 kart / 8 bike',wizard.discovery.text())
            self.assertIn('Automatic '+wizard.driver_choice.category+': model',wizard.driver_note.text())
            self.assertIn('rs_menu.brres',wizard.driver_note.text())
            self.assertEqual(wizard.driver_choice.archive_member,'')
            wizard.close();wizard.deleteLater();self.app.processEvents()

    def test_fields_fit_font_and_resource_list_remains_usable_on_resize(self):
        from PySide6.QtWidgets import QLineEdit,QStyle,QStyleOptionFrame
        with tempfile.TemporaryDirectory() as tmp:
            window=MainWindow(self.pack(Path(tmp),False));window.show()
            wizard=ImportWizard(window.pack,'wr');wizard.show()
            wizard.probe()
            self.assertEqual(wizard.discovery.text(),'No source selected')
            self.assertIsNone(wizard.driver_choice)
            for width,height in ((1510,940),(1130,690)):
                window.resize(width,height);self.app.processEvents()
                self.assertGreaterEqual(window.resource_list.height(),180)
                for owner in (window,wizard):
                    for field in owner.findChildren(QLineEdit):
                        if not field.isVisible(): continue
                        option=QStyleOptionFrame();option.initFrom(field)
                        content=field.style().subElementRect(QStyle.SubElement.SE_LineEditContents,option,field)
                        self.assertGreaterEqual(content.height(),field.fontMetrics().height(),field.objectName())
            wizard.close();window.close();self.app.processEvents()

    @unittest.skipUnless(fixture_path('Character.zip').is_file(),'Optional RR portraits unavailable')
    def test_actual_plessie_petey_and_goku_css_are_detected_before_minimap(self):
        import zipfile
        with tempfile.TemporaryDirectory() as tmp:
            pack=self.pack(Path(tmp),False)
            with zipfile.ZipFile(fixture_path('Character.zip')) as z:
                for code,slot in (('bk',3),('bk',4),('kt',3)):
                    for category,suffix,extension in (('Driver','','brres'),('Map','','tpl'),('Portrait','-css','tpl')):
                        name=f'{category}/{code}-{slot}{suffix}.{extension}'
                        path=pack.character/name;path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(z.read('Character/'+name))
            pack.reload();window=MainWindow(pack)
            images=[]
            for key in (('bk',3),('bk',4),('kt',3)):
                skin=pack.inventory.skins[key]
                css=window.skin_portrait(skin)
                self.assertIsNotNone(css)
                self.assertEqual(window.skin_thumbnail(skin).toImage(),css.toImage())
                images.append(css.toImage())
            self.assertNotEqual(images[0],images[2])
            self.assertNotEqual(images[1],images[2])
            # Remove only the temporary Plessie portrait to exercise fallback.
            (pack.character/'Portrait/bk-4-css.tpl').unlink();pack.reload()
            skin=pack.inventory.skins['bk',4]
            self.assertIsNone(window.skin_portrait(skin))
            self.assertEqual(window.skin_thumbnail(skin).toImage(),window.skin_image(skin,'Map',True).toImage())
            window.close();window.deleteLater();self.app.processEvents()

    @unittest.skipUnless(fixture_path('samus_v10_hotfix.zip').is_file(),'Optional Samus archive unavailable')
    def test_unsupported_main_model_does_not_hide_supported_variant_selector(self):
        import struct
        from wcm.models import discover_models
        from wcm.preview3d import list_models
        entries=source_entries(fixture_path('samus_v10_hotfix.zip'))
        candidate=next(c for c in discover_models(entries) if c.source_path.endswith('la_kart-rs.szs') and c.archive_member=='driver_model.brres')
        raw=bytearray(extract_model_bytes(entries,candidate));models=list_models(bytes(raw))
        struct.pack_into('>I',raw,models[0].offset+8,9)  # memory only; original archive is not changed
        dialog=ModelExplorerDialog([('Driver/rs.brres',bytes(raw))]);dialog.show()
        self.assertTrue(wait_until(lambda:dialog.model_combo.count()==2))
        self.assertIsNone(dialog.viewport.mesh)
        self.assertIn('version 9 unsupported',dialog.details.text())
        dialog.model_combo.setCurrentIndex(1)
        self.assertTrue(wait_until(lambda:dialog.viewport.mesh is not None))
        self.assertIn('lod',dialog.viewport.mesh.name)
        dialog.close();dialog.deleteLater();self.app.processEvents()

if __name__=='__main__':unittest.main()
