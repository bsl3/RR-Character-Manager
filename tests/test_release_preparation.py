"""Source checks that do not build an executable."""
import importlib.util
import unittest
import sys
from pathlib import Path
from unittest.mock import patch
from wcm import __version__
from wcm.updates import version, release_url

ROOT = Path(__file__).resolve().parents[1]


class ReleasePreparation(unittest.TestCase):
    def test_release_version_and_windows_metadata(self):
        self.assertEqual(__version__, '1.0')
        self.assertEqual(version(__version__), (1, 0, 0))
        self.assertGreater(version('v1.0.1'), version(__version__))
        if sys.platform != 'win32' or importlib.util.find_spec('PyInstaller') is None:
            self.skipTest('PyInstaller is only needed for packaging checks')
        from PyInstaller.utils.win32.versioninfo import load_version_info_from_text_file
        info = load_version_info_from_text_file(str(ROOT / 'tools/windows_version.txt'))
        self.assertEqual((info.ffi.fileVersionMS, info.ffi.fileVersionLS), (1 << 16, 0))
        spec = (ROOT / 'RR Character Manager.spec').read_text(encoding='utf-8')
        self.assertIn('from wcm import __version__', spec)
        self.assertNotIn('C:/Users/', spec)

    def test_build_script_uses_one_spec_and_has_no_import_side_effects(self):
        spec = importlib.util.spec_from_file_location('release_build', ROOT / 'tools/build_windows_exe.py')
        module = importlib.util.module_from_spec(spec)
        with patch('subprocess.run') as run:
            spec.loader.exec_module(module)
            run.assert_not_called()
        with patch.object(module, 'build_release') as build, patch.object(module.sys, 'platform', 'win32'):
            module.main()
            build.assert_called_once_with([])
        from tools.build_release import build_command
        self.assertIn(str(ROOT / 'RR Character Manager.spec'), build_command())

    def test_release_links_allow_repository_capitalization(self):
        self.assertTrue(release_url('https://github.com/Owner/Repo/releases/tag/v1.1', 'owner/repo', 'tag'))
        self.assertFalse(release_url('https://example.com/Owner/Repo/releases/tag/v1.1', 'owner/repo', 'tag'))
