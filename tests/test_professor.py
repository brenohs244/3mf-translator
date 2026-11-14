import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.professor import (
    PrintGoal, Advice, advise_offline, apply_advice, validate_change
)
from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


class ProfessorTest(unittest.TestCase):
    def setUp(self):
        self.project_pla = ProjectInfo(
            Path("cube.3mf"),
            {"printer_model": "Bambu Lab X1C", "layer_height": "0.20", "wall_loops": "2", "sparse_infill_density": "15%"},
            (FilamentInfo(1, "PLA", "#FFFFFF", "PLA Profile"),),
            (PlateInfo(1, 1),), ("Cube",), (), ()
        )
        self.dummy_machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {})
        self.dummy_process = Profile("0.20mm Standard @Elegoo CC2 0.4 nozzle", "process", Path("p.json"), {})
        self.dummy_filament_abs = Profile("Elegoo ABS @ECC2", "filament", Path("f.json"), {})

        self.machine_settings = {
            "printer_model": "Elegoo Centauri Carbon 2",
            "nozzle_diameter": ["0.4"],
            "min_layer_height": ["0.08"],
            "max_layer_height": ["0.28"],
        }
        self.process_settings = {
            "wall_loops": "2",
            "top_shell_layers": "5",
            "bottom_shell_layers": "3",
            "sparse_infill_density": "15%",
            "sparse_infill_pattern": "rectilinear",
            "layer_height": "0.2",
            "brim_type": "no_brim",
            "brim_width": "5",
            "outer_wall_speed": "160",
            "seam_position": "aligned",
            "ironing_type": "no ironing",
        }
        self.filament_abs_settings = {
            "filament_type": ["ABS"],
            "fan_max_speed": ["40"],
            "fan_min_speed": ["10"],
            "additional_cooling_fan_speed": ["0"],
            "during_print_exhaust_fan_speed": ["70"],
            "temperature_vitrification": ["100"],
        }

        self.plan_abs = ConversionPlan(
            machine=self.dummy_machine,
            process=self.dummy_process,
            filaments=(self.dummy_filament_abs,),
            machine_settings=self.machine_settings,
            process_settings=self.process_settings,
            filament_settings=(self.filament_abs_settings,),
            transferred={"wall_loops": "2", "sparse_infill_density": "15%"},
            unmapped={},
            replaced={},
            source_repairs={},
            material_findings=(),
        )

    def test_advise_abs_mechanical_strength(self):
        goal = PrintGoal(purpose="esforco", priority="equilibrio")
        advices = advise_offline(self.project_pla, self.plan_abs, goal)
        keys = {a.key for a in advices if a.key}
        self.assertIn("wall_loops", keys)
        self.assertIn("sparse_infill_density", keys)
        self.assertIn("sparse_infill_pattern", keys)
        self.assertIn("fan_max_speed", keys)
        self.assertIn("brim_type", keys)

        # Verificar que a exaustão vem desmarcada por padrão
        exhaust = next(a for a in advices if a.key == "during_print_exhaust_fan_speed")
        self.assertFalse(exhaust.default_on)
        self.assertEqual(exhaust.proposed, "30")

        # Verificar valor de paredes reforçadas (>=4)
        wall_adv = next(a for a in advices if a.key == "wall_loops")
        self.assertEqual(wall_adv.proposed, "4")

        # Verificar redução de ventoinha para fusão de camadas
        fan_adv = next(a for a in advices if a.key == "fan_max_speed")
        self.assertEqual(fan_adv.proposed, "25")

    def test_apply_advice(self):
        goal = PrintGoal(purpose="esforco", priority="equilibrio")
        advices = advise_offline(self.project_pla, self.plan_abs, goal)
        approved = [a for a in advices if a.default_on]
        new_plan = apply_advice(self.plan_abs, approved)

        self.assertEqual(new_plan.process_settings["wall_loops"], "4")
        self.assertEqual(new_plan.filament_settings[0]["fan_max_speed"], ["25"])
        # Exaustão não foi aprovada porque default_on era False
        self.assertEqual(new_plan.filament_settings[0]["during_print_exhaust_fan_speed"], ["70"])

    def test_qualidade_and_velocidade_suggest_layer_height(self):
        plan_pla = ConversionPlan(
            machine=self.dummy_machine,
            process=self.dummy_process,
            filaments=(Profile("Elegoo PLA @ECC2", "filament", Path("pla.json"), {}),),
            machine_settings=self.machine_settings,
            process_settings=dict(self.process_settings),
            filament_settings=({"filament_type": ["PLA"], "fan_max_speed": ["100"]},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        qual = advise_offline(self.project_pla, plan_pla, PrintGoal("decorativa", "qualidade"))
        q_layer = next((a for a in qual if a.key == "layer_height"), None)
        self.assertIsNotNone(q_layer)
        self.assertEqual(q_layer.proposed, "0.12")

        vel = advise_offline(self.project_pla, plan_pla, PrintGoal("decorativa", "velocidade"))
        v_layer = next((a for a in vel if a.key == "layer_height"), None)
        self.assertIsNotNone(v_layer)
        self.assertEqual(v_layer.proposed, "0.24")

    def test_moveis_in_pla_provides_clearance_guidance(self):
        plan_pla = ConversionPlan(
            machine=self.dummy_machine,
            process=self.dummy_process,
            filaments=(Profile("Elegoo PLA @ECC2", "filament", Path("pla.json"), {}),),
            machine_settings=self.machine_settings,
            process_settings={**self.process_settings, "brim_type": "outer_only"},
            filament_settings=({"filament_type": ["PLA"], "fan_max_speed": ["100"]},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        advices = advise_offline(self.project_pla, plan_pla, PrintGoal("moveis", "equilibrio"))
        self.assertTrue(any(a.scope == "alert" and "folga" in a.why.lower() for a in advices))
        brim_adv = next((a for a in advices if a.key == "brim_type"), None)
        self.assertIsNotNone(brim_adv)
        self.assertEqual(brim_adv.proposed, "no_brim")

    def test_brim_type_works_even_when_missing_in_elegoo_process_json(self):
        proc_no_brim_key = {k: v for k, v in self.process_settings.items() if k != "brim_type"}
        plan_abs = ConversionPlan(
            machine=self.dummy_machine,
            process=self.dummy_process,
            filaments=(self.dummy_filament_abs,),
            machine_settings=self.machine_settings,
            process_settings=proc_no_brim_key,
            filament_settings=({**self.filament_abs_settings, "overhang_fan_speed": ["80"]},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        advices = advise_offline(self.project_pla, plan_abs, PrintGoal("esforco", "equilibrio"))
        brim_adv = next((a for a in advices if a.key == "brim_type"), None)
        self.assertIsNotNone(brim_adv)
        self.assertEqual(brim_adv.proposed, "outer_only")

        overhang_adv = next((a for a in advices if a.key == "overhang_fan_speed"), None)
        self.assertIsNotNone(overhang_adv)
        self.assertEqual(overhang_adv.proposed, "40")

        updated = apply_advice(plan_abs, [a for a in advices if a.default_on])
        self.assertEqual(updated.process_settings.get("brim_type"), "outer_only")
        self.assertEqual(updated.filament_settings[0].get("overhang_fan_speed"), ["40"])

    def test_consolidates_conflicting_infill_suggestions_and_decorative_variable_layer_alert(self):
        plan_pla = ConversionPlan(
            machine=self.dummy_machine,
            process=self.dummy_process,
            filaments=(Profile("Elegoo PLA @ECC2", "filament", Path("pla.json"), {}),),
            machine_settings=self.machine_settings,
            process_settings={**self.process_settings, "sparse_infill_density": "20%"},
            filament_settings=({"filament_type": ["PLA"], "fan_max_speed": ["100"]},),
            transferred={}, unmapped={}, replaced={}, source_repairs={}, material_findings=(),
        )
        advices = advise_offline(self.project_pla, plan_pla, PrintGoal("decorativa", "economia"))
        infill_advs = [a for a in advices if a.key == "sparse_infill_density"]
        self.assertEqual(len(infill_advs), 1)
        self.assertEqual(infill_advs[0].proposed, "10%")
        self.assertTrue(any(a.scope == "alert" and "camada variável" in a.why.lower() for a in advices))

        proj_var = ProjectInfo(
            Path("chibi.3mf"), self.project_pla.source_settings, self.project_pla.filaments,
            self.project_pla.plates, self.project_pla.objects,
            ("Metadata/layer_heights_profile.txt",), (),
        )
        advices_var = advise_offline(proj_var, plan_pla, PrintGoal("decorativa", "equilibrio"))
        self.assertTrue(any(a.scope == "alert" and "detectada" in a.why.lower() for a in advices_var))

    def test_abs_moveis_and_articulated_keychain_do_not_enable_brim_by_default(self):
        for purpose in ("moveis", "chaveiro_articulado"):
            with self.subTest(purpose=purpose):
                advices = advise_offline(self.project_pla, self.plan_abs, PrintGoal(purpose, "equilibrio"))
                brim_on = [a for a in advices if a.key in {"brim_type", "brim_width"} and a.default_on]
                self.assertEqual(brim_on, [])
                self.assertTrue(
                    any(a.scope == "alert" and "brim" in a.title.lower() and "articula" in a.why.lower() for a in advices)
                )

