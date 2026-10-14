"""QTabWidget integration for profile switching (requires PySide6)."""
import importlib.util
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from unittest.mock import patch

if importlib.util.find_spec('PySide6') is None:
    raise unittest.SkipTest('PySide6 not installed')

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from PySide6.QtCore import QSettings, QPoint
from wcm.gui import OpenPackDialog
from wcm.profiles import ACTIVE_KEY, PROFILES_KEY


class ConnectionProfilesGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Isolate production QSettings from tests by supplying in-memory settings.
        class FakeSettings:
            def __init__(self, values):
                self.values = values
            def value(self, key, default=''):
                return self.values.get(key, default)
            def setValue(self, key, value):
                self.values[key] = value
            def sync(self):
                pass
        self.memory = FakeSettings({'characterPath': 'RR/Character',
                                    'archivePath': 'RR/Assets/ReplacedAssets.szs',
                                    'patchesPath': 'RR/Patches'})
        self.settings_patch = patch('wcm.gui.QSettings', return_value=self.memory)
        self.settings_patch.start()
        self.dialog = OpenPackDialog()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        QApplication.processEvents()
        self.settings_patch.stop()

    def test_default_and_new_tabs_have_independent_fields(self):
        self.assertEqual(self.dialog.tabs.count(), 1)
        self.assertEqual(self.dialog.folder.text(), 'RR/Character')
        with patch('wcm.gui.QInputDialog.getText', return_value=('WiiLoaded', True)):
            self.dialog.add_profile()
        self.assertEqual(self.dialog.tabs.count(), 2)
        self.assertEqual(self.dialog.folder.text(), '')
        self.dialog.folder.setText('WL/Character')
        self.dialog.archive.setText('WL/Assets/ReplacedAssets.szs')
        self.dialog.patches.setText('WL/Patches')
        self.dialog.developer_checkbox.setChecked(True)
        self.dialog.tabs.setCurrentIndex(0)
        self.assertEqual(self.dialog.folder.text(), 'RR/Character')
        self.assertFalse(self.dialog.developer_checkbox.isChecked())
        self.dialog.tabs.setCurrentIndex(1)
        self.assertEqual(self.dialog.folder.text(), 'WL/Character')
        self.assertTrue(self.dialog.developer_checkbox.isChecked())

    def test_open_only_current_pack_and_saves_all_profiles(self):
        class StubPack:
            def __init__(self, character, archive, patches, *, developer_mode=False):
                self.character = character
                self.archive_path = archive
                self.patches_path = patches
                self.developer_mode = developer_mode
        with patch('wcm.gui.QInputDialog.getText', return_value=('WiiLoaded', True)):
            self.dialog.add_profile()
        self.dialog.folder.setText('WL/Character')
        self.dialog.archive.setText('WL/Assets/ReplacedAssets.szs')
        self.dialog.patches.setText('WL/Patches')
        with patch('wcm.gui.CharacterPack', side_effect=StubPack) as constructor:
            self.dialog.open()
        constructor.assert_called_once()
        self.assertEqual(self.dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.dialog.pack.character.as_posix(), 'WL/Character')
        self.assertEqual(self.memory.value('characterPath'), 'RR/Character')
        self.assertEqual(self.memory.value('archivePath'), 'RR/Assets/ReplacedAssets.szs')
        self.assertEqual(self.memory.value('patchesPath'), 'RR/Patches')
        self.assertIn('WiiLoaded', self.memory.value(PROFILES_KEY))

    def test_add_button_follows_last_tab_after_add_remove_and_resize(self):
        d=self.dialog;d.resize(900,650);d.show()
        def check():
            for _ in range(4):QApplication.processEvents()
            bar=d.profile_tab_bar;plus=d.add_profile_button
            right=bar.mapTo(d.tabs,QPoint(bar.tabRect(bar.count()-1).right(),0)).x()
            left=plus.mapTo(d.tabs,QPoint(0,0)).x()
            self.assertGreater(left,right)
            self.assertLessEqual(left-right,12)
            self.assertLess(plus.mapTo(d.tabs,QPoint(plus.width()-1,0)).x(),d.tabs.width())
        check()
        with patch('wcm.gui.QInputDialog.getText',return_value=('Second',True)):d.add_profile()
        check();d.resize(1100,650);check()
        with patch('wcm.gui.QMessageBox.question',return_value=QMessageBox.StandardButton.Yes):d.remove_profile(1)
        check()

    def test_uniform_tabs_scroll_without_covering_add_button(self):
        self.dialog.resize(790,720);self.dialog.show()
        for index in range(20):
            with patch('wcm.gui.QInputDialog.getText',return_value=(f'Profile {index}',True)):
                self.dialog.add_profile()
        QApplication.processEvents()
        bar=self.dialog.tabs.tabBar();plus=self.dialog.add_profile_button
        sizes=[bar.tabRect(i).size() for i in range(bar.count())]
        self.assertTrue(all(size==sizes[0] for size in sizes))
        self.assertTrue(bar.usesScrollButtons())
        self.assertTrue(plus.isVisible())
        self.assertLessEqual(plus.mapTo(self.dialog.tabs,QPoint(plus.width()-1,0)).x(),self.dialog.tabs.width())
        self.assertLessEqual(bar.geometry().right(),plus.mapTo(self.dialog.tabs,QPoint(0,0)).x())
        bar.setCurrentIndex(0);QApplication.processEvents()
        self.assertGreaterEqual(bar.tabRect(0).left(),0)
        bar.setCurrentIndex(20);QApplication.processEvents()
        self.assertLessEqual(bar.tabRect(20).right(),bar.width())
        with patch('wcm.gui.QInputDialog.getText',return_value=('Still accessible',True)):
            plus.click()
        self.assertEqual(self.dialog.tabs.count(),22)

    def test_default_profile_cannot_be_removed(self):
        self.dialog.remove_profile(0)
        self.assertEqual(self.dialog.tabs.count(), 1)

    def test_cancel_does_not_modify_saved_paths(self):
        with patch('wcm.gui.QInputDialog.getText', return_value=('WiiLoaded', True)):
            self.dialog.add_profile()
        self.dialog.folder.setText('WL/Character')
        self.dialog.reject()
        self.assertFalse(self.memory.value(PROFILES_KEY))
        self.assertEqual(self.memory.value('characterPath'), 'RR/Character')

if __name__ == '__main__':
    unittest.main()
