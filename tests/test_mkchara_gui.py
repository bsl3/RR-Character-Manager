"""Exercise the existing wizard, explorer, conflict review and export action."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import importlib.util
import io
import unittest
from unittest.mock import patch
if importlib.util.find_spec('PySide6') is None:
    raise unittest.SkipTest('PySide6 unavailable')
from PySide6.QtWidgets import QApplication, QDialog
from wcm.gui import ImportWizard, MainWindow, STYLESHEET
from wcm.mkchara import read_package
from wcm.models import discover_models, source_entries
import test_mkchara as package_tests


class PackageGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=QApplication.instance() or QApplication([])
        cls.app.setStyle('Fusion');cls.app.setStyleSheet(STYLESHEET)

    def setUp(self):
        self.fixture=package_tests.PackageTests('test_roundtrip_different_slot_all_payloads_and_metadata')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)

    def test_wizard_prefills_metadata_preview_override_and_conflicts(self):
        f=self.fixture
        dialog=ImportWizard(f.pack,'lg');dialog.show();self.app.processEvents()
        dialog.source.setText(str(f.package));dialog.probe()
        self.assertEqual(dialog.name.text(),'Test Skin')
        self.assertEqual(dialog.author.text(),'Artist')
        self.assertEqual(dialog.base.currentData(),'wr')
        self.assertEqual(dialog.driver_choice.source_path,'Driver/wr.brres')
        self.assertIn('kart /',dialog.discovery.text())
        entries=source_entries(f.package)
        choice=next(c for c in discover_models(entries) if c.source_path=='ma_bike-wr.szs')
        class Explorer:
            chosen=choice
            def __init__(self,*args,**kwargs): self.entries=args[0]
            def exec(self): return QDialog.DialogCode.Accepted
            def deleteLater(self): pass
        with patch('wcm.gui.ModelExplorerDialog',Explorer):dialog.explore_models()
        self.assertEqual(dialog.driver_choice,choice)
        dialog.slot.setValue(7)
        with patch('wcm.gui.QMessageBox.warning') as warning:
            dialog.validate();warning.assert_called_once()
            self.assertIn('already exists',warning.call_args.args[2])
        self.assertIsNone(dialog.plan)
        dialog.base.setCurrentIndex(dialog.base.findData('lg'));dialog.slot.setValue(12)
        dialog.validate()
        self.assertEqual(dialog.result(),QDialog.DialogCode.Accepted)
        self.assertIn('LG slot 12',dialog.plan.description)
        self.assertNotIn(('lg',12),f.pack.inventory.skins,'Review mutated the installed pack')
        dialog.close();dialog.deleteLater();self.app.processEvents()

    def test_selected_export_action_writes_readable_package_without_pack_changes(self):
        f=self.fixture
        window=MainWindow(f.pack);window.change_base('wr');window.show();self.app.processEvents()
        window.table.selectRow(0);window.on_selected()
        self.assertTrue(window.export_action.isEnabled())
        target=f.root/'GuiExport.mkchara'
        original=f.pack.archive_path.read_bytes()
        with patch('wcm.gui.QFileDialog.getSaveFileName',return_value=(str(target),'Character packages (*.mkchara)')),patch('wcm.gui.QMessageBox.information') as information:
            window.export_action.trigger();information.assert_called_once()
        self.assertEqual(read_package(target).character['name'],'Test Skin')
        self.assertEqual(f.pack.archive_path.read_bytes(),original)
        window.clear_details();self.assertFalse(window.export_action.isEnabled())
        window.close();window.deleteLater();self.app.processEvents()

    def test_manual_folder_zip_and_explicit_icons_use_detected_previews(self):
        import zipfile
        from PIL import Image
        f=self.fixture
        dialog=ImportWizard(f.pack,'wr');dialog.show()
        self.addCleanup(dialog.close)
        archive=f.root/'Manual.zip'
        with zipfile.ZipFile(archive,'w') as output:
            for path in f.source.rglob('*'):
                if path.is_file(): output.write(path,path.relative_to(f.source))
        for source in (f.source,archive):
            dialog.source.setText(str(source));dialog.probe();self.app.processEvents()
            self.assertTrue(dialog.package_preview_widget.isVisible())
            for category in ('Portrait','Map'):
                label,_=dialog.package_icon_previews[category]
                self.assertFalse(label.pixmap().isNull())
                self.assertIn('.tpl',label.toolTip())
        dialog.source.setText(str(f.source/'wr.brres'));dialog.probe()
        for category in ('Portrait','Map'):
            self.assertEqual(dialog.package_icon_previews[category][0].text(),'Not detected')
        css=f.root/'Selected.png';Image.new('RGBA',(64,64),'blue').save(css)
        dialog.portrait.setText(str(css));dialog.map.setText(str(f.source/'wr.tpl'))
        dialog.portrait.editingFinished.emit();self.app.processEvents()
        for category in ('Portrait','Map'):
            self.assertFalse(dialog.package_icon_previews[category][0].pixmap().isNull())
        self.assertIn('Selected.png',dialog.package_icon_previews['Portrait'][0].toolTip())
