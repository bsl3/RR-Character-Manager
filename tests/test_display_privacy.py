"""Display-contract tests for read-only previews and screenshot-safe pack paths."""
import ast
from pathlib import Path
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'wcm' / 'gui.py').read_text(encoding='utf-8')


def masking_function():
    tree = ast.parse(SOURCE)
    fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'mask_windows_user')
    namespace = {'re': __import__('re')}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), '<mask_windows_user>', 'exec'), namespace)
    return namespace['mask_windows_user']


class TestReadOnlyPortrait(unittest.TestCase):
    def test_image_widget_remains_enabled_and_colored_in_standard_mode(self):
        self.assertIn('self.portrait.setEditable(portrait_editable)', SOURCE)
        self.assertIn('self.map_preview.setEditable(editable)', SOURCE)
        self.assertNotIn('self.portrait.setEnabled(editable)', SOURCE)
        self.assertNotIn('self.map_preview.setEnabled(editable)', SOURCE)
        preview_class = SOURCE.split('class EditableImagePreview(QPushButton):', 1)[1].split('class CenteredCSSDelegate', 1)[0]
        self.assertIn('self._editable = bool(editable)', preview_class)
        self.assertIn('if self._editable:', preview_class)
        self.assertNotIn('super().setEnabled(', preview_class)

    def test_edit_permission_still_guarded_for_clicks(self):
        self.assertIn('if not self.pack.can_replace_portrait(self.current_code, self.current_slot):', SOURCE)
        self.assertIn('self.save_button.setEnabled(editable)', SOURCE)
        self.assertIn('self.portrait.setEditable(portrait_editable)', SOURCE)
        self.assertIn('self.map_preview.setEditable(editable)', SOURCE)


class TestPathPrivacy(unittest.TestCase):
    def test_mask_only_username_with_exact_number_of_stars(self):
        mask = masking_function()
        self.assertEqual(mask(r'C:\Users\kafia\Downloads\RetroRewind6\Character'),
                         r'C:\Users\*****\Downloads\RetroRewind6\Character')
        self.assertEqual(mask('C:/Users/Maria Lee/Documents/Character'),
                         'C:/Users/*********/Documents/Character')
        self.assertEqual(mask(r'D:\RR\Character'), r'D:\RR\Character')
        self.assertEqual(mask(r'C:\Users\One\Users\Three\Character'),
                         r'C:\Users\***\Users\*****\Character')

    def test_clicked_path_copies_unmasked_version(self):
        path_widget = SOURCE.split('class ClickToCopyPath(QLabel):', 1)[1].split('def note(', 1)[0]
        self.assertIn('self.setText(mask_windows_user(self._full_path))', path_widget)
        self.assertIn('QApplication.clipboard().setText(self._full_path)', path_widget)
        self.assertIn('Qt.MouseButton.LeftButton', path_widget)
        self.assertIn('self.subtitle.setPath(str(self.pack.character))', SOURCE)
        self.assertNotIn('self.subtitle.setText(f\'{mode_name}', SOURCE)


if __name__ == '__main__':
    unittest.main()
