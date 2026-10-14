import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from wcm.updates import latest, platform_key
from wcm.portable_files import rename_new


class PortableRelease(unittest.TestCase):
    def test_platform_architectures(self):
        for system, machine, expected in [('win32','AMD64','windows-x86_64'),('darwin','arm64','macos-arm64'),('darwin','x86_64','macos-x86_64'),('linux','aarch64','linux-arm64')]:
            self.assertEqual(platform_key(system,machine),expected)
        self.assertEqual(platform_key('linux','unknown'),'')

    def test_download_matches_platform_and_unknown_uses_page(self):
        page='https://github.com/a/b/releases/tag/v1.1'
        targets=['windows-x86_64','macos-arm64','macos-x86_64','linux-x86_64']
        data={'tag_name':'v1.1','html_url':page,'assets':[{'state':'uploaded','name':'manager-'+t+'.zip','browser_download_url':'https://github.com/a/b/releases/download/v1.1/manager-'+t+'.zip'} for t in targets]}
        def opener(request,timeout):return io.BytesIO(json.dumps(data).encode())
        for target in targets:
            with patch('wcm.updates.platform_key',return_value=target):
                self.assertTrue(latest('https://github.com/a/b','1.0',opener)['download'].endswith('-'+target+'.zip'))
        with patch('wcm.updates.platform_key',return_value=''):
            self.assertEqual(latest('https://github.com/a/b','1.0',opener)['download'],page)

    def test_native_rename_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source';target=Path(folder)/'target'
            source.write_bytes(b'new');target.write_bytes(b'original')
            with self.assertRaises(OSError):rename_new(source,target)
            self.assertEqual(target.read_bytes(),b'original')
            self.assertEqual(source.read_bytes(),b'new')
            target.unlink();rename_new(source,target)
            self.assertFalse(source.exists());self.assertEqual(target.read_bytes(),b'new')

    def test_build_environment_removes_host_qt_paths(self):
        from tools.build_release import build_environment
        with patch.dict('os.environ',{'QT_PLUGIN_PATH':'foreign','QML2_IMPORT_PATH':'foreign','PYTHONPATH':'foreign'}):
            env=build_environment()
        for key in ('QT_PLUGIN_PATH','QML2_IMPORT_PATH','PYTHONPATH'):self.assertNotIn(key,env)
