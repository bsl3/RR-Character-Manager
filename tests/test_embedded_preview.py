from fixture_paths import fixture_path, require_fixture
"""Real-fixture tests for the BRRES geometry preview (no GUI needed)."""
from pathlib import Path
import unittest
from wcm.models import source_entries, discover_models, extract_model_bytes
from wcm.preview3d import decode_brres, PreviewDecodeError

SAMUS = fixture_path('samus_v10_hotfix.zip')
BIKER = fixture_path('bikerwario-porko_v1(1).zip')

class SafetyTests(unittest.TestCase):
    def test_rejects_non_brres(self):
        for raw in (b'',b'MDL0'+bytes(80),b'bres'+bytes(80)):
            with self.assertRaises(PreviewDecodeError):
                decode_brres(raw)

    def test_rejects_unbounded_input(self):
        with self.assertRaisesRegex(PreviewDecodeError, 'too large'):
            decode_brres(b'bres'+bytes(128*1024*1024))

@unittest.skipUnless(SAMUS.exists() and BIKER.exists(), 'Real user models not provided')
class RealCharacterModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.samus_entries = source_entries(SAMUS)
        cls.biker_entries = source_entries(BIKER)

    def find(self, entries, ending, member=''):
        c = next(c for c in discover_models(entries) if
                 c.source_path.endswith(ending) and c.archive_member == member)
        return decode_brres(extract_model_bytes(entries, c))

    def test_samus_menu_has_drawable_triangles(self):
        mesh = self.find(self.samus_entries,'rs_menu.brres')
        self.assertGreater(len(mesh.vertices), 500)
        self.assertGreater(len(mesh.triangles), 900)
        self.assertTrue(all(max(face[:3]) < len(mesh.vertices) for face in mesh.triangles))

    def test_samus_two_distinct_suits_have_embedded_geometry(self):
        kart = self.find(self.samus_entries,'la_kart-rs.szs','driver_model.brres')
        bike = self.find(self.samus_entries,'la_bike-rs.szs','driver_model.brres')
        self.assertGreater(len(kart.triangles), 300)
        self.assertGreater(len(bike.triangles), 300)
        self.assertNotEqual(kart.vertices,bike.vertices)

    def test_biker_wario_standalone_drawable(self):
        mesh = self.find(self.biker_entries,'Full Slot/Driver/wr.brres')
        self.assertGreater(len(mesh.triangles), 400)

class NativePreviewGUIContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gui = (Path(__file__).parents[1] / 'wcm/gui.py').read_text(encoding='utf-8')
        cls.widget = (Path(__file__).parents[1] / 'wcm/preview_widget.py').read_text(encoding='utf-8')

    def test_selected_model_decoded_to_embedded_viewport(self):
        self.assertIn('self.viewport = MeshPreviewWidget()',self.gui)
        self.assertIn('decode_brres(data, chosen)',self.gui)
        self.assertIn('self.viewport.set_mesh(mesh)',self.gui)

    def test_offline_rotation_and_zoom_controls(self):
        self.assertIn('def mouseMoveEvent',self.widget)
        self.assertIn('def wheelEvent',self.widget)
        self.assertIn('def paintEvent',self.widget)
        self.assertIn('def set_wireframe',self.widget)

if __name__=='__main__': unittest.main()
