import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.mapping import build_conversion
from maker_elegoo.profiles import Profile, SlicerInstall
from maker_elegoo.project import FilamentInfo, PlateInfo, ProjectInfo


class MappingTests(unittest.TestCase):
    def test_preserves_shared_process_choices_but_uses_elegoo_machine_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, name, data in [
                ("machine", "Machine", {"printer_model": "Elegoo Centauri Carbon 2", "nozzle_diameter": ["0.4"], "machine_max_speed_x": "500"}),
                ("process", "Standard", {"wall_loops": "2", "layer_height": "0.2", "enable_support": "0"}),
                ("filament", "PLA", {"filament_type": ["PLA"], "nozzle_temperature": ["210"]}),
            ]:
                path = root / "system" / "Elegoo" / kind / (name + ".json")
                path.parent.mkdir(parents=True, exist_ok=True)
                import json
                path.write_text(json.dumps({"type": kind, "name": name, **data}), encoding="utf-8")
            machine, process, filament = [Profile(name, kind, root / "system" / "Elegoo" / kind / (name + ".json"), {}) for kind, name in [("machine", "Machine"), ("process", "Standard"), ("filament", "PLA")]]
            project = ProjectInfo(root / "source.3mf", {
                "wall_loops": "4", "enable_support": "1", "layer_height": "0.1",
                "machine_max_speed_x": "900", "experimental_bambu_option": "yes",
                "raft_first_layer_expansion": "-1", "tree_support_wall_count": "-1",
            }, (FilamentInfo(1, "PLA", "#FFFFFF", "Source PLA"),), (PlateInfo(1, 1),), ("Cube",), (), ())
            plan = build_conversion(project, SlicerInstall(root / "exe", root), machine, process, [filament])
        self.assertEqual(plan.process_settings["wall_loops"], "4")
        self.assertEqual(plan.process_settings["enable_support"], "1")
        self.assertEqual(plan.process_settings["layer_height"], "0.2")
        self.assertEqual(plan.machine_settings["machine_max_speed_x"], "500")
        self.assertIn("experimental_bambu_option", plan.unmapped)
        self.assertEqual(plan.source_repairs["raft_first_layer_expansion"], "0")

    def test_requires_one_target_filament_per_source_slot(self):
        root = Path(".")
        project = ProjectInfo(root, {}, (FilamentInfo(1, "PLA", "#fff", ""),), (), (), (), ())
        with self.assertRaisesRegex(ValueError, "filamento"):
            build_conversion(project, SlicerInstall(root, root), None, None, [])
