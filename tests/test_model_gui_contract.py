"""Lightweight source contracts for model viewer and Qt button signal bug."""
from pathlib import Path
import unittest

GUI = Path(__file__).parents[1] / 'wcm/gui.py'

class ModelGUIContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = GUI.read_text(encoding='utf-8')

    def test_bump_checked_bool_not_treated_as_amount(self):
        self.assertIn('if isinstance(amount, bool):\n            amount = None', self.source)
        self.assertIn('amount = int(self.bump_amount.text())', self.source)

    def test_model_explorer_connected_to_import_and_selected_skin(self):
        self.assertIn('class ModelExplorerDialog(QDialog):', self.source)
        self.assertIn('def explore_models(self):', self.source)
        self.assertIn('def view_installed_model(self):', self.source)
        self.assertIn("button('View Model…', self.view_installed_model)", self.source)
        self.assertIn('driver_candidate=self.driver_choice', self.source)
        self.assertIn('self.table.cellDoubleClicked.connect(', self.source)

    def test_external_viewer_preserves_windows_and_native_launch_paths(self):
        self.assertIn("title = 'Locate BrawlCrate.exe' if sys.platform == 'win32' else 'Choose a BRRES viewer'", self.source)
        self.assertIn("'externalModelViewer'", self.source)
        self.assertIn("else [exe, str(target)]", self.source)
        self.assertIn("['open', '-a', exe, str(target)]", self.source)
        self.assertIn('subprocess.Popen(command)', self.source)
