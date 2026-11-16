"""Testes TDD para Task 5: Professor orientado à aplicação, lições estruturadas e mecanismos ABS."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.geometry_check import GeometrySummary
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.professor import Advice, PrintGoal, advise_offline
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo
from maker_elegoo.teaching import Lesson, build_lessons, format_lessons


def _setup(
    *,
    src_mat: str = "PLA",
    dst_mat: str = "PLA",
    object_names: tuple[str, ...] = ("Corpo",),
    plates: tuple[PlateInfo, ...] | None = None,
    fil_extra: dict | None = None,
) -> tuple[ProjectInfo, ConversionPlan]:
    proj = ProjectInfo(
        Path("exemplo.3mf"),
        {"printer_model": "Bambu Lab A1", "layer_height": "0.2"},
        (FilamentInfo(1, src_mat, "#FFFFFF", src_mat),),
        plates or (PlateInfo(1, len(object_names), tuple(str(i) for i in range(1, len(object_names) + 1)), ("1",), ("1",)),),
        object_names,
        (),
        (),
        geometry_summary=GeometrySummary(4500, 1, (0, 0, 0, 40, 40, 50), 40.0, 40.0, 50.0, 420.0, 1600.0, False),
        used_filament_slots=("1",),
    )
    fil_cfg = {
        "filament_type": [dst_mat],
        "fan_min_speed": ["15" if dst_mat == "ABS" else "50"],
        "fan_max_speed": ["35" if dst_mat == "ABS" else "100"],
        "overhang_fan_speed": ["50" if dst_mat == "ABS" else "100"],
        "additional_cooling_fan_speed": ["60" if dst_mat == "ABS" else "80"],
        "during_print_exhaust_fan_speed": ["70"],
        "close_fan_the_first_x_layers": ["1" if dst_mat == "ABS" else "1"],
        "slow_down_layer_time": ["5"],
    }
    if fil_extra:
        fil_cfg.update(fil_extra)
    plan = ConversionPlan(
        machine=Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {}),
        process=Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", Path("p.json"), {}),
        filaments=(Profile(f"Elegoo {dst_mat} @ECC2", "filament", Path("f.json"), {}),),
        machine_settings={
            "printer_model": "Elegoo Centauri Carbon 2",
            "nozzle_diameter": ["0.4"],
            "min_layer_height": ["0.08"],
            "max_layer_height": ["0.28"],
            "support_chamber_temp_control": "0",
            "machine_start_gcode": "G28\n",
        },
        process_settings={
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
            "elefant_foot_compensation": "0.0",
        },
        filament_settings=(fil_cfg,),
        transferred={},
        unmapped={},
        replaced={},
        source_repairs={},
        material_findings=(),
    )
    return proj, plan


class TeachingTests(unittest.TestCase):
    def _assert_lessons_well_formed(self, lessons: tuple[Lesson, ...]):
        self.assertGreater(len(lessons), 0)
        for lesson in lessons:
            self.assertIsInstance(lesson, Lesson)
            for field_name in ("observed", "reason", "proposal", "tradeoff", "verification", "evidence_class"):
                val = getattr(lesson, field_name)
                self.assertTrue(isinstance(val, str) and len(val.strip()) >= 8, f"Campo vazio/curto {field_name}: {lesson}")
            text_all = " ".join((lesson.observed, lesson.reason, lesson.proposal, lesson.tradeoff, lesson.verification)).lower()
            self.assertNotIn("garantid", text_all)
            self.assertNotIn("solda correta garantida", text_all)
            self.assertNotIn("comprova resistência", text_all)

    def test_decorative_pla_lessons_have_5_fields_no_strength_guarantee_and_coherent_check(self):
        proj, plan = _setup(src_mat="PLA", dst_mat="PLA")
        goal = PrintGoal("decorativa", "qualidade", physical_material="PLA")
        advices = tuple(advise_offline(proj, plan, goal))
        lessons = build_lessons(proj, plan, goal, advices)
        self._assert_lessons_well_formed(lessons)
        joined = format_lessons(lessons).lower()
        self.assertIn("o que observei", joined)
        self.assertIn("por que isso importa", joined)
        self.assertIn("como conferir", joined)
        self.assertNotIn("resistência garantida", joined)

    def test_functional_pla_to_abs_explains_cooling_mechanisms_honestly(self):
        proj, plan = _setup(src_mat="PLA", dst_mat="ABS")
        goal = PrintGoal(
            "esforco",
            "equilibrio",
            load_type="flexao_lateral",
            criticality="alta",
            fit_clearance="encaixe_justo",
            heat_exposure="ambiente",
            physical_material="ABS",
        )
        advices = tuple(advise_offline(proj, plan, goal))
        lessons = build_lessons(proj, plan, goal, advices)
        self._assert_lessons_well_formed(lessons)
        joined = format_lessons(lessons).lower()
        # Diferencia os mecanismos reais de resfriamento e câmara passiva
        self.assertIn("ventoinha da peça", joined)
        self.assertIn("auxiliar", joined)
        self.assertIn("câmara passiva", joined)
        self.assertIn("exaustão", joined)
        # Usa valores reais do perfil (ex: 35% e 70%), sem afirmar que pré-aquecimento aquece câmara ativamente
        self.assertIn("35%", joined)
        self.assertNotIn("câmara aquecida garantida", joined)
        self.assertNotIn("percentual universal", joined)

    def test_articulated_abs_and_z_load_and_mixed_use_project_lessons(self):
        proj, plan = _setup(
            src_mat="PLA",
            dst_mat="ABS",
            object_names=("Suporte Estrutural", "Capa Decorativa"),
            plates=(PlateInfo(1, 2, ("1", "2"), ("1",), ("1",)),),
        )
        goal_art = PrintGoal("moveis", "velocidade", fit_clearance="partes_moveis", physical_material="ABS")
        lessons_art = build_lessons(proj, plan, goal_art, tuple(advise_offline(proj, plan, goal_art)))
        self._assert_lessons_well_formed(lessons_art)
        txt_art = format_lessons(lessons_art).lower()
        self.assertIn("folga", txt_art)
        self.assertIn("brim", txt_art)
        self.assertIn("retração", txt_art)
        # Projeto multi-objeto identifica limitação do objetivo global sem adivinhar por aparência
        self.assertIn("objetivo global", txt_art)
        self.assertIn("aparência", txt_art)

        goal_z = PrintGoal(
            "esforco",
            "equilibrio",
            load_type="tracao_eixo_z",
            criticality="alta",
            physical_material="ABS",
        )
        lessons_z = build_lessons(proj, plan, goal_z, tuple(advise_offline(proj, plan, goal_z)))
        self._assert_lessons_well_formed(lessons_z)
        txt_z = format_lessons(lessons_z).lower()
        self.assertIn("eixo z", txt_z)
        self.assertIn("preenchimento", txt_z)
        self.assertIn("magnitude", txt_z)
        self.assertIn("ensaio", txt_z)


if __name__ == "__main__":
    unittest.main()
