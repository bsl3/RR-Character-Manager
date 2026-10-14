"""Displayed pack paths remain useful identifiers for exact BRRES extraction."""
import tempfile
import unittest
from pathlib import Path
from wcm.models import find_installed_models, extract_model_bytes, installed_model_label

class InstalledPaths(unittest.TestCase):
    def test_character_and_named_patch_folder_never_show_host_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);char=root/'Character';patch=root/'My local overrides'
            files=[char/'Driver/mr-1.brres',patch/'Fire Mario/Driver/mr-1.brres']
            for i,file in enumerate(files):
                file.parent.mkdir(parents=True);file.write_bytes(b'bres'+bytes([i]))
            candidates,entries=find_installed_models(files,patches=patch,character=char)
            self.assertEqual([c.label for c in candidates],
                             ['Character/Driver/mr-1.brres','Patches/Fire Mario/Driver/mr-1.brres'])
            for i,candidate in enumerate(candidates):
                self.assertEqual(extract_model_bytes(entries,candidate),b'bres'+bytes([i]))
                self.assertNotIn(str(root),candidate.label)

    def test_default_labels_and_unrelated_file_use_local_path(self):
        self.assertEqual(installed_model_label(Path('Character/Driver/mr-1.brres')),'Character/Driver/mr-1.brres')
        self.assertEqual(installed_model_label(Path('Patches/Skin/file.szs')),'Patches/Skin/file.szs')
        self.assertEqual(installed_model_label(Path('unrelated/file.brres')),'file.brres')
