import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.labels import (
    describe_change,
    format_duration,
    priority_code,
    priority_label,
    purpose_code,
    purpose_label,
)


class LabelsTest(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(None), "indisponível")
        self.assertEqual(format_duration(0), "0min")
        self.assertEqual(format_duration(50), "1min")
        self.assertEqual(format_duration(3600), "1h 00min")
        self.assertEqual(format_duration(5432), "1h 31min")

    def test_describe_change(self):
        desc = describe_change("nozzle_temperature", "220", "270")
        self.assertEqual(desc, "Temperatura do bico: 220 → 270 °C")

        desc_wall = describe_change("wall_loops", "2", "4")
        self.assertEqual(desc_wall, "Paredes: 2 → 4")

    def test_purpose_and_priority_labels_roundtrip(self):
        self.assertEqual(purpose_code(purpose_label("esforco")), "esforco")
        self.assertEqual(priority_code(priority_label("equilibrio")), "equilibrio")
        self.assertNotIn("_", purpose_label("funcional_leve"))
