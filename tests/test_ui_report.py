import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.ui import format_project_summary
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


class UIReportTests(unittest.TestCase):
    def test_summary_shows_materials_and_plates(self):
        project = ProjectInfo(Path("example.3mf"), {"printer_model": "Bambu Lab P1S"},
                              (FilamentInfo(1, "PETG", "#ff0000", ""),
                               FilamentInfo(2, "TPU", "#0000ff", "")),
                              (PlateInfo(1, 2), PlateInfo(2, 1)), ("A", "B"), (), ())
        summary = format_project_summary(project)
        self.assertIn("Bambu Lab P1S", summary)
        self.assertIn("2 placas", summary)
        self.assertIn("PETG", summary)
        self.assertIn("TPU", summary)
