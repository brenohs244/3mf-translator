"""Testes TDD para Task 30: polímeros, bico endurecido, resfriamento avançado, validação progressiva e cargas/folgas."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.professor import (
    SAFE_FILAMENT_KEYS,
    Advice,
    PrintGoal,
    _base_polymer,
    advise_offline,
    apply_advice,
    validate_change,
)
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


class RevisaoProfessorPolymersTests(unittest.TestCase):
    def setUp(self):
        self.machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {})
        self.process = Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", Path("p.json"), {})
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
            "sparse_infill_pattern": "rectilinear",
            "outer_wall_speed": "160",
            "inner_wall_speed": "200",
            "top_surface_speed": "200",
            "brim_type": "no_brim",
            "brim_width": "5",
            "seam_position": "aligned",
            "ironing_type": "no ironing",
            "elefant_foot_compensation": "0.1",
        }

    def _proj(self, mats: tuple[str, ...], used: tuple[str, ...] | None = None) -> ProjectInfo:
        fils = tuple(FilamentInfo(i, m, "#FFFFFF", m) for i, m in enumerate(mats, 1))
        used_slots = used if used is not None else tuple(str(i) for i in range(1, len(mats) + 1))
        return ProjectInfo(
            Path("peca.3mf"),
            {"printer_model": "Bambu Lab A1", "layer_height": "0.2"},
            fils,
            (PlateInfo(1, 1, ("1",), used_slots, used_slots),),
            ("Peca",),
            (),
            (),
            used_filament_slots=used_slots,
        )

    def _plan(self, fil_specs: list[tuple[str, dict]], **proc_overrides) -> ConversionPlan:
        fils = tuple(Profile(name, "filament", Path(f"{i}.json"), {}) for i, (name, _) in enumerate(fil_specs, 1))
        cfgs = tuple(dict(cfg) for _, cfg in fil_specs)
        return ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=fils,
            machine_settings=dict(self.machine_settings),
            process_settings={**self.process_settings, **proc_overrides},
            filament_settings=cfgs,
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )

    def test_base_polymer_handles_pc_abs_pa_cf_petg_cf_and_nylon(self):
        self.assertEqual(_base_polymer("PC-ABS"), "PC")
        self.assertEqual(_base_polymer("PC/ABS Blend"), "PC")
        self.assertEqual(_base_polymer("PA12-CF"), "PA")
        self.assertEqual(_base_polymer("Nylon Carbon"), "PA")
        self.assertEqual(_base_polymer("PETG-CF"), "PETG")
        self.assertEqual(_base_polymer("ABS-GF"), "ABS")

    def test_petg_tpu_pa_pc_composite_and_incompatible_multislot_alerts(self):
        proj_1 = self._proj(("PLA",))

        # PETG
        plan_petg = self._plan([("Elegoo PETG HF @ECC2", {"filament_type": ["PETG"], "fan_max_speed": ["60"], "fan_min_speed": ["20"]})])
        adv_petg = advise_offline(proj_1, plan_petg, PrintGoal("funcional_leve", "equilibrio", physical_material="PETG"))
        self.assertTrue(any(a.scope == "alert" and "petg" in a.title.lower() and ("umidade" in a.why.lower() or "pei" in a.why.lower()) for a in adv_petg))

        # TPU
        plan_tpu = self._plan([("Elegoo Rapid TPU 95A @ECC2", {"filament_type": ["TPU"], "fan_max_speed": ["100"], "fan_min_speed": ["100"]})])
        adv_tpu = advise_offline(proj_1, plan_tpu, PrintGoal("funcional_leve", "equilibrio", physical_material="TPU"))
        self.assertTrue(any(a.scope == "alert" and "tpu" in a.title.lower() for a in adv_tpu))
        spd_tpu = next((a for a in adv_tpu if a.key == "outer_wall_speed"), None)
        self.assertIsNotNone(spd_tpu)
        self.assertLessEqual(float(spd_tpu.proposed), 80.0)

        # PA / PC-ABS
        plan_pa = self._plan([("Bambu PA12-CF", {"filament_type": ["PA12-CF"], "fan_max_speed": ["20"], "fan_min_speed": ["0"]})])
        adv_pa = advise_offline(proj_1, plan_pa, PrintGoal("esforco", "equilibrio", physical_material="PA12-CF"))
        self.assertTrue(any(a.scope == "alert" and ("secagem" in f"{a.title} {a.why}".lower() or "umidade" in f"{a.title} {a.why}".lower()) for a in adv_pa))
        self.assertTrue(any(a.scope == "alert" and "endurecido" in f"{a.title} {a.why}".lower() for a in adv_pa))
        self.assertTrue(any(a.key == "brim_type" and a.proposed == "outer_only" for a in adv_pa))

        # Composto -GF no PLA/PETG também alerta bico endurecido
        plan_petg_cf = self._plan([("Elegoo PETG-CF @ECC2", {"filament_type": ["PETG-CF"], "fan_max_speed": ["60"]})])
        adv_cf = advise_offline(proj_1, plan_petg_cf, PrintGoal("esforco", "equilibrio"))
        self.assertTrue(any(a.scope == "alert" and "endurecido" in f"{a.title} {a.why}".lower() for a in adv_cf))

        # Slots incompatíveis usados ao mesmo tempo (PLA + ABS)
        proj_multi = self._proj(("PLA", "ABS"), used=("1", "2"))
        plan_multi = self._plan([
            ("Elegoo PLA @ECC2", {"filament_type": ["PLA"], "fan_max_speed": ["100"]}),
            ("Elegoo ABS @ECC2", {"filament_type": ["ABS"], "fan_max_speed": ["40"]}),
        ])
        adv_multi = advise_offline(proj_multi, plan_multi, PrintGoal("decorativa", "equilibrio"))
        self.assertTrue(any(a.scope == "alert" and "incompat" in f"{a.title} {a.why}".lower() for a in adv_multi))

    def test_abs_outdoor_or_sun_alerts_to_prefer_asa(self):
        proj_1 = self._proj(("PLA",))
        plan_abs = self._plan([("Elegoo ABS @ECC2", {"filament_type": ["ABS"], "fan_max_speed": ["40"], "fan_min_speed": ["10"]})])

        adv_ext = advise_offline(proj_1, plan_abs, PrintGoal("externa", "equilibrio", physical_material="ABS"))
        self.assertTrue(any(a.scope == "alert" and "asa" in f"{a.title} {a.why}".lower() and "uv" in f"{a.title} {a.why}".lower() for a in adv_ext))

        adv_sun = advise_offline(proj_1, plan_abs, PrintGoal("esforco", "equilibrio", heat_exposure="calor_sol", physical_material="ABS"))
        self.assertTrue(any(a.scope == "alert" and "asa" in f"{a.title} {a.why}".lower() and "uv" in f"{a.title} {a.why}".lower() for a in adv_sun))

    def test_advanced_abs_cooling_keys_bounded_increases_and_progressive_apply_advice(self):
        for key in ("close_fan_the_first_x_layers", "slow_down_layer_time", "fan_cooling_layer_time"):
            self.assertIn(key, SAFE_FILAMENT_KEYS)

        plan_abs = self._plan([
            ("Elegoo ABS @ECC2", {
                "filament_type": ["ABS"],
                "fan_min_speed": ["30"],
                "fan_max_speed": ["40"],
                "close_fan_the_first_x_layers": ["1"],
                "slow_down_layer_time": ["3"],
                "fan_cooling_layer_time": ["15"],
            })
        ])
        # Aumento limitado válido (1->3, 3->8, 15->30); valores absurdos rejeitados
        self.assertTrue(validate_change("filament", "close_fan_the_first_x_layers", "3", plan_abs, slot=1))
        self.assertFalse(validate_change("filament", "close_fan_the_first_x_layers", "50", plan_abs, slot=1))
        self.assertTrue(validate_change("filament", "slow_down_layer_time", "8", plan_abs, slot=1))
        self.assertFalse(validate_change("filament", "slow_down_layer_time", "120", plan_abs, slot=1))
        self.assertTrue(validate_change("filament", "fan_cooling_layer_time", "30", plan_abs, slot=1))
        self.assertFalse(validate_change("filament", "fan_cooling_layer_time", "200", plan_abs, slot=1))

        # Offline ABS propõe elevar close_fan_the_first_x_layers e slow_down_layer_time quando baixos
        adv_abs = advise_offline(self._proj(("PLA",)), plan_abs, PrintGoal("esforco", "equilibrio", physical_material="ABS"))
        close_adv = next((a for a in adv_abs if a.key == "close_fan_the_first_x_layers"), None)
        slow_adv = next((a for a in adv_abs if a.key == "slow_down_layer_time"), None)
        self.assertIsNotNone(close_adv)
        self.assertGreaterEqual(int(close_adv.proposed), 3)
        self.assertIsNotNone(slow_adv)
        self.assertGreaterEqual(int(slow_adv.proposed), 6)

        # Validação progressiva em apply_advice: reduzir fan_min_speed 30->10 permite reduzir fan_max_speed 40->25 no mesmo lote
        batch = [
            Advice("filament", 1, "fan_min_speed", "30", "10", "Reduz mín", "Teste", True),
            Advice("filament", 1, "fan_max_speed", "40", "25", "Reduz máx após mín", "Teste", True),
        ]
        applied = apply_advice(plan_abs, batch)
        self.assertEqual(applied.filament_settings[0]["fan_min_speed"], ["10"])
        self.assertEqual(applied.filament_settings[0]["fan_max_speed"], ["25"])

    def test_load_types_differentiation_and_elephant_foot_on_moveis_and_partes_moveis(self):
        plan_pla = self._plan([("Elegoo PLA @ECC2", {"filament_type": ["PLA"], "fan_max_speed": ["100"], "fan_min_speed": ["20"]})])
        proj = self._proj(("PLA",))

        # compressao -> infill >= 40%
        adv_comp = advise_offline(proj, plan_pla, PrintGoal("esforco", "equilibrio", load_type="compressao"))
        infill_comp = next((a for a in adv_comp if a.key == "sparse_infill_density"), None)
        self.assertIsNotNone(infill_comp)
        self.assertGreaterEqual(int(infill_comp.proposed.rstrip("%")), 40)

        # flexao_lateral -> wall_loops >= 5
        adv_flex = advise_offline(proj, plan_pla, PrintGoal("esforco", "equilibrio", load_type="flexao_lateral"))
        wall_flex = next((a for a in adv_flex if a.key == "wall_loops"), None)
        self.assertIsNotNone(wall_flex)
        self.assertGreaterEqual(int(wall_flex.proposed), 5)

        # impacto em funcional_leve -> gyroid + >= 4 paredes + alerta choque
        adv_imp = advise_offline(proj, plan_pla, PrintGoal("funcional_leve", "equilibrio", load_type="impacto"))
        wall_imp = next((a for a in adv_imp if a.key == "wall_loops"), None)
        self.assertIsNotNone(wall_imp)
        self.assertGreaterEqual(int(wall_imp.proposed), 4)
        self.assertTrue(any(a.key == "sparse_infill_pattern" and a.proposed == "gyroid" for a in adv_imp))
        self.assertTrue(any(a.scope == "alert" and "impacto" in f"{a.title} {a.why}".lower() for a in adv_imp))

        # moveis e partes_moveis devem propor elefant_foot_compensation = 0.15 quando < 0.15
        for purp, clr in (("moveis", "normal"), ("encaixe", "partes_moveis")):
            adv_ef = advise_offline(proj, plan_pla, PrintGoal(purp, "equilibrio", fit_clearance=clr))
            ef_adv = next((a for a in adv_ef if a.key == "elefant_foot_compensation"), None)
            self.assertIsNotNone(ef_adv, f"elefant_foot_compensation ausente em {purp}/{clr}")
            self.assertEqual(ef_adv.proposed, "0.15")


if __name__ == "__main__":
    unittest.main()
