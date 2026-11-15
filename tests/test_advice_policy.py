"""Testes TDD para Task 2: política comum de restrições (Professor, IA e prioridades)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.advice_policy import (
    HARD_POLICY_RULES,
    OPTIONAL_ADVICE_KEYS,
    PolicyResult,
    enforce_advice_policy,
)
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.professor import Advice, PrintGoal, advise_offline, merge_with_offline_alerts
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


def _make_setup(
    *,
    target_mat: str = "ABS",
    process_overrides: dict | None = None,
    fil_overrides: dict | None = None,
) -> tuple[ProjectInfo, ConversionPlan]:
    proj = ProjectInfo(
        Path("peca.3mf"),
        {"printer_model": "Bambu Lab A1", "layer_height": "0.2"},
        (FilamentInfo(1, "PLA", "#FFFFFF", "Bambu PLA"),),
        (PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
        ("Peca",),
        (),
        (),
        used_filament_slots=("1",),
    )
    proc = {
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
    if process_overrides:
        proc.update(process_overrides)
    fil_cfg = {
        "filament_type": [target_mat],
        "fan_min_speed": ["10" if target_mat in {"ABS", "ASA"} else "50"],
        "fan_max_speed": ["40" if target_mat in {"ABS", "ASA"} else "100"],
        "overhang_fan_speed": ["50" if target_mat in {"ABS", "ASA"} else "100"],
        "additional_cooling_fan_speed": ["0"],
        "close_fan_the_first_x_layers": ["3"],
        "slow_down_layer_time": ["6"],
    }
    if fil_overrides:
        fil_cfg.update(fil_overrides)
    plan = ConversionPlan(
        machine=Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {}),
        process=Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", Path("p.json"), {}),
        filaments=(Profile(f"Elegoo {target_mat} @ECC2", "filament", Path("f.json"), {}),),
        machine_settings={
            "printer_model": "Elegoo Centauri Carbon 2",
            "nozzle_diameter": ["0.4"],
            "min_layer_height": ["0.08"],
            "max_layer_height": ["0.28"],
            "support_chamber_temp_control": "0",
        },
        process_settings=proc,
        filament_settings=(fil_cfg,),
        transferred={},
        unmapped={},
        replaced={},
        source_repairs={},
        material_findings=(),
    )
    return proj, plan


def _proc_adv(key: str, proposed: str, title: str, current: str = "2") -> Advice:
    return Advice(
        scope="process",
        slot=None,
        key=key,
        current=current,
        proposed=proposed,
        title=title,
        why="Proposta de teste",
        default_on=True,
    )


class AdvicePolicyTests(unittest.TestCase):
    def test_rules_classify_hard_vs_optional(self):
        self.assertIn("wall_loops", HARD_POLICY_RULES)
        self.assertIn("brim_type", HARD_POLICY_RULES)
        self.assertIn("seam_position", OPTIONAL_ADVICE_KEYS)

    def test_rejects_ai_downgrade_to_1_wall_when_effort_requires_4_and_explains_conservative_floor(self):
        proj, plan = _make_setup(target_mat="PLA")
        goal = PrintGoal("esforco", "equilibrio", load_type="nao_sei", physical_material="PLA")
        local_4 = _proc_adv("wall_loops", "4", "Offline: 4 Paredes")
        ai_1 = _proc_adv("wall_loops", "1", "IA: Reduzir para 1 Parede")

        res = enforce_advice_policy(proj, plan, goal, (ai_1, local_4))
        self.assertIsInstance(res, PolicyResult)
        self.assertNotIn(ai_1, res.accepted)
        self.assertIn(ai_1, res.rejected)
        self.assertIn(local_4, res.accepted)
        reason_txt = " ".join(res.reasons).lower()
        self.assertIn("wall_loops", reason_txt)
        self.assertIn("conservadora", reason_txt)

        # No merge_with_offline_alerts, IA=1 é descartada e o conselho local de 4 paredes prevalece com alerta visível
        merged = merge_with_offline_alerts([ai_1], advise_offline(proj, plan, goal), project=proj, plan=plan, goal=goal)
        wall_props = [a for a in merged if a.scope == "process" and a.key == "wall_loops"]
        self.assertEqual(len(wall_props), 1)
        self.assertGreaterEqual(int(wall_props[0].proposed), 4)
        self.assertTrue(any(a.scope == "alert" and "conflito" in a.title.lower() for a in merged))

    def test_rejects_out_of_range_ai_value(self):
        proj, plan = _make_setup(target_mat="PLA")
        goal = PrintGoal("decorativa", "equilibrio", physical_material="PLA")
        bad_wall = _proc_adv("wall_loops", "25", "IA: 25 Paredes")
        bad_height = _proc_adv("layer_height", "0.50", "IA: Camada 0.50 mm", current="0.2")

        res = enforce_advice_policy(proj, plan, goal, (bad_wall, bad_height))
        self.assertEqual(res.accepted, ())
        self.assertEqual(set(res.rejected), {bad_wall, bad_height})
        self.assertEqual(len(res.reasons), 2)

    def test_accepts_compatible_additional_advice(self):
        proj, plan = _make_setup(target_mat="PLA")
        goal = PrintGoal("esforco", "equilibrio", load_type="flexao_lateral", physical_material="PLA")
        compatible_wall = _proc_adv("wall_loops", "6", "IA: 6 Paredes")
        optional_seam = _proc_adv("seam_position", "back", "IA: Costura traseira", current="aligned")

        res = enforce_advice_policy(proj, plan, goal, (compatible_wall, optional_seam))
        self.assertEqual(res.rejected, ())
        self.assertEqual(res.accepted, (compatible_wall, optional_seam))

    def test_articulated_abs_rejects_ai_automatic_brim(self):
        proj, plan = _make_setup(target_mat="ABS", process_overrides={"brim_type": "no_brim"})
        goal = PrintGoal("chaveiro_articulado", "equilibrio", fit_clearance="partes_moveis", physical_material="ABS")
        ai_brim = _proc_adv("brim_type", "outer_only", "IA: Ativar Brim Externo", current="no_brim")
        ai_auto_brim = _proc_adv("brim_type", "auto_brim", "IA: Auto Brim", current="no_brim")

        res = enforce_advice_policy(proj, plan, goal, (ai_brim, ai_auto_brim))
        self.assertEqual(res.accepted, ())
        self.assertEqual(len(res.rejected), 2)
        self.assertTrue(any("brim" in r.lower() for r in res.reasons))

    def test_velocity_or_ai_cannot_bypass_clearance_layer_protection_or_abs_cooling(self):
        proj, plan = _make_setup(target_mat="ABS")
        goal = PrintGoal("moveis", "velocidade", fit_clearance="partes_moveis", physical_material="ABS")
        coarsen_layer = _proc_adv("layer_height", "0.24", "Velocidade: engrossar camada", current="0.2")
        high_fan = Advice(
            scope="filament",
            slot=1,
            key="fan_max_speed",
            current="40",
            proposed="90",
            title="IA: Ventoinha 90%",
            why="Resfriar mais",
            default_on=True,
        )
        res = enforce_advice_policy(proj, plan, goal, (coarsen_layer, high_fan))
        self.assertEqual(res.accepted, ())
        self.assertEqual(set(res.rejected), {coarsen_layer, high_fan})


if __name__ == "__main__":
    unittest.main()
