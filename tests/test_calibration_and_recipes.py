import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.calibration import (
    ShrinkageStats,
    compute_shrinkage_stats,
    write_calibration_source_3mf,
)
from maker_elegoo.geometry_check import analyze_project_geometry
from maker_elegoo.history import (
    FeedbackRecord,
    append_feedback_record,
    find_validated_recipes,
    load_feedback_history,
    adjust_advices_from_history,
)
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.professor import PrintGoal, apply_advice, validate_change
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo, inspect_project


class CalibrationAndRecipesTests(unittest.TestCase):
    def test_generates_manifold_calibration_3mf_inspectable_and_flat(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "calibracao.3mf"
            write_calibration_source_3mf(target, material="ABS")
            info = inspect_project(target)
            geom = analyze_project_geometry(target)

        self.assertEqual(len(info.plates), 1)
        self.assertEqual(len(info.filaments), 1)
        self.assertEqual(info.filaments[0].material, "ABS")
        self.assertEqual(geom.object_count, 3)
        self.assertAlmostEqual(geom.bounds[4], 0.0, places=3)
        self.assertAlmostEqual(geom.bounds[5], 4.0, places=3)
        # Barra de 50.00 mm presente como primeiro objeto
        self.assertAlmostEqual(geom.parts[0].size_x, 50.0, places=2)
        self.assertGreater(geom.contact_mm2, 500.0)

    def test_compute_shrinkage_stats_and_validation_bounds(self):
        stats = compute_shrinkage_stats(49.70)
        self.assertIsInstance(stats, ShrinkageStats)
        self.assertAlmostEqual(stats.shrinkage_pct, 0.60, places=2)
        self.assertEqual(stats.recommended_filament_shrink, "99.4%")
        self.assertAlmostEqual(stats.xy_scale_factor, 50.0 / 49.70, places=4)
        with self.assertRaises(ValueError):
            compute_shrinkage_stats(20.0)

    def test_history_roundtrip_backward_compatibility_and_validated_recipes(self):
        with tempfile.TemporaryDirectory() as directory:
            hist_file = Path(directory) / "hist.json"
            # Grava registro legado sem novos campos para checar retrocompatibilidade
            legacy_payload = [{
                "timestamp": "2026-11-10T10:00:00",
                "project_label": "suporte_antigo",
                "source_material": "PLA",
                "target_material": "ABS",
                "nozzle_mm": "0.4",
                "purpose": "esforco",
                "priority": "qualidade",
                "load_type": "flexao_lateral",
                "visual_result": "aprovado",
                "applied_params": {"wall_loops": "4", "layer_height": "0.2"},
                "notes": "",
            }]
            hist_file.write_text(json.dumps(legacy_payload), encoding="utf-8")

            append_feedback_record(
                FeedbackRecord(
                    timestamp="",
                    project_label="calibracao_abs",
                    source_material="ABS",
                    target_material="ABS",
                    nozzle_mm="0.4",
                    purpose="moveis",
                    priority="qualidade",
                    load_type="decorativa",
                    visual_result="aprovado",
                    applied_params={"wall_loops": "3", "layer_height": "0.2"},
                    notes="Barra 49.70 mm, folga 0.20 mm deslizou livre",
                    filament_brand="3D FILA Preto",
                    profile_name="0.20mm Standard",
                    measured_bar_mm=49.70,
                    fitted_clearance_mm=0.20,
                ),
                path=hist_file,
            )

            records = load_feedback_history(hist_file)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].filament_brand, "")
            self.assertEqual(records[1].measured_bar_mm, 49.70)

            recipes = find_validated_recipes(
                records,
                "ABS",
                nozzle_mm="0.4",
                filament_brand="3D FILA Preto",
            )
            self.assertGreaterEqual(len(recipes), 1)
            top = recipes[0]
            self.assertEqual(top.filament_brand, "3D FILA Preto")
            self.assertEqual(top.recommended_filament_shrink, "99.4%")
            self.assertAlmostEqual(top.best_clearance_mm, 0.20, places=2)

            plan = ConversionPlan(
                machine=Profile("CC2", "machine", Path("m.json"), {}),
                process=Profile("0.20", "process", Path("p.json"), {}),
                filaments=(Profile("ABS 3D FILA", "filament", Path("f.json"), {}),),
                machine_settings={"printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"]},
                process_settings={"layer_height": "0.2", "wall_loops": "2", "xy_hole_compensation": "0"},
                filament_settings=({"filament_type": ["ABS"], "filament_shrink": ["100%"]},),
                transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
            )
            project = ProjectInfo(
                path=Path("p.3mf"),
                source_settings={"layer_height": "0.2"},
                filaments=(FilamentInfo(1, "ABS", "#000000", "ABS"),),
                plates=(PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
                objects=("Part",),
                archive_entries=("3D/3dmodel.model",),
                warnings=(),
            )
            goal = PrintGoal("moveis", "qualidade", fit_clearance="encaixe_justo", physical_material="ABS")
            adjusted = adjust_advices_from_history([], project, plan, goal, records)
            shrink_alerts = [a for a in adjusted if "contração medida" in a.title.lower()]
            self.assertEqual(len(shrink_alerts), 1)
            self.assertIn("100.60%", shrink_alerts[0].proposed)
            self.assertTrue(validate_change("process", "xy_hole_compensation", "0.08", plan))
            applied = apply_advice(
                plan,
                [a for a in adjusted if a.scope == "process" and a.key == "xy_hole_compensation"],
            )
            recipe_alerts = [a for a in adjusted if "receita validada" in a.title.lower()]
            self.assertEqual(len(recipe_alerts), 1)
            self.assertIsNotNone(applied)

            multi_plan = ConversionPlan(
                machine=plan.machine,
                process=plan.process,
                filaments=(plan.filaments[0], plan.filaments[0]),
                machine_settings=plan.machine_settings,
                process_settings=plan.process_settings,
                filament_settings=({"filament_type": ["ABS"]}, {"filament_type": ["ABS"]}),
                transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
            )
            multi_adjusted = adjust_advices_from_history([], project, multi_plan, goal, records)
            self.assertEqual(
                len([a for a in multi_adjusted if "receita validada" in a.title.lower()]),
                1,
            )
            self.assertEqual(
                len([a for a in multi_adjusted if "contração medida" in a.title.lower()]),
                1,
            )


if __name__ == "__main__":
    unittest.main()
