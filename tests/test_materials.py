import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.materials import analyze_material_change
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


class MaterialTests(unittest.TestCase):
    def test_reports_pla_to_petg_changes_by_slot(self):
        project = ProjectInfo(Path("source.3mf"), {
            "nozzle_temperature": ["210"], "textured_plate_temp": ["60"],
            "fan_max_speed": ["100"], "filament_max_volumetric_speed": ["21"],
        }, (FilamentInfo(1, "PLA", "#fff", ""),), (PlateInfo(1, 1),), (), (), ())
        target = {"filament_type": ["PETG"], "nozzle_temperature": ["250"],
                  "textured_plate_temp": ["70"], "fan_max_speed": ["40"],
                  "filament_max_volumetric_speed": ["11"]}
        findings = analyze_material_change(project, [target])
        self.assertEqual({item.key for item in findings}, {
            "filament_type", "nozzle_temperature", "textured_plate_temp", "fan_max_speed", "filament_max_volumetric_speed"})
        self.assertTrue(all(item.slot == 1 for item in findings))
