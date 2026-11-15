"""Testes TDD para Professor confiável: origem PLA/PETG/mista, 'Não sei', checklist ABS, 4 classes de evidência e histórico local."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


class ProfessorConfiavelTests(unittest.TestCase):
    def setUp(self):
        self.machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {})
        self.process = Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", Path("p.json"), {})
        self.fil_abs = Profile("Elegoo ABS @ECC2", "filament", Path("abs.json"), {})
        self.fil_pla = Profile("Elegoo PLA @ECC2", "filament", Path("pla.json"), {})
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
            "brim_width": "5",
            "seam_position": "aligned",
            "ironing_type": "no ironing",
        }
        self.abs_settings = {
            "filament_type": ["ABS"],
            "nozzle_temperature": ["270"],
            "textured_plate_temp": ["90"],
            "fan_max_speed": ["40"],
            "fan_min_speed": ["30"],
            "overhang_fan_speed": ["80"],
            "during_print_exhaust_fan_speed": ["70"],
        }
        self.pla_settings = {
            "filament_type": ["PLA"],
            "nozzle_temperature": ["210"],
            "textured_plate_temp": ["60"],
            "fan_max_speed": ["100"],
            "fan_min_speed": ["50"],
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

    def _plan(self, fil_profile: Profile, fil_cfg: dict, **proc_overrides) -> ConversionPlan:
        return ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=(fil_profile,),
            machine_settings=self.machine_settings,
            process_settings={**self.process_settings, **proc_overrides},
            filament_settings=(dict(fil_cfg),),
            transferred={},
            unmapped={},
            replaced={},
            source_repairs={},
            material_findings=(),
        )

    def test_distinguishes_pla_petg_and_mixed_origins_never_labeling_petg_as_pla(self):
        from maker_elegoo.professor import PrintGoal, advise_offline, source_material_summary

        proj_pla = self._proj(("PLA",))
        proj_petg = self._proj(("PETG", "PLA"), used=("1",))  # Só slot 1 (PETG) usado, como no CANIVETE
        proj_mixed = self._proj(("PLA", "PETG"), used=("1", "2"))

        sum_pla = source_material_summary(proj_pla)
        sum_petg = source_material_summary(proj_petg)
        sum_mixed = source_material_summary(proj_mixed)

        self.assertTrue(sum_pla["has_pla"])
        self.assertFalse(sum_pla["has_petg"])
        self.assertFalse(sum_petg["has_pla"])
        self.assertTrue(sum_petg["has_petg"])
        self.assertEqual(sum_petg["label"], "PETG")
        self.assertTrue(sum_mixed["has_pla"])
        self.assertTrue(sum_mixed["has_petg"])
        self.assertTrue(sum_mixed["is_mixed"])

        plan_abs = self._plan(self.fil_abs, self.abs_settings)
        adv_petg = advise_offline(proj_petg, plan_abs, PrintGoal("moveis", "equilibrio", physical_material="ABS"))
        titles_petg = " | ".join(a.title for a in adv_petg)
        why_petg = " | ".join(a.why for a in adv_petg)
        self.assertNotIn("PLA → ABS", titles_petg)
        self.assertNotIn("modelado para PLA", why_petg)
        self.assertIn("PETG", titles_petg + why_petg)

        plan_abs_2 = ConversionPlan(
            machine=self.machine,
            process=self.process,
            filaments=(self.fil_abs, self.fil_abs),
            machine_settings=self.machine_settings,
            process_settings=dict(self.process_settings),
            filament_settings=(dict(self.abs_settings), dict(self.abs_settings)),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        adv_mixed = advise_offline(proj_mixed, plan_abs_2, PrintGoal("moveis", "equilibrio", physical_material="ABS"))
        mixed_text = " | ".join(f"{a.title} {a.why}" for a in adv_mixed)
        self.assertIn("PLA", mixed_text)
        self.assertIn("PETG", mixed_text)

    def test_unknown_nao_sei_reduces_confidence_and_contextual_questions_add_targeted_advice(self):
        from maker_elegoo.professor import PrintGoal, advise_offline, goal_confidence

        proj = self._proj(("PLA",))
        plan_pla = self._plan(self.fil_pla, self.pla_settings)

        goal_unknown = PrintGoal(
            purpose="esforco",
            priority="equilibrio",
            load_type="nao_sei",
            criticality="nao_sei",
            fit_clearance="nao_sei",
            heat_exposure="nao_sei",
            physical_material="nao_sei",
        )
        conf_low, reasons = goal_confidence(goal_unknown)
        self.assertEqual(conf_low, "baixa")
        self.assertGreaterEqual(len(reasons), 3)

        advices_unknown = advise_offline(proj, plan_pla, goal_unknown)
        self.assertTrue(any(a.scope == "alert" and a.confidence == "baixa" for a in advices_unknown))

        goal_known = PrintGoal(
            purpose="esforco",
            priority="equilibrio",
            load_type="tracao_eixo_z",
            criticality="alta",
            fit_clearance="encaixe_justo",
            heat_exposure="calor_sol",
            physical_material="PLA",
        )
        conf_high, _ = goal_confidence(goal_known)
        self.assertEqual(conf_high, "alta")

        advices_known = advise_offline(proj, plan_pla, goal_known)
        joined = " | ".join(f"{a.title} {a.why}" for a in advices_known).lower()
        self.assertIn("eixo z", joined)
        self.assertIn("crític", joined)
        self.assertIn("45", joined)  # Alerta PLA sob calor/sol

        for adv in advices_known:
            if adv.scope != "alert":
                self.assertTrue(adv.expected_effect, f"Faltou expected_effect em {adv.title}")
                self.assertTrue(adv.what_to_check, f"Faltou what_to_check em {adv.title}")
            self.assertIn(
                adv.evidence_class,
                {"verificado_3mf", "verificado_fatiamento", "estimado_regra_ia", "depende_teste_fisico"},
            )

    def test_abs_checklist_respects_fan_min_speed_removes_guarantees_and_has_4_evidence_classes(self):
        from maker_elegoo.professor import PrintGoal, advise_offline, build_abs_asa_checklist, build_print_summary

        proj = self._proj(("PLA",))
        plan_abs = self._plan(self.fil_abs, self.abs_settings)
        goal = PrintGoal(
            purpose="esforco",
            priority="equilibrio",
            load_type="flexao_lateral",
            criticality="media",
            fit_clearance="encaixe_justo",
            heat_exposure="interno",
            physical_material="ABS",
        )
        advices = advise_offline(proj, plan_abs, goal)
        fan_max_adv = next((a for a in advices if a.key == "fan_max_speed"), None)
        # fan_min_speed do perfil é 30%, logo fan_max_speed não pode propor 25% abaixo do mínimo!
        if fan_max_adv is not None:
            self.assertGreaterEqual(int(fan_max_adv.proposed), 30)

        checklist = build_abs_asa_checklist(proj, plan_abs, goal)
        checklist_txt = "\n".join(checklist).lower()
        for expected_topic in (
            "contração",
            "empenamento",
            "adesão à mesa",
            "270",
            "90",
            "câmara",
            "ventilação da peça",
            "exaustão",
        ):
            self.assertIn(expected_topic, checklist_txt)

        summary = build_print_summary(proj, plan_abs, goal, advices)
        lower_sum = summary.lower()
        self.assertNotIn("garantir", lower_sum)
        self.assertNotIn("garante", lower_sum)
        for heading in (
            "verificado no 3mf",
            "verificado pelo fatiamento",
            "estimado por regra/ia",
            "depende de teste físico",
        ):
            self.assertIn(heading, lower_sum)
        self.assertIn("fatiar não prova acabamento, estabilidade dimensional nem resistência mecânica", lower_sum)

    def test_local_feedback_history_records_and_informs_future_advices(self):
        from maker_elegoo.history import (
            FeedbackRecord,
            adjust_advices_from_history,
            append_feedback_record,
            clear_feedback_history,
            load_feedback_history,
        )
        from maker_elegoo.professor import PrintGoal, advise_offline

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"MAKER_ELEGOO_CONFIG_DIR": tmp}):
            rec = FeedbackRecord(
                timestamp="2026-11-14T08:00:00",
                project_label="suporte.3mf",
                source_material="PLA",
                target_material="ABS",
                nozzle_mm="0.4",
                purpose="esforco",
                priority="equilibrio",
                load_type="tracao_eixo_z",
                visual_result="empenou_soltou",
                applied_params={"brim_type": "no_brim"},
                notes="Cantos descolaram aos 40 min",
            )
            append_feedback_record(rec)
            loaded = load_feedback_history()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].visual_result, "empenou_soltou")

            proj = self._proj(("PLA",))
            plan = self._plan(self.fil_abs, self.abs_settings)
            goal = PrintGoal("esforco", "equilibrio", load_type="tracao_eixo_z", physical_material="ABS")
            base = advise_offline(proj, plan, goal)
            adjusted = adjust_advices_from_history(base, proj, plan, goal, loaded)
            self.assertTrue(any("histórico local" in f"{a.title} {a.why}".lower() for a in adjusted))

            clear_feedback_history()
            self.assertEqual(load_feedback_history(), [])

    def test_task28_decorativa_all_priorities_abs_economia_articulados_velocidade_and_aux_summary(self):
        from dataclasses import replace
        from maker_elegoo.geometry_check import GeometrySummary
        from maker_elegoo.professor import PrintGoal, advise_offline, build_print_summary

        # (a) Decorativa em equilibrio e velocidade também ativam suporte otimizado
        # when overhang >= 250 (ou sem geom), e desativam default_on quando overhang < 250 mm²
        proj_big_oh = replace(
            self._proj(("PLA",)),
            geometry_summary=GeometrySummary(1000, 1, (0, 0, 0, 40, 40, 50), 40.0, 40.0, 50.0, 1600.0, 420.0, False),
        )
        proj_small_oh = replace(
            self._proj(("PLA",)),
            geometry_summary=GeometrySummary(1000, 1, (0, 0, 0, 40, 40, 50), 40.0, 40.0, 50.0, 1600.0, 80.0, False),
        )
        plan_pla = self._plan(self.fil_pla, self.pla_settings, enable_support="0")
        for prio in ("qualidade", "equilibrio", "velocidade"):
            goal = PrintGoal("decorativa", prio, physical_material="PLA")
            adv_big = advise_offline(proj_big_oh, plan_pla, goal)
            sup_big = next((a for a in adv_big if a.key == "enable_support"), None)
            self.assertIsNotNone(sup_big, f"enable_support ausente em decorativa/{prio}")
            self.assertEqual(sup_big.proposed, "1")
            self.assertTrue(sup_big.default_on, f"enable_support deveria vir ligado para overhang>=250 em {prio}")

            adv_small = advise_offline(proj_small_oh, plan_pla, goal)
            sup_small = next((a for a in adv_small if a.key == "enable_support"), None)
            self.assertIsNotNone(sup_small, f"enable_support ausente em decorativa/{prio} pequeno")
            self.assertFalse(sup_small.default_on, f"enable_support deveria ficar default_on=False para overhang<250 em {prio}")

        # (b) ABS + economia nunca rebaixa enchimento abaixo de 20%
        plan_abs_high_infill = self._plan(self.fil_abs, self.abs_settings, sparse_infill_density="20%")
        goal_abs_eco = PrintGoal("decorativa", "economia", physical_material="ABS")
        adv_eco = advise_offline(self._proj(("PLA",)), plan_abs_high_infill, goal_abs_eco)
        infill_eco = [a for a in adv_eco if a.key == "sparse_infill_density"]
        for adv in infill_eco:
            self.assertGreaterEqual(int(adv.proposed.rstrip("%")), 20)

        plan_abs_low_infill = self._plan(self.fil_abs, self.abs_settings, sparse_infill_density="12%")
        adv_eco_low = advise_offline(self._proj(("PLA",)), plan_abs_low_infill, goal_abs_eco)
        infill_low = next((a for a in adv_eco_low if a.key == "sparse_infill_density"), None)
        self.assertIsNotNone(infill_low)
        self.assertGreaterEqual(int(infill_low.proposed.rstrip("%")), 20)

        # (c) ABS em peças articuladas (moveis / chaveiro_articulado / partes_moveis) deve propor brim_type="no_brim"
        for purp, clearance in (("moveis", "normal"), ("chaveiro_articulado", "normal"), ("encaixe", "partes_moveis")):
            plan_abs_brim = self._plan(self.fil_abs, self.abs_settings, brim_type="auto_brim")
            goal_art = PrintGoal(purp, "equilibrio", fit_clearance=clearance, physical_material="ABS")
            adv_art = advise_offline(self._proj(("PLA",)), plan_abs_brim, goal_art)
            brim_adv = next((a for a in adv_art if a.key == "brim_type"), None)
            self.assertIsNotNone(brim_adv, f"brim_type='no_brim' ausente em ABS + {purp}/{clearance}")
            self.assertEqual(brim_adv.proposed, "no_brim")

        # E alerta de peça esbelta avalia contra o brim planejado (não dispara alerta de 'sem brim' quando brim já foi proposto!)
        proj_slender = replace(
            self._proj(("PLA",)),
            geometry_summary=GeometrySummary(1000, 1, (0, 0, 0, 12, 12, 80), 12.0, 12.0, 80.0, 100.0, 10.0, True),
        )
        plan_abs_nobrim = self._plan(self.fil_abs, self.abs_settings, brim_type="no_brim")
        adv_slender = advise_offline(proj_slender, plan_abs_nobrim, PrintGoal("esforco", "equilibrio", physical_material="ABS"))
        brim_planned = next((a for a in adv_slender if a.key == "brim_type" and a.default_on), None)
        self.assertIsNotNone(brim_planned)
        self.assertNotEqual(brim_planned.proposed, "no_brim")
        self.assertFalse(
            any("esbelta" in a.title.lower() and "sem brim" in a.title.lower() for a in adv_slender),
            "Não deve alertar 'peça esbelta sem brim' quando outer_brim já foi planejado!",
        )

        # (d) velocidade não pode subir layer_height para 0.24 em usos articulados
        plan_pla_016 = self._plan(self.fil_pla, self.pla_settings, layer_height="0.16")
        for purp, clearance in (("moveis", "normal"), ("chaveiro_articulado", "normal"), ("encaixe", "partes_moveis")):
            adv_vel = advise_offline(proj_big_oh, plan_pla_016, PrintGoal(purp, "velocidade", fit_clearance=clearance, physical_material="PLA"))
            lh_adv = next((a for a in adv_vel if a.key == "layer_height"), None)
            if lh_adv is not None:
                self.assertLessEqual(float(lh_adv.proposed), 0.20)

        # (e) build_print_summary verifica explicitamente se additional_cooling_fan_speed == "0" nos slots ABS
        abs_aux_bad = {**self.abs_settings, "additional_cooling_fan_speed": ["60"]}
        plan_aux_bad = self._plan(self.fil_abs, abs_aux_bad)
        sum_bad = build_print_summary(self._proj(("PLA",)), plan_aux_bad, PrintGoal("esforco", "equilibrio", physical_material="ABS"), [])
        self.assertIn("aux", sum_bad.lower())
        self.assertIn("60", sum_bad)

        abs_aux_ok = {**self.abs_settings, "additional_cooling_fan_speed": ["0"]}
        plan_aux_ok = self._plan(self.fil_abs, abs_aux_ok)
        sum_ok = build_print_summary(self._proj(("PLA",)), plan_aux_ok, PrintGoal("esforco", "equilibrio", physical_material="ABS"), [])
        self.assertIn("desligada", sum_ok.lower())


if __name__ == "__main__":
    unittest.main()
