import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.optimization import compare_objectives, OBJECTIVES


class OptimizationTests(unittest.TestCase):
    def test_variants_keep_original_plan_and_use_distinct_paths(self):
        @dataclass(frozen=True)
        class Plan:
            process_settings: dict

        plan = Plan({"sparse_infill_density": "20%", "wall_loops": "2"})
        project = SimpleNamespace(path=Path("sample.3mf"))
        with tempfile.TemporaryDirectory() as directory, patch(
                "maker_elegoo.optimization.convert_project", side_effect=lambda p, q, d, s: d) as convert:
            variants = compare_objectives(project, plan, Path(directory), object())
        self.assertEqual(len(variants), len(OBJECTIVES))
        self.assertEqual(len({v.result for v in variants}), len(OBJECTIVES))
        self.assertEqual(plan.process_settings["wall_loops"], "2")
        self.assertEqual(convert.call_count, len(OBJECTIVES))
        self.assertEqual(OBJECTIVES["economia"]["sparse_infill_density"], "10%")

    def test_compare_objectives_respects_nozzle_and_machine_layer_limits(self):
        @dataclass(frozen=True)
        class Plan:
            process_settings: dict
            machine_settings: dict

        plan = Plan(
            {"layer_height": "0.26", "sparse_infill_density": "15%"},
            {"nozzle_diameter": ["0.4"], "min_layer_height": ["0.08"], "max_layer_height": ["0.28"]},
        )
        project = SimpleNamespace(path=Path("sample.3mf"))
        with tempfile.TemporaryDirectory() as directory, patch(
                "maker_elegoo.optimization.convert_project", side_effect=lambda p, q, d, s: d):
            variants = {v.objective: v for v in compare_objectives(project, plan, Path(directory), object())}
        # 0.26 * 1.2 = 0.312 > 0.28 max para bico 0.4 -> limitado a 0.28
        self.assertEqual(variants["velocidade"].changed.get("layer_height"), "0.28")


