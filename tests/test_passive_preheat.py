import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.mapping import ConversionPlan
from maker_elegoo.professor import (
    PrintGoal,
    advise_offline,
    apply_advice,
    inject_passive_preheat_gcode,
    validate_change,
)
from maker_elegoo.profiles import Profile
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


def _make_abs_plan(*, start_gcode: str = "G90\nM140 S[bed_temperature_initial_layer_single]\nM190 S[bed_temperature_initial_layer_single] A\nG28\n"):
    machine = Profile("Elegoo Centauri Carbon 2 0.4 nozzle", "machine", Path("m.json"), {})
    process = Profile("0.20mm Standard", "process", Path("p.json"), {})
    fil = Profile("Generic ABS", "filament", Path("f.json"), {})
    return ConversionPlan(
        machine=machine,
        process=process,
        filaments=(fil,),
        machine_settings={
            "printer_model": "Elegoo Centauri Carbon 2",
            "nozzle_diameter": ["0.4"],
            "support_chamber_temp_control": "0",
            "machine_start_gcode": start_gcode,
        },
        process_settings={"layer_height": "0.2", "wall_loops": "2"},
        filament_settings=({
            "filament_type": ["ABS"],
            "fan_max_speed": ["80"],
            "fan_min_speed": ["10"],
            "additional_cooling_fan_speed": ["50"],
        },),
        transferred={},
        unmapped={},
        replaced={},
        source_repairs={},
        material_findings=(),
    )


def _make_project(material: str = "PLA") -> ProjectInfo:
    return ProjectInfo(
        path=Path("test.3mf"),
        source_settings={"layer_height": "0.2"},
        filaments=(FilamentInfo(1, material, "#FFFFFF", material),),
        plates=(PlateInfo(1, 1, ("1",), ("1",), ("1",)),),
        objects=("Part",),
        archive_entries=("3D/3dmodel.model",),
        warnings=(),
    )


class PassivePreheatTests(unittest.TestCase):
    def test_inject_passive_preheat_places_g4_after_m190_and_is_idempotent(self):
        base = "G90\nM104 S140\nM190 S[bed_temperature_initial_layer_single] A\nM106 S0\nG28"
        once = inject_passive_preheat_gcode(base, 300)
        self.assertIn("G4 S300", once)
        self.assertLess(once.index("M190 "), once.index("G4 S300"))
        self.assertLess(once.index("G4 S300"), once.index("G28"))
        twice = inject_passive_preheat_gcode(once, 480)
        self.assertNotIn("G4 S300", twice)
        self.assertIn("G4 S480", twice)
        self.assertEqual(twice.count("pre-aquecimento passivo"), 1)

    def test_validate_change_enforces_safe_bounds_on_passive_preheat(self):
        plan = _make_abs_plan()
        self.assertTrue(validate_change("machine", "passive_preheat_seconds", "300", plan))
        self.assertTrue(validate_change("machine", "passive_preheat_seconds", "600", plan))
        self.assertFalse(validate_change("machine", "passive_preheat_seconds", "30", plan))
        self.assertFalse(validate_change("machine", "passive_preheat_seconds", "3600", plan))
        self.assertFalse(validate_change("machine", "unknown_machine_key", "1", plan))

    def test_advise_offline_offers_opt_in_preheat_for_abs_passive_chamber(self):
        project = _make_project("PLA")
        plan = _make_abs_plan()
        goal = PrintGoal(purpose="esforco", priority="equilibrio", physical_material="ABS")
        advices = advise_offline(project, plan, goal)
        preheat = [a for a in advices if a.scope == "machine" and a.key == "passive_preheat_seconds"]
        self.assertEqual(len(preheat), 1)
        self.assertFalse(preheat[0].default_on)
        updated = apply_advice(plan, preheat)
        self.assertIn("G4 S", updated.machine_settings["machine_start_gcode"])
        self.assertNotIn("passive_preheat_seconds", updated.machine_settings)

    def test_advise_offline_does_not_offer_preheat_for_pla(self):
        project = _make_project("PLA")
        plan = _make_abs_plan()
        plan = ConversionPlan(
            **{
                **plan.__dict__,
                "filament_settings": ({"filament_type": ["PLA"], "fan_max_speed": ["100"], "fan_min_speed": ["50"]},),
            }
        )
        goal = PrintGoal(purpose="decorativa", priority="equilibrio", physical_material="PLA")
        advices = advise_offline(project, plan, goal)
        self.assertFalse(any(a.key == "passive_preheat_seconds" for a in advices))


if __name__ == "__main__":
    unittest.main()
