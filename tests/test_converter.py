import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.converter import compare_geometry
from test_project import write_project


class ConverterTests(unittest.TestCase):
    def test_geometry_comparison_ignores_xml_formatting_and_metadata(self):
        mesh_a = b'''<model><metadata name="Application">Bambu</metadata><resources><object id="1"><mesh><vertices><vertex x="0" y="0" z="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/></vertices><triangles><triangle v1="0" v2="1" v3="2"/></triangles></mesh></object></resources></model>'''
        mesh_b = b'''<model>\n<metadata name="Application">ELEGOO</metadata>\n<resources><object id="1"><mesh><vertices><vertex z="0" y="0" x="0"/><vertex x="1" y="0" z="0"/><vertex x="0" y="1" z="0"/></vertices><triangles><triangle v3="2" v2="1" v1="0"/></triangles></mesh></object></resources></model>'''
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.3mf"
            target = Path(directory) / "target.3mf"
            write_project(source, names=[("3D/3dmodel.model", mesh_a), ("Metadata/project_settings.config", b"{}")])
            write_project(target, names=[("3D/3dmodel.model", mesh_b), ("Metadata/project_settings.config", b"{}")])
            result = compare_geometry(source, target)
        self.assertTrue(result.unchanged)

    def test_geometry_comparison_accepts_renamed_mesh_resource(self):
        mesh = b'<model><mesh><vertices><vertex x="1" y="2" z="3"/></vertices><triangles><triangle v1="0" v2="0" v3="0"/></triangles></mesh></model>'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.3mf"
            target = Path(directory) / "target.3mf"
            write_project(source, names=[("3D/3dmodel.model", b"<model/>"), ("3D/Objects/old.model", mesh)])
            write_project(target, names=[("3D/3dmodel.model", b"<model/>"), ("3D/Objects/new.model", mesh)])
            result = compare_geometry(source, target)
        self.assertTrue(result.unchanged)

    def test_geometry_comparison_allows_plate_repositioning(self):
        mesh = b'<model><mesh><vertices><vertex x="1" y="2" z="3"/></vertices><triangles><triangle v1="0" v2="0" v3="0"/></triangles></mesh></model>'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.3mf"
            target = Path(directory) / "target.3mf"
            write_project(source, names=[("3D/3dmodel.model", b'<model><item transform="1 0 0"/></model>'), ("3D/Objects/mesh.model", mesh)])
            write_project(target, names=[("3D/3dmodel.model", b'<model><item transform="1 10 10"/></model>'), ("3D/Objects/mesh.model", mesh)])
            result = compare_geometry(source, target)
        self.assertTrue(result.unchanged)

    def test_geometry_comparison_detects_changed_mesh(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.3mf"
            target = Path(directory) / "target.3mf"
            write_project(source)
            write_project(target, names=[
                ("3D/3dmodel.model", b"different mesh"),
                ("Metadata/project_settings.config", b"{}"),
            ])
            result = compare_geometry(source, target)
        self.assertFalse(result.unchanged)
        self.assertEqual(result.changed_resources, ("3D/3dmodel.model",))
