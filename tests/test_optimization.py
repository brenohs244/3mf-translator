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

    def test_compare_objectives_covers_all_five_and_formats_per_plate_without_false_strength_claim(self):
        from maker_elegoo.optimization import OBJECTIVES, Variant, format_objective_comparison
        from maker_elegoo.professor import PrintGoal
        from maker_elegoo.slicer import ExportResult, PlateValidationMetric, ValidationResult
        from maker_elegoo.converter import ConversionResult

        self.assertEqual(
            tuple(OBJECTIVES.keys()),
            ("original", "qualidade", "velocidade", "equilibrio", "economia"),
        )

        variants = []
        for idx, (obj, changed, secs1, g1, secs2, g2) in enumerate(
            [
                ("original", {}, 1800, 10.0, 1200, 6.0),
                ("qualidade", {"layer_height": "0.16"}, 2400, 10.2, 1600, 6.1),
                ("velocidade", {"layer_height": "0.24"}, 1300, 9.8, 900, 5.9),
                ("equilibrio", {"sparse_infill_density": "20%", "wall_loops": "3"}, 2000, 11.4, 1400, 6.8),
                ("economia", {"sparse_infill_density": "10%"}, 1650, 8.7, 1100, 5.1),
            ],
            1,
        ):
            val = ValidationResult(
                True,
                2,
                "Todas as placas foram fatiadas",
                (),
                secs1 + secs2,
                round(g1 + g2, 2),
                (
                    PlateValidationMetric(1, secs1, g1),
                    PlateValidationMetric(2, secs2, g2),
                ),
            )
            dest = Path(f"out_{obj}.3mf")
            res = ConversionResult(
                True,
                dest,
                "Conversão e fatiamento concluídos",
                ExportResult(True, dest, "Projeto ELEGOO exportado"),
                val,
                None,
                None,
                {},
            )
            variants.append(Variant(obj, res, changed))

        goal = PrintGoal(
            purpose="esforco",
            priority="equilibrio",
            load_type="tracao_eixo_z",
            criticality="alta",
            fit_clearance="sem_encaixe",
            heat_exposure="ambiente_interno",
            physical_material="ABS",
        )
        text = format_objective_comparison(tuple(variants), goal=goal)
        lower = text.lower()
        for obj in ("original", "qualidade", "velocidade", "equilibrio", "economia"):
            self.assertIn(obj, lower)
        self.assertIn("placa 1", lower)
        self.assertIn("placa 2", lower)
        self.assertIn("eixo z", lower)
        self.assertIn("tração perpendicular às camadas", lower)
        self.assertNotIn("mais forte", lower)
        self.assertIn("resistência mecânica não comprovada", lower)
        for cls_heading in (
            "verificado no 3mf",
            "verificado pelo fatiamento",
            "estimado por regra/ia",
            "depende de teste físico",
        ):
            self.assertIn(cls_heading, lower)



