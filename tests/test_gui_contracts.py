"""Source-contract tests for the Qt view; PySide6 runtime requires Windows."""
import unittest
from pathlib import Path

GUI=Path(__file__).resolve().parents[1]/'wcm'/'gui.py'

class TestGUIContracts(unittest.TestCase):
    def test_two_column_game_order_without_weight_sections(self):
        src=GUI.read_text(encoding='utf-8')
        self.assertIn('grid.addWidget(tile,index//2,index%2)',src)
        self.assertNotIn('group_heading=QLabel(group_name.upper())',src)
        self.assertIn('for index,code in enumerate(DISPLAY_CODES)',src)

    def test_switching_character_forces_inspector_sync(self):
        src=GUI.read_text(encoding='utf-8')
        block=src[src.index('    def refresh_table(self):'):src.index('    def clear_details(self):')]
        self.assertIn('self.table.clearSelection()',block)
        self.assertIn('self.table.selectRow(nextrow)',block)
        self.assertIn('self.on_selected()',block)
        self.assertLess(block.index('self.table.selectRow(nextrow)'),block.index('self.on_selected()'))

    def test_css_preview_left_of_minimap(self):
        src=GUI.read_text(encoding='utf-8')
        ui=src[src.index('    def setup_content(self):'):src.index('    def change_base(self,code):')]
        css=ui.index('        css_col=QVBoxLayout()')
        mini=ui.index('        map_col=QVBoxLayout()')
        self.assertLess(css,mini)
        self.assertLess(ui.index('preview_row.addLayout(css_col)'),ui.index('preview_row.addLayout(map_col)'))
        self.assertIn('self.map_preview.setFixedSize(78,78)',ui)
        self.assertIn('self.portrait.setFixedSize(132,132)',ui)
        self.assertIn('self.pack.replace_map(',src)

    def test_hover_edit_badges_and_clickable_images(self):
        src=GUI.read_text(encoding='utf-8')
        self.assertIn('class EditableImagePreview(QPushButton):',src)
        self.assertIn('self._edit_badge = QLabel(',src)
        self.assertIn('self._edit_badge.show()',src)
        self.assertIn('self._edit_badge.hide()',src)
        self.assertIn('WA_TransparentForMouseEvents',src)
        self.assertIn('self.portrait=EditableImagePreview(',src)
        self.assertIn('self.map_preview=EditableImagePreview(',src)
        self.assertIn('self.portrait.clicked.connect(self.replace_css_portrait)',src)
        self.assertIn('self.map_preview.clicked.connect(self.replace_map_icon)',src)

    def test_no_image_border_or_replacement_buttons(self):
        src=GUI.read_text(encoding='utf-8')
        self.assertIn('QPushButton#CSSPreview { background: #23344a; border: none;',src)
        self.assertNotIn('border: 1px dashed',src)
        self.assertNotIn("button('Replace Map…',",src)
        self.assertNotIn("button('Replace CSS…',",src)

    def test_retro_rewind_brand(self):
        src=GUI.read_text(encoding='utf-8')
        self.assertIn('Retro Rewind Character Manager',src)
        self.assertIn("QSettings('Retro Rewind', 'Character Manager')",src)

if __name__=='__main__':unittest.main()

class TestModeGUIContracts(unittest.TestCase):
    def test_setup_opt_in_is_unchecked(self):
        src=GUI.read_text(encoding='utf-8')
        self.assertIn("QCheckBox('Developer Mode — edit distribution characters')", src)
        self.assertIn('self.developer_checkbox.setChecked(False)', src)
        self.assertIn('developer = editor.developer_checkbox.isChecked()', src)
        self.assertIn('developer_mode=developer', src)

    def test_regular_ui_disables_distribution_modification(self):
        src=GUI.read_text(encoding='utf-8')
        self.assertIn('if self.pack.developer_mode:', src)
        self.assertIn('self.move_action.setVisible(self.pack.developer_mode)', src)
        self.assertIn('self.move_button.setVisible(self.pack.developer_mode)', src)
        self.assertIn('editable = self.pack.can_edit_skin(self.current_code, slot)', src)
        self.assertIn('self.save_button.setEnabled(editable)', src)
        self.assertIn('self.portrait.setEditable(portrait_editable)', src)
        self.assertIn('self.map_preview.setEditable(portrait_editable)', src)
