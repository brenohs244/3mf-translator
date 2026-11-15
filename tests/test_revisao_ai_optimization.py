"""Testes TDD para Task 29: paridade do Gemini, merge offline e alinhamento do comparador de 5 alternativas."""

from __future__ import annotations

import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.ai_client import GeminiClient, advise_gemini
from maker_elegoo.converter import ConversionResult
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.optimization import compare_objectives, format_objective_comparison
from maker_elegoo.professor import Advice, PrintGoal, advise_offline, merge_with_offline_alerts
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo
from maker_elegoo.slicer import ExportResult, SlicerCLI, ValidationResult
from maker_elegoo.ui import MakerElegooApp


class _FakeGemini(GeminiClient):
    def __init__(self, payload: dict):
        super().__init__(api_key="dummy-key")
        self.payload = payload
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema: dict | None = None) -> dict:
        self.prompts.append(prompt)
        return self.payload


class RevisaoAIAndOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {})
        self.process = Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", Path("p.json"), {})
        self.fil_pla = Profile("Elegoo PLA @ECC2", "filament", Path("pla.json"), {})
        self.fil_abs = Profile("Elegoo ABS @ECC2", "filament", Path("abs.json"), {})
        self.machine_settings = {
            "printer_model": "Elegoo Centauri Carbon 2",
            "nozzle_diameter": ["0.4"],
            "min_layer_height": ["0.08"],
            "max_layer_height": ["0.28"],
            "support_chamber_temp_control": "0",
        }
        self.process_settings = {
            "layer_height": "0.2",
            "wall_loops": "2",
            "wall_generator": "classic",
            "top_shell_layers": "3",
            "bottom_shell_layers": "3",
            "sparse_infill_density": "15%",
            "sparse_infill_pattern": "grid",
            "outer_wall_speed": "160",
            "inner_wall_speed": "200",
            "top_surface_speed": "200",
            "brim_type": "no_brim",
            "seam_position": "aligned",
            "ironing_type": "no ironing",
        }

    def _proj(self, mats: tuple[str, ...] = ("PLA",), used: tuple[str, ...] = ("1",)) -> ProjectInfo:
        fils = tuple(FilamentInfo(i, m, "#FFFFFF", m) for i, m in enumerate(mats, 1))
        return ProjectInfo(
            Path("peca.3mf"),
            {"printer_model": "Bambu Lab A1", "layer_height": "0.2"},
            fils,
            (PlateInfo(1, 1, ("1",), used, used),),
            ("Peca",),
            (),
            (),
            used_filament_slots=used,
        )

    def _plan(self, filaments=None, fil_cfgs=None, **proc_overrides) -> ConversionPlan:
        fils = filaments if filaments is not None else (self.fil_abs,)
        cfgs = fil_cfgs if fil_cfgs is not None else ({"filament_type": ["ABS"], "fan_max_speed": ["40"], "fan_min_speed": ["20"]},)
        return ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=tuple(fils),
            machine_settings=dict(self.machine_settings),
            process_settings={**self.process_settings, **proc_overrides},
            filament_settings=tuple(dict(c) for c in cfgs),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )

    def test_merge_with_offline_alerts_preserves_non_alert_offline_adjustments_and_consolidates(self):
        ai_wall = Advice(
            scope="process", slot=None, key="wall_loops", current="2", proposed="4",
            title="IA: 4 Paredes", why="Reforço IA", expected_effect="Casca mais grossa",
            what_to_check="Prévia", evidence_class="estimado_regra_ia",
            requires_physical_test=False, confidence="alta", default_on=True,
        )
        off_wall = Advice(
            scope="process", slot=None, key="wall_loops", current="2", proposed="3",
            title="Offline: 3 Paredes", why="Não deve duplicar wall_loops já coberto pela IA",
            expected_effect="-", what_to_check="-", evidence_class="estimado_regra_ia",
            requires_physical_test=False, confidence="alta", default_on=True,
        )
        off_brim = Advice(
            scope="process", slot=None, key="brim_type", current="no_brim", proposed="outer_only",
            title="Offline: Brim Externo", why="Contém empenamento ABS",
            expected_effect="Maior adesão", what_to_check="1ª camada",
            evidence_class="estimado_regra_ia", requires_physical_test=False, confidence="alta", default_on=True,
        )
        off_alert = Advice(
            scope="alert", slot=None, key="", current="", proposed="",
            title="Câmara Passiva", why="Câmara passiva", expected_effect="-", what_to_check="-",
            evidence_class="verificado_3mf", requires_physical_test=False, confidence="alta", default_on=False,
        )
        merged = merge_with_offline_alerts([ai_wall], [off_wall, off_brim, off_alert])
        keys = [(a.scope, a.key, a.proposed) for a in merged]
        self.assertIn(("process", "brim_type", "outer_only"), keys)
        self.assertIn(("alert", "", ""), keys)
        # Apenas 1 ajuste por key (IA prevalece sem duplicar wall_loops)
        wall_items = [a for a in merged if a.key == "wall_loops"]
        self.assertEqual(len(wall_items), 1)
        self.assertEqual(wall_items[0].proposed, "4")

    def test_advise_gemini_coerces_string_slot_filters_used_slots_and_mentions_passive_chamber(self):
        proj = self._proj(("PETG", "PLA"), used=("1",))
        plan = self._plan(
            filaments=(self.fil_abs, self.fil_pla),
            fil_cfgs=(
                {"filament_type": ["ABS"], "fan_max_speed": ["40"], "fan_min_speed": ["20"]},
                {"filament_type": ["PLA"], "fan_max_speed": ["100"], "fan_min_speed": ["50"]},
            ),
        )
        fake = _FakeGemini({
            "advices": [
                {
                    "scope": "filament",
                    "slot": "1",
                    "key": "fan_max_speed",
                    "proposed": "35",
                    "title": "Reduzir ventoinha ABS",
                    "why": "Câmara passiva",
                    "expected_effect": "Menos warping",
                    "what_to_check": "Camada",
                    "requires_physical_test": False,
                    "default_on": True,
                },
                {
                    "scope": "filament",
                    "slot": "abc",
                    "key": "fan_max_speed",
                    "proposed": "35",
                    "title": "Slot inválido não deve quebrar",
                    "why": "Teste",
                    "expected_effect": "Nada",
                    "what_to_check": "Nada",
                    "requires_physical_test": False,
                    "default_on": True,
                },
            ]
        })
        goal = PrintGoal("esforco", "equilibrio", physical_material="ABS")
        advices = advise_gemini(fake, proj, plan, goal)
        self.assertEqual(len(fake.prompts), 1)
        prompt = fake.prompts[0]
        self.assertIn("passiva", prompt.lower())
        self.assertIn("support_chamber_temp_control", prompt)
        # Slot 2 (PLA não usado) não deve aparecer em target_materials no prompt
        self.assertNotIn("'PLA'", prompt)
        self.assertTrue(any(a.scope == "filament" and a.slot == 1 and a.proposed == "35" for a in advices))

    def test_compare_objectives_applies_professor_goal_avoids_existing_files_and_shows_priority_label(self):
        proj = self._proj(("PLA",), used=("1",))
        plan = self._plan()
        goal = PrintGoal("esforco", "equilibrio", physical_material="ABS")
        self.assertIn("goal", inspect.signature(compare_objectives).parameters)

        seen_plans: list[ConversionPlan] = []
        seen_dests: list[Path] = []

        def fake_convert(p, variant_plan, dest, cli):
            seen_plans.append(variant_plan)
            seen_dests.append(dest)
            dest.write_bytes(b"ok")
            return ConversionResult(
                True, dest, "ok",
                ExportResult(True, dest, "ok"),
                ValidationResult(True, 1, "ok", (), 1200, 24.5),
                None, proj, {}, proj.plates,
            )

        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            # Pré-cria arquivos para garantir que next_available_destination é usado sem sobrescrever
            (out_dir / f"{proj.path.stem}_equilibrio.3mf").write_bytes(b"existing")
            with patch("maker_elegoo.optimization.convert_project", side_effect=fake_convert):
                variants = compare_objectives(proj, plan, out_dir, SlicerCLI(Path("fake.exe")), goal=goal)
            self.assertEqual(len(variants), 5)
            self.assertTrue(all(d.name != f"{proj.path.stem}_equilibrio.3mf" for d in seen_dests))
            # Em esforco + ABS com goal aplicado, variantes partem dos pisos offline (gyroid, infill>=20%, walls>=4)
            eq_idx = [v.objective for v in variants].index("equilibrio")
            self.assertEqual(seen_plans[eq_idx].process_settings.get("sparse_infill_pattern"), "gyroid")
            self.assertGreaterEqual(int(seen_plans[eq_idx].process_settings.get("wall_loops", "0")), 4)
            self.assertGreaterEqual(int(str(seen_plans[eq_idx].process_settings.get("sparse_infill_density", "0")).rstrip("%")), 20)

            formatted = format_objective_comparison(variants, goal=goal)
            self.assertIn("Equilíbrio", formatted)
            self.assertIn("equilibrio", formatted.lower())

        # ui._compare_objectives também deve repassar goal=self._current_goal()
        src_compare = inspect.getsource(MakerElegooApp._compare_objectives)
        self.assertIn("_current_goal", src_compare)

    def test_merge_with_offline_alerts_with_context_blocks_incompatible_ai_and_warns(self):
        proj = self._proj(("PLA",), used=("1",))
        plan = self._plan()
        goal = PrintGoal("esforco", "equilibrio", load_type="flexao_lateral", physical_material="ABS")
        bad_fan = Advice("filament", 1, "fan_max_speed", "35", "95", "IA: Vento 95%", "Secar rápido", True)
        good_seam = Advice("process", None, "seam_position", "aligned", "back", "IA: Costura traseira", "Visual", True)
        offline = advise_offline(proj, plan, goal)
        merged = merge_with_offline_alerts([bad_fan, good_seam], offline, project=proj, plan=plan, goal=goal)

        fan_props = [a for a in merged if a.scope == "filament" and a.key == "fan_max_speed"]
        self.assertEqual(len(fan_props), 1)
        self.assertLessEqual(int(fan_props[0].proposed), 35)
        self.assertTrue(any(a.scope == "process" and a.key == "seam_position" and a.proposed == "back" for a in merged))
        self.assertTrue(any(a.scope == "alert" and "conflito" in a.title.lower() for a in merged))

    def test_compare_objectives_moveis_velocidade_never_coarsens_layer_by_fallback_and_tracks_filament_changes(self):
        proj = self._proj(("PLA",), used=("1",))
        plan = self._plan()
        plan.filament_settings[0]["fan_max_speed"] = ["80"]
        plan.filament_settings[0]["additional_cooling_fan_speed"] = ["50"]
        goal = PrintGoal(
            "moveis",
            "velocidade",
            fit_clearance="partes_moveis",
            physical_material="ABS",
        )
        seen_plans = {}

        def fake_convert(p, variant_plan, dest, cli):
            obj = dest.stem.rsplit("_", 1)[-1]
            seen_plans[obj] = variant_plan
            dest.write_bytes(b"ok")
            return ConversionResult(
                True, dest, "ok",
                ExportResult(True, dest, "ok"),
                ValidationResult(True, 1, "ok", (), 1100, 18.0),
                None, proj, {}, proj.plates,
            )

        with tempfile.TemporaryDirectory() as tmp, patch("maker_elegoo.optimization.convert_project", side_effect=fake_convert):
            variants = {
                v.objective: v
                for v in compare_objectives(proj, plan, Path(tmp), SlicerCLI(Path("fake.exe")), goal=goal)
            }

        self.assertEqual(seen_plans["velocidade"].process_settings["layer_height"], "0.2")
        self.assertNotIn("layer_height", variants["velocidade"].changed)
        fil_changes = variants["velocidade"].changes_by_scope.get("filament", {})
        self.assertEqual(fil_changes.get("Slot 1.additional_cooling_fan_speed"), "0")
        self.assertIn("Slot 1.fan_max_speed", fil_changes)
        report = format_objective_comparison(tuple(variants.values()), goal=goal)
        self.assertIn("additional_cooling_fan_speed", report)
        self.assertIn("fan_max_speed", report)


if __name__ == "__main__":
    unittest.main()
