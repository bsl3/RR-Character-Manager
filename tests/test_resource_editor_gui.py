from fixture_paths import fixture_path, require_fixture
"""Resource editor UI checks; interactive Qt checks run where PySide6 is installed."""
from pathlib import Path
import importlib.util
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'wcm' / 'gui.py'


class ResourceEditorSourceContracts(unittest.TestCase):
    def test_filename_cells_have_persistent_text_inputs(self):
        source = SOURCE.read_text(encoding='utf-8')
        editor = source.split('class ResourceEditorDialog(', 1)[1].split('\nclass MainWindow(', 1)[0]
        self.assertIn('QLineEdit(physical.name, self.table)', editor)
        self.assertIn('self.table.setCellWidget(i, j, editor)', editor)
        self.assertIn('self.filename_inputs[row].text()', editor)
        self.assertIn('self.filename_inputs.get(row)', editor)

    def test_native_title_bar_controls(self):
        source = SOURCE.read_text(encoding='utf-8')
        editor = source.split('class ResourceEditorDialog(', 1)[1].split('\nclass MainWindow(', 1)[0]
        self.assertIn('Qt.WindowType.WindowMinMaxButtonsHint', editor)
        self.assertIn('Qt.WindowType.WindowCloseButtonHint', editor)
        self.assertIn('Qt.WindowType.WindowSystemMenuHint', editor)


@unittest.skipUnless(importlib.util.find_spec('PySide6') is not None, 'PySide6 unavailable in test environment')
class ResourceEditorQtContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_developer_filename_input_stages_physical_rename(self):
        import tempfile
        import zipfile
        from wcm.operations import CharacterPack
        from wcm.gui import ResourceEditorDialog
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            character = root / 'Character'
            (character / 'Driver').mkdir(parents=True)
            (character / 'Driver/lg-1.brres').write_bytes(b'original-driver')
            archive = root / 'Assets/ReplacedAssets.szs'
            archive.parent.mkdir()
            with zipfile.ZipFile(require_fixture('RRAssets.zip')) as z:
                archive.write_bytes(z.read('Assets/ReplacedAssets.szs'))
            pack = CharacterPack(character, archive, root / 'Patches', developer_mode=True)
            dialog = ResourceEditorDialog(pack, 'lg', 1)
            self.assertEqual(len(dialog.filename_inputs), 1)
            editor = dialog.filename_inputs[0]
            editor.setText('custom-driver.brres')
            dialog.save()
            self.assertIsNotNone(dialog.plan)
            self.assertEqual(dialog.plan.moves[0][1].name, 'custom-driver.brres')
            self.assertTrue(dialog.windowFlags() & __import__('PySide6.QtCore', fromlist=['Qt']).Qt.WindowType.WindowMinMaxButtonsHint)
            dialog.close()

    def test_standard_mode_original_files_remain_read_only(self):
        import tempfile
        import zipfile
        from wcm.operations import CharacterPack
        from wcm.gui import ResourceEditorDialog
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            character = root / 'Character'
            (character / 'Driver').mkdir(parents=True)
            (character / 'Driver/lg-1.brres').write_bytes(b'original-driver')
            archive = root / 'Assets/ReplacedAssets.szs'
            archive.parent.mkdir()
            with zipfile.ZipFile(require_fixture('RRAssets.zip')) as z:
                archive.write_bytes(z.read('Assets/ReplacedAssets.szs'))
            pack = CharacterPack(character, archive, root / 'Patches')
            dialog = ResourceEditorDialog(pack, 'lg', 1)
            self.assertFalse(dialog.filename_inputs)
            self.assertFalse(dialog.save_button.isEnabled())
            dialog.close()


if __name__ == '__main__':
    unittest.main()
