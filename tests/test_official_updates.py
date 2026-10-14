import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PySide6.QtWidgets import QApplication, QMessageBox
from wcm.gui import MainWindow
from wcm.updates import DEFAULT_REPOSITORY, version

class OfficialUpdates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_official_repository_and_equivalent_tag(self):
        self.assertEqual(DEFAULT_REPOSITORY,'https://github.com/bsl3/RR-Character-Manager')
        self.assertEqual(version('v1.0.0'),version('1.0'))

    def test_startup_and_manual_checks_use_official_repository(self):
        for manual in (False,True):
            window=SimpleNamespace(_update_worker=None,update_result=Mock())
            with patch('wcm.gui.UpdateWorker') as worker:
                MainWindow.check_updates(window,manual)
                worker.assert_called_once_with(DEFAULT_REPOSITORY,window)
                worker.return_value.start.assert_called_once()
                callback=worker.return_value.result.connect.call_args.args[0]
                callback(None,'');window.update_result.assert_called_once_with(None,'',manual)

    def test_in_progress_check_is_not_restarted(self):
        window=SimpleNamespace(_update_worker=Mock())
        window._update_worker.isRunning.return_value=True
        with patch('wcm.gui.UpdateWorker') as worker:
            MainWindow.check_updates(window,True);worker.assert_not_called()

    def test_automatic_no_update_is_silent_manual_reports(self):
        with patch('wcm.gui.QMessageBox.information') as info:
            MainWindow.update_result(None,None,'',False);info.assert_not_called()
            MainWindow.update_result(None,None,'',True);info.assert_called_once()

    def test_download_prompt_opens_selected_platform_url(self):
        release={'version':'v1.1','download':DEFAULT_REPOSITORY+'/releases/download/v1.1/manager-windows-x86_64.zip'}
        with patch('wcm.gui.QMessageBox') as box, patch('wcm.gui.QDesktopServices.openUrl') as opened:
            box.ButtonRole=QMessageBox.ButtonRole
            download=object();box.return_value.addButton.side_effect=[download,object()]
            box.return_value.clickedButton.return_value=download
            MainWindow.update_result(None,release,'',False)
            opened.assert_called_once();self.assertEqual(opened.call_args.args[0].toString(),release['download'])

    def test_later_does_not_open_download(self):
        release={'version':'v1.1','download':DEFAULT_REPOSITORY+'/releases/tag/v1.1'}
        with patch('wcm.gui.QMessageBox') as box, patch('wcm.gui.QDesktopServices.openUrl') as opened:
            box.ButtonRole=QMessageBox.ButtonRole
            download=object();later=object();box.return_value.addButton.side_effect=[download,later]
            box.return_value.clickedButton.return_value=later
            MainWindow.update_result(None,release,'',False);opened.assert_not_called()

    def test_configuration_menu_and_saved_repository_override_are_removed(self):
        import inspect
        self.assertFalse(hasattr(MainWindow,'configure_updates'))
        self.assertNotIn('updates/repository',inspect.getsource(MainWindow.check_updates))
