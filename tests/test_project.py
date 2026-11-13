import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.project import ProjectError, inspect_project


MODEL = b'<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" type="model"/></resources></model>'
SETTINGS = b'''<config><object id="1"><metadata key="name" value="Cube"/></object><plate><model_instance object_id="1"/></plate><plate/></config>'''


def write_project(path, names=None, settings=None):
    entries = names or [
        ("3D/3dmodel.model", MODEL),
        ("Metadata/model_settings.config", SETTINGS),
        ("Metadata/project_settings.config", json.dumps(settings or {
            "printer_model": "Bambu Lab P1S",
            "filament_type": ["PLA", "PETG"],
            "filament_colour": ["#FF0000", "#0000FF"],
            "filament_settings_id": ["A", "B"],
        }).encode()),
    ]
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Duplicate name:", category=UserWarning)
        with ZipFile(path, "w") as archive:
            for name, payload in entries:
                archive.writestr(name, payload)


class ProjectTests(unittest.TestCase):
    def test_reads_filaments_plates_and_object_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.3mf"
            write_project(path)
            project = inspect_project(path)
        self.assertEqual(project.source_settings["printer_model"], "Bambu Lab P1S")
        self.assertEqual([f.material for f in project.filaments], ["PLA", "PETG"])
        self.assertEqual([f.color for f in project.filaments], ["#FF0000", "#0000FF"])
        self.assertEqual(len(project.plates), 2)
        self.assertEqual(project.plates[0].object_ids, ("1",))
        self.assertEqual(project.objects, ("Cube",))

    def test_rejects_duplicate_and_unsafe_archive_names(self):
        for extra in ("../outside", "3D/3dmodel.model"):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "bad.3mf"
                write_project(path, names=[
                    ("3D/3dmodel.model", MODEL),
                    (extra, b"x"),
                ])
                with self.assertRaises(ProjectError):
                    inspect_project(path)

    def test_rejects_missing_project_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.3mf"
            write_project(path, names=[("3D/3dmodel.model", MODEL)])
            with self.assertRaisesRegex(ProjectError, "configurações"):
                inspect_project(path)

    def test_rejects_excessive_uncompressed_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.3mf"
            write_project(path)
            with self.assertRaises(ProjectError):
                inspect_project(path, max_uncompressed_bytes=10)

    def test_detects_advanced_features_from_3mf_entries_and_xml(self):
        adv_model = b'<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources><object id="1" type="model"><mesh><triangles><triangle v1="0" v2="1" v3="2" paint_color="4"/></triangles></mesh></object></resources></model>'
        adv_settings = b'''<config><object id="1"><metadata key="name" value="Fig"/><metadata key="support_type" value="tree(manual)"/><part id="1" subtype="modifier_part"/></object><plate><model_instance object_id="1"/></plate></config>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "adv.3mf"
            write_project(path, names=[
                ("3D/3dmodel.model", adv_model),
                ("Metadata/model_settings.config", adv_settings),
                ("Metadata/layer_heights_profile.txt", b"object_id=1|0.0;0.2"),
                ("Metadata/custom_gcode_per_layer.xml", b"<custom_gcodes/>"),
                ("Metadata/project_settings.config", json.dumps({"printer_model": "Bambu Lab A1"}).encode()),
            ])
            project = inspect_project(path)
        joined = " | ".join(project.advanced_features)
        self.assertIn("camada variável", joined.lower())
        self.assertIn("g-code", joined.lower())
        self.assertIn("modificador", joined.lower())
        self.assertIn("pintura", joined.lower())
        self.assertIn("suporte manual", joined.lower())
