import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from maker_elegoo.profiles import ProfileError, SlicerInstall, discover_slicer, list_profiles, resolve_profile


def profile(root, relative, values):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values), encoding="utf-8")
    return path


class ProfileTests(unittest.TestCase):
    def test_discovers_machine_process_and_user_filament(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exe = root / "elegoo-slicer.exe"
            exe.touch()
            profile(root, "system/Elegoo/machine/ECC2/cc2.json", {
                "type": "machine", "name": "Elegoo Centauri Carbon 2 0.4 nozzle", "nozzle_diameter": ["0.4"]})
            profile(root, "system/Elegoo/process/ECC2/standard.json", {
                "type": "process", "name": "Standard", "compatible_printers": ["Elegoo Centauri Carbon 2 0.4 nozzle"]})
            profile(root, "user/default/filament/custom.json", {
                "name": "My PLA", "filament_type": ["PLA"]})
            install = discover_slicer(executable=exe, data_dir=root)
            self.assertEqual([p.name for p in list_profiles(install, "machine", "0.4")],
                             ["Elegoo Centauri Carbon 2 0.4 nozzle"])
            self.assertEqual([p.name for p in list_profiles(install, "process", "0.4")], ["Standard"])
            self.assertIn("My PLA", [p.name for p in list_profiles(install, "filament", "0.4")])

    def test_resolves_inheritance_and_rejects_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = profile(root, "system/Elegoo/filament/base.json", {
                "type": "filament", "name": "Base", "nozzle_temperature": ["220"]})
            child = profile(root, "system/Elegoo/filament/ECC2/child.json", {
                "type": "filament", "name": "Child", "inherits": "Base", "filament_type": ["PETG"]})
            install = SlicerInstall(root / "elegoo-slicer.exe", root)
            resolved = resolve_profile(child, install)
            self.assertEqual(resolved["nozzle_temperature"], ["220"])
            self.assertEqual(resolved["filament_type"], ["PETG"])
            base.write_text(json.dumps({"type": "filament", "name": "Base", "inherits": "Child"}))
            with self.assertRaisesRegex(ProfileError, "ciclo"):
                resolve_profile(child, install)

    def test_rejects_missing_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = profile(root, "system/Elegoo/process/ECC2/child.json", {
                "type": "process", "name": "Child", "inherits": "Absent"})
            with self.assertRaisesRegex(ProfileError, "não encontrado"):
                resolve_profile(child, SlicerInstall(root / "elegoo-slicer.exe", root))
