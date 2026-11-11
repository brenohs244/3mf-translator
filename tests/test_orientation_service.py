import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "src"), str(Path(__file__).resolve().parent)]

from maker_elegoo.orientation import IDENTITY, OrientationError, load_scene
from maker_elegoo.orientation_service import apply_orientation, evaluate_orientations
from maker_elegoo.project import inspect_project
from maker_elegoo.slicer import ExportResult, ValidationResult
from test_orientation import write_figure


def plan():
    return SimpleNamespace(machine_settings={"printable_area": ["0x0", "256x0", "256x256", "0x256"],
                                             "printable_height": "256"},
                           unmapped={}, source_repairs={})


class LocalSlicer:
    def __init__(self, *, fail_alternatives=False):
        self.fail_alternatives = fail_alternatives
        self.exported = []

    def export(self, project, conversion_plan, destination):
        destination = Path(destination)
        with ZipFile(project.path) as source, ZipFile(destination, "w") as target:
            for name in source.namelist():
                content = source.read(name)
                if name == "Metadata/project_settings.config":
                    settings = json.loads(content)
                    settings["printer_model"] = "Elegoo Centauri Carbon 2"
                    content = json.dumps(settings).encode()
                target.writestr(name, content)
        self.exported.append(destination)
        return ExportResult(True, destination, "ok")

    def validate(self, project, plate_count):
        scene = load_scene(project)
        is_alt = any(abs(a - b) > 1e-4 for a, b in
                     zip(scene.item_transform[:9], IDENTITY[:9]))
        success = not (self.fail_alternatives and is_alt)
        return ValidationResult(success, 1 if success else 0, "ok" if success else "falha")


class OrientationServiceTests(unittest.TestCase):
    def test_recommends_sliced_alternative_and_cleans_temporary_files(self):
        with tempfile.TemporaryDirectory() as folder:
            project = inspect_project(write_figure(Path(folder) / "figure.3mf"))
            slicer = LocalSlicer()
            result = evaluate_orientations(project, plan(), "-Y", slicer)
            self.assertEqual(result.current.candidate.label, "Atual")
            self.assertTrue(result.current.result.success)
            self.assertNotEqual(result.recommended.label, "Atual")
            self.assertTrue(any(item.result.success for item in result.alternatives))
            self.assertTrue(all(not path.exists() for path in slicer.exported))
            self.assertTrue(project.path.exists())

    def test_failed_alternatives_do_not_replace_current(self):
        with tempfile.TemporaryDirectory() as folder:
            project = inspect_project(write_figure(Path(folder) / "figure.3mf"))
            result = evaluate_orientations(project, plan(), "-Y", LocalSlicer(fail_alternatives=True))
        self.assertEqual(result.recommended.label, "Atual")

    def test_cancelled_analysis_does_not_export(self):
        with tempfile.TemporaryDirectory() as folder:
            project = inspect_project(write_figure(Path(folder) / "figure.3mf"))
            slicer = LocalSlicer()
            with self.assertRaisesRegex(OrientationError, "cancelada"):
                evaluate_orientations(project, plan(), "-Y", slicer, cancelled=lambda: True)
            self.assertEqual(slicer.exported, [])

    def test_approved_orientation_creates_validated_copy_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as folder:
            source = write_figure(Path(folder) / "figure.3mf")
            original = source.read_bytes()
            project = inspect_project(source)
            slicer = LocalSlicer()
            analysis = evaluate_orientations(project, plan(), "-Y", slicer)
            destination = Path(folder) / "oriented.3mf"
            result = apply_orientation(project, plan(), analysis.recommended, destination, slicer)
            self.assertTrue(result.success, result.message)
            self.assertTrue(destination.exists())
            self.assertEqual(source.read_bytes(), original)
            for actual, expected in zip(load_scene(destination).item_transform[:9],
                                        analysis.recommended.item_transform[:9]):
                self.assertAlmostEqual(actual, expected, places=6)

    def test_failed_application_does_not_leave_unvalidated_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            project = inspect_project(write_figure(Path(folder) / "figure.3mf"))
            candidate = evaluate_orientations(project, plan(), "-Y", LocalSlicer()).recommended
            destination = Path(folder) / "oriented.3mf"
            result = apply_orientation(project, plan(), candidate, destination,
                                       LocalSlicer(fail_alternatives=True))
            self.assertFalse(result.success)
            self.assertFalse(destination.exists())
