import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.converter import ConversionResult
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.professor import Advice
from maker_elegoo.profiles import Profile
from maker_elegoo.slicer import ExportResult, ValidationResult
from maker_elegoo.ui import format_conversion_report, format_project_summary
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


class UIReportTests(unittest.TestCase):
    def test_summary_shows_materials_and_plates(self):
        project = ProjectInfo(Path("example.3mf"), {"printer_model": "Bambu Lab P1S", "layer_height": "0.16"},
                              (FilamentInfo(1, "PETG", "#ff0000", ""),
                               FilamentInfo(2, "TPU", "#0000ff", "")),
                              (PlateInfo(1, 2), PlateInfo(2, 1)), ("A", "B"), (), (),
                              advanced_features=("Altura de camada variável (detectada no arquivo)",))
        summary = format_project_summary(project)
        self.assertIn("Bambu Lab P1S", summary)
        self.assertIn("0.16 mm", summary)
        self.assertIn("2 placas", summary)
        self.assertIn("PETG", summary)
        self.assertIn("TPU", summary)
        self.assertIn("Altura de camada variável", summary)

    def test_conversion_report_lists_professor_advices_and_alerts(self):
        plan = ConversionPlan(
            machine=Profile("ECC2 0.4", "machine", Path("m.json"), {}),
            process=Profile("0.20mm Standard", "process", Path("p.json"), {}),
            filaments=(Profile("Elegoo ABS @ECC2", "filament", Path("f.json"), {}),),
            machine_settings={}, process_settings={}, filament_settings=({},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        result = ConversionResult(
            True, Path("out.3mf"), "Todas as placas foram fatiadas",
            ExportResult(True, Path("out.3mf"), "ok"),
            ValidationResult(True, 1, "ok", (), 5432, 12.3),
            None, None, {},
        )
        advices = [
            Advice("process", None, "wall_loops", "2", "4", "Mais paredes", "Resiste mais", True),
            Advice("alert", None, "", "", "", "Câmara fechada", "Feche a porta", False),
        ]
        report = format_conversion_report(result, plan, professor_advices=advices)
        self.assertIn("O Professor ajustou", report)
        self.assertIn("Paredes: 2 → 4", report)
        self.assertIn("Resiste mais", report)
        self.assertIn("Câmara fechada", report)
        self.assertIn("1h 31min", report)
